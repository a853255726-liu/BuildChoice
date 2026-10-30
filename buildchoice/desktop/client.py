"""Small HTTP client and hidden worker launcher; no torch/model imports."""
import csv
import json
import os
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from buildchoice.desktop.common import ROOT, DEFAULT_CONFIG, local_path, read_config


class LocalServiceError(RuntimeError):
    pass


def token_for(config):
    path = local_path(config['service']['token_file'])
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        for _ in range(100):
            token = path.read_text(encoding='ascii').strip()
            if len(token) >= 32:
                return token
            time.sleep(0.02)
        raise LocalServiceError('INVALID_LOCAL_TOKEN_FILE')
    with os.fdopen(fd, 'w', encoding='ascii') as f:
        if os.name == 'nt':
            result = subprocess.run(['whoami', '/user', '/fo', 'csv', '/nh'],
                                    capture_output=True, text=True, check=True,
                                    creationflags=subprocess.CREATE_NO_WINDOW)
            sid = config['service'].get('windows_owner_sid') or next(csv.reader(result.stdout.strip().splitlines()))[1]
            subprocess.run(['icacls', str(path), '/inheritance:r', '/grant:r',
                            '*' + sid + ':(F)', '*S-1-5-18:(F)'],
                           check=True, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        token = secrets.token_urlsafe(48)
        f.write(token)
    return token


class BuildChoiceClient:
    def __init__(self, config_path=DEFAULT_CONFIG):
        self.config_path = Path(config_path).resolve()
        self.config = read_config(self.config_path)
        self.token = token_for(self.config)
        self.url = 'http://127.0.0.1:' + str(self.config['service']['port'])
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def call(self, path, data=None, timeout=2):
        request = urllib.request.Request(self.url + path,
                                        data=json.dumps(data, ensure_ascii=False).encode() if data is not None else None,
                                        headers={'Authorization': 'Bearer ' + self.token,
                                                 'Content-Type': 'application/json'})
        try:
            with self.opener.open(request, timeout=timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as e:
            if e.code == 503:
                return json.load(e)
            raise LocalServiceError('LOCAL_HTTP_' + str(e.code)) from e

    def ensure(self):
        try:
            status = self.call('/healthz')
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            directory = local_path(self.config['service']['log_directory'])
            directory.mkdir(parents=True, exist_ok=True)
            with (directory / 'worker.stdout.log').open('ab') as out, (directory / 'worker.stderr.log').open('ab') as err:
                subprocess.Popen([sys.executable, '-m', 'buildchoice.desktop.service',
                                  '--config', str(self.config_path)], cwd=ROOT,
                                 stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                                 env={**os.environ, 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8',
                                      'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1'},
                                 creationflags=(subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP)
                                 if os.name == 'nt' else 0, close_fds=True)
            status = None
        deadline = time.monotonic() + self.config['service']['startup_timeout_seconds']
        while time.monotonic() < deadline:
            if status:
                if status.get('service') != 'buildchoice':
                    raise LocalServiceError('WRONG_SERVICE_ON_CONFIGURED_PORT')
                if status.get('config_sha256') != self.config['_config_sha256']:
                    raise LocalServiceError('CONFIG_CHANGED_RESTART_WORKER')
                if status['status'] == 'OK':
                    return status
                if status['status'] == 'ERROR':
                    raise LocalServiceError(status['error_code'])
            time.sleep(0.2)
            try:
                status = self.call('/healthz')
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                status = None
        raise LocalServiceError('MODEL_STARTUP_TIMEOUT')

    def status(self):
        try:
            result = self.call('/healthz')
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            return self.ensure()
        if result.get('config_sha256') != self.config['_config_sha256']:
            raise LocalServiceError('CONFIG_CHANGED_RESTART_WORKER')
        return result

    def assess(self, request):
        self.ensure()
        return self.call('/v1/assess', request,
                         timeout=self.config['service']['request_timeout_seconds'])


def failure(exc):
    from buildchoice.desktop.auto_call import FeatureDisabledError
    if isinstance(exc, FeatureDisabledError):
        return {'status': 'DISABLED', 'action': None, 'task_executed': False, 'reason': 'FEATURE_DISABLED'}
    return {'status': 'ERROR' if isinstance(exc, LocalServiceError) and
            ('FAILED' in str(exc) or 'HTTP_' in str(exc)) else 'NOT_READY',
            'action': None, 'task_executed': False,
            'reason': str(exc) if isinstance(exc, LocalServiceError) else 'LOCAL_SERVICE_UNAVAILABLE'}
