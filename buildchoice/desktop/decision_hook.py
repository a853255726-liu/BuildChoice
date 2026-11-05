"""Small trusted-callback entrypoint; no candidate extraction or model invocation."""
from pathlib import Path
from .decision_settings import read as read_settings
from .decision_store import DecisionStore


def handle_prompt(event,workspace,settings_path=None):
    config=read_settings(settings_path) if settings_path is not None else read_settings()
    if config['mode']!='pilot' or event.get('hook_event_name')!='UserPromptSubmit':return None
    cwd=event.get('cwd')
    if not isinstance(cwd,str) or not Path(cwd).resolve().is_relative_to(Path(workspace).resolve()):return None
    store=DecisionStore(workspace,ttl=config['context_ttl_seconds'])
    observed=store.observe_hook(event)
    if observed is None:return None
    if observed.get('session_handle'):
        context=('BuildChoice V3 pilot：当前 Hook 关联句柄 '+observed['session_handle']+'。'
                 '开发或实施前检查使用 decision-discovery Skill；长期记忆管理使用 decision-memory Skill。'
                 '纯咨询直接回答，句柄本身不要求调用工具。'+
                 '用户回复状态：'+observed.get('confirmation_status','none')+'。'+
                 (observed.get('reply_hint','') if observed.get('confirmation_status')=='awaiting_user' else '')+
                 ('记忆管理结果：'+str({k:v for k,v in observed.items() if k.startswith('memory_') or k=='reason'})+'。'
                  if 'memory_status' in observed else ''))
    else:
        context='BuildChoice V3：本轮缺少可核验的 Hook 身份，确认记录必须保持未核验；不阻塞原编程任务。'
    return {'hookSpecificOutput':{'hookEventName':'UserPromptSubmit','additionalContext':context}}
