"""Native settings for Prompt-first and independent decision cards."""
from .settings import SETTINGS, read, update, status

LABELS = {'prompt': 'Prompt 优先', 'off': '完全关闭'}
MODES = {label: mode for mode, label in LABELS.items()}
CAPABILITY = {'openai/settings': {'readTool': 'buildchoice_settings_read', 'updateTool': 'buildchoice_settings_update'}}


def read_settings(path=SETTINGS, include_v3=True):
    values = {'mode': LABELS[read(path)['mode']]}
    properties = {'mode': {'type': 'string', 'title': '运行模式', 'enum': list(MODES),
        'description': 'Prompt 优先：注入澄清原则，可按需审计。完全关闭：停用提示、审计工具和决策卡。'}}
    items = [{'kind': 'property', 'property': 'mode'}, {'kind': 'tool', 'tool': 'buildchoice_settings_status',
        'description': '查看当前模式、决策卡设置与 Hook 状态'}]
    if include_v3:
        from .decision_settings import read as read_decisions
        properties['decision_guidance'] = {'type': 'string', 'enum': ['关闭', '试用'], 'title': 'V3 关键决策引导'}
        values['decision_guidance'] = '试用' if read_decisions()['mode'] == 'pilot' else '关闭'
        items.append({'kind': 'property', 'property': 'decision_guidance'})
        properties['tool_profile']={'type':'string','enum':['日常','完整'],'title':'工具集',
            'description':'日常：决策、上下文和文档。完整：另含独立审计、记忆管理、代码关联和实验验证。'}
        values['tool_profile']='日常' if read_decisions()['tool_profile']=='core' else '完整'
        items.append({'kind':'property','property':'tool_profile'})
    return {'schema': {'type': 'object', 'properties': properties, 'required': ['mode']},
            'values': values, 'layout': [{'kind': 'group', 'title': 'BuildChoice', 'items': items}]}


def update_settings(arguments, path=SETTINGS):
    if (not isinstance(arguments, dict) or set(arguments) != {'set'} or not isinstance(arguments['set'], dict) or
            not arguments['set'] or set(arguments['set']) - {'mode', 'decision_guidance','tool_profile'}):
        raise ValueError('Expected explicitly selected BuildChoice settings')
    values = arguments['set']
    if 'mode' in values and values['mode'] not in MODES: raise ValueError('Invalid mode')
    if 'decision_guidance' in values and values['decision_guidance'] not in ('关闭', '试用'): raise ValueError('Invalid V3 mode')
    if 'tool_profile' in values and values['tool_profile'] not in ('日常','完整'):raise ValueError('Invalid tool profile')
    if 'mode' in values: update(MODES[values['mode']], path)
    if 'decision_guidance' in values:
        from .decision_settings import update as update_decisions
        update_decisions(mode='pilot' if values['decision_guidance'] == '试用' else 'off')
    if 'tool_profile' in values:
        from .decision_settings import update as update_decisions
        update_decisions(tool_profile='core' if values['tool_profile']=='日常' else 'full')
    return {'values': dict(values)}


def settings_status(path=SETTINGS):
    from .decision_settings import read as read_decisions
    result = status(path)
    result['decision_guidance'] = read_decisions()['mode']
    result['tool_profile']=read_decisions()['tool_profile']
    result['decision_guidance_active'] = result['mode'] != 'off' and result['decision_guidance'] == 'pilot'
    return result
