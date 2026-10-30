import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import uuid
import zipfile

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
from jsonschema import Draft202012Validator
from buildchoice.desktop.bundle import build_core_runtime, VERSION
from buildchoice.desktop.distribution import archive_plugin

out=Path(os.environ.get('BUILDCHOICE_CHECK_ROOT',tempfile.gettempdir())).resolve()/('buildchoice-package-check-'+uuid.uuid4().hex)
out.mkdir()
for path in root.rglob('*.py'):
    if not any(p in path.parts for p in ('__pycache__','.git')):
        ast.parse(path.read_text(encoding='utf-8'),filename=str(path))
for path in [root/'README.md',*(root/'docs').rglob('*.md'),*(root/'plugins/buildchoice').rglob('*.md')]:
    for href in re.findall(r'\]\(([^)]+)\)',path.read_text(encoding='utf-8')):
        if '://' not in href and not href.startswith('#'):
            assert (path.parent/href.split('#')[0]).exists(),(path,href)
for contract in ('decision-v3.schema.json','acceptance-v1.schema.json','verification-v1.schema.json'):
    schema=json.loads((root/'docs/contracts'/contract).read_text(encoding='utf-8'))
    Draft202012Validator.check_schema(schema)
for package in ['backends','predictor']:
    assert not list((root/'buildchoice'/package).glob('*.py'))
for path in (root/'buildchoice').rglob('*.py'):
    for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
        modules=[node.module or ''] if isinstance(node,ast.ImportFrom) else [n.name for n in node.names] if isinstance(node,ast.Import) else []
        assert not any(name.split('.')[0] in {'torch','transformers','peft','sentencepiece'} for name in modules)
archives=[build_core_runtime(out/f'buildchoice-core-{VERSION}.zip'),archive_plugin(out/f'buildchoice-plugin-{VERSION}.zip')]
for result in archives:
    path=Path(result['path'])
    assert hashlib.sha256(path.read_bytes()).hexdigest()==result['sha256']
    with zipfile.ZipFile(path) as archive:
        assert archive.testzip() is None
        assert not any('/backends/' in name or '/predictor/' in name or 'requirements-model' in name for name in archive.namelist())
        if 'core' in path.name:
            manifest=json.loads(archive.read('runtime_manifest.json'))
            assert manifest['package_version']==VERSION=='0.8.0'
            assert {'scripts/buildchoice_run_verification.py','scripts/buildchoice_test_worker.py',
                'docs/contracts/acceptance-v1.schema.json','docs/contracts/verification-v1.schema.json'}<=set(archive.namelist())
            assert not any('model' in name for name in archive.namelist())
            for name,entry in manifest['files'].items():
                data=archive.read(name)
                assert len(data)==entry['bytes'] and hashlib.sha256(data).hexdigest()==entry['sha256']
        else:
            plugin=json.loads(archive.read('buildchoice/.codex-plugin/plugin.json'))
            assert plugin['version']==VERSION
            assert set(json.loads(archive.read('buildchoice/hooks/hooks.json'))['hooks'])=={'UserPromptSubmit'}

# Initialize from the actual source and from the checksummed runtime bundle.
spec=importlib.util.spec_from_file_location('buildchoice_setup',root/'plugins/buildchoice/setup.py')
setup=importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)
for mode in ['source','bundle']:
    home=out/mode
    args={'runtime_root':root} if mode=='source' else {'bundle':Path(archives[0]['path'])}
    result=setup.initialize(out,reuse_python=sys.executable,home=home,**args)
    assert result['initialized'] and not result['hook_trust_modified']
    runtime=Path(result['runtime_root'])
    assert (runtime/'scripts/buildchoice_hook.py').exists()
    assert (runtime/'configs/buildchoice.json').exists()
    before=(out/'.buildchoice_audit').exists()
    doctor=subprocess.run([sys.executable,str(runtime/'scripts/buildchoice_doctor.py'),'--data-home',str(home),'--json'],
        capture_output=True,text=True,encoding='utf-8',check=True,timeout=30)
    diagnosis=json.loads(doctor.stdout)
    states={item['name']:item['status'] for item in diagnosis['checks']}
    assert states['binding']=='pass' and states['python_dependencies']=='pass' and states['local_mcp']=='pass',diagnosis
    assert states['host_plugin']=='unknown' and states['hook_trust']=='unknown'
    assert diagnosis['overall']=='unverified' and not diagnosis['hook_trust_modified']
    assert (out/'.buildchoice_audit').exists()==before
    env={**os.environ,'BUILDCHOICE_DATA':str(home)}
    event={'hook_event_name':'UserPromptSubmit','cwd':str(out),'session_id':'package-check','turn_id':'1','prompt':'解释一下'}
    run=subprocess.run([sys.executable,str(root/'plugins/buildchoice/scripts/buildchoice_plugin_hook.py')],
        input=json.dumps(event),capture_output=True,text=True,encoding='utf-8',env=env,check=True,timeout=20)
    assert json.loads(run.stdout)['hookSpecificOutput']['hookEventName']=='UserPromptSubmit'
    # Exercise the actual collector and verifier from each initialized runtime.
    from verification_helpers import setup_fixture,small_manifest
    fixture=setup_fixture();small_manifest(fixture)
    command=[sys.executable,str(runtime/'scripts/buildchoice_run_verification.py'),'--workspace',str(fixture['workspace']),
        '--acceptance-id',fixture['conditions']['acceptance_id'],'--manifest','manifest.json',
        '--settings',str(fixture['global_settings']),'--decision-settings',str(fixture['settings'])]
    execution=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',check=True,timeout=30)
    execution_id=json.loads(execution.stdout)['execution_id']
    code=('import json,sys; sys.path.insert(0,sys.argv[1]); '
          'from buildchoice.desktop.decision_store import DecisionStore; from buildchoice.desktop.verification import verify; '
          'value=verify(DecisionStore(sys.argv[2]),{"id":sys.argv[3]},sys.argv[4],1,sys.argv[5],[],sys.argv[6],"package"); '
          'print(json.dumps({"verdict":value["verdict"],"current_pass":value["current_pass"]}))')
    verified=subprocess.run([sys.executable,'-c',code,str(runtime),str(fixture['workspace']),fixture['task']['id'],
        fixture['item']['decision_id'],fixture['conditions']['acceptance_id'],execution_id],
        capture_output=True,text=True,encoding='utf-8',check=True,timeout=30)
    assert json.loads(verified.stdout)=={'verdict':'passed','current_pass':True},verified.stdout
print(json.dumps({'checks':'syntax, docs links, schema, no model imports/resources, ZIP hashes, source/bundle initialization and installed Hook launcher',
    'archives':archives,'source_and_bundle_observed_verification':'passed','live_codex_install':False},ensure_ascii=False,indent=2))
