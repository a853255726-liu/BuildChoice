"""Bounded explicit file manifests and actual execution-environment fingerprints."""
import hashlib
import importlib.metadata
import os
from pathlib import Path
import sys
from .acceptance import validate
from .audit import MAX_BYTES, linked_path
from .common import ROOT, file_sha
from .decision_store import fingerprint

ADAPTER_VERSION='python-unittest-v1.0'
RULE_VERSION='acceptance-verification-v1.0'


def manifest(store, value):
    validate('verification-v1.schema.json','InputManifest',value)
    files=[p for group in value['files'].values() for p in group]
    if len(files)!=len(set(files)):raise ValueError('DUPLICATE_MANIFEST_PATH')
    if value['test_file'] not in value['files']['tests']:raise ValueError('TEST_ENTRY_NOT_IN_MANIFEST')
    if not value['test_file'].endswith('.py'):raise ValueError('PYTHON_TEST_ENTRY_REQUIRED')
    for path in files:store.ledger.path(path)
    return value


def input_snapshot(store, value):
    files={}
    for kind,paths in value['files'].items():
        for path in paths:
            file=store.ledger.path(path)
            with file.open('rb') as stream:data=stream.read(MAX_BYTES+1)
            if len(data)>MAX_BYTES:raise ValueError('MANIFEST_FILE_TOO_LARGE')
            files[path]={'kind':kind,'sha256':hashlib.sha256(data).hexdigest()}
    return {'files':files,'manifest_digest':fingerprint(value),'digest':fingerprint({'manifest':value,'files':files})}


def environment_snapshot(dependencies):
    # These paths originate in this collector, never in arbitrary MCP arguments.
    paths={Path(sys.executable).resolve()}
    packages={}
    for name in dependencies:
        distribution=importlib.metadata.distribution(name)
        packages[name]=distribution.version
        for file in distribution.files or []:
            path=Path(distribution.locate_file(file)).resolve()
            if path.is_file() and path.suffix not in ('.pyc','.pyo') and '__pycache__' not in path.parts:
                paths.add(path)
    browser=os.environ.get('BUILDCHOICE_TEST_BROWSER')
    if browser:
        path=Path(browser).resolve(strict=True);paths.add(path)
        # Chrome/Edge's main engine lives beside a versioned directory.
        for sibling in path.parent.glob('*/chrome.dll'):paths.add(sibling.resolve())
        for sibling in path.parent.glob('*/msedge.dll'):paths.add(sibling.resolve())
    if len(paths)>1500:raise ValueError('ENVIRONMENT_FILE_LIMIT')
    files={str(p):file_sha(p) for p in sorted(paths)}
    body={'python':sys.version,'packages':packages,'files':files,'selected_browser':str(Path(browser).resolve()) if browser else None}
    return {**body,'digest':fingerprint(body),
            'scope':'collector interpreter, declared distributions and explicitly selected browser engine files; not all transitive system dependencies'}


def runtime_digest():
    names=['buildchoice/desktop/'+name for name in ('acceptance.py','verification_inputs.py','verification.py','verification_runner.py','verification_worker.py')]
    names+=['scripts/buildchoice_test_worker.py','scripts/buildchoice_run_verification.py',
            'docs/contracts/acceptance-v1.schema.json','docs/contracts/verification-v1.schema.json']
    return fingerprint({name:file_sha(ROOT/name) for name in names})


def environment_current(value):
    try:return environment_snapshot(list(value['packages']))['digest']==value['digest']
    except (OSError,ValueError,ImportError):return False


def artifact_directory(store, execution_id, create=False):
    import re
    if not re.fullmatch(r'exec-[0-9a-f]{32}',execution_id):raise ValueError('INVALID_EXECUTION_ID')
    path=store.workspace
    for part in ('.buildchoice_audit','verification_runs',execution_id):
        path=path/part
        if linked_path(path):raise ValueError('LINKED_ARTIFACT_PATH')
    if not path.resolve().is_relative_to(store.workspace):raise ValueError('ARTIFACT_PATH_ESCAPE')
    if create:path.mkdir(parents=True,exist_ok=False)
    return path
