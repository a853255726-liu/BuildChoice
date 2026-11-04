"""Initialize the source runtime, Python dependencies and local plugin installation.

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
from launch import data_home,project_id,register,projects,select_project,write_json


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
        staging = Path(tempfile.mkdtemp(prefix='buildchoice-unpack-',dir=destination.parent))
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
                if staging.resolve().parent != destination.parent.resolve() or not staging.name.startswith('buildchoice-unpack-'):
                    raise ValueError('Refusing cleanup outside the installation staging directory')
                shutil.rmtree(staging)
    return index


def prepare_python(home, reuse=None):
    if reuse:
        python = Path(reuse).resolve()
    else:
        environment = home/'venv'
        if not environment.exists():
            venv.EnvBuilder(with_pip=True).create(environment)
        python = environment/('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        # Only initializer runs installers. Installing the plugin never runs package-manager lifecycle scripts.
        subprocess.run([str(python),'-m','pip','install','-r',str(PACKAGE/'requirements-core.txt')],check=True)
    imports = 'mcp,jsonschema,openai_codex'
    check = subprocess.run([str(python),'-c',
        'import sys,'+imports+'; '
        'assert sys.version_info >= (3,11); print("DEPENDENCIES_OK")'],
        capture_output=True,text=True,check=True)
    if 'DEPENDENCIES_OK' not in check.stdout:
        raise ValueError('Python dependencies failed validation')
    return python


def initialize(workspace, *, bundle=None, runtime_root=None, reuse_python=None, home=None, decision_mode=None):
    home=Path(home or data_home()).resolve()
    workspace=Path(workspace).resolve(strict=True)
    if not workspace.is_dir():raise ValueError('Invalid workspace')
    if decision_mode not in (None,'pilot','off'):raise ValueError('Invalid decision mode')
    if home.is_relative_to(PACKAGE):raise ValueError('Choose a data directory outside the source package')
    ident=project_id(workspace);profile=home/'projects'/ident
    if runtime_root:
        root=Path(runtime_root).resolve(strict=True)
        if bundle:raise ValueError('Choose bundle or existing runtime, not both')
        if home.is_relative_to(root):raise ValueError('Choose a data directory outside the runtime source')
    else:
        if not bundle:raise ValueError('A runtime bundle is required for a clean installation')
        root=profile/'runtime'
        if not root.exists():extract_bundle(bundle,root)
        elif json.loads((root/'runtime_manifest.json').read_text(encoding='utf-8')).get('bundle_version')!=1:
            raise ValueError('Existing runtime is invalid')
    for member in ('scripts/buildchoice_mcp.py','scripts/buildchoice_hook.py','buildchoice/desktop/settings.py',
                   'docs/contracts/decision-v3.schema.json'):
        if not (root/member).is_file():raise ValueError('Runtime is missing '+member)
    home.mkdir(parents=True,exist_ok=True);profile.mkdir(parents=True,exist_ok=True)
    python=prepare_python(home,reuse_python)
    for name in ('buildchoice.json','decision_v3.json'):
        target=profile/'configs'/name
        if not target.exists():write_json(target,json.loads((root/'configs'/name).read_text(encoding='utf-8')))
    if decision_mode is not None:
        target=profile/'configs/decision_v3.json'
        config=json.loads(target.read_text(encoding='utf-8'));config['mode']=decision_mode;write_json(target,config)
    value={'binding_version':1,'python':str(python),'runtime_root':str(root),'workspace':str(workspace),
           'project_id':ident,'profile_home':str(profile)}
    sys.path.insert(0,str(PACKAGE))
    from installation import prepare_installation
    package,marketplace=prepare_installation(PACKAGE,value,home)
    value.update(plugin_root=str(package),marketplace=str(marketplace))
    register(home,value)
    return {'initialized':True,**value,'data_home':str(home),'hook_trust_modified':False}


def install(workspace, python, home):
    # The marketplace lives beside this self-contained plugin, so no original checkout path is required.
    script = (PACKAGE/'install_local.py')
    subprocess.run([str(python),str(script),'--workspace',str(workspace)],
                   env={**os.environ,'BUILDCHOICE_DATA':str(home)},check=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--workspace',type=Path)
    parser.add_argument('--list-projects',action='store_true')
    parser.add_argument('--use-project',type=Path)
    parser.add_argument('--decision-mode',choices=['pilot','off'])
    parser.add_argument('--bundle',type=Path)
    parser.add_argument('--runtime-root',type=Path)
    parser.add_argument('--reuse-python',type=Path)
    parser.add_argument('--data-home',type=Path)
    parser.add_argument('--install',action='store_true')
    args = parser.parse_args()
    if args.list_projects:
        if args.workspace or args.use_project or args.install:parser.error('--list-projects is read-only')
        print(json.dumps(projects(args.data_home or data_home()),ensure_ascii=False,indent=2))
        raise SystemExit(0)
    if args.use_project:
        if args.workspace or args.bundle or args.runtime_root:parser.error('Choose a new setup or an existing project')
        value=select_project(args.use_project,args.data_home)
        if args.decision_mode:
            if not value.get('profile_home'):parser.error('Reinitialize this legacy project before changing its settings')
            target=Path(value['profile_home'])/'configs/decision_v3.json'
            config=json.loads(target.read_text(encoding='utf-8'));config['mode']=args.decision_mode;write_json(target,config)
        report={'selected':True,**value,'data_home':str(args.data_home or data_home()),'requires_mcp_reconnect':True}
    else:
        if not args.workspace:parser.error('--workspace is required for initialization')
        report=initialize(args.workspace,bundle=args.bundle,runtime_root=args.runtime_root,
            reuse_python=args.reuse_python,home=args.data_home,decision_mode=args.decision_mode)
    print(json.dumps(report,ensure_ascii=False,indent=2))
    if args.install:install(report['workspace'],report['python'],report['data_home'])
