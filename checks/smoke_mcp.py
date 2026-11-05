"""Launch the actual MCP server and exercise its retained tools over JSON-RPC."""
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import tempfile
import threading
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'checks'))
from test_guidance import candidate as base_candidate


def candidate():
    value=base_candidate();value['decision_key']='profile.visibility';value['suggested_action']='ASK_NOW'
    for option in value['options']:
        option['option_key']='profile.private' if option['id']=='A' else 'profile.public'
    return value

workspace=Path(os.environ.get('BUILDCHOICE_CHECK_ROOT',tempfile.gettempdir())).resolve()/('buildchoice-mcp-'+uuid.uuid4().hex)
workspace.mkdir()
settings=workspace/'settings.json'
settings.write_text('{"config_version":1,"mode":"prompt"}',encoding='utf-8')
decisions=workspace/'decision_v3.json'
decisions.write_text('{"config_version":2,"mode":"pilot","context_ttl_seconds":900}',encoding='utf-8')
env={**os.environ,'BUILDCHOICE_WORKSPACE':str(workspace),'BUILDCHOICE_V3_SETTINGS':str(decisions),
     'PYTHONUTF8':'1','PYTHONIOENCODING':'utf-8'}
log=(workspace/'server.stderr.log').open('w',encoding='utf-8')
command=[sys.executable,str(ROOT/'scripts/buildchoice_mcp.py'),'--native-settings','--settings',str(settings)]
process=subprocess.Popen(command,
    stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=log,text=True,encoding='utf-8',env=env)
replies=queue.Queue()
def collect():
    for line in process.stdout:
        replies.put(json.loads(line))
    replies.put({'server_closed':True})
threading.Thread(target=collect,daemon=True).start()
ident=0
def send(method,params=None,notify=False):
    global ident
    request={'jsonrpc':'2.0','method':method}
    if params is not None:request['params']=params
    if not notify:
        ident+=1
        request['id']=ident
    process.stdin.write(json.dumps(request,ensure_ascii=False)+'\n')
    process.stdin.flush()
    if notify:return
    while True:
        response=replies.get(timeout=20)
        if response.get('server_closed'):raise AssertionError('Server exited; inspect '+str(workspace))
        if response.get('id')==ident:
            assert 'error' not in response,response
            return response['result']
def call(name,arguments):
    result=send('tools/call',{'name':name,'arguments':arguments})
    assert not result.get('isError'),result
    if 'structuredContent' in result:return result['structuredContent']
    return json.loads(''.join(c['text'] for c in result['content'] if c['type']=='text'))
def hook(event):
    run=subprocess.run([sys.executable,str(ROOT/'scripts/buildchoice_hook.py')],input=json.dumps(event,ensure_ascii=False),
        capture_output=True,text=True,encoding='utf-8',env=env,check=True,timeout=20)
    return json.loads(run.stdout)['hookSpecificOutput']['additionalContext']

try:
    init=send('initialize',{'protocolVersion':'2024-11-05','capabilities':{},'clientInfo':{'name':'BuildChoice smoke','version':'1'}})
    assert init['serverInfo']['name']=='buildchoice'
    send('notifications/initialized',notify=True)
    listed={t['name']:t for t in send('tools/list',{})['tools']};names=set(listed)
    assert len(names)==19,names
    from jsonschema import Draft202012Validator
    schema=listed['buildchoice_screen_candidates']['inputSchema'];Draft202012Validator.check_schema(schema)
    assert 'suggested_action' in schema['$defs']['Candidate']['required']
    assert 'phase' not in schema['$defs']['ScreenRequest']['properties']
    assert schema['$defs']['Candidate']['properties']['suggested_action']['enum']==['ASK_NOW','INSPECT','DEFER','PROCEED']
    assert not names & {'buildchoice_evaluate','buildchoice_assess_snapshot','buildchoice_get_status','buildchoice_set_auto_call'}
    native=call('buildchoice_settings_read',{})
    assert native['values']['mode']=='Prompt 优先'
    assert 'decision_model_check' not in native['values']
    assert call('buildchoice_settings_status',{})['decision_guidance_active']

    # Audit and actual source binding through the running server.
    (workspace/'requirements.txt').write_text('Only the owner can read profiles.',encoding='utf-8')
    session=call('buildchoice_audit_start',{'title':'MCP smoke','task':'Check profile visibility'})
    source=call('buildchoice_audit_read',{'session':session['id'],'path':'requirements.txt'})
    call('buildchoice_audit_decision',{'session':session['id'],'title':'Visibility','value':'private',
        'refs':[{'source_id':source['id'],'quote':'Only the owner'}]})
    assert call('buildchoice_audit_report',{'session':session['id']})['report']['summary']['decisions']==1

    event={'hook_event_name':'UserPromptSubmit','cwd':str(workspace),'session_id':'mcp-smoke','turn_id':'1','prompt':'给现有项目加登录\r\n'}
    handle=re.search(r'buildchoice-v3-ctx-[A-Za-z0-9_-]+',hook(event))[0]
    context=call('buildchoice_context',{'session_handle':handle,'paths':['requirements.txt'],'max_chars':3000})
    reused=call('buildchoice_context',{'session_handle':handle,'paths':['requirements.txt'],'since':context['snapshot_id']})
    assert reused['sources'][0]['source_id']==context['sources'][0]['source_id']
    assert reused['sources'][0]['reused'] and reused['changes']==[]
    response=call('buildchoice_screen_candidates',{'request':{'task_text':event['prompt'].strip('\r\n'),'phase':'before_implementation',
        'next_step':'Implement access rules','candidates':[candidate()],'session_handle':handle,'idempotency_key':'screen',
        'coverage':[{'dimension':'access_visibility','status':'candidate','reason':'Access rule needs a choice.','candidate_ids':['visibility']}]}})
    item=response['decisions'][0]
    # Display-only risk metadata does not change option identity or Hook reply parsing.
    risk_candidate=candidate()
    risk_candidate['options'][1].update(risk_level='high',risk_basis='potential',
        risk_warning='If a link is shared with the wrong person, profile details may become visible.',
        risk_condition='If a user forwards the profile link',risk_reason='The option uses a transferable link.')
    risk_response=call('buildchoice_screen_candidates',{'request':{'task_id':response['task_id'],
        'task_text':event['prompt'].strip('\r\n'),'phase':'before_implementation','next_step':'Implement access rules',
        'candidates':[risk_candidate],'session_handle':handle,'idempotency_key':'risk-copy',
        'coverage':[{k:v for k,v in e.items() if k in ('dimension','status','reason','candidate_ids','evidence_refs')}
                    for e in response['coverage']['entries']]}})
    assert risk_response['decisions'][0]['decision_id']==item['decision_id']
    assert risk_response['decisions'][0]['revision']==1
    assert item['status']=='ASK_NOW' and response['coverage']['reported']
    active=call('buildchoice_card_activate',{'task_id':response['task_id'],'decision_id':item['decision_id'],
        'revision':1,'idempotency_key':'activate','session_handle':handle})
    assert 'BuildChoice' in active['message']
    assert '风险提示' in active['message']
    retried=call('buildchoice_card_activate',{'task_id':response['task_id'],'decision_id':item['decision_id'],
        'revision':1,'idempotency_key':'activate','session_handle':handle})
    assert retried==active
    confirmed=re.search(r'buildchoice-v3-ctx-[A-Za-z0-9_-]+',hook({**event,'turn_id':'2','prompt':'我选第一个方案\r\n'}))[0]
    status=call('buildchoice_decision_status',{'task_id':response['task_id'],'session_handle':confirmed})
    assert status['decisions'][0]['status']=='PROCEED'
    assert status['confirmation_history'][0]['choice_id']=='A'
    risk_candidate['options'][1]['risk_warning']='If the link is forwarded, access may reach unintended viewers.'
    refreshed=call('buildchoice_screen_candidates',{'request':{'task_id':response['task_id'],
        'task_text':event['prompt'].strip('\r\n'),'phase':'during_implementation','next_step':'Continue access rules',
        'candidates':[risk_candidate],'session_handle':confirmed,'idempotency_key':'confirmed-risk-copy'}})
    assert refreshed['decisions'][0]['revision']==1
    assert refreshed['decisions'][0]['confirmation_status']=='user_message_observed'
    assert status['coverage']==response['coverage']
    old_activation=send('tools/call',{'name':'buildchoice_card_activate','arguments':{
        'task_id':response['task_id'],'decision_id':item['decision_id'],'revision':1,
        'idempotency_key':'activate','session_handle':confirmed}})
    assert old_activation.get('isError'),old_activation
    invalid_revision=candidate();invalid_revision['options'][1]['id']='A'
    rejected_revision=send('tools/call',{'name':'buildchoice_decision_prepare_revision','arguments':{
        'task_id':response['task_id'],'decision_id':item['decision_id'],'revision':1,'candidate':invalid_revision,
        'reason':'Invalid duplicate option IDs must not be saved','session_handle':confirmed}})
    assert rejected_revision.get('isError'),rejected_revision
    assert call('buildchoice_decision_status',{'task_id':response['task_id'],'session_handle':confirmed})['decisions'][0]['revision']==1

    (workspace/'profile.py').write_text('visibility = "private"\n',encoding='utf-8')
    linked=call('buildchoice_link_implementation',{'task_id':response['task_id'],'decision_id':item['decision_id'],
        'revision':1,'path':'profile.py','note':'Uses the selected private visibility.','start_line':1,'session_handle':confirmed})
    assert linked['provenance']=='agent_reported_implementation'
    status=call('buildchoice_decision_status',{'task_id':response['task_id'],'session_handle':confirmed})
    assert not status['implementations'][0]['needs_recheck']
    (workspace/'profile.py').write_text('visibility = "public"\n',encoding='utf-8')
    status=call('buildchoice_decision_status',{'task_id':response['task_id'],'session_handle':confirmed})
    assert status['implementations'][0]['needs_recheck']
    # Preparation and verification are MCP calls; execution is a separate explicit CLI.
    (workspace/'profile.py').write_text('def can_read(owner, viewer): return owner == viewer\n',encoding='utf-8')
    (workspace/'test_profile.py').write_text('import unittest\nfrom profile import can_read\nclass Access(unittest.TestCase):\n def test_private(self): self.assertFalse(can_read("alice", "bob"))\n',encoding='utf-8')
    manifest={'adapter':'python-unittest-v1','test_file':'test_profile.py','files':{'implementation':['profile.py'],
        'tests':['test_profile.py'],'fixtures':[],'config':[]},'dependencies':[],'timeout_seconds':20,'scope':'Profile access smoke'}
    (workspace/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
    arguments={'task_id':response['task_id'],'decision_id':item['decision_id'],'revision':1,'session_handle':confirmed}
    conditions=call('buildchoice_acceptance_prepare',{**arguments,'criteria':[{'criterion_id':'private',
        'description':'Other users cannot read a private profile.','basis':'Choice A private visibility.','required':True,
        'evidence_type':'behavior','test_ids':['buildchoice_tests.Access.test_private']}],'idempotency_key':'conditions'})
    foreign=re.search(r'buildchoice-v3-ctx-[A-Za-z0-9_-]+',hook({**event,'session_id':'other-smoke-session','turn_id':'1'}))[0]
    for change in ({'session_handle':foreign},{'revision':99}):
        rejected=send('tools/call',{'name':'buildchoice_acceptance_prepare','arguments':{**arguments,
            'criteria':conditions['criteria'],'idempotency_key':'invalid',**change}})
        assert rejected.get('isError'),rejected
    verify_args={**arguments,'acceptance_id':conditions['acceptance_id'],'code_evidence_refs':[],'idempotency_key':'no-tests'}
    assert call('buildchoice_verify_decision',verify_args)['verdict']=='inconclusive'
    collected=subprocess.run([sys.executable,str(ROOT/'scripts/buildchoice_run_verification.py'),'--workspace',str(workspace),
        '--acceptance-id',conditions['acceptance_id'],'--manifest','manifest.json','--settings',str(settings),
        '--decision-settings',str(decisions)],capture_output=True,text=True,encoding='utf-8',env=env,check=True,timeout=30)
    receipt=json.loads(collected.stdout)
    verified=call('buildchoice_verify_decision',{**verify_args,'execution_id':receipt['execution_id'],'idempotency_key':'tested'})
    assert verified['current_pass'],verified
    (workspace/'profile.py').write_text('def can_read(owner, viewer): return True\n',encoding='utf-8')
    status=call('buildchoice_decision_status',{'task_id':response['task_id'],'session_handle':confirmed})
    assert not status['verification']['verifications'][0]['current_pass']
    memories=call('buildchoice_memory',{'query':'Profile','session_handle':confirmed})
    entry=memories['entries'][0]
    assert entry['tier']=='reference' and entry['provenance']=='user_message_observed'
    def memory_hook(prompt,turn,session='mcp-smoke'):
        return re.search(r'buildchoice-v3-ctx-[A-Za-z0-9_-]+',hook({**event,
            'session_id':session,'turn_id':turn,'prompt':prompt}))[0]
    blocked=call('buildchoice_memory_manage',{'memory_id':entry['memory_id'],'revision':1,'session_handle':confirmed})
    assert blocked['reason']=='EXPLICIT_USER_MEMORY_REQUEST_REQUIRED',blocked
    confirmed=memory_hook('把刚才的选择长期记住','3')
    intent=call('buildchoice_memory',{'session_handle':confirmed})['management_request']
    assert intent['reason']=='TARGET_UNIQUE',intent
    promoted=call('buildchoice_memory_manage',{'memory_id':entry['memory_id'],'revision':1,'session_handle':confirmed})
    assert promoted['memory_status']=='applied',promoted
    assert call('buildchoice_memory',{'session_handle':confirmed})['entries'][0]['tier']=='rule'
    fresh=memory_hook('查找历史决定','2','other-smoke-session')
    assert call('buildchoice_memory',{'session_handle':fresh})['entries'][0]['confirmation_id']==entry['confirmation_id']
    cross_task=send('tools/call',{'name':'buildchoice_decision_status','arguments':{'task_id':response['task_id'],'session_handle':fresh}})
    assert cross_task.get('isError'),cross_task
    fresh=memory_hook('遗忘 '+entry['memory_id'],'3','other-smoke-session')
    assert call('buildchoice_memory',{'session_handle':fresh})['entries']==[]
    assert call('buildchoice_memory',{'session_handle':fresh,'include_archived':True})['entries'][0]['state']=='forgotten'
    fresh=memory_hook('恢复 '+entry['memory_id'],'4','other-smoke-session')
    assert call('buildchoice_memory',{'session_handle':fresh})['entries'][0]['tier']=='rule'
    call('buildchoice_decision_prepare_revision',{'task_id':response['task_id'],'decision_id':item['decision_id'],
        'revision':1,'candidate':candidate(),'reason':'Changed access rule','session_handle':confirmed})
    status=call('buildchoice_decision_status',{'task_id':response['task_id'],'session_handle':confirmed})
    assert 'DECISION_REVISION_CHANGED' in status['implementations'][0]['reason_codes']
    assert call('buildchoice_memory',{'session_handle':confirmed})['entries']==[]
    rejected=send('tools/call',{'name':'buildchoice_verify_decision','arguments':verify_args})
    assert rejected.get('isError'),rejected

    # Actual MCP context/resume, LLM-interpreted reply and protected generated document.
    natural=memory_hook('开发用户页面的访问范围','1','natural-smoke')
    natural_request={'task_text':'开发用户页面的访问范围',
        'next_step':'Implement visibility','candidates':[candidate()],'session_handle':natural,'idempotency_key':'natural-screen'}
    natural_response=call('buildchoice_screen_candidates',{'request':natural_request})
    natural_item=natural_response['decisions'][0]
    natural_args={'task_id':natural_response['task_id'],'decision_id':natural_item['decision_id'],'revision':1,'session_handle':natural}
    shown=call('buildchoice_card_activate',{**natural_args,'idempotency_key':'natural-activate'})
    same=call('buildchoice_card_activate',{**natural_args,'idempotency_key':'natural-activate-new-key'})
    assert same['already_active'] and same['card']==shown['card']
    resumed=call('buildchoice_context',{'session_handle':natural})
    assert resumed['decisions'][0]['resume_action']=='continue_current_card'
    natural=memory_hook('采用私密方案，请继续完成页面。','2','natural-smoke');natural_args['session_handle']=natural
    interpreted=call('buildchoice_reply_interpret',{**natural_args,'choice_id':'A','quote':'采用私密方案',
        'reason':'The private option is the first offered option'})
    assert interpreted['confirmation']['provenance']=='llm_interpreted_user_reply'
    assert interpreted['semantic_verified_by_program'] is False
    assert call('buildchoice_reply_interpret',{**natural_args,'choice_id':'A','quote':'采用私密方案',
        'reason':'Same reading of the actual message'})['replayed']
    resumed=call('buildchoice_context',{'session_handle':natural,'since':resumed['snapshot_id']})
    assert resumed['decisions'][0]['state']=='confirmed' and 'pending_reply' not in resumed
    assert any(c['kind']=='decisions' for c in resumed['changes'])
    document=call('buildchoice_decision_document',{'session_handle':natural,'write':True})
    assert document['written'] and (workspace/document['path']).is_file()
    assert '选项对应由 LLM 解释' in document['markdown']
    assert any(r['confirmation'] and r['confirmation']['provenance']=='llm_interpreted_user_reply' for r in document['decisions'])
    (workspace/'USER_DECISIONS.md').write_text('My own notes',encoding='utf-8')
    assert send('tools/call',{'name':'buildchoice_decision_document','arguments':{
        'session_handle':natural,'write':True,'path':'USER_DECISIONS.md'}}).get('isError')
    assert (workspace/'USER_DECISIONS.md').read_text(encoding='utf-8')=='My own notes'
    new_tool_args={'buildchoice_context':{'session_handle':natural},
        'buildchoice_decision_document':{'session_handle':natural},
        'buildchoice_reply_interpret':{**natural_args,'choice_id':'A','quote':'采用私密方案','reason':'Existing reply'}}

    call('buildchoice_settings_update',{'set':{'mode':'完全关闭'}})
    names={t['name'] for t in send('tools/list',{})['tools']}
    assert names=={'buildchoice_settings_read','buildchoice_settings_update','buildchoice_settings_status','buildchoice_decision_status'},names
    assert not call('buildchoice_decision_status',{})['enabled']
    blocked=send('tools/call',{'name':'buildchoice_audit_start','arguments':{'title':'Blocked','task':'No write'}})
    assert blocked.get('isError'),blocked
    assert send('tools/call',{'name':'buildchoice_memory','arguments':{'session_handle':fresh}}).get('isError')
    for tool,args in new_tool_args.items():
        assert send('tools/call',{'name':tool,'arguments':args}).get('isError')
    for tool in ('buildchoice_acceptance_prepare','buildchoice_verify_decision'):
        blocked=send('tools/call',{'name':tool,'arguments':({**arguments,'criteria':[],'idempotency_key':'off'} if tool.endswith('prepare') else verify_args)})
        assert blocked.get('isError'),blocked
    call('buildchoice_settings_update',{'set':{'mode':'Prompt 优先','decision_guidance':'关闭'}})
    assert len(send('tools/list',{})['tools'])==8
    for tool,args in new_tool_args.items():
        assert send('tools/call',{'name':tool,'arguments':args}).get('isError')
    assert send('tools/call',{'name':'buildchoice_memory','arguments':{'session_handle':fresh}}).get('isError')
    for tool in ('buildchoice_acceptance_prepare','buildchoice_verify_decision'):
        blocked=send('tools/call',{'name':tool,'arguments':({**arguments,'criteria':conditions['criteria'],'idempotency_key':'pilot-off'} if tool.endswith('prepare') else verify_args)})
        assert blocked.get('isError'),blocked
    print('PASS actual MCP: advertised contracts, 19 tools, reusable context, resume, direct/LLM-bound replies, protected decision document, memory, explicit verification and off/pilot-off behavior')
finally:
    process.stdin.close()
    try:process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.terminate()
        process.wait(timeout=5)
    log.close()
