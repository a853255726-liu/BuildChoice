"""Dependency-free launcher shared by the installed MCP server and its prompt Hook."""
import json
import os
import hashlib
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


def data_home():
    return Path(os.environ.get('BUILDCHOICE_DATA') or Path.home()/'.buildchoice').resolve()


def project_id(workspace):
    return hashlib.sha256(os.path.normcase(str(Path(workspace).resolve())).encode()).hexdigest()[:20]


def write_json(path, value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        temporary.replace(path)
    finally:temporary.unlink(missing_ok=True)


@contextmanager
def registry_lock(home):
    lock=Path(home)/'.projects.lock';deadline=time.monotonic()+5
    while True:
        try:descriptor=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY);break
        except FileExistsError:
            if time.monotonic()>deadline:raise ValueError('Another project setup is in progress')
            time.sleep(.05)
    try:yield
    finally:os.close(descriptor);lock.unlink()


def projects(home=None):
    home=Path(home) if home else data_home()
    path=home/'projects.json'
    if path.exists():
        value=json.loads(path.read_text(encoding='utf-8'))
        if value.get('registry_version')!=1:raise ValueError('Invalid project registry')
        return value
    return {'registry_version':1,'active_project':None,'projects':{}}


def register(home, value):
    home=Path(home)
    with registry_lock(home):
        registry=projects(home)
        legacy=home/'binding.json'
        if not registry['projects'] and legacy.exists():
            old=json.loads(legacy.read_text(encoding='utf-8'))
            registry['projects'][project_id(old['workspace'])]=old
        ident=project_id(value['workspace'])
        registry['projects'][ident]=value;registry['active_project']=ident
        write_json(home/'projects'/ident/'binding.json',value)
        write_json(home/'projects.json',registry)
        # Keep the former active-binding entry readable by older diagnostics.
        write_json(home/'binding.json',value)


def select_project(workspace,home=None):
    home=Path(home) if home else data_home()
    with registry_lock(home):
        registry=projects(home);ident=project_id(workspace)
        if ident not in registry['projects']:raise ValueError('Project is not registered; run setup.py --workspace first')
        registry['active_project']=ident
        write_json(home/'projects.json',registry)
        write_json(home/'binding.json',registry['projects'][ident])
    return binding(home,workspace)


def binding(home=None,workspace=None):
    home=Path(home) if home else data_home()
    registry=projects(home)
    if registry['projects']:
        requested=workspace or os.environ.get('BUILDCHOICE_WORKSPACE')
        cwd=Path(requested or Path.cwd()).resolve()
        matches=[v for v in registry['projects'].values() if cwd.is_relative_to(Path(v['workspace']))]
        if requested and not matches:raise ValueError('Requested project is not registered')
        value=max(matches,key=lambda v:len(Path(v['workspace']).parts)) if matches else registry['projects'][registry['active_project']]
    else:
        value=json.loads((home/'binding.json').read_text(encoding='utf-8'))
        if workspace is not None and not Path(workspace).resolve().is_relative_to(Path(value['workspace']).resolve()):
            raise ValueError('Requested project does not match the legacy binding')
    if value.get('binding_version') != 1 or not all(isinstance(value.get(k),str) and Path(value[k]).is_absolute()
            for k in ('python','runtime_root','workspace')):
        raise ValueError('Invalid BuildChoice installation binding')
    for key in ('python','runtime_root','workspace'):
        if not Path(value[key]).exists():
            raise ValueError('Missing installation path: ' + key)
    return value


def run(kind='mcp',home=None):
    try:
        raw=None;workspace=None
        if kind=='hook':
            raw=sys.stdin.buffer.read(2*1024*1024+1)
            if len(raw)>2*1024*1024:return 0
            event=json.loads(raw.decode('utf-8'));workspace=event.get('cwd')
            if not isinstance(workspace,str):return 0
        value = binding(home,workspace)
        root = Path(value['runtime_root'])
        script = root/'scripts'/('buildchoice_mcp.py' if kind == 'mcp' else 'buildchoice_hook.py')
        command = [value['python'],str(script)] + (['--native-settings'] if kind == 'mcp' else [])
        env={**os.environ,'BUILDCHOICE_WORKSPACE':value['workspace'],'PYTHONUTF8':'1','PYTHONIOENCODING':'utf-8'}
        if value.get('profile_home'):
            profile=Path(value['profile_home'])
            env.update(BUILDCHOICE_SETTINGS=str(profile/'configs/buildchoice.json'),
                       BUILDCHOICE_V3_SETTINGS=str(profile/'configs/decision_v3.json'))
        options={'cwd':value['workspace'],'env':env,'stdout':sys.stdout.buffer,'stderr':sys.stderr.buffer,
                 'creationflags':subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0}
        if raw is not None:return subprocess.run(command,input=raw,**options).returncode
        return subprocess.call(command,stdin=sys.stdin.buffer,**options)
    except Exception as error:
        print('BuildChoice setup required: run setup.py before enabling this plugin. '+type(error).__name__,file=sys.stderr)
        # An uninitialized global hook must not block unrelated projects.
        return 1 if kind == 'mcp' else 0


if __name__ == '__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--data-home')
    sys.exit(run(home=parser.parse_args().data_home))
