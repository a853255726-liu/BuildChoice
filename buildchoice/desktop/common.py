"""Shared workspace identity and file digests."""
import hashlib
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKSPACE = Path(os.environ.get('BUILDCHOICE_WORKSPACE', str(ROOT))).resolve()


def file_sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()
