"""CLI for explicit decision auditing and a dependency-free local workbench."""
import argparse
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from buildchoice.desktop.audit import Ledger, markdown


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    p = argparse.ArgumentParser()
    p.add_argument('--workspace', type=Path, default=ROOT)
    sub = p.add_subparsers(dest='command', required=True)
    sub.add_parser('list')
    serve = sub.add_parser('serve')
    serve.add_argument('--port', type=int, default=0)
    serve.add_argument('--no-browser', action='store_true')
    start = sub.add_parser('start'); start.add_argument('title'); start.add_argument('--task', default='')
    read = sub.add_parser('read'); read.add_argument('session'); read.add_argument('path')
    decide = sub.add_parser('decide'); decide.add_argument('session'); decide.add_argument('title')
    decide.add_argument('--value', required=True, help='JSON literal, e.g. 3 or "JWT"')
    decide.add_argument('--refs', default='[]', help='JSON array: [{"source_id":"src-...","pointer":"/key"}]')
    decide.add_argument('--rationale', default='')
    report = sub.add_parser('report'); report.add_argument('session'); report.add_argument('--out', type=Path)
    review = sub.add_parser('review'); review.add_argument('session'); review.add_argument('decision')
    review.add_argument('--disposition', required=True, choices=['accept', 'revise', 'ask'])
    review.add_argument('--note', required=True)
    args = p.parse_args()
    if args.command == 'serve':
        from buildchoice.desktop.audit_web import main as serve_main
        sys.argv = [sys.argv[0], '--workspace', str(args.workspace), '--port', str(args.port)] + (['--no-browser'] if args.no_browser else [])
        serve_main()
        return
    ledger = Ledger(args.workspace)
    if args.command == 'list': result = ledger.list_sessions()
    elif args.command == 'start': result = ledger.start(args.title, args.task)
    elif args.command == 'read': result = ledger.read(args.session, args.path)
    elif args.command == 'decide': result = ledger.decide(args.session, args.title, json.loads(args.value), json.loads(args.refs), rationale=args.rationale)
    elif args.command == 'review': result = ledger.review(args.session, args.decision, args.disposition, args.note)
    else:
        result = ledger.report(args.session)
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(markdown(result), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
