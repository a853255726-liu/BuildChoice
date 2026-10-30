"""Build portable, checksummed runtime assets from an explicit allowlist, never local state."""
import json
import zipfile
from pathlib import Path
from buildchoice.desktop.common import ROOT, file_sha

VERSION = '0.6.0'


def build_core_runtime(destination, root=ROOT):
    """Prompt-first, audit and decision-card runtime without model dependencies."""
    import hashlib
    root, destination = Path(root), Path(destination)
    names = {p.relative_to(root).as_posix() for p in (root/'buildchoice').rglob('*')
             if p.is_file() and '__pycache__' not in p.parts and p.suffix in ('.py', '.html', '.css', '.js')}
    names.update('scripts/'+n for n in ('buildchoice_mcp.py','buildchoice_hook.py','buildchoice_settings.py',
                                       'buildchoice_audit.py','buildchoice_decisions.py'))
    names.add('docs/contracts/decision-v3.schema.json')
    data = {name: (root/name).read_bytes() for name in sorted(names)}
    data['configs/buildchoice.json'] = json.dumps({'config_version':1,'mode':'prompt'}).encode()
    data['configs/decision_v3.json'] = json.dumps({'config_version':2,'mode':'off','context_ttl_seconds':900}).encode()
    index = {'bundle_version':1,'package_version':VERSION,'profile':'prompt-first-core',
             'files':{n:{'sha256':hashlib.sha256(b).hexdigest(),'bytes':len(b)} for n,b in data.items()}}
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, body in data.items(): archive.writestr(name, body)
        archive.writestr('runtime_manifest.json', json.dumps(index, ensure_ascii=False, indent=2))
    checksum = file_sha(destination)
    destination.with_suffix(destination.suffix+'.sha256').write_text(checksum+'  '+destination.name+'\n',encoding='ascii')
    return {'path':str(destination),'sha256':checksum,'bytes':destination.stat().st_size}

