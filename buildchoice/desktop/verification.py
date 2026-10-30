"""Read evidence and collector receipts, never execute tests or project commands."""
import hashlib
import json
import uuid
from jsonschema import ValidationError
from . import acceptance
from .audit import encode, now, pointer_value
from .common import file_sha
from .decision_store import fingerprint
from .verification_inputs import (ADAPTER_VERSION,RULE_VERSION,artifact_directory,environment_current,
                                  input_snapshot,runtime_digest)


def execution(store, conditions, execution_id):
    matches=[r for r in acceptance.events(store,'VERIFICATION_EXECUTION_OBSERVED',conditions['task_id']) if r['execution_id']==execution_id]
    if len(matches)!=1:raise ValueError('UNKNOWN_OR_AMBIGUOUS_COLLECTOR_EXECUTION')
    receipt=matches[0]
    acceptance.validate('verification-v1.schema.json','ExecutionReceipt',receipt)
    if receipt['receipt_digest']!=fingerprint({k:v for k,v in receipt.items() if k!='receipt_digest'}):
        raise ValueError('RECEIPT_DIGEST_MISMATCH')
    for name in ('task_id','acceptance_id','acceptance_digest','decision_id','decision_revision','confirmation_id'):
        expected=conditions['decision_revision'] if name=='decision_revision' else conditions[name]
        if receipt[name]!=expected:raise ValueError('EXECUTION_SCOPE_MISMATCH')
    starts=[r for r in acceptance.events(store,'VERIFICATION_EXECUTION_STARTED',conditions['task_id']) if r['execution_id']==execution_id]
    if len(starts)!=1 or starts[0]['acceptance_id']!=conditions['acceptance_id'] or starts[0]['acceptance_digest']!=conditions['acceptance_digest']:
        raise ValueError('COLLECTOR_START_REQUIRED')
    if receipt['report'] is not None:
        acceptance.validate('verification-v1.schema.json','WorkerReport',receipt['report'])
        if (receipt['report']['execution_id']!=execution_id or
            hashlib.sha256(receipt['report']['nonce'].encode()).hexdigest()!=starts[0]['nonce_digest']):
            raise ValueError('REPORT_EXECUTION_BINDING_MISMATCH')
    return receipt


def static_evidence(store, refs, criterion_ids):
    if not isinstance(refs,list) or len(refs)>50:raise ValueError('BOUNDED_CODE_EVIDENCE_REQUIRED')
    results=[]
    for ref in refs:
        acceptance.validate('verification-v1.schema.json','CodeEvidenceRef',ref)
        if ref['criterion_id'] not in criterion_ids:raise ValueError('UNKNOWN_EVIDENCE_CRITERION')
        result={**ref,'provenance':'collector_file_read','bound':False,'current':False,'path':None,'sha256':None}
        with store.connect() as db:
            source=db.execute('SELECT s.* FROM sources s JOIN sessions t ON t.id=s.session WHERE s.id=? AND t.workspace=?',
                              (ref['source_id'],str(store.workspace))).fetchone()
        if source is not None and source['origin']=='collector_file_read':
            result.update(path=source['locator'],sha256=source['digest'])
            try:
                result['current']=file_sha(store.ledger.path(source['locator']))==source['digest']
                if 'quote' in ref:result['bound']=ref['quote'] in source['content']
                else:pointer_value(source['content'],ref['pointer']);result['bound']=True
            except (OSError,ValueError,KeyError,IndexError,TypeError):pass
        results.append(result)
    return results


def freshness(store, conditions, receipt=None, code_evidence=None):
    reasons=[]
    try:acceptance.current(store,conditions)
    except ValueError:reasons.append('DECISION_CONFIRMATION_OR_ACCEPTANCE_CHANGED')
    for entry in code_evidence or []:
        if not entry['current'] or not entry['bound']:reasons.append('CODE_EVIDENCE_UNVERIFIED')
        elif entry['path']:
            try:
                if file_sha(store.ledger.path(entry['path']))!=entry['sha256']:reasons.append('CODE_EVIDENCE_CHANGED')
            except (OSError,ValueError):reasons.append('CODE_EVIDENCE_UNAVAILABLE')
    if receipt is not None:
        if receipt['adapter_version']!=ADAPTER_VERSION or receipt['rule_version']!=RULE_VERSION or receipt['runtime_digest']!=runtime_digest():
            reasons.append('VERIFIER_RUNTIME_CHANGED')
        if receipt['before']!=receipt['after'] or receipt['manifest_sha256']!=receipt['manifest_after_sha256']:
            reasons.append('INPUT_CHANGED_DURING_EXECUTION')
        if receipt['environment']['digest']!=receipt['environment_after_digest']:reasons.append('ENVIRONMENT_CHANGED_DURING_EXECUTION')
        try:
            if input_snapshot(store,receipt['manifest'])!=receipt['before']:reasons.append('INPUT_SNAPSHOT_CHANGED')
            if file_sha(store.ledger.path(receipt['manifest_path']))!=receipt['manifest_sha256']:reasons.append('MANIFEST_CHANGED')
        except (OSError,ValueError):reasons.append('INPUT_OR_MANIFEST_UNAVAILABLE')
        if not environment_current(receipt['environment']):reasons.append('EXECUTION_ENVIRONMENT_CHANGED')
        directory=artifact_directory(store,receipt['execution_id'])
        for name,key in [('report.json','report_sha256'),('output.log','log_sha256')]:
            expected=receipt[key]
            if expected is None:continue
            try:
                path=directory/name
                if path.is_symlink() or file_sha(path)!=expected:reasons.append('EXECUTION_ARTIFACT_CHANGED')
            except OSError:reasons.append('EXECUTION_ARTIFACT_UNAVAILABLE')
    return sorted(set(reasons))


def present(store, run):
    reasons=[]
    try:
        conditions=acceptance.get(store,run['acceptance_id'])
        receipt=execution(store,conditions,run['execution_id']) if run['execution_id'] else None
        reasons=freshness(store,conditions,receipt,run['code_evidence'])
        if run['rule_version']!=RULE_VERSION or run['runtime_digest']!=runtime_digest():reasons.append('VERIFIER_RUNTIME_CHANGED')
    except (OSError,ValueError,KeyError,ValidationError):reasons=['VERIFICATION_BINDING_UNAVAILABLE']
    return {**run,'applicability':'stale' if reasons else 'current','stale_reasons':sorted(set(reasons)),
            'current_pass':run['verdict']=='passed' and not reasons}


def verify(store, task, decision_id, revision, acceptance_id, refs, execution_id, key):
    if type(revision) is not int or not isinstance(key,str) or not 1<=len(key)<=150:raise ValueError('VALID_REVISION_AND_IDEMPOTENCY_KEY_REQUIRED')
    conditions=acceptance.get(store,acceptance_id)
    if (conditions['task_id'],conditions['decision_id'],conditions['decision_revision'])!=(task['id'],decision_id,revision):
        raise ValueError('ACCEPTANCE_SCOPE_MISMATCH')
    acceptance.current(store,conditions)
    given={'decision_id':decision_id,'revision':revision,'acceptance_id':acceptance_id,'refs':refs,'execution_id':execution_id}
    with store.connect() as db:
        cached=db.execute("SELECT * FROM decision_v3_operations WHERE task_id=? AND operation='verify' AND key=?",(task['id'],key)).fetchone()
    if cached:
        if cached['input_digest']!=fingerprint(given):raise ValueError('IDEMPOTENCY_INPUT_CHANGED')
        return present(store,json.loads(cached['response_json']))
    code=static_evidence(store,refs,{c['criterion_id'] for c in conditions['criteria']})
    receipt=execution(store,conditions,execution_id) if execution_id else None
    stale=freshness(store,conditions,receipt,code)
    cases=(receipt['report'] or {}).get('cases',[]) if receipt else []
    results=[]
    for criterion in conditions['criteria']:
        matched=[c for c in cases if c['test_id'] in criterion['test_ids']]
        statuses={c['status'] for c in matched}
        seen={c['test_id'] for c in matched}
        reason='MISSING_TRUSTED_BEHAVIOR_EXECUTION';verdict='inconclusive'
        if receipt and not stale:
            if 'failed' in statuses:verdict='failed';reason='OBSERVED_ASSERTION_FAILED'
            elif receipt['execution_status']!='completed' or receipt['exit_code'] not in (0,1) or 'error' in statuses:
                verdict='error';reason='EXECUTION_ERROR'
            elif set(criterion['test_ids'])<=seen and statuses=={'passed'} and (receipt['report'] or {}).get('tests_run',0)>0:
                verdict='passed';reason='DECLARED_TESTS_OBSERVED_PASSED'
            elif receipt['exit_code']!=0 and any(c['status']=='error' for c in cases):verdict='error';reason='EXECUTION_ERROR'
            else:reason='MISSING_SKIPPED_OR_UNMAPPED_TESTS'
        elif stale:reason='EVIDENCE_NOT_CURRENT'
        results.append({'criterion_id':criterion['criterion_id'],'required':criterion['required'],'verdict':verdict,
            'reason':reason,'test_ids':criterion['test_ids'],'observed_cases':matched,
            'static_evidence':[e for e in code if e['criterion_id']==criterion['criterion_id']],
            'behavior_provenance':receipt['provenance'] if receipt else None})
    required=[r['verdict'] for r in results if r['required']]
    verdict='failed' if any(r['verdict']=='failed' for r in results) else 'error' if 'error' in required else 'inconclusive' if any(v!='passed' for v in required) else 'passed'
    if verdict=='passed' and receipt and receipt['exit_code']!=0:verdict='error'
    run={'schema_version':'verification.v1','verification_id':'verify-'+uuid.uuid4().hex,'task_id':task['id'],
        'decision_id':decision_id,'decision_revision':revision,'acceptance_id':acceptance_id,'acceptance_digest':conditions['acceptance_digest'],
        'execution_id':execution_id,'created':now(),'verdict':verdict,'criteria':results,'code_evidence':code,
        'input_snapshot':receipt['before'] if receipt else None,'rule_version':RULE_VERSION,'runtime_digest':runtime_digest(),
        'scope':'Agent-derived conditions; declared file and environment manifest; observed test cases only. Static evidence is not behavior proof.',
        'execution_summary':None if receipt is None else {'status':receipt['execution_status'],'exit_code':receipt['exit_code'],
             'tests_run':(receipt['report'] or {}).get('tests_run',0)},'coverage_complete':False}
    acceptance.validate('verification-v1.schema.json','VerificationRun',run)
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        acceptance.confirmed(store,task['id'],decision_id,revision,db)
        # Do not accept a concurrent replacement of the acceptance set.
        rows=db.execute("SELECT data_json FROM decision_v3_events WHERE task_id=? AND event_type='ACCEPTANCE_PREPARED' ORDER BY id DESC",(task['id'],)).fetchall()
        latest=next(json.loads(row[0]) for row in rows if json.loads(row[0])['decision_id']==decision_id)
        if latest['acceptance_id']!=acceptance_id:raise ValueError('ACCEPTANCE_SUPERSEDED')
        db.execute('INSERT INTO decision_v3_operations VALUES(?,?,?,?,?)',(task['id'],'verify',key,fingerprint(given),encode(run)))
        store.event(db,task['id'],'VERIFICATION_RECORDED',run)
    return present(store,run)


def status(store, task_id):
    sets=acceptance.events(store,'ACCEPTANCE_PREPARED',task_id)
    runs=acceptance.events(store,'VERIFICATION_RECORDED',task_id)
    latest_sets={a['decision_id']:a for a in sets}
    latest_runs={r['decision_id']:r for r in runs}
    conditions=[]
    for value in latest_sets.values():
        try:acceptance.current(store,value);applicability='current'
        except ValueError:applicability='stale'
        conditions.append({**value,'applicability':applicability})
    return {'acceptance_sets':conditions,'verifications':[present(store,r) for r in latest_runs.values()],
            'history_counts':{'acceptance_sets':len(sets),'verifications':len(runs)}}
