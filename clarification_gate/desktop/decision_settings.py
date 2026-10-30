"""V3 pilot switch is independent of legacy invocation modes."""
import json
import os
import uuid
from pathlib import Path
from .common import ROOT

SETTINGS = Path(os.environ.get('CLARIFICATION_GATE_V3_SETTINGS', ROOT / 'configs/decision_v3.json'))
DEFAULT = {'config_version': 1, 'mode': 'off', 'model_check': 'off', 'context_ttl_seconds': 900, 'model_runtime': None}


def read(path=SETTINGS):
    value = json.loads(Path(path).read_text(encoding='utf-8')) if Path(path).exists() else dict(DEFAULT)
    if (set(value) != set(DEFAULT) or value['config_version'] != 1 or value['mode'] not in ('off', 'pilot') or
            value['model_check'] not in ('off', 'on') or type(value['context_ttl_seconds']) is not int or
            not 60 <= value['context_ttl_seconds'] <= 3600):
        raise ValueError('Invalid V3 settings')
    runtime = value['model_runtime']
    if runtime is not None:
        if (not isinstance(runtime, dict) or set(runtime) != {'python', 'root', 'config'} or
                not all(isinstance(runtime[k], str) and Path(runtime[k]).is_absolute() for k in runtime)):
            raise ValueError('Model runtime must use explicitly configured absolute paths')
    return value


def update(mode=None, model_check=None, path=SETTINGS):
    value = read(path)
    if mode is not None: value['mode'] = mode
    if model_check is not None: value['model_check'] = model_check
    if value['mode'] not in ('off', 'pilot') or value['model_check'] not in ('off', 'on'):
        raise ValueError('Unknown V3 setting')
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        os.replace(temporary, path)
    finally: temporary.unlink(missing_ok=True)
    return value
