"""Build the portable product runtime and plugin archives."""
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from clarification_gate.desktop.bundle import build_core_runtime, VERSION
from clarification_gate.desktop.distribution import archive_plugin

if __name__ == '__main__':
    out = ROOT / 'dist'
    print(json.dumps({'core': build_core_runtime(out / f'clarification-gate-core-{VERSION}.zip'),
                      'plugin': archive_plugin(out / f'clarification-gate-plugin-{VERSION}.zip')}, indent=2))
