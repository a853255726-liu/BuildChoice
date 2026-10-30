"""Adapt only real candidates; keep evidence intact and distinguish model fallback."""
import json
import os
import subprocess
import sys
import time
import queue
import threading
import atexit
from pathlib import Path
from .common import ROOT


def batches(candidates):
    result = []; remaining = list(candidates)
    while remaining:
        size = 2 if len(remaining) in (2, 4) else min(3, len(remaining))
        result.append(remaining[:size]); remaining = remaining[size:]
    return result


class RuntimeProvider:
    def __init__(self, runtime):
        self.runtime = runtime
        self.process = None
        self.lock = threading.Lock()
        atexit.register(self.close)

    def close(self):
        process, self.process = self.process, None
        if process is not None:
            try:
                process.stdin.close()
                process.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                process.kill(); process.wait(timeout=3)

    def assess(self, task, names, evidence, resources):
        if self.runtime is None:
            return {'status': 'NOT_READY', 'reason': 'NO_MODEL_RUNTIME_CONFIGURED'}
        runtime = self.runtime
        if not all(Path(runtime[k]).exists() for k in ('python', 'root', 'config')):
            return {'status': 'NOT_READY', 'reason': 'MODEL_RUNTIME_PATH_MISSING'}
        payload = {'task': task, 'names': names, 'evidence': evidence, 'resources': resources}
        command = [runtime['python'], str(ROOT / 'scripts/decision_nli_bridge.py'), '--persistent',
                   '--runtime-root', runtime['root'], '--config', runtime['config']]
        with self.lock:
            try:
                if self.process is None or self.process.poll() is not None:
                    self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL, env={**os.environ, 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'},
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                self.process.stdin.write(json.dumps(payload, ensure_ascii=False).encode('utf-8') + b'\n')
                self.process.stdin.flush()
                reply = queue.Queue(maxsize=1)
                stream = self.process.stdout
                def collect():
                    try: reply.put(stream.readline(1024 * 1024 + 1))
                    except OSError: reply.put(b'')
                threading.Thread(target=collect, daemon=True).start()
                try: raw = reply.get(timeout=100)
                except queue.Empty:
                    self.close()
                    return {'status':'ERROR','reason':'MODEL_BRIDGE_TIMEOUT'}
                if not raw or len(raw) > 1024 * 1024:
                    self.close()
                    return {'status':'ERROR','reason':'MODEL_BRIDGE_INVALID_OUTPUT'}
                return json.loads(raw)
            except (OSError, ValueError):
                self.close()
                return {'status': 'ERROR', 'reason': 'MODEL_BRIDGE_UNAVAILABLE'}


def assess_candidates(task, candidates, evidence, resources, enabled=False, provider=None):
    outputs = {}; diagnostics = {'calls': 0, 'batches': [], 'elapsed_seconds': 0.0}
    started = time.monotonic()
    provider = provider or RuntimeProvider(None)
    for batch in batches(candidates):
        names = [c['field'] for c in batch]
        result = None
        if not enabled: result = {'status': 'SKIPPED', 'reason': 'MODEL_CHECK_OFF'}
        elif len(batch) == 1: result = {'status': 'UNSUPPORTED', 'reason': 'SINGLE_REAL_CANDIDATE'}
        elif len(resources) > 1: result = {'status': 'UNSUPPORTED', 'reason': 'MULTIPLE_UNREAD_RESOURCES'}
        elif len(evidence.encode('utf-8')) > 128 * 1024:
            result = {'status': 'UNSUPPORTED', 'reason': 'EVIDENCE_TOO_LARGE_NO_TRUNCATION'}
        if result is None:
            diagnostics['calls'] += 1
            try: result = provider.assess(task, names, evidence, resources)
            except Exception: result = {'status': 'ERROR', 'reason': 'MODEL_PROVIDER_FAILED'}
        status = result.get('status')
        if status not in ('OK', 'UNSUPPORTED', 'NOT_READY', 'ERROR', 'SKIPPED'):
            result = {'status': 'ERROR', 'reason': 'UNKNOWN_MODEL_STATUS'}
        if result['status'] == 'OK':
            fields = result.get('fields', {})
            if (not isinstance(fields, dict) or set(fields) != set(names) or any(not isinstance(value, dict) or set(value) != {'required', 'resolved', 'indexed'} or
                    any(type(v) is not bool for v in value.values()) for value in fields.values())):
                result = {'status': 'ERROR', 'reason': 'INVALID_MODEL_FIELD_RESULT'}
        for name in names:
            outputs[name] = {'status': result['status'], 'fields': result.get('fields', {}).get(name),
                             'reason': result.get('reason')}
        diagnostics['batches'].append({'fields': names, 'result': result})
    diagnostics['elapsed_seconds'] = time.monotonic() - started
    return outputs, diagnostics
