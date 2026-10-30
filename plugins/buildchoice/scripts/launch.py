"""Dependency-free launcher shared by the installed MCP server and its four Hooks."""
import json
import os
import subprocess
import sys
from pathlib import Path


def data_home():
    return Path(os.environ.get('BUILDCHOICE_DATA') or Path.home()/'.buildchoice').resolve()


def binding(home=None):
    value = json.loads((Path(home) if home else data_home()).joinpath('binding.json').read_text(encoding='utf-8'))
    if value.get('binding_version') != 1 or not all(isinstance(value.get(k),str) and Path(value[k]).is_absolute()
            for k in ('python','runtime_root','workspace')):
        raise ValueError('Invalid BuildChoice installation binding')
    for key in ('python','runtime_root','workspace'):
        if not Path(value[key]).exists():
            raise ValueError('Missing installation path: ' + key)
    return value


def run(kind='mcp',home=None):
    try:
        value = binding(home)
        root = Path(value['runtime_root'])
        script = root/'scripts'/('buildchoice_mcp.py' if kind == 'mcp' else 'buildchoice_required_call_hook.py')
        command = [value['python'],str(script)] + (['--native-settings'] if kind == 'mcp' else [])
        return subprocess.call(command, cwd=root, env={**os.environ,
            'BUILDCHOICE_WORKSPACE':value['workspace'], 'PYTHONUTF8':'1','PYTHONIOENCODING':'utf-8'},
            stdin=sys.stdin.buffer,stdout=sys.stdout.buffer,stderr=sys.stderr.buffer,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    except Exception as error:
        print('BuildChoice setup required: run setup.py before enabling this plugin. '+type(error).__name__,file=sys.stderr)
        # An uninitialized global hook must not block unrelated projects.
        return 1 if kind == 'mcp' else 0


if __name__ == '__main__':
    sys.exit(run())
