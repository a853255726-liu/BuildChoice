"""Same-origin loopback settings UI. No model token is sent to the browser."""
import argparse
import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from buildchoice.desktop.auto_call import set_switch
from buildchoice.desktop.common import ROOT
from buildchoice.desktop.panel_state import PanelState

ASSETS = ROOT / 'buildchoice/desktop/web'
DEFAULT_PORT = 8771


def create_server(port=DEFAULT_PORT, state=None):
    state = state or PanelState()
    csrf = secrets.token_urlsafe(32)
    origin = f'http://127.0.0.1:{port}'

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def log_message(self, *args):
            pass

        def write(self, status, payload, content_type='application/json; charset=utf-8'):
            # Drain small rejected request bodies before closing. Otherwise Windows may
            # reset the connection before the client can receive the JSON error response.
            if self.command == 'POST' and status >= 400 and not getattr(self, '_body_consumed', False):
                try:
                    size = int(self.headers.get('Content-Length', '-1'))
                    if 0 <= size <= 8192 and not self.headers.get('Transfer-Encoding'):
                        self.rfile.read(size)
                except (ValueError, OSError):
                    pass
            data = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(status)
            for name, value in {
                'Content-Type': content_type, 'Content-Length': str(len(data)), 'Cache-Control': 'no-store',
                'X-Content-Type-Options': 'nosniff', 'X-Frame-Options': 'DENY',
                'Referrer-Policy': 'no-referrer',
                'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
            }.items():
                self.send_header(name, value)
            self.end_headers()
            try:
                self.wfile.write(data)
            except OSError:
                pass

        def allowed_host(self):
            return self.headers.get('Host') == f'127.0.0.1:{self.server.server_port}'

        def same_origin(self):
            return self.allowed_host() and self.headers.get('Origin') in (None, self.server.panel_origin) and self.headers.get('Sec-Fetch-Site') != 'cross-site'

        def do_GET(self):
            path = urlsplit(self.path)
            if not self.allowed_host():
                return self.write(403, {'error': 'LOCAL_HOST_REQUIRED'})
            files = {'/': ('index.html', 'text/html; charset=utf-8'),
                     '/panel.css': ('panel.css', 'text/css; charset=utf-8'),
                     '/panel.js': ('panel.js', 'text/javascript; charset=utf-8')}
            if path.path in files:
                name, mime = files[path.path]
                return self.write(200, (ASSETS / name).read_bytes(), mime)
            if not self.same_origin():
                return self.write(403, {'error': 'SAME_ORIGIN_REQUIRED'})
            if path.path == '/api/session':
                return self.write(200, {'csrf': csrf})
            if path.path == '/api/healthz':
                return self.write(200, {'service': 'buildchoice-panel', 'status': 'OK'})
            if path.path == '/api/status':
                try:
                    return self.write(200, state.snapshot(refresh=parse_qs(path.query).get('refresh') == ['1']))
                except Exception:
                    return self.write(503, {'error': 'STATE_UNAVAILABLE', 'message': '暂时无法读取本地配置，请稍后刷新。'})
            return self.write(404, {'error': 'NOT_FOUND'})

        def do_POST(self):
            if not self.same_origin() or self.headers.get('Origin') != self.server.panel_origin:
                return self.write(403, {'error': 'SAME_ORIGIN_REQUIRED'})
            if not secrets.compare_digest(self.headers.get('X-BuildChoice-CSRF', ''), csrf):
                return self.write(403, {'error': 'CSRF_REQUIRED'})
            if self.headers.get_content_type() != 'application/json' or self.headers.get('Transfer-Encoding'):
                return self.write(415, {'error': 'JSON_REQUIRED'})
            try:
                size = int(self.headers.get('Content-Length', '-1'))
                if not 0 < size <= 1024:
                    return self.write(413, {'error': 'INVALID_BODY_SIZE'})
                body = self.rfile.read(size)
                self._body_consumed = True
                value = json.loads(body)
            except (ValueError, TypeError):
                return self.write(400, {'error': 'INVALID_JSON'})
            if self.path == '/api/shutdown':
                self.write(200, {'stopping': True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            if self.path != '/api/switch':
                return self.write(404, {'error': 'NOT_FOUND'})
            if not isinstance(value, dict) or set(value) != {'enabled'} or type(value['enabled']) is not bool:
                return self.write(400, {'error': 'BOOLEAN_REQUIRED'})
            try:
                saved = set_switch(value['enabled'])
                return self.write(200, {'switch': saved, 'saved': True})
            except Exception:
                return self.write(503, {'error': 'SAVE_FAILED', 'message': '保存失败，请刷新确认实际状态。'})

    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.daemon_threads = True
    server.panel_origin = f'http://127.0.0.1:{server.server_port}'
    return server


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=DEFAULT_PORT)
    args = parser.parse_args()
    with create_server(args.port) as server:
        server.serve_forever(poll_interval=0.2)
