"""Real message binding, versioned direct choices and recoverable file projection."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import uuid
from concurrent.futures import ThreadPoolExecutor
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from buildchoice.desktop.decision_service import DecisionService
from buildchoice.desktop.decision_store import DecisionStore
from buildchoice.desktop.decision_contracts import validate
from buildchoice.desktop import document_projection
from test_guidance import candidate


class InstructionTests(unittest.TestCase):
    def setUp(self):
        self.workspace=Path(os.environ.get('BUILDCHOICE_CHECK_ROOT',tempfile.gettempdir()))/('buildchoice-instruction-'+uuid.uuid4().hex)
        self.workspace.mkdir()
        self.settings=self.workspace/'mode.json'
        self.settings.write_text('{"config_version":2,"mode":"pilot","context_ttl_seconds":900}',encoding='utf-8')
        self.service=DecisionService(self.workspace,'owner',self.settings)
        self.store=DecisionStore(self.workspace);self.turn=0
        self.observe('所有账本先核对再保存')

    def observe(self,text,host='chat'):
        self.turn+=1;self.text=text
        self.handle=self.store.observe_hook({'hook_event_name':'UserPromptSubmit','cwd':str(self.workspace),
            'session_id':host,'turn_id':str(self.turn),'prompt':text})['session_handle']
        return self.handle

    def request(self,previous=None,value=None,**extras):
        request={'session_handle':self.handle,'user_message':self.text,'quote':self.text,'reason':'用户明确修改本项目入账规则',
            'expected_revision':previous['revision'] if previous else 0,'idempotency_key':uuid.uuid4().hex}
        if previous:request['decision_id']=previous['decision_id']
        if value is not None or not previous:
            request['decision']={'decision_key':'receipt.saving','field':'入账方式','scope_key':'project',
                'choice':{'label':'当前入账方式','value':value or {'ordinary':'review','travel':'review'}}}
        return request|extras

    def record(self,previous=None,value=None,**extras):return self.service.record_instruction(self.request(previous,value,**extras))

    def counts(self):
        with self.store.connect() as db:return tuple(db.execute('SELECT count(*) FROM '+n).fetchone()[0] for n in
            ('decision_v3_items','decision_v3_confirmations'))

    def test_changes_reaffirm_and_fresh_chat_recover_canonical_choice(self):
        first=self.record();self.assertEqual(first['document']['status'],'synchronized')
        self.observe('普通和旅行账本都改成自动入账');second=self.record(first,{'ordinary':'auto','travel':'auto'})
        self.observe('确认刚才的修改');reaffirm=self.record(second)
        self.assertTrue(reaffirm['unchanged']);self.assertEqual(self.counts(),(2,2))
        self.observe('旅行账本恢复核对，普通仍自动');third=self.record(second,{'ordinary':'auto','travel':'review'})
        self.observe('确认最终规则');self.record(third)
        self.assertEqual(self.counts(),(3,3));self.assertEqual(third['revision'],3)
        self.observe('恢复项目决定',host='fresh')
        context=self.service.context_bundle(self.handle)
        self.assertEqual(context['document']['status'],'synchronized')
        self.assertEqual(len(context['memory']),1)
        self.assertEqual(context['memory'][0]['choice']['value'],{'ordinary':'auto','travel':'review'})
        self.assertEqual(context['memory'][0]['tier'],'reference')
        self.assertEqual(context['memory'][0]['provenance'],'llm_interpreted_user_instruction')
        markdown=(self.workspace/third['document']['path']).read_text(encoding='utf-8')
        self.assertIn('"ordinary":"auto"',markdown);self.assertIn('"travel":"review"',markdown)
        self.assertIn('v3',markdown)
        # Cross-chat recall is read-only, not permission to take over the originating task.
        with self.assertRaisesRegex(ValueError,'host session|Cross-session'):
            self.record(third,{'ordinary':'review','travel':'review'})

    def test_pending_unactivated_proposal_accepts_observed_instruction(self):
        cand={**candidate(),'decision_key':'receipt.saving','suggested_action':'ASK_NOW'}
        self.observe('开发资料访问功能')
        screened=self.service.screen({'task_text':self.text,'next_step':'实现访问范围','candidates':[cand],
            'session_handle':self.handle,'idempotency_key':'screen'})
        item=screened['decisions'][0]
        self.service.prepare_revision(screened['task_id'],item['decision_id'],1,cand,'修订提案',self.handle)
        self.observe('采用仅本人可见的方案')
        answer=self.record({'decision_id':item['decision_id'],'revision':2},choice_id='A')
        self.assertEqual(answer['revision'],2);self.assertEqual(self.counts(),(2,1))
        self.assertEqual(answer['choice']['label'],'Private')
        status=self.service.status(screened['task_id'],self.handle)
        self.assertEqual(status['decisions'][0]['state'],'confirmed')

    def test_source_quote_owner_and_stale_handle_rejections_roll_back(self):
        before=self.counts();request=self.request()
        for changed in ({'user_message':'伪造用户选择'},{'quote':'不存在的内容'},{'user_message':' 所有账本先核对再保存'}):
            with self.assertRaises(ValueError):self.service.record_instruction(request|changed)
        self.assertEqual(before,self.counts())
        first=self.service.record_instruction(request)
        other=DecisionService(self.workspace,'other',self.settings)
        with self.assertRaisesRegex(ValueError,'another MCP'):other.record_instruction(request)
        self.observe('新的消息')
        with self.assertRaisesRegex(ValueError,'expired'):self.service.record_instruction(request)
        with self.assertRaisesRegex(ValueError,'REVISION_CHANGED'):
            self.record({'decision_id':first['decision_id'],'revision':20})

    def test_idempotency_conflicting_readings_and_old_receipt_never_revert(self):
        request=self.request();first=self.service.record_instruction(request)
        self.assertTrue(self.service.record_instruction(request)['replayed'])
        self.assertTrue(self.service.record_instruction(request|{'idempotency_key':'another'})['replayed'])
        changed=json.loads(json.dumps(request));changed['decision']['choice']['value']='auto'
        with self.assertRaisesRegex(ValueError,'conflicts'):self.service.record_instruction(changed)
        with self.assertRaisesRegex(ValueError,'already has'):self.record(first,{'ordinary':'auto'})
        self.observe('全部自动入账');second=self.record(first,{'ordinary':'auto','travel':'auto'})
        self.observe(request['user_message'])
        replay=self.service.record_instruction(request|{'session_handle':self.handle})
        self.assertFalse(replay['current']);self.assertEqual(replay['latest_revision'],2)
        self.assertEqual(self.counts(),(2,2))
        self.assertIn('v2',(self.workspace/second['document']['path']).read_text(encoding='utf-8'))

    def test_file_failure_durable_pending_and_reconnect_retry_no_duplicate(self):
        request=self.request()
        with patch('buildchoice.desktop.document_projection.os.replace',side_effect=OSError('disk unavailable')):
            result=self.service.record_instruction(request)
        self.assertTrue(result['recorded']);self.assertEqual(result['document']['status'],'pending')
        self.assertFalse((self.workspace/'BUILDCHOICE_DECISIONS.md').exists())
        self.assertEqual(self.service.context_bundle(self.handle)['document']['status'],'pending')
        self.observe(self.text)
        other=DecisionService(self.workspace,'reconnected',self.settings)
        replay=other.record_instruction(request|{'session_handle':self.handle})
        self.assertTrue(replay['replayed']);self.assertEqual(replay['document']['status'],'synchronized')
        self.assertEqual(self.counts(),(1,1))

    def test_user_document_is_preserved_and_modified_projection_is_detected(self):
        original=self.workspace/'BUILDCHOICE_DECISIONS.md';original.write_text('用户自己的记录',encoding='utf-8')
        first=self.record();self.assertNotEqual(first['document']['path'],original.name)
        self.assertEqual(original.read_text(encoding='utf-8'),'用户自己的记录')
        target=self.workspace/first['document']['path'];target.write_text('用户接管此文件',encoding='utf-8')
        self.assertEqual(self.service.context_bundle(self.handle)['document']['status'],'pending')
        repaired=self.service.decision_document(self.handle,write=True)
        self.assertTrue(repaired['written']);self.assertNotEqual(repaired['path'],target.name)
        self.assertEqual(target.read_text(encoding='utf-8'),'用户接管此文件')

    def test_database_failure_rolls_back_without_file_ahead(self):
        with patch('buildchoice.desktop.document_projection.queue',side_effect=RuntimeError('render failure')):
            with self.assertRaises(RuntimeError):self.record()
        self.assertEqual(self.counts(),(0,0));self.assertFalse((self.workspace/'BUILDCHOICE_DECISIONS.md').exists())

    def test_concurrent_writes_require_current_revision(self):
        first=self.record();self.observe('更改所有账本')
        requests=[self.request(first,{'ordinary':v,'travel':v}) for v in ('auto','review')]
        def write(request):
            try:return self.service.record_instruction(request)
            except ValueError:return None
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(write,requests))
        self.assertEqual(sum(r is not None for r in results),1)
        self.assertEqual(self.service.context_bundle(self.handle)['document']['status'],'synchronized')

    def test_refs_and_identity_cannot_be_fabricated(self):
        request=self.request();request['decision']['evidence_refs']=[{'source_id':'src-invented','quote':'假资料'}]
        with self.assertRaisesRegex(ValueError,'references'):self.service.record_instruction(request)
        first=self.record();self.observe('明确修改方案')
        request=self.request(first,'auto');request['decision']['decision_key']='other.key'
        with self.assertRaisesRegex(ValueError,'retain'):self.service.record_instruction(request)

    def test_optional_implementation_guard_accepts_direct_instruction_source(self):
        first=self.record();(self.workspace/'app.py').write_text('mode="review"\n',encoding='utf-8')
        linked=self.service.link_implementation(first['task_id'],first['decision_id'],1,'app.py','入账规则',session_handle=self.handle)
        self.assertTrue(linked['does_not_prove_correctness'])
        status=self.service.status(first['task_id'],self.handle)
        self.assertEqual(status['decisions'][0]['confirmation']['provenance'],'llm_interpreted_user_instruction')
        confirmation=status['decisions'][0]['confirmation']
        event={k:confirmation[k] for k in ('decision_id','revision','choice_id','provenance','host_turn_digest','user_prompt_digest')}
        self.assertEqual(validate('ConfirmationEvent',event),event)
        validate('ConfirmationEvent',event|{'provenance':'llm_interpreted_user_reply'})

    def test_new_key_cannot_duplicate_same_chat_decision(self):
        self.record();self.observe('再次保存同一选择')
        with self.assertRaisesRegex(ValueError,'Existing decision requires'):self.record()

    def test_ordinary_card_change_marks_projection_stale_and_document_write_repairs(self):
        first=self.record();self.observe('重新选择访问范围')
        cand={**candidate(),'decision_key':'receipt.saving','suggested_action':'ASK_NOW'}
        self.service.prepare_revision(first['task_id'],first['decision_id'],1,cand,'重新选择',self.handle)
        self.assertEqual(self.service.context_bundle(self.handle)['document']['status'],'pending')
        repaired=self.service.decision_document(self.handle,write=True)
        self.assertNotIn('已选方案：当前入账方式',repaired['markdown'])
        self.assertEqual(self.service.context_bundle(self.handle)['document']['status'],'synchronized')
