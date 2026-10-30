"""Synchronous required-call hook. Never edits trust or invokes a task/model itself."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from clarification_gate.desktop.required_call import handle_event as required_event, failure_output
from clarification_gate.desktop.auto_call import read_switch, mode_of
from clarification_gate.desktop.common import WORKSPACE


def handle_event(event):
    if mode_of(read_switch()) == 'prompt':
        from clarification_gate.desktop.prompt_policy import handle_prompt
        return handle_prompt(event, WORKSPACE)
    return required_event(event)


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    event = {}
    try:
        data = sys.stdin.buffer.read(2 * 1024 * 1024 + 1)
        if len(data) > 2 * 1024 * 1024:
            raise ValueError('Oversize hook input')
        event = json.loads(data.decode('utf-8'))
        result = handle_event(event)
        if result:
            print(json.dumps(result, ensure_ascii=False))
    except Exception:
        # Optional policy never converts an audit/configuration failure into a task blockade.
        try:
            required = mode_of(read_switch()) == 'required'
        except Exception:
            required = False
        if required:
            print(json.dumps(failure_output(event.get('hook_event_name'), 'Hook input, configuration or state failed.')))
    return 0


if __name__ == '__main__':
    sys.exit(main())
