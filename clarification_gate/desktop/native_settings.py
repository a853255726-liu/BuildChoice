"""Native ChatGPT Structured Settings contract; no HTML, model loading or trust edits."""
from clarification_gate.desktop.auto_call import SWITCH, switch_status, set_mode
from clarification_gate.desktop.common import WORKSPACE

LABELS = {'prompt': 'Prompt 优先', 'required': '强制调用', 'auto': '自动选择', 'off': '完全关闭'}
MODES = {label: mode for mode, label in LABELS.items()}
CAPABILITY = {'openai/settings': {'readTool': 'gate_settings_read', 'updateTool': 'gate_settings_update'}}
READ_SCHEMA = {'type': 'object', 'properties': {
    'schema': {'type': 'object'}, 'values': {'type': 'object'},
    'layout': {'type': 'array', 'items': {'type': 'object'}}}, 'required': ['schema', 'values']}
UPDATE_INPUT = {'type': 'object', 'properties': {'set': {
    'type': 'object', 'properties': {'mode': {'type': 'string', 'enum': list(MODES)}},
    'minProperties': 1, 'additionalProperties': False}}, 'required': ['set'], 'additionalProperties': False}


def read_settings(path=SWITCH):
    # Fresh installs default to automatic. Reading never creates or modifies a file.
    mode = switch_status(path)['mode'] if path.exists() else 'prompt'
    return {'schema': {'type': 'object', 'properties': {'mode': {
        'type': 'string', 'title': '判别调用模式', 'enum': list(MODES),
        'description': 'Prompt 优先：注入澄清原则，不调用分类器，可按需审计。强制：受支持的本地流程先取得回执，需信任四项 Hook；'
                       '自动：由 Codex 决定是否调用；关闭：拒绝判别请求。'
                       f'ASK / INSPECT / PASS 均为建议。项目：{WORKSPACE}。'}}, 'required': ['mode']},
        'values': {'mode': LABELS[mode]},
        'layout': [{'kind': 'group', 'title': 'Clarification Gate',
                    'items': [{'kind': 'property', 'property': 'mode'},
                              {'kind': 'tool', 'tool': 'gate_settings_status',
                               'description': '查看实际模式与 Hook 信任状态（不会启动模型）'}]}]}


def update_settings(arguments, path=SWITCH):
    if (not isinstance(arguments, dict) or set(arguments) != {'set'} or
            not isinstance(arguments['set'], dict) or set(arguments['set']) != {'mode'} or
            not isinstance(arguments['set']['mode'], str) or arguments['set']['mode'] not in MODES):
        raise ValueError('Expected exactly one valid mode setting')
    state = set_mode(MODES[arguments['set']['mode']], path)
    return {'values': {'mode': LABELS[state['mode']]}}
