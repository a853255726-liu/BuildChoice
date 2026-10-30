import hashlib
import json
import tomllib
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKSPACE = Path(os.environ.get('BUILDCHOICE_WORKSPACE', str(ROOT))).resolve()
DEFAULT_CONFIG = ROOT / 'configs/buildchoice.toml'


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def file_sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def local_path(value):
    p = (ROOT / value).resolve()
    if not p.is_relative_to(ROOT):
        raise ValueError('Runtime paths must stay inside the project')
    return p


def read_config(path=DEFAULT_CONFIG):
    c = tomllib.loads(Path(path).read_text(encoding='utf-8'))
    if c['config_version'] != 1 or c['buildchoice']['mode'] != 'advisory':
        raise ValueError('This runtime only supports advisory mode')
    if c['service']['bind'] != '127.0.0.1':
        raise ValueError('Only loopback binding is supported')
    if not 1024 <= c['service']['port'] <= 65535:
        raise ValueError('Invalid local service port')
    c['_config_sha256'] = file_sha(path)
    return c
