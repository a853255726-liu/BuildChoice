"""Prompt policy and observed decision replies; never blocks a task."""
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from buildchoice.desktop.common import WORKSPACE
from buildchoice.desktop.settings import read
from buildchoice.desktop.hook_diagnostics import record_failure, failure_context


def handle_event(event):
    if read()['mode']=='off': return None
    if event.get('hook_event_name')=='PostToolUse':
        from buildchoice.desktop.product_observer import observe as observe_product
        product=observe_product(event,WORKSPACE)
        from buildchoice.desktop.read_observer import observe
        return product or observe(event,WORKSPACE)
    if event.get('hook_event_name')!='UserPromptSubmit':return None
    from buildchoice.desktop.prompt_policy import handle_prompt
    try:
        result=handle_prompt(event,WORKSPACE)
    except Exception as error:
        record_failure(error,WORKSPACE,event,'prompt_policy')
        result=None
    from buildchoice.desktop.decision_hook import handle_prompt as decision_prompt
    try:
        extra=decision_prompt(event,WORKSPACE)
    except Exception as error:
        record_failure(error,WORKSPACE,event,'decision_prompt')
        extra=failure_context()
    if extra is not None:
        if result is None: return extra
        result['hookSpecificOutput']['additionalContext']+='\n'+extra['hookSpecificOutput']['additionalContext']
    return result


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    event=None
    try:
        raw=sys.stdin.buffer.read(2*1024*1024+1)
        if len(raw)>2*1024*1024: return 0
        event=json.loads(raw.decode('utf-8'))
        result=handle_event(event)
        if result: print(json.dumps(result,ensure_ascii=False))
    except Exception as error:
        record_failure(error,WORKSPACE,event,'dispatch' if event is not None else 'input')
        if isinstance(event,dict) and event.get('hook_event_name')=='UserPromptSubmit':
            print(json.dumps(failure_context(),ensure_ascii=False))
    return 0

if __name__=='__main__': sys.exit(main())
