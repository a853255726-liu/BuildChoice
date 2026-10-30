"""Use an unchanged frozen backend in a persistent isolated model process."""
import argparse
import importlib
import json
import sys
import time
from pathlib import Path


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser()
    parser.add_argument('--runtime-root', type=Path, required=True)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--persistent', action='store_true')
    args = parser.parse_args()
    runtime_root = args.runtime_root.resolve(strict=True)
    sys.path.insert(0, str(runtime_root))
    # A frozen pre-rename runtime must keep its own code and manifest intact.
    # Choose by the actual package directory, not by catching dependency errors.
    package = 'buildchoice' if (runtime_root / 'buildchoice').is_dir() else 'clarification_gate'
    if not (runtime_root / package).is_dir():
        raise ValueError('Model runtime package is missing')
    build_request = importlib.import_module(package + '.desktop.contracts').build_request
    read_config = importlib.import_module(package + '.desktop.common').read_config
    engine_module = importlib.import_module(package + '.desktop.engine')
    engine_class = getattr(engine_module, 'BuildChoiceEngine' if package == 'buildchoice' else 'GateEngine')
    config_section = 'buildchoice' if package == 'buildchoice' else 'gate'
    backend = None
    engine = None

    def assess(given):
        nonlocal backend, engine
        started = time.monotonic()
        config = read_config(args.config)
        if config[config_section]['active_backend'] not in config.get('backends', {}):
            return {'status':'NOT_READY','reason':'BACKEND_NOT_CONFIGURED'}
        if engine is None:
            spec = config['backends'][config[config_section]['active_backend']]
            module, name = spec['factory'].split(':', 1)
            factory = getattr(importlib.import_module(module), name)
            backend = factory(spec['manifest'], spec['manifest_sha256'], spec['device'])
            engine = engine_class(backend)
        request = build_request(given['task'], given['names'], given['evidence'],
            json.dumps(given['resources'], ensure_ascii=False) if given['resources'] else '',
            given['resources'][0]['path'] if given['resources'] else None, 'decision-v3-bridge')
        body = engine.evaluate(request)
        if body.get('status') != 'OK':
            return {'status':body.get('status') if body.get('status') in ('UNSUPPORTED','NOT_READY','ERROR') else 'ERROR',
                    'reason':'BACKEND_' + str(body.get('status')), 'backend_response':body}
        states = body.get('assessment', {}).get('field_states')
        if not isinstance(states, dict) or set(states) != {'required','resolved','indexed'}:
            return {'status':'ERROR','reason':'MISSING_REAL_FIELD_STATES'}
        mapping = {c['field_id']:c['name'] for c in request['snapshot']['candidates']}
        fields = {name:{kind:fid in states[kind] for kind in ('required','resolved','indexed')} for fid,name in mapping.items()}
        return {'status':'OK','fields':fields,'backend':body['backend'],'backend_response':body,
                'margin_scores':backend.last_scores,'thresholds':backend.manifest['thresholds'],
                'score_semantics':'sigmoid(entailment_logit-contradiction_logit), not calibrated probability',
                'elapsed_seconds':time.monotonic()-started}

    try:
        while True:
            raw = sys.stdin.buffer.readline(1024*1024+1) if args.persistent else sys.stdin.buffer.read(1024*1024+1)
            if not raw: break
            try:
                result = {'status':'UNSUPPORTED','reason':'REQUEST_TOO_LARGE'} if len(raw)>1024*1024 else assess(json.loads(raw))
            except Exception as exc:
                result = {'status':'ERROR','reason':type(exc).__name__}
            print(json.dumps(result,ensure_ascii=False),flush=True)
            if not args.persistent: break
    finally:
        if backend is not None: backend.close()


if __name__ == '__main__': main()
