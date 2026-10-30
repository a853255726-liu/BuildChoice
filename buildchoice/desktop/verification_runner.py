"""Explicit test collector. This module is never invoked by a verification MCP tool."""
import hashlib
import json
import os
from pathlib import Path
import secrets
import signal
import subprocess
import sys
import time
import uuid
from jsonschema import ValidationError
from . import acceptance
from .audit import now
from .common import ROOT, file_sha
from .decision_store import DecisionStore, fingerprint
from .verification_inputs import (ADAPTER_VERSION,RULE_VERSION,artifact_directory,environment_snapshot,
                                  input_snapshot,manifest,runtime_digest)


def stop(process):
    if process.poll() is not None:return
    if os.name=='nt':
        try:subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=3,creationflags=subprocess.CREATE_NO_WINDOW)
        except (OSError,subprocess.SubprocessError):pass
    else:
        try:os.killpg(process.pid,signal.SIGKILL)
        except ProcessLookupError:pass
    if process.poll() is None:process.kill()
    process.wait(timeout=3)


def collect(workspace, acceptance_id, manifest_path, settings_path=None, decision_settings_path=None):
    from .settings import read as read_global,SETTINGS
    from .decision_settings import read as read_decisions,SETTINGS as DECISIONS
    if read_global(settings_path or SETTINGS)['mode']=='off' or read_decisions(decision_settings_path or DECISIONS)['mode']!='pilot':
        raise ValueError('VERIFICATION_DISABLED')
    workspace=Path(workspace).resolve(strict=True)
    if not (workspace/'.buildchoice_audit/ledger.sqlite3').is_file():raise ValueError('EXISTING_ACCEPTANCE_REQUIRED')
    store=DecisionStore(workspace);conditions=acceptance.get(store,acceptance_id);acceptance.current(store,conditions)
    manifest_file=store.ledger.path(manifest_path)
    raw=manifest_file.read_bytes()
    if len(raw)>65536:raise ValueError('MANIFEST_TOO_LARGE')
    declared=manifest(store,json.loads(raw.decode('utf-8-sig')))
    before=input_snapshot(store,declared);environment=environment_snapshot(declared['dependencies'])
    execution_id='exec-'+uuid.uuid4().hex;directory=artifact_directory(store,execution_id,create=True)
    nonce=secrets.token_hex(24);started=now();runtime=runtime_digest()
    # Isolate bytecode lookup too: same-size edits within one timestamp tick must
    # execute the declared source, never a cached earlier test/implementation.
    command=[sys.executable,'-B','-X','pycache_prefix='+str(directory/'bytecode'),str(ROOT/'scripts/buildchoice_test_worker.py'),'--test-file',str(store.ledger.path(declared['test_file'])),
             '--report',str(directory/'report.json'),'--execution-id',execution_id,'--nonce',nonce]
    with store.connect() as db:
        store.event(db,conditions['task_id'],'VERIFICATION_EXECUTION_STARTED',{'execution_id':execution_id,
            'acceptance_id':acceptance_id,'acceptance_digest':conditions['acceptance_digest'],'started':started,
            'nonce_digest':hashlib.sha256(nonce.encode()).hexdigest()})
    execution_status='completed';reason='COLLECTOR_OBSERVED_EXECUTION';code=None;process=None
    log_path=directory/'output.log'
    with log_path.open('wb') as log:
        try:
            options={'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {'start_new_session':True}
            process=subprocess.Popen(command,cwd=workspace,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,
                env={**os.environ,'PYTHONUTF8':'1','PYTHONIOENCODING':'utf-8'},**options)
            deadline=time.monotonic()+declared['timeout_seconds']
            while process.poll() is None:
                if time.monotonic()>deadline:
                    execution_status='timeout';reason='TEST_TIMEOUT';stop(process);break
                if log_path.stat().st_size>1024*1024:
                    execution_status='output_limit';reason='TEST_OUTPUT_LIMIT';stop(process);break
                time.sleep(0.025)
            code=process.wait(timeout=3)
        except (OSError,subprocess.SubprocessError):
            execution_status='error';reason='TEST_PROCESS_ERROR'
        finally:
            if process is not None:stop(process)
    # Bound retained logs. A limit breach is an execution error, never a pass.
    if log_path.stat().st_size>1024*1024:
        with log_path.open('r+b') as stream:stream.truncate(1024*1024)
        execution_status='output_limit';reason='TEST_OUTPUT_LIMIT'
    report=None;report_hash=None
    try:
        report_file=directory/'report.json'
        if report_file.is_symlink() or report_file.stat().st_size>1024*1024:raise ValueError('INVALID_REPORT')
        report=json.loads(report_file.read_text(encoding='utf-8'))
        acceptance.validate('verification-v1.schema.json','WorkerReport',report)
        if report['execution_id']!=execution_id or report['nonce']!=nonce:raise ValueError('REPORT_BINDING_MISMATCH')
        report_hash=file_sha(report_file)
    except (OSError,ValueError,ValidationError):
        report=None
        if execution_status=='completed':execution_status='error';reason='MISSING_OR_INVALID_WORKER_REPORT'
    try:after=input_snapshot(store,declared)
    except (OSError,ValueError):after={'unavailable':True}
    try:after_environment=environment_snapshot(declared['dependencies'])['digest']
    except (OSError,ValueError,ImportError):after_environment=None
    try:after_manifest=file_sha(manifest_file)
    except OSError:after_manifest=None
    receipt={'schema_version':'execution.v1','execution_id':execution_id,'task_id':conditions['task_id'],
        'acceptance_id':acceptance_id,'acceptance_digest':conditions['acceptance_digest'],'decision_id':conditions['decision_id'],
        'decision_revision':conditions['decision_revision'],'confirmation_id':conditions['confirmation_id'],
        'provenance':'collector_observed_execution','started':started,'finished':now(),'argv':command,'cwd':str(workspace),
        'exit_code':code,'execution_status':execution_status,'reason':reason,'adapter_version':ADAPTER_VERSION,'rule_version':RULE_VERSION,
        'runtime_digest':runtime,'manifest':declared,'manifest_path':manifest_file.relative_to(workspace).as_posix(),
        'manifest_sha256':hashlib.sha256(raw).hexdigest(),'manifest_after_sha256':after_manifest,
        'before':before,'after':after,'environment':environment,'environment_after_digest':after_environment,
        'report_sha256':report_hash,'log_sha256':file_sha(log_path),'report':report}
    receipt['receipt_digest']=fingerprint(receipt)
    acceptance.validate('verification-v1.schema.json','ExecutionReceipt',receipt)
    with store.connect() as db:store.event(db,conditions['task_id'],'VERIFICATION_EXECUTION_OBSERVED',receipt)
    return receipt
