"""Prompt-first/off settings. Reads never invoke tools or modify Hook trust."""
import json
import os
import uuid
from pathlib import Path
from .common import ROOT, WORKSPACE

SETTINGS = ROOT / 'configs/buildchoice.json'
DEFAULT = {'config_version': 1, 'mode': 'prompt'}


def read(path=SETTINGS):
    value = json.loads(Path(path).read_text(encoding='utf-8')) if Path(path).exists() else dict(DEFAULT)
    if set(value) != set(DEFAULT) or type(value['config_version']) is not int or value['config_version'] != 1 or value['mode'] not in ('prompt', 'off'):
        raise ValueError('Invalid BuildChoice settings')
    return value


def update(mode, path=SETTINGS):
    if mode not in ('prompt', 'off'):
        raise ValueError('Unknown BuildChoice mode')
    read(path)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temporary.write_text(json.dumps({'config_version': 1, 'mode': mode}, indent=2) + '\n', encoding='utf-8')
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return read(path)


def status(path=SETTINGS):
    value = read(path)
    return {**value, 'workspace': str(WORKSPACE), 'prompt_policy_enabled': value['mode'] == 'prompt',
            'audit_available': value['mode'] != 'off', 'hook_trust_status': 'not_inspected'}
