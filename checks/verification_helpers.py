"""Isolated synthetic confirmation fixtures; never evidence of a real host confirmation."""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import uuid
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from buildchoice.desktop.decision_store import DecisionStore
from buildchoice.desktop.decision_service import DecisionService
from buildchoice.desktop import acceptance


def criteria():
    return [{'criterion_id':key,'description':description,'basis':'Derived from review-before-save choice',
             'required':True,'evidence_type':'behavior','test_ids':['buildchoice_tests.ReceiptTests.'+test]}
        for key,description,test in [('display','Show recognized fields','test_display'),
                                    ('edit','Persist edited values','test_edit'),
                                    ('before-confirm','No formal write before confirmation','test_before_confirm'),
                                    ('cancel','No formal write on cancellation','test_cancel')]]


def setup_fixture(browser=False):
    base=Path(os.environ.get('BUILDCHOICE_CHECK_ROOT',tempfile.gettempdir())).resolve()
    workspace=base/('buildchoice-verification-'+uuid.uuid4().hex);workspace.mkdir()
    if browser:shutil.copytree(ROOT/'examples/receipt_review',workspace,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__'))
    settings=workspace/'v3.json';settings.write_text('{"config_version":2,"mode":"pilot","context_ttl_seconds":900}',encoding='utf-8')
    global_settings=workspace/'settings.json';global_settings.write_text('{"config_version":1,"mode":"prompt"}',encoding='utf-8')
    store=DecisionStore(workspace);service=DecisionService(workspace,'verification-fixture',settings_path=settings)
    event={'hook_event_name':'UserPromptSubmit','cwd':str(workspace),'session_id':'synthetic-test-session',
           'turn_id':'1','prompt':'开发拍照记账应用，识别结果核对后才正式保存。'}
    handle=store.observe_hook(event)['session_handle']
    candidate={'candidate_id':'saving','field':'入账流程','category':'business_rule','question':'何时正式入账？',
        'impact':'错误识别可能进入正式账本','why_user_choice':'产品使用流程','needs_user_choice':'yes','current_dependency':'yes',
        'risk_flags':[],'evidence_refs':[],'options':[{'id':'A','label':'核对后保存','tradeoff':'确认前允许修改'},
          {'id':'B','label':'直接保存','tradeoff':'识别后立即入账'}],'recommended_option_id':None,'recommendation_reason':''}
    response=service.screen({'task_text':event['prompt'],'phase':'before_implementation','next_step':'实现入账流程',
        'candidates':[candidate],'session_handle':handle,'idempotency_key':'screen'})
    item=response['decisions'][0];task_id=response['task_id']
    service.activate(task_id,item['decision_id'],1,'activate',handle)
    observed=store.observe_hook({**event,'turn_id':'2','prompt':'A'})
    handle=observed['session_handle'];task=store.task(task_id,service.owner,handle)
    conditions=acceptance.prepare(store,task,item['decision_id'],1,criteria(),'prepare')
    return {'workspace':workspace,'store':store,'service':service,'task':task,'item':item,'handle':handle,
            'conditions':conditions,'settings':settings,'global_settings':global_settings,'candidate':candidate,'event':event}


def small_manifest(fixture, body='import unittest\nclass Checks(unittest.TestCase):\n def test_ok(self): self.assertTrue(True)\n'):
    workspace=fixture['workspace']
    (workspace/'app.py').write_text('value = 1\n',encoding='utf-8')
    (workspace/'test_app.py').write_text(body,encoding='utf-8')
    value={'adapter':'python-unittest-v1','test_file':'test_app.py',
        'files':{'implementation':['app.py'],'tests':['test_app.py'],'fixtures':[],'config':[]},
        'dependencies':[],'timeout_seconds':10,'scope':'Isolated test fixture only'}
    (workspace/'manifest.json').write_text(json.dumps(value),encoding='utf-8')
    single=[{'criterion_id':'one','description':'Declared check','basis':'Synthetic selected choice','required':True,
             'evidence_type':'behavior','test_ids':['buildchoice_tests.Checks.test_ok']}]
    fixture['conditions']=acceptance.prepare(fixture['store'],fixture['task'],fixture['item']['decision_id'],1,single,'single')
    return value
