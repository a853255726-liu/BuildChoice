"""Versioned Prompt-first policy. Deliberately no classifier imports."""
from .guidance import compose
PRINCIPLES = compose('entry','zh')
POLICY_VERSION = 'intent-alignment.v1'
DISCOVERY_POLICY_VERSION = 'decision-discovery-v3'


def handle_prompt(event, workspace):
    from pathlib import Path
    if event.get('hook_event_name') != 'UserPromptSubmit':
        return None
    cwd = event.get('cwd')
    if not isinstance(cwd, str) or not Path(cwd).resolve().is_relative_to(Path(workspace).resolve()):
        return None
    return {'hookSpecificOutput': {'hookEventName': 'UserPromptSubmit', 'additionalContext': PRINCIPLES}}
