"""Start, stop or query the lightweight local panel without restarting the model."""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from buildchoice.desktop.panel import DEFAULT_PORT


def main(command):
    url = f'http://127.0.0.1:{DEFAULT_PORT}'
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def get(path):
        with opener.open(url + path, timeout=2) as response:
            return json.load(response)
    try:
        health = get('/api/healthz')
        if health.get('service') != 'buildchoice-panel':
            raise RuntimeError('Another service occupies the panel port')
        alive = True
    except urllib.error.URLError:
        alive = False
    if command == 'stop':
        if alive:
            token = get('/api/session')['csrf']
            request = urllib.request.Request(url+'/api/shutdown', data=b'{}',
                                            headers={'Origin': url, 'X-BuildChoice-CSRF': token, 'Content-Type': 'application/json'})
            with opener.open(request, timeout=2) as response:
                json.load(response)
        return {'stopped': True}
    if not alive and command == 'start':
        directory = ROOT/'runs/buildchoice/panel'
        directory.mkdir(parents=True, exist_ok=True)
        with (directory/'stdout.log').open('ab') as out, (directory/'stderr.log').open('ab') as err:
            subprocess.Popen([sys.executable, '-m', 'buildchoice.desktop.panel'], cwd=ROOT,
                             stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                             env={**os.environ, 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'},
                             creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
                             if os.name == 'nt' else 0, close_fds=True)
        for _ in range(40):
            time.sleep(0.2)
            try:
                if get('/api/healthz').get('service') == 'buildchoice-panel':
                    alive = True
                    break
            except urllib.error.URLError:
                pass
    if not alive:
        raise RuntimeError('Panel is not running')
    return {'status': 'OK', 'url': url, 'service': 'buildchoice-panel'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['start', 'status', 'stop'], default='start', nargs='?')
    print(json.dumps(main(parser.parse_args().command)))
