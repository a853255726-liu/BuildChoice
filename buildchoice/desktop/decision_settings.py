"""Independent V3 pilot settings; legacy model keys are ignored on read."""
import json
import os
import uuid
from pathlib import Path
from .common import ROOT

SETTINGS = Path(os.environ.get('BUILDCHOICE_V3_SETTINGS', ROOT / 'configs/decision_v3.json'))
DEFAULT = {'config_version': 2, 'mode': 'off', 'context_ttl_seconds': 900}


def read(path=SETTINGS):
    value = json.loads(Path(path).read_text(encoding='utf-8')) if Path(path).exists() else dict(DEFAULT)
    # Existing settings can be opened without reviving removed model capabilities.
    if value.get('config_version') == 1:
        if set(value) != {'config_version', 'mode', 'model_check', 'context_ttl_seconds', 'model_runtime'}:
            raise ValueError('Invalid legacy V3 settings')
        value = {key: value[key] for key in DEFAULT}
        value['config_version'] = 2
    if (set(value) != set(DEFAULT) or type(value['config_version']) is not int or value['config_version'] != 2 or
            value['mode'] not in ('off', 'pilot') or type(value['context_ttl_seconds']) is not int or
            not 60 <= value['context_ttl_seconds'] <= 3600):
        raise ValueError('Invalid V3 settings')
    return value


def update(mode=None, path=SETTINGS):
    value = read(path)
    if mode is not None: value['mode'] = mode
    if value['mode'] not in ('off', 'pilot'):
        raise ValueError('Unknown V3 setting')
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return value
