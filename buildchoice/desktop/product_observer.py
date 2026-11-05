"""Structural native tool receipts for enabled tasks; no test/intent classifier."""
import json
from pathlib import Path
from .audit import encode, now
from .decision_store import DecisionStore, message_digest, fingerprint
from .decision_settings import read as read_settings


def observe(event, workspace, settings_path=None):
    try:
        config = read_settings(settings_path) if settings_path is not None else read_settings()
        if config['mode'] != 'pilot' or event.get('hook_event_name') != 'PostToolUse': return None
        if not all(isinstance(event.get(k), str) and event[k] for k in ('cwd', 'session_id', 'turn_id', 'tool_use_id', 'tool_name')): return None
        root = Path(workspace).resolve()
        if not Path(event['cwd']).resolve().is_relative_to(root): return None
        database = root / '.buildchoice_audit' / 'ledger.sqlite3'
        if not database.exists(): return None
        # Reading enabled state must not create workflow records for ordinary tasks.
        store = DecisionStore(root)
        with store.transaction() as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE name='product_tasks'").fetchone(): return None
            tasks = db.execute('SELECT t.id FROM product_tasks p JOIN decision_v3_tasks t ON t.id=p.task '
                'JOIN product_task_hosts h ON h.task=t.id WHERE p.enabled=1 AND t.workspace=? AND h.host=?',
                (str(root), message_digest(event['session_id']))).fetchall()
            if len(tasks) != 1: return None
            response = event.get('tool_response')
            if isinstance(response, str):
                try: response = json.loads(response)
                except ValueError: return None
            if not isinstance(response, dict) or response.get('session_id') is not None or response.get('truncated'): return None
            if type(response.get('exit_code')) is not int: return None
            output = response.get('output', response.get('stdout', ''))
            if not isinstance(output, str) or len(output) > 32000: return None
            args = event.get('tool_input')
            if not isinstance(args, dict): return None
            command = args.get('command', args.get('cmd'))
            if not isinstance(command, str) or not command.strip() or len(command) > 4000: return None
            from .workspace_snapshot import SECRET_CONTENT
            if SECRET_CONTENT.search(command + '\n' + output): return None
            from . import product_store as ps
            ident = 'tool-observation-' + fingerprint({'host': event['session_id'], 'call': event['tool_use_id']})[:32]
            if db.execute('SELECT 1 FROM product_objects WHERE id=?', (ident,)).fetchone(): return None
            data = {'tool_name': event['tool_name'], 'tool_use_id': event['tool_use_id'],
                'host': message_digest(event['session_id']), 'turn': message_digest(event['turn_id']),
                'command': command, 'output': output, 'exit_code': response['exit_code'],
                'observed_at': now(), 'provenance': 'actual_post_tool_use',
                'meaning_and_behavior_coverage': 'llm_declared', 'input_state_during_execution': 'not_observed'}
            # Bind observed code state AFTER the command, without claiming its inputs were stable
            # during execution. Later uses can still detect a stale test receipt.
            from .workspace_snapshot import current_files
            snapshots = ps.objects(db, tasks[0]['id'], 'code_snapshot')
            if snapshots:
                snapshot = snapshots[-1]
                data['scope_snapshot_id'] = snapshot['id']
                data['code_state_after'] = current_files(store, snapshot)
            ps.put(store, db, tasks[0]['id'], 'tool_observation', data, ident)
            return {'hookSpecificOutput': {'hookEventName': 'PostToolUse', 'additionalContext':
                'BuildChoice 工具执行记录：' + ident + '。仅证明该工具返回内容及退出码；测试含义和覆盖范围由 Agent 解释。'}}
    except (OSError, ValueError, TypeError, UnicodeError): return None
