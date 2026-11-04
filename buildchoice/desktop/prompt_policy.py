"""Versioned Prompt-first policy. Deliberately no classifier imports."""
PRINCIPLES = ('执行会改变关键行为的任务前，检查必要约束是否已经明确。'
    '能从项目文件查明的先查文件；需要用户作出业务取舍的先提出具体问题。'
    '信息足够或存在合理可逆默认值时直接推进。只要求方案时可以给有条件的建议，避免不必要的追问。')
POLICY_VERSION = 'prompt-first-b-v1'
DISCOVERY_POLICY_VERSION = 'decision-discovery-v3'


def handle_prompt(event, workspace):
    from pathlib import Path
    if event.get('hook_event_name') != 'UserPromptSubmit':
        return None
    cwd = event.get('cwd')
    if not isinstance(cwd, str) or not Path(cwd).resolve().is_relative_to(Path(workspace).resolve()):
        return None
    return {'hookSpecificOutput': {'hookEventName': 'UserPromptSubmit', 'additionalContext': PRINCIPLES}}
