"""Build portable, checksummed runtime assets from an explicit allowlist, never local state."""
import json
import zipfile
from pathlib import Path
from clarification_gate.desktop.common import ROOT, file_sha

VERSION = '0.3.0'


def build_core_runtime(destination, root=ROOT):
    """Small Prompt-first runtime. Existing model bundle remains an optional add-on."""
    import hashlib
    root, destination = Path(root), Path(destination)
    names = {p.relative_to(root).as_posix() for p in (root/'clarification_gate').rglob('*')
             if p.is_file() and '__pycache__' not in p.parts and p.suffix in ('.py', '.html', '.css', '.js')}
    names.update('scripts/'+n for n in ('codex_gate_mcp.py', 'gate_required_call_hook.py', 'gate_auto_call.py',
                                       'gate_audit.py', 'manage_desktop_gate.py'))
    names.add('docs/contracts/gate-v1.schema.json')
    config = ('config_version = 1\n[gate]\nmode = "advisory"\nactive_backend = "mdeberta_v10"\n'
              'policy_version = "field-policy-v1"\n[service]\nbind = "127.0.0.1"\nport = 8769\n'
              'token_file = "runs/desktop_gate/local.token"\nlog_directory = "runs/desktop_gate"\n'
              'startup_timeout_seconds = 90\nrequest_timeout_seconds = 60\n')
    data = {name: (root/name).read_bytes() for name in sorted(names)}
    data['configs/codex_desktop_gate.toml'] = config.encode()
    data['configs/gate_auto_call.json'] = json.dumps({'config_version':4,'enabled':False,'scope':'workspace',
        'mechanism':'prompt_first_hooks','enforce_call':False,'enforce_decision':False,'mode':'prompt'}).encode()
    index = {'bundle_version':1, 'package_version':VERSION, 'models':[], 'profile':'prompt-first-core',
             'files':{n:{'sha256':hashlib.sha256(b).hexdigest(),'bytes':len(b)} for n,b in data.items()}}
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, body in data.items(): archive.writestr(name, body)
        archive.writestr('runtime_manifest.json', json.dumps(index, ensure_ascii=False, indent=2))
    checksum = file_sha(destination)
    destination.with_suffix(destination.suffix+'.sha256').write_text(checksum+'  '+destination.name+'\n',encoding='ascii')
    return {'path':str(destination),'sha256':checksum,'bytes':destination.stat().st_size,'models':[]}

