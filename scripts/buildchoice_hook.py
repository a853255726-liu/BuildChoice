"""Prompt policy and observed decision replies; never blocks a task."""
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from buildchoice.desktop.common import WORKSPACE
from buildchoice.desktop.settings import read


def handle_event(event):
    if event.get('hook_event_name')!='UserPromptSubmit' or read()['mode']=='off': return None
    from buildchoice.desktop.prompt_policy import handle_prompt
    result=handle_prompt(event,WORKSPACE)
    from buildchoice.desktop.decision_hook import handle_prompt as decision_prompt
    extra=decision_prompt(event,WORKSPACE)
    if extra is not None:
        if result is None: return extra
        result['hookSpecificOutput']['additionalContext']+='\n'+extra['hookSpecificOutput']['additionalContext']
    return result


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        raw=sys.stdin.buffer.read(2*1024*1024+1)
        if len(raw)>2*1024*1024: return 0
        result=handle_event(json.loads(raw.decode('utf-8')))
        if result: print(json.dumps(result,ensure_ascii=False))
    except Exception:
        # Optional guidance failure must not block unrelated work.
        pass
    return 0

if __name__=='__main__': sys.exit(main())
