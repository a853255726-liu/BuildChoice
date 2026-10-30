"""Build the portable product runtime and plugin archives."""
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from buildchoice.desktop.bundle import build_core_runtime, VERSION
from buildchoice.desktop.distribution import archive_plugin

if __name__ == '__main__':
    out = ROOT / 'dist'
    print(json.dumps({'core': build_core_runtime(out / f'buildchoice-core-{VERSION}.zip'),
                      'plugin': archive_plugin(out / f'buildchoice-plugin-{VERSION}.zip')}, indent=2))
