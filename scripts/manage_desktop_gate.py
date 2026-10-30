"""Local worker lifecycle. Stop uses authenticated graceful shutdown, never kill-by-name."""
import argparse
import json
import sys
import time
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from clarification_gate.desktop.common import DEFAULT_CONFIG
from clarification_gate.desktop.client import GateClient

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('command', choices=['start', 'status', 'stop', 'restart'])
    ap.add_argument('--config', default=str(DEFAULT_CONFIG))
    args = ap.parse_args()
    client = GateClient(args.config)
    if args.command in ('stop', 'restart'):
        try:
            result = client.call('/shutdown', {})
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                try:
                    client.call('/healthz')
                except (urllib.error.URLError, ConnectionError, TimeoutError):
                    break
                time.sleep(0.2)
            else:
                raise RuntimeError('Worker has not stopped; refusing a racing restart')
        except urllib.error.URLError:
            result = {'stopping': False, 'reason': 'ALREADY_STOPPED'}
        if args.command == 'stop':
            print(json.dumps(result))
    if args.command in ('start', 'restart'):
        print(json.dumps(client.ensure(), ensure_ascii=False, indent=2))
    if args.command == 'status':
        print(json.dumps(client.call('/healthz'), ensure_ascii=False, indent=2))
