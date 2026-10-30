"""One initializer for model resources, Python dependencies and local plugin installation.

stdlib only until dependencies are prepared. No automatic trust or authentication changes.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import venv
import zipfile
from pathlib import Path, PurePosixPath

PACKAGE = Path(__file__).resolve().parent
sys.path.insert(0,str(PACKAGE/'scripts'))
from launch import data_home


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()


def extract_bundle(bundle, destination):
    """Verify every member before publishing an extracted runtime directory."""
    bundle, destination = Path(bundle), Path(destination)
    if destination.exists():
        raise ValueError('Destination already exists; use a new installation directory')
    with zipfile.ZipFile(bundle) as archive:
        index = json.loads(archive.read('runtime_manifest.json'))
        if index.get('bundle_version') != 1 or not isinstance(index.get('files'),dict):
            raise ValueError('Invalid runtime bundle manifest')
        expected = set(index['files']) | {'runtime_manifest.json'}
        names = archive.namelist()
        if len(names)>10000 or len(set(names)) != len(names) or set(names) != expected:
            raise ValueError('Unexpected or duplicate archive members')
        if sum(archive.getinfo(name).file_size for name in names)>2*1024**3:
            raise ValueError('Runtime archive is too large')
        for name in names:
            path = PurePosixPath(name)
            item = archive.getinfo(name)
            if (not name or '\\' in name or ':' in name or path.is_absolute() or '..' in path.parts or
                    item.is_dir() or (item.external_attr >> 16) & 0o170000 == 0o120000):
                raise ValueError('Unsafe runtime archive member')
        destination.parent.mkdir(parents=True,exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix='gate-unpack-',dir=destination.parent))
        try:
            for name in names:
                target = staging/name
                target.parent.mkdir(parents=True,exist_ok=True)
                with archive.open(name) as source, target.open('wb') as out:
                    shutil.copyfileobj(source,out)
                if name in index['files']:
                    entry = index['files'][name]
                    if target.stat().st_size != entry['bytes'] or sha(target) != entry['sha256']:
                        raise ValueError('Runtime member checksum failed: '+name)
            staging.replace(destination)
        finally:
            if staging.exists():
                # Only our newly-created staging directory is removed, never an existing installation.
                if staging.resolve().parent != destination.parent.resolve() or not staging.name.startswith('gate-unpack-'):
                    raise ValueError('Refusing cleanup outside the installation staging directory')
                shutil.rmtree(staging)
    return index


def prepare_python(home, reuse=None, with_classifier=False):
    if reuse:
        python = Path(reuse).resolve()
    else:
        environment = home/'venv'
        if not environment.exists():
            venv.EnvBuilder(with_pip=True).create(environment)
        python = environment/('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        # Only initializer runs installers. Installing the plugin never runs package-manager lifecycle scripts.
        subprocess.run([str(python),'-m','pip','install','-r',str(PACKAGE/'requirements-core.txt')],check=True)
        if with_classifier:
            subprocess.run([str(python),'-m','pip','install','torch==2.11.0',
                            '--index-url','https://download.pytorch.org/whl/cpu'],check=True)
            subprocess.run([str(python),'-m','pip','install','-r',str(PACKAGE/'requirements-model.txt')],check=True)
    imports = 'mcp,jsonschema,openai_codex' + (',torch,transformers,peft' if with_classifier else '')
    check = subprocess.run([str(python),'-c',
        'import sys,'+imports+'; '
        'assert sys.version_info >= (3,11); print("DEPENDENCIES_OK")'],
        capture_output=True,text=True,check=True)
    if 'DEPENDENCIES_OK' not in check.stdout:
        raise ValueError('Python dependencies failed validation')
    return python


def initialize(workspace, *, bundle=None, runtime_root=None, reuse_python=None, home=None, port=8769, device='cpu', with_classifier=False):
    home = Path(home or data_home()).resolve()
    workspace = Path(workspace).resolve(strict=True)
    if not workspace.is_dir() or not 1024 <= port <= 65535:
        raise ValueError('Invalid workspace or loopback port')
    home.mkdir(parents=True,exist_ok=True)
    old_binding = home/'binding.json'
    if old_binding.exists():
        old = json.loads(old_binding.read_text(encoding='utf-8'))
        if old['workspace'] != str(workspace):
            raise ValueError('Existing installation targets another workspace; select another data directory')
    if runtime_root:
        root = Path(runtime_root).resolve(strict=True)
        if bundle:
            raise ValueError('Choose bundle or existing runtime, not both')
    else:
        if not bundle:
            raise ValueError('A runtime bundle is required for a clean installation')
        root = home/'runtime'
        if not root.exists():
            extract_bundle(bundle,root)
        else:
            # Do not replace a running installation or overwrite its models/config on a repeated setup.
            manifest = json.loads((root/'runtime_manifest.json').read_text(encoding='utf-8'))
            if manifest.get('bundle_version') != 1:
                raise ValueError('Existing runtime is invalid')
    for member in ('scripts/codex_gate_mcp.py','configs/codex_desktop_gate.toml',
                   'docs/contracts/gate-v1.schema.json'):
        if not (root/member).is_file():
            raise ValueError('Runtime is missing '+member)
    python = prepare_python(home,reuse_python,with_classifier)
    if not runtime_root and not old_binding.exists():
        config = root/'configs/codex_desktop_gate.toml'
        text = config.read_text(encoding='utf-8').replace('port = 8769',f'port = {port}').replace('device = "cpu"',f'device = "{device}"')
        config.write_text(text,encoding='utf-8')
    # New installations default to Prompt-first; existing workspace selections are preserved.
    switch = root/'configs/gate_auto_call.json'
    if not switch.exists():
        subprocess.run([str(python),str(root/'scripts/gate_auto_call.py'),'prompt'],
                       cwd=root,stdout=subprocess.DEVNULL,check=True)
    value = {'binding_version':1,'python':str(python),'runtime_root':str(root),'workspace':str(workspace)}
    temporary = home/'binding.tmp'
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    temporary.replace(old_binding)
    return {'initialized':True,**value,'data_home':str(home),'hook_trust_modified':False}


def install(workspace, python, home):
    # The marketplace lives beside this self-contained plugin, so no original checkout path is required.
    script = (PACKAGE/'install_local.py')
    subprocess.run([str(python),str(script),'--workspace',str(workspace)],
                   env={**os.environ,'CLARIFICATION_GATE_DATA':str(home)},check=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--workspace',type=Path,required=True)
    parser.add_argument('--bundle',type=Path)
    parser.add_argument('--runtime-root',type=Path)
    parser.add_argument('--reuse-python',type=Path)
    parser.add_argument('--data-home',type=Path)
    parser.add_argument('--port',type=int,default=8769)
    parser.add_argument('--device',choices=['cpu','cuda:0'],default='cpu')
    parser.add_argument('--install',action='store_true')
    parser.add_argument('--with-classifier',action='store_true',help='Optional model dependencies; use a model-inclusive bundle')
    args = parser.parse_args()
    report = initialize(args.workspace,bundle=args.bundle,runtime_root=args.runtime_root,
        reuse_python=args.reuse_python,home=args.data_home,port=args.port,device=args.device,with_classifier=args.with_classifier)
    print(json.dumps(report,ensure_ascii=False,indent=2))
    if args.install:
        install(args.workspace,report['python'],report['data_home'])
