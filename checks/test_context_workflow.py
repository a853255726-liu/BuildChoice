"""Observable role boundaries, reusable context, resume and readable projections."""
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
import uuid
from jsonschema import Draft202012Validator
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from buildchoice.desktop.audit import encode
from buildchoice.desktop.decision_contracts import input_schema
from buildchoice.desktop.decision_service import DecisionService
from buildchoice.desktop.decision_store import DecisionStore
from test_guidance import candidate


class ContextWorkflowTests(unittest.TestCase):
    def setUp(self):
        base=Path(os.environ.get('BUILDCHOICE_CHECK_ROOT',tempfile.gettempdir())).resolve()
        self.workspace=base/('buildchoice-context-'+uuid.uuid4().hex);self.workspace.mkdir()
        self.settings=self.workspace/'mode.json'
        self.settings.write_text('{"config_version":2,"mode":"pilot","context_ttl_seconds":900}',encoding='utf-8')
        self.service=DecisionService(self.workspace,'owner-a',self.settings);self.store=DecisionStore(self.workspace)
        self.turn=0;self.prompt='Implement profile visibility';self.handle=self.hook(self.prompt)

    def hook(self,prompt,host='chat-a'):
        self.turn+=1
        return self.store.observe_hook({'hook_event_name':'UserPromptSubmit','cwd':str(self.workspace),
            'session_id':host,'turn_id':str(self.turn),'prompt':prompt})['session_handle']

    def screen(self,cand=None,task_id=None,key=None,**extras):
        value={**candidate(),'suggested_action':'ASK_NOW','decision_key':'profile.visibility'} if cand is None else cand
        request={'task_text':self.prompt,'phase':'before_implementation','next_step':'Implement profile rule',
            'candidates':[value],'session_handle':self.handle,'idempotency_key':key or uuid.uuid4().hex,**extras}
        if task_id:request['task_id']=task_id
        return self.service.screen(request)

    def activate(self,value):
        item=value['decisions'][0]
        return self.service.activate(value['task_id'],item['decision_id'],item['revision'],uuid.uuid4().hex,self.handle)

    def counts(self):
        with self.store.connect() as db:
            return {name:db.execute('SELECT count(*) FROM '+name).fetchone()[0] for name in
                ('sources','decision_v3_items','decision_v3_confirmations','decision_v3_events')}

    def test_llm_action_is_not_overridden_by_risk_keywords_or_uncertainty(self):
        for action in ('PROCEED','DEFER','INSPECT','ASK_NOW'):
            item=self.screen({**candidate(),'suggested_action':action,'risk_flags':['payment','publish']},next_step='Deploy public; pay for the API')['decisions'][0]
            self.assertEqual(item['suggested_action'],action)
            self.assertEqual(item['status'],action)
            self.assertEqual(item['validation_status'],'valid')

    def test_false_quote_blocks_binding_but_not_the_llm_recommendation(self):
        (self.workspace/'policy.txt').write_text('Only owner',encoding='utf-8')
        context=self.service.context_bundle(self.handle,paths=['policy.txt']);source=context['sources'][0]
        item=self.screen({**candidate(),'suggested_action':'PROCEED','evidence_refs':[{'source_id':source['source_id'],'quote':'Everyone'}]})['decisions'][0]
        self.assertEqual(item['suggested_action'],'PROCEED')
        self.assertEqual((item['status'],item['validation_status']),('INSPECT','needs_evidence'))

    def test_advertised_contract_exposes_fields_and_enums_for_minimal_request(self):
        schema=input_schema('ScreenRequest');Draft202012Validator.check_schema(schema)
        self.assertIn('suggested_action',schema['$defs']['Candidate']['required'])
        self.assertNotIn('phase',schema['$defs']['ScreenRequest']['properties'])
        self.assertNotIn('phase',schema['$defs']['ScreenRequest']['required'])
        self.assertEqual(schema['$defs']['EngineeringRisk']['properties']['recoverability']['enum'],['easy','costly','irreversible','unknown'])
        minimal={k:v for k,v in candidate().items() if k in ('candidate_id','field','category','question','impact','options')}
        minimal['suggested_action']='ASK_NOW'
        self.assertEqual(self.screen(minimal)['decisions'][0]['status'],'ASK_NOW')

    def test_omitted_phase_records_unknown_metadata_and_preserves_legacy_calls(self):
        for phase in (None,'before_implementation','during_implementation'):
            self.handle=self.hook(self.prompt)
            request={'task_text':self.prompt,'next_step':'Check visibility','candidates':[],
                'session_handle':self.handle,'idempotency_key':uuid.uuid4().hex,'suggested_action':'PROCEED'}
            if phase is not None:request['phase']=phase
            result=self.service.screen(request)
            self.assertEqual(result['screen_status'],'PROCEED')
            with self.store.connect() as db:
                recorded=db.execute('SELECT phase FROM decision_v3_tasks WHERE id=?',(result['task_id'],)).fetchone()[0]
            self.assertEqual(recorded,phase or 'unspecified')
            if phase is None:self.assertNotIn('phase',request)

    def test_explicit_invalid_phase_is_rejected_without_writing_a_task(self):
        with self.store.connect() as db:before=db.execute('SELECT count(*) FROM decision_v3_tasks').fetchone()[0]
        for phase in ('实施前需求检查','requirements_check','requirements'):
            with self.assertRaisesRegex(ValueError,'phase'):
                self.screen(phase=phase)
        with self.store.connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM decision_v3_tasks').fetchone()[0],before)

    def test_context_reuses_collector_source_without_new_receipts(self):
        (self.workspace/'README.md').write_text('Local profile requirement',encoding='utf-8')
        first=self.service.context_bundle(self.handle,paths=['README.md']);count=self.counts()['sources']
        second=self.service.context_bundle(self.handle,paths=['README.md'])
        self.assertEqual(first['sources'][0]['source_id'],second['sources'][0]['source_id'])
        self.assertTrue(second['sources'][0]['reused']);self.assertEqual(self.counts()['sources'],count)

    def test_context_source_resolves_only_the_resource_it_actually_read(self):
        (self.workspace/'policy.txt').write_text('Owner only',encoding='utf-8')
        (self.workspace/'unread.txt').write_text('Separate material',encoding='utf-8')
        source=self.service.context_bundle(self.handle,paths=['policy.txt'])['sources'][0]
        cand={**candidate(),'suggested_action':'PROCEED','evidence_refs':[{'source_id':source['source_id'],'quote':'Owner only'}]}
        good=self.screen(cand,resources=[{'path':'policy.txt','covers':[cand['field']]}])
        self.assertEqual(good['screen_status'],'PROCEED');self.assertEqual(good['validation_status'],'valid')
        unread=self.screen(cand,resources=[{'path':'unread.txt','covers':[cand['field']]}])
        self.assertEqual(unread['screen_status'],'INSPECT')
        (self.workspace/'policy.txt').write_text('Changed',encoding='utf-8')
        stale=self.screen(cand,resources=[{'path':'policy.txt','covers':[cand['field']]}])
        self.assertEqual(stale['validation_status'],'needs_evidence')

    def test_context_reuses_real_full_file_observation_and_keeps_partial_scope(self):
        raw=b'Line one\nLine two';(self.workspace/'rules.txt').write_bytes(raw)
        event={'session_id':'chat-a','turn_id':'read-1','tool_use_id':'read-tool','tool_name':'Bash'}
        observed=self.store.ledger.observe_read(event,'rules.txt',raw,1,2,raw.decode())
        result=self.service.context_bundle(self.handle,paths=['rules.txt'])
        self.assertEqual(result['sources'][0]['source_id'],observed['source_id'])
        self.assertEqual(result['sources'][0]['provenance'],'hook_file_read')
        event.update(turn_id='read-2',tool_use_id='partial-tool')
        self.store.ledger.observe_read(event,'rules.txt',raw,1,1,'Line one')
        result=self.service.context_bundle(self.handle,paths=['rules.txt'])
        self.assertEqual(result['sources'][0]['source_id'],observed['source_id'])
        (self.workspace/'partial.txt').write_bytes(raw)
        self.store.ledger.observe_read(event,'partial.txt',raw,1,1,'Line one')
        result=self.service.context_bundle(self.handle,paths=['partial.txt'])
        self.assertEqual(result['sources'][0]['content'],'Line one\nLine two')
        self.assertNotEqual(result['sources'][0]['provenance'],'hook_file_read')

    def test_context_reuses_same_chat_decision_sources_and_detects_tampering(self):
        ledger=self.store.ledger;path=self.workspace/'rules.txt';path.write_text('Owner only',encoding='utf-8')
        session=ledger.start('Prior read','Profile implementation');source=ledger.read(session['id'],'rules.txt')
        self.screen({**candidate(),'suggested_action':'ASK_NOW','evidence_refs':[{'source_id':source['id'],'quote':'Owner only'}]})
        bundle=self.service.context_bundle(self.handle,paths=['rules.txt'])
        self.assertEqual(bundle['sources'][0]['source_id'],source['id']);self.assertTrue(bundle['sources'][0]['reused'])
        with self.store.connect() as db:db.execute("UPDATE sources SET content='Tampered' WHERE id=?",(source['id'],))
        with self.assertRaises(ValueError):ledger.source_text(source | {'content':'Tampered'})
        repaired=self.service.context_bundle(self.handle,paths=['rules.txt'])
        self.assertNotEqual(repaired['sources'][0]['source_id'],source['id'])
        self.assertEqual(repaired['sources'][0]['content'],'Owner only')

    def test_context_keeps_old_active_task_and_source_review_memory(self):
        path=self.workspace/'rules.txt';path.write_text('Owner only',encoding='utf-8')
        source=self.service.context_bundle(self.handle,paths=['rules.txt'])['sources'][0]
        value=self.screen({**candidate(),'suggested_action':'ASK_NOW','evidence_refs':[{'source_id':source['source_id'],'quote':'Owner only'}]})
        self.activate(value)
        with self.store.connect() as db:
            db.execute("UPDATE decision_v3_tasks SET created='2000-01-01' WHERE id=?",(value['task_id'],))
            for index in range(51):db.execute('INSERT INTO decision_v3_tasks '
                'SELECT ?,workspace,host_session_digest,task_digest,owner,phase,binding_status,? '
                'FROM decision_v3_tasks WHERE id=?',('task-fixture-'+str(index),'2026-11-04',value['task_id']))
        self.assertEqual(self.service.context_bundle(self.handle)['decisions'][0]['decision_id'],value['decisions'][0]['decision_id'])
        self.handle=self.hook('A');path.write_text('Changed requirement',encoding='utf-8')
        bundle=self.service.context_bundle(self.handle)
        self.assertEqual(bundle['memory'][0]['state'],'needs_review')
        self.assertEqual(bundle['memory'][0]['choice']['id'],'A')

    def test_context_diff_marks_file_change_without_revoking_choice(self):
        path=self.workspace/'policy.txt';path.write_text('Only owner',encoding='utf-8')
        before=self.service.context_bundle(self.handle,paths=['policy.txt'])
        cand={**candidate(),'suggested_action':'ASK_NOW','evidence_refs':[{'source_id':before['sources'][0]['source_id'],'quote':'Only owner'}]}
        value=self.screen(cand);self.activate(value);self.handle=self.hook('A')
        path.write_text('The wording was edited',encoding='utf-8')
        after=self.service.context_bundle(self.handle,since=before['snapshot_id'])
        self.assertTrue(any(c['kind']=='files' for c in after['changes']))
        item=after['decisions'][0]
        self.assertEqual(item['state'],'confirmed');self.assertEqual(item['revision'],1)
        self.assertEqual(item['validation_status'],'needs_evidence')
        self.assertEqual(self.counts()['decision_v3_confirmations'],1)

    def test_budget_is_explicit_and_keeps_active_reference(self):
        (self.workspace/'large.txt').write_text('Text '*15000,encoding='utf-8')
        value=self.screen();self.activate(value)
        bundle=self.service.context_bundle(self.handle,paths=['large.txt'],max_chars=2000)
        self.assertLessEqual(len(encode(bundle)),2000)
        self.assertTrue(bundle.get('omitted') or any(r.get('content_truncated') for r in bundle['sources']))
        self.assertEqual(bundle['active_card_ref']['decision_id'],value['decisions'][0]['decision_id'])

    def test_context_and_snapshot_are_scoped_to_real_chat(self):
        snapshot=self.service.context_bundle(self.handle)['snapshot_id']
        other=self.hook('Other task','other-chat')
        with self.assertRaises(ValueError):self.service.context_bundle(other,since=snapshot)
        with self.assertRaises(ValueError):self.service.context_bundle(None)
        for path in ('../outside.txt','.git/config','.env'):
            with self.assertRaises((ValueError,OSError)):self.service.context_bundle(other,paths=[path])

    def test_reconnection_returns_pending_card_without_reactivation(self):
        value=self.screen();self.activate(value);before=self.counts()
        self.handle=self.hook('Continue discussing this choice')
        restarted=DecisionService(self.workspace,'owner-reconnected',self.settings)
        bundle=restarted.context_bundle(self.handle)
        self.assertEqual(bundle['decisions'][0]['resume_action'],'continue_current_card')
        self.assertEqual(self.counts()['decision_v3_events'],before['decision_v3_events']+1)
        self.assertEqual(self.counts()['decision_v3_confirmations'],0)

    def test_same_work_with_new_key_preserves_active_card_and_does_not_extend_ttl(self):
        value=self.screen();shown=self.activate(value)
        with self.store.connect() as db:expires=db.execute('SELECT expires FROM decision_v3_active').fetchone()[0]
        again=self.screen(task_id=value['task_id'])
        self.assertTrue(again['decisions'][0]['processing']['duplicate'])
        resumed=self.activate(again)
        self.assertTrue(resumed['already_active']);self.assertEqual(resumed['card'],shown['card'])
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT expires FROM decision_v3_active').fetchone()[0],expires)
            self.assertEqual(db.execute("SELECT count(*) FROM decision_v3_events WHERE event_type='CARD_ACTIVATED'").fetchone()[0],1)
        self.handle=self.hook('A');answered=self.screen(task_id=value['task_id'])
        self.assertTrue(answered['decisions'][0]['processing']['already_answered'])
        self.assertEqual(self.counts()['decision_v3_confirmations'],1)

    def test_local_candidate_id_changes_do_not_revise_or_repeat_answered_work(self):
        cand={**candidate(),'decision_key':'profile.visibility','suggested_action':'ASK_NOW','material_change':True}
        value=self.screen(cand);self.activate(value);self.handle=self.hook('A')
        again=self.screen({**cand,'candidate_id':'new-extraction-id'},task_id=value['task_id'])['decisions'][0]
        self.assertEqual(again['revision'],1);self.assertTrue(again['processing']['duplicate'])
        self.assertTrue(again['processing']['already_answered']);self.assertEqual(again['status'],'PROCEED')

    def test_duplicate_declarations_and_empty_ask_are_rejected(self):
        one={**candidate(),'candidate_id':'first','suggested_action':'PROCEED'}
        two={**one,'candidate_id':'second','suggested_action':'ASK_NOW'}
        with self.assertRaises(ValueError):self.screen(candidates=[one,two])
        with self.assertRaises(ValueError):self.screen(candidates=[],suggested_action='ASK_NOW')

    def test_deferred_state_and_expired_cards_survive_reconnection(self):
        value=self.screen();self.activate(value);self.handle=self.hook('暂缓')
        restored=self.service.context_bundle(self.handle)
        self.assertEqual(restored['decisions'][0]['state'],'deferred')
        self.activate(value)
        with self.store.connect() as db:db.execute('UPDATE decision_v3_active SET expires=?',(time.time()-1,))
        restored=self.service.context_bundle(self.handle)
        self.assertEqual(restored['decisions'][0]['resume_action'],'reactivate_with_current_handle')
        self.assertEqual(self.counts()['decision_v3_confirmations'],0)

    def test_natural_reply_is_saved_as_llm_interpretation_with_exact_source(self):
        value=self.screen();self.activate(value);item=value['decisions'][0]
        text='采用仅本人可见，请继续并保存这个决定。';self.handle=self.hook(text)
        args=(value['task_id'],item['decision_id'],1,'A','采用仅本人可见','It refers to the private option',self.handle)
        first=self.service.interpret_reply(*args);again=self.service.interpret_reply(*args)
        self.assertEqual(first['confirmation']['provenance'],'llm_interpreted_user_reply')
        self.assertFalse(first['semantic_verified_by_program']);self.assertTrue(again['replayed'])
        self.assertEqual(self.counts()['decision_v3_confirmations'],1)
        self.assertEqual(self.service.context_bundle(self.handle)['memory'][0]['provenance'],'llm_interpreted_user_reply')
        self.assertNotIn('pending_reply',self.service.context_bundle(self.handle))
        self.service.prepare_revision(value['task_id'],item['decision_id'],1,
            {**candidate(),'decision_key':'profile.visibility','suggested_action':'ASK_NOW'},'New requirement',self.handle)
        with self.assertRaises(ValueError):self.service.interpret_reply(*args)

    def test_interpretation_rejects_fabricated_quote_other_chat_stale_card_and_no_hook(self):
        value=self.screen();self.activate(value);item=value['decisions'][0];self.handle=self.hook('Use the private option please')
        def interpret(handle,quote='private option',revision=1):
            return self.service.interpret_reply(value['task_id'],item['decision_id'],revision,'A',quote,'Actual user choice',handle)
        with self.assertRaises(ValueError):interpret(self.handle,'Not actually said')
        with self.assertRaises(ValueError):interpret(None)
        with self.assertRaises(ValueError):interpret(self.hook('Use private','other-chat'))
        with self.store.connect() as db:db.execute('UPDATE decision_v3_active SET expires=?',(time.time()-1,))
        with self.assertRaises(ValueError):interpret(self.handle)
        self.assertEqual(self.counts()['decision_v3_confirmations'],0)

    def test_document_preserves_user_files_and_reports_actual_revision_differences(self):
        value=self.screen();self.activate(value);self.handle=self.hook('A')
        preview=self.service.decision_document(self.handle)
        self.assertIn('Private',preview['markdown']);self.assertFalse(preview['written'])
        saved=self.service.decision_document(self.handle,write=True)
        self.assertTrue(saved['written']);self.assertIn('已选方案', (self.workspace/saved['path']).read_text(encoding='utf-8'))
        changed={**candidate(),'suggested_action':'ASK_NOW','decision_key':'profile.visibility','material_change':True}
        changed['options'][0]['value']='private-with-expiry'
        self.service.prepare_revision(value['task_id'],value['decisions'][0]['decision_id'],1,changed,'New requirement',self.handle)
        result=self.service.decision_document(self.handle,write=True)
        self.assertTrue(any(row['changes'] for row in result['decisions']))
        self.assertIn('原确认：v1',result['markdown'])
        self.assertIn('方案 A 的取值：未设置 → private-with-expiry',result['markdown'])
        self.assertNotIn('"field":"options"',result['markdown'])
        user_file=self.workspace/'DECISIONS.md';user_file.write_text('User notes',encoding='utf-8')
        with self.assertRaises(ValueError):self.service.decision_document(self.handle,write=True,path='DECISIONS.md')
        self.assertEqual(user_file.read_text(encoding='utf-8'),'User notes')
        for path in ('../outside.md','.git/notes.md','.env.md'):
            with self.assertRaises(ValueError):self.service.decision_document(self.handle,write=True,path=path)

    def test_forgotten_entries_are_not_reintroduced_by_context_or_document(self):
        value=self.screen();self.activate(value);self.handle=self.hook('A')
        entry=self.service.memory('',False,self.handle)['entries'][0]
        self.handle=self.hook('遗忘 '+entry['memory_id'])
        self.assertEqual(self.service.context_bundle(self.handle)['memory'],[])
        self.assertEqual(self.service.context_bundle(self.handle)['decisions'],[])
        self.assertEqual(self.service.decision_document(self.handle)['decisions'],[])


if __name__=='__main__':unittest.main()
