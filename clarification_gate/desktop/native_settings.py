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


def read_settings(path=SWITCH, include_v3=False):
    # Fresh installs default to automatic. Reading never creates or modifies a file.
    mode = switch_status(path)['mode'] if path.exists() else 'prompt'
    result = {'schema': {'type': 'object', 'properties': {'mode': {
        'type': 'string', 'title': '判别调用模式', 'enum': list(MODES),
        'description': 'Prompt 优先：注入澄清原则，不调用分类器，可按需审计。强制：受支持的本地流程先取得回执，需信任四项 Hook；'
                       '自动：由 Codex 决定是否调用；关闭：拒绝判别请求。'
                       f'ASK / INSPECT / PASS 均为建议。项目：{WORKSPACE}。'}}, 'required': ['mode']},
        'values': {'mode': LABELS[mode]},
        'layout': [{'kind': 'group', 'title': 'BuildChoice',
                    'items': [{'kind': 'property', 'property': 'mode'},
                              {'kind': 'tool', 'tool': 'gate_settings_status',
                               'description': '查看实际模式与 Hook 信任状态（不会启动模型）'}]}]}
    if include_v3:
        from .decision_settings import read
        settings=read()
        result['schema']['properties'].update({
            'decision_guidance':{'type':'string','enum':['关闭','试用'],'title':'V3 关键决策引导（独立试用开关）'},
            'decision_model_check':{'type':'string','enum':['关闭','开启'],'title':'V3 NLI 第二意见'}})
        result['values'].update(decision_guidance='试用' if settings['mode']=='pilot' else '关闭',
                                decision_model_check='开启' if settings['model_check']=='on' else '关闭')
        result['layout'][0]['items'] += [{'kind':'property','property':'decision_guidance'},
                                         {'kind':'property','property':'decision_model_check'}]
    return result


def update_settings(arguments, path=SWITCH):
    if (not isinstance(arguments,dict) or set(arguments)!={'set'} or not isinstance(arguments['set'],dict) or
            not arguments['set'] or set(arguments['set'])-{'mode','decision_guidance','decision_model_check'}):
        raise ValueError('Expected valid explicitly selected settings')
    values=arguments['set']
    if 'mode' in values and (not isinstance(values['mode'],str) or values['mode'] not in MODES):raise ValueError('Invalid mode')
    if 'decision_guidance' in values and values['decision_guidance'] not in ('关闭','试用'):raise ValueError('Invalid V3 mode')
    if 'decision_model_check' in values and values['decision_model_check'] not in ('关闭','开启'):raise ValueError('Invalid model check')
    result={}
    if 'mode' in values:
        state=set_mode(MODES[values['mode']],path);result['mode']=LABELS[state['mode']]
    if 'decision_guidance' in values or 'decision_model_check' in values:
        from .decision_settings import update
        update(mode={'关闭':'off','试用':'pilot'}[values['decision_guidance']] if 'decision_guidance' in values else None,
               model_check={'关闭':'off','开启':'on'}[values['decision_model_check']] if 'decision_model_check' in values else None)
        result.update({k:v for k,v in values.items() if k!='mode'})
    return {'values':result}
