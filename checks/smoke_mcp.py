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
from test_guidance import candidate

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
    names={t['name'] for t in send('tools/list',{})['tools']}
    assert len(names)==14,names
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

    event={'hook_event_name':'UserPromptSubmit','cwd':str(workspace),'session_id':'mcp-smoke','turn_id':'1','prompt':'给现有项目加登录'}
    handle=re.search(r'buildchoice-v3-ctx-[A-Za-z0-9_-]+',hook(event))[0]
    response=call('buildchoice_screen_candidates',{'request':{'task_text':event['prompt'],'phase':'before_implementation',
        'next_step':'Implement access rules','candidates':[candidate()],'session_handle':handle,'idempotency_key':'screen',
        'coverage':[{'dimension':'access_visibility','status':'candidate','reason':'Access rule needs a choice.','candidate_ids':['visibility']}]}})
    item=response['decisions'][0]
    assert item['status']=='ASK_NOW' and response['coverage']['reported']
    active=call('buildchoice_card_activate',{'task_id':response['task_id'],'decision_id':item['decision_id'],
        'revision':1,'idempotency_key':'activate','session_handle':handle})
    assert 'BuildChoice' in active['message']
    retried=call('buildchoice_card_activate',{'task_id':response['task_id'],'decision_id':item['decision_id'],
        'revision':1,'idempotency_key':'activate','session_handle':handle})
    assert retried==active
    confirmed=re.search(r'buildchoice-v3-ctx-[A-Za-z0-9_-]+',hook({**event,'turn_id':'2','prompt':'A'}))[0]
    status=call('buildchoice_decision_status',{'task_id':response['task_id'],'session_handle':confirmed})
    assert status['decisions'][0]['status']=='PROCEED'
    assert status['confirmation_history'][0]['choice_id']=='A'
    assert status['coverage']==response['coverage']
    old_activation=send('tools/call',{'name':'buildchoice_card_activate','arguments':{
        'task_id':response['task_id'],'decision_id':item['decision_id'],'revision':1,
        'idempotency_key':'activate','session_handle':confirmed}})
    assert old_activation.get('isError'),old_activation

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
    call('buildchoice_decision_prepare_revision',{'task_id':response['task_id'],'decision_id':item['decision_id'],
        'revision':1,'candidate':candidate(),'reason':'Changed access rule','session_handle':confirmed})
    status=call('buildchoice_decision_status',{'task_id':response['task_id'],'session_handle':confirmed})
    assert 'DECISION_REVISION_CHANGED' in status['implementations'][0]['reason_codes']
    rejected=send('tools/call',{'name':'buildchoice_verify_decision','arguments':verify_args})
    assert rejected.get('isError'),rejected

    call('buildchoice_settings_update',{'set':{'mode':'完全关闭'}})
    names={t['name'] for t in send('tools/list',{})['tools']}
    assert names=={'buildchoice_settings_read','buildchoice_settings_update','buildchoice_settings_status','buildchoice_decision_status'},names
    assert not call('buildchoice_decision_status',{})['enabled']
    blocked=send('tools/call',{'name':'buildchoice_audit_start','arguments':{'title':'Blocked','task':'No write'}})
    assert blocked.get('isError'),blocked
    for tool in ('buildchoice_acceptance_prepare','buildchoice_verify_decision'):
        blocked=send('tools/call',{'name':tool,'arguments':({**arguments,'criteria':[],'idempotency_key':'off'} if tool.endswith('prepare') else verify_args)})
        assert blocked.get('isError'),blocked
    call('buildchoice_settings_update',{'set':{'mode':'Prompt 优先','decision_guidance':'关闭'}})
    assert len(send('tools/list',{})['tools'])==8
    for tool in ('buildchoice_acceptance_prepare','buildchoice_verify_decision'):
        blocked=send('tools/call',{'name':tool,'arguments':({**arguments,'criteria':conditions['criteria'],'idempotency_key':'pilot-off'} if tool.endswith('prepare') else verify_args)})
        assert blocked.get('isError'),blocked
    print('PASS actual MCP initialize, 14 tools, settings, audit, synthetic Hook confirmation, acceptance, explicit CLI execution, verification, stale results and off/pilot-off behavior')
finally:
    process.stdin.close()
    try:process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.terminate()
        process.wait(timeout=5)
    log.close()
