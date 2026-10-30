"""Remove only known legacy registrations, preserving unrelated user config exactly in meaning."""
import json
import os
import re
import tomllib
import uuid
from pathlib import Path


def migrate_text(config_text,hooks_text,root):
    root = Path(root).resolve()
    config = tomllib.loads(config_text)
    entry = config.get('mcp_servers',{}).get('clarification_gate')
    removed_server = False
    updated = config_text
    if entry is not None:
        if (Path(entry.get('command','')).resolve()!=root/'.venv/Scripts/python.exe' or
                not entry.get('args') or Path(entry['args'][0]).resolve()!=root/'scripts/codex_gate_mcp.py'):
            raise ValueError('Unrelated clarification_gate server exists; refusing migration')
        chunks = re.split(r'(?m)(?=^\[)',config_text)
        updated = ''.join(c for c in chunks if not re.match(r'^\[mcp_servers\.clarification_gate(?:\]|\.)',c))
        after = tomllib.loads(updated)
        wanted = json.loads(json.dumps(config))
        wanted['mcp_servers'].pop('clarification_gate')
        if not wanted['mcp_servers']:
            wanted.pop('mcp_servers')
        normalized = json.loads(json.dumps(after))
        if normalized.get('mcp_servers')=={}:
            normalized.pop('mcp_servers')
        if normalized != wanted:
            raise ValueError('Unrelated config would change')
        removed_server = True
    hooks = json.loads(hooks_text)
    result = json.loads(hooks_text)
    known = {f'{(root/".venv/Scripts/python.exe").as_posix()} {(root/"scripts"/name).as_posix()}'
             for name in ('gate_auto_call_hook.py','gate_required_call_hook.py')}
    removed_hooks = 0
    for event,groups in result.get('hooks',{}).items():
        kept = []
        for group in groups:
            handlers = group['hooks']
            remaining = [h for h in handlers if h.get('command') not in known]
            removed_hooks += len(handlers)-len(remaining)
            if remaining:
                kept.append({**group,'hooks':remaining})
        result['hooks'][event] = kept
    return updated,json.dumps(result,ensure_ascii=False,indent=2)+'\n',{
        'legacy_server_removed':removed_server,'legacy_hook_handlers_removed':removed_hooks,'hook_trust_modified':False}


def atomic_write(path,text):
    path = Path(path)
    temporary = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        temporary.write_text(text,encoding='utf-8')
        os.replace(temporary,path)
    finally:
        temporary.unlink(missing_ok=True)


def migrate(config_path,hooks_path,root):
    config_path,hooks_path = Path(config_path),Path(hooks_path)
    original_config = config_path.read_text(encoding='utf-8')
    original_hooks = hooks_path.read_text(encoding='utf-8') if hooks_path.exists() else '{"hooks":{}}'
    config,hooks,report = migrate_text(original_config,original_hooks,root)
    for path,text in ((config_path,original_config),(hooks_path,original_hooks)):
        backup = path.with_name(path.name+'.before-unified-gate.bak')
        if not backup.exists():
            backup.write_text(text,encoding='utf-8')
    try:
        atomic_write(config_path,config)
        atomic_write(hooks_path,hooks)
    except BaseException:
        atomic_write(config_path,original_config)
        atomic_write(hooks_path,original_hooks)
        raise
    return report
