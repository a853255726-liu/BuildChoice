"""Small trusted-callback entrypoint; no candidate extraction or model invocation."""
import re
from pathlib import Path
from .decision_settings import read as read_settings
from .decision_store import DecisionStore


def coding_request(prompt):
    """A positive hint only; a miss never prevents creating a turn context."""
    if not isinstance(prompt,str):return False
    if (re.match(r'^\s*(?:(?:请|帮我|能否|可以)\s*)?(解释|说明|介绍|讲讲|什么是|为什么|explain|what is|why\b)',prompt,re.I)
            and not re.search(r'(并|然后|再|and then).{0,8}(实现|开发|修复|修改|implement|fix)',prompt,re.I)):
        return False
    return bool(re.search(r'(做一个|做个|做一套|实现|开发|搭建|编写|创建|修改|重构|修复|build|make|implement|develop|fix|refactor|create).{0,100}(网站|应用|接口|页面|功能|程序|代码|配置|软件|site|app|api|page|feature|code|config)',prompt,re.I))


def handle_prompt(event,workspace,settings_path=None):
    config=read_settings(settings_path) if settings_path is not None else read_settings()
    if config['mode']!='pilot' or event.get('hook_event_name')!='UserPromptSubmit':return None
    cwd=event.get('cwd')
    if not isinstance(cwd,str) or not Path(cwd).resolve().is_relative_to(Path(workspace).resolve()):return None
    hint=coding_request(event.get('prompt',''))
    store=DecisionStore(workspace,ttl=config['context_ttl_seconds'])
    observed=store.observe_hook(event)
    if observed is None:return None
    if observed.get('session_handle'):
        context=('BuildChoice V3 pilot：当前 Hook 关联句柄 '+observed['session_handle']+'。'
                 '结合本轮消息和对话上下文判断是否正在实施开发；正则未命中不排除简短修改或承接请求。'
                 '仅实际开发或实施前检查使用 decision-discovery Skill；纯咨询与解释直接回答，句柄本身不要求调用工具或提问。'
                 '需要提取时，在同一次提取中附简短 coverage 依据，不增加第二轮复核；零候选正常继续。'
                 '已有待答卡先处理回复状态，一次一张卡。'+
                 ('检测到开发表达提示。' if hint else '')+
                 '用户回复状态：'+observed.get('confirmation_status','none')+'。')
    else:
        context='BuildChoice V3：本轮缺少可核验的 Hook 身份，确认记录必须保持未核验；不阻塞原编程任务。'
    return {'hookSpecificOutput':{'hookEventName':'UserPromptSubmit','additionalContext':context}}
