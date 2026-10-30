import argparse
import importlib
import json
import logging
import os
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from jsonschema import ValidationError
from buildchoice.desktop.common import DEFAULT_CONFIG, local_path, read_config
from buildchoice.desktop.engine import BuildChoiceEngine


def serve(config_path=DEFAULT_CONFIG):
    config = read_config(config_path)
    service = config['service']
    token = local_path(service['token_file']).read_text(encoding='ascii').strip()
    if len(token) < 32:
        raise ValueError('Local service token is missing or invalid')
    active = config['buildchoice']['active_backend']
    spec = config['backends'][active]
    state = {'status': 'NOT_READY', 'engine': None, 'started_at': time.time(), 'error': None}
    audit_path = local_path(service['log_directory']) / 'events.jsonl'
    audit_lock = threading.Lock()
    slots = threading.BoundedSemaphore(4)

    def status():
        engine = state['engine']
        return {'service': 'buildchoice', 'status': state['status'], 'mode': 'advisory',
                'pid': os.getpid(), 'active_backend': active,
                'backend': engine.reference if engine else None,
                'config_sha256': config['_config_sha256'],
                'uptime_seconds': round(time.time() - state['started_at'], 2),
                'inference_count': getattr(engine.backend, 'inference_count', None) if engine else 0,
                'real_model': True, 'model_loaded': engine is not None, 'automatic_interception': False,
                'deployment_pass': False, 'task_executed': False,
                'error_code': state['error']}

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(65)

        def log_message(self, *args):
            pass

        def send_json(self, code, value):
            data = json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
            self.send_response(code)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            try:
                self.wfile.write(data)
            except (ConnectionError, OSError):
                # The requesting client may time out during a slow native-library import.
                pass

        def authorized(self):
            # Reject browser-origin calls, proxy hosts and all unauthenticated local requests.
            return (self.headers.get('Origin') is None and
                    self.headers.get('Host') == f"127.0.0.1:{service['port']}" and
                    secrets.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + token))

        def do_GET(self):
            if not self.authorized():
                return self.send_json(403, {'error': 'LOCAL_AUTH_REQUIRED'})
            if self.path not in ('/healthz', '/readyz'):
                return self.send_json(404, {'error': 'NOT_FOUND'})
            self.send_json(200 if state['status'] == 'OK' or self.path == '/healthz' else 503, status())

        def do_POST(self):
            if not self.authorized():
                return self.send_json(403, {'error': 'LOCAL_AUTH_REQUIRED'})
            if self.path == '/shutdown':
                self.send_json(200, {'stopping': True})
                threading.Thread(target=server.shutdown, daemon=True).start()
                return
            if self.path != '/v1/assess':
                return self.send_json(404, {'error': 'NOT_FOUND'})
            try:
                size = int(self.headers.get('Content-Length', '-1'))
            except ValueError:
                size = -1
            if not 0 < size <= 64000 or self.headers.get('Transfer-Encoding'):
                return self.send_json(413, {'status': 'UNSUPPORTED', 'action': None,
                                           'reason': 'INVALID_OR_OVERSIZE_BODY', 'task_executed': False})
            if state['status'] != 'OK':
                return self.send_json(503, {**status(), 'action': None})
            if not slots.acquire(blocking=False):
                return self.send_json(503, {'status': 'NOT_READY', 'action': None,
                                           'reason': 'QUEUE_FULL', 'task_executed': False})
            start = time.perf_counter()
            try:
                request = json.loads(self.rfile.read(size))
                result = state['engine'].evaluate(request)
                with audit_lock, audit_path.open('a', encoding='utf-8') as f:
                    f.write(json.dumps({'utc_epoch': time.time(), 'request_id': result['request_id'],
                                        'snapshot_sha256': request['snapshot']['snapshot_sha256'],
                                        'backend': result['backend'], 'status': result['status'],
                                        'action': result['action'],
                                        'latency_ms': round((time.perf_counter() - start) * 1000, 2)},
                                       ensure_ascii=False) + '\n')
                self.send_json(200, result)
            except (ValueError, TypeError, ValidationError, KeyError):
                self.send_json(400, {'status': 'UNSUPPORTED', 'action': None,
                                     'reason': 'INVALID_BUILDCHOICE_REQUEST', 'task_executed': False})
            finally:
                slots.release()

    # Bind before loading weights: racing launchers cannot allocate duplicate GPU models.
    server = ThreadingHTTPServer((service['bind'], service['port']), Handler)
    server.daemon_threads = True

    def load():
        try:
            module, name = spec['factory'].split(':', 1)
            if not module.startswith('buildchoice.backends.'):
                raise ValueError('Backend factory must be a trusted project adapter')
            backend = getattr(importlib.import_module(module), name)(
                manifest=spec['manifest'], expected_sha256=spec['manifest_sha256'],
                device=spec.get('device', 'cuda:0'))
            if backend.reference['backend_id'] != active:
                raise ValueError('Configured backend ID differs from manifest')
            state['engine'] = BuildChoiceEngine(backend, config['buildchoice']['policy_version'])
            state['status'] = 'OK'
        except Exception:
            logging.exception('Model startup failed')
            state['status'] = 'ERROR'
            state['error'] = 'MODEL_STARTUP_FAILED_CHECK_LOCAL_STDERR_LOG'

    threading.Thread(target=load, daemon=True).start()
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        server.server_close()
        # Process exit releases models. Do not clear CUDA state while an in-flight request owns it.


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', default=str(DEFAULT_CONFIG))
    serve(ap.parse_args().config)
