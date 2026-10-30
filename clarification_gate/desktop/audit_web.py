"""Single-user loopback review app; stdlib only. No cloud, keys or model needed."""
import argparse
import json
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from .audit import Ledger, markdown

ASSETS = Path(__file__).parent / 'audit_web'


def make_server(workspace, port=0):
    ledger = Ledger(workspace)
    token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def send(self, status, data, mime='application/json; charset=utf-8'):
            body = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(body)

        def allowed(self):
            expected = '127.0.0.1:' + str(self.server.server_port)
            if self.headers.get('Host') != expected:
                self.send(403, {'error': 'Invalid local Host'})
                return False
            origin = self.headers.get('Origin')
            if origin and origin != 'http://' + expected:
                self.send(403, {'error': 'Invalid origin'})
                return False
            return True

        def authenticated(self):
            if not self.allowed():
                return False
            if not secrets.compare_digest(self.headers.get('X-Gate-Token', ''), token):
                self.send(403, {'error': '请使用启动器打开的本地链接'})
                return False
            return True

        def do_GET(self):
            route = urlsplit(self.path)
            if route.path in ('/', '/app.js', '/style.css'):
                if not self.allowed():
                    return
                name, mime = {'/': ('index.html', 'text/html; charset=utf-8'),
                              '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                              '/style.css': ('style.css', 'text/css; charset=utf-8')}[route.path]
                self.send(200, (ASSETS / name).read_bytes(), mime)
                return
            if not self.authenticated():
                return
            try:
                if route.path == '/api/sessions':
                    self.send(200, {'sessions': ledger.list_sessions(), 'workspace': str(ledger.workspace),
                                    'mode': 'Prompt-first', 'version': '0.3.0'})
                elif route.path == '/api/report':
                    report = ledger.report(parse_qs(route.query)['session'][0])
                    self.send(200, {'report': report, 'markdown': markdown(report)})
                else:
                    self.send(404, {'error': 'Not found'})
            except (ValueError, OSError, KeyError) as exc:
                self.send(400, {'error': str(exc)})

        def do_POST(self):
            if not self.authenticated():
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if length < 1 or length > 300000:
                    raise ValueError('Invalid request size')
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ValueError('Expected object')
                route = urlsplit(self.path).path
                if route == '/api/session':
                    result = ledger.start(body['title'], body.get('task', ''))
                elif route == '/api/source':
                    result = ledger.read(body['session'], body['path'])
                elif route == '/api/decision':
                    result = ledger.decide(body['session'], body['title'], body.get('value'),
                                           body.get('refs', []), body.get('impact', '关键交付'), body.get('rationale', ''))
                elif route == '/api/review':
                    result = ledger.review(body['session'], body['decision'], body['disposition'], body['note'])
                else:
                    self.send(404, {'error': 'Not found'})
                    return
                self.send(200, result)
            except (ValueError, OSError, KeyError, TypeError) as exc:
                self.send(400, {'error': str(exc)})

    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.daemon_threads = True
    server.ledger = ledger
    server.local_token = token
    return server


def main():
    parser = argparse.ArgumentParser(description='BuildChoice V2 · 决策证据工作台')
    parser.add_argument('--workspace', type=Path, default=Path.cwd())
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    server = make_server(args.workspace, args.port)
    url = f'http://127.0.0.1:{server.server_port}/#token={server.local_token}'
    print('BuildChoice V2 · 本地决策证据工作台', flush=True)
    print(url, flush=True)
    print('窗口保持开启；Ctrl+C 停止。数据保存在工作区 .gate_audit。', flush=True)
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
