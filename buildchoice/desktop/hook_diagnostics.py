"""Bounded Hook diagnostics: no prompts, paths, identifiers, or exception messages."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys

MAX_BYTES = 64 * 1024
STAGES = {'input', 'prompt_policy', 'decision_prompt', 'product_observer', 'read_observer', 'dispatch'}
EVENTS = {'UserPromptSubmit', 'PostToolUse'}


def record_failure(error, workspace, event=None, stage='dispatch'):
    entry = {'time': datetime.now(timezone.utc).isoformat(), 'code': 'HOOK_EVENT_FAILED',
             'stage': stage if stage in STAGES else 'dispatch',
             'event': event.get('hook_event_name') if isinstance(event, dict) and
                      event.get('hook_event_name') in EVENTS else 'unknown',
             'error_type': type(error).__name__}
    line = json.dumps(entry, ensure_ascii=True) + '\n'
    try:
        print('BuildChoice Hook diagnostic: ' + line.strip(), file=sys.stderr)
    except (OSError, ValueError):
        pass
    try:
        home = Path(os.environ.get('BUILDCHOICE_DATA') or Path.home() / '.buildchoice')
        identity = hashlib.sha256(os.path.normcase(str(Path(workspace).resolve())).encode()).hexdigest()[:20]
        path = home / 'projects' / identity / 'diagnostics' / 'hooks.jsonl'
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size + len(line.encode()) > MAX_BYTES:
            path.replace(path.with_suffix('.jsonl.1'))
        with path.open('a', encoding='utf-8') as stream:
            stream.write(line)
    except (OSError, ValueError):
        pass  # Diagnostics must never prevent the user's task or create a confirmation.


def failure_context():
    return {'hookSpecificOutput': {'hookEventName': 'UserPromptSubmit', 'additionalContext':
            'BuildChoice：本轮消息关联失败，未取得可信的新回复句柄。不要复用旧句柄或切换记账接口重试；'
            '保持未登记状态，必要时仅说明一次恢复方式。诊断已尝试写入本地日志。'}}
