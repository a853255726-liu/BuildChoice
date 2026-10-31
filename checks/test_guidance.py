"""Behavior checks for discovery, declared coverage and retained decision history."""
import gc
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT))
from buildchoice.desktop.audit import Ledger
from buildchoice.desktop.candidate_policy import route
from buildchoice.desktop.decision_contracts import validate
from buildchoice.desktop.decision_hook import handle_prompt
from buildchoice.desktop.decision_service import DecisionService
from buildchoice.desktop.decision_settings import read, update
from buildchoice.desktop.decision_store import DecisionStore


def candidate():
    return {'candidate_id': 'visibility', 'field': 'Profile visibility', 'category': 'access_control',
        'question': 'Who can see a profile?', 'impact': 'Changes who can read the profile.',
        'why_user_choice': 'Product access rule.', 'needs_user_choice': 'yes', 'current_dependency': 'yes',
        'risk_flags': ['privacy'], 'evidence_refs': [],
        'options': [{'id': 'A', 'label': 'Private', 'tradeoff': 'Only the owner can read it.'},
                    {'id': 'B', 'label': 'Shared', 'tradeoff': 'People with a link can read it.'}],
        'recommended_option_id': None, 'recommendation_reason': ''}


class GuidanceTests(unittest.TestCase):
    def setUp(self):
        # mkdir inherits workspace ACLs; no user data is used or removed.
        base=Path(os.environ.get('BUILDCHOICE_CHECK_ROOT', tempfile.gettempdir())).resolve()
        self.workspace=base/('buildchoice-check-'+uuid.uuid4().hex)
        self.workspace.mkdir()
        self.settings=self.workspace/'decision_v3.json'
        self.settings.write_text(json.dumps({'config_version':2,'mode':'pilot','context_ttl_seconds':900}),encoding='utf-8')
        self.service=DecisionService(self.workspace,'test-owner',settings_path=self.settings)
        self.event={'hook_event_name':'UserPromptSubmit','cwd':str(self.workspace),'session_id':'test-session','turn_id':'1','prompt':'给现有项目加登录'}

    def tearDown(self):
        # Keep inspectable scratch artifacts; do not recursively delete a workspace.
        gc.collect()

    def request(self, candidates=None, **extras):
        return {'task_text':self.event['prompt'],'phase':'before_implementation','next_step':'Implement access rules',
            'candidates':[candidate()] if candidates is None else candidates,'idempotency_key':uuid.uuid4().hex,**extras}

    def context(self):
        output=handle_prompt(self.event,self.workspace,self.settings)
        self.assertIn('buildchoice-v3-ctx-',output['hookSpecificOutput']['additionalContext'])
        return DecisionStore(self.workspace).observe_hook(self.event)['session_handle']

    def test_short_and_contextual_prompts_get_context_without_a_task_or_card(self):
        for i,prompt in enumerate(['给现有项目加登录','这里改成自动保存','按刚才说的做','为什么这样设计？']):
            self.event.update(turn_id=str(i+1),prompt=prompt)
            self.context()
        with DecisionStore(self.workspace).connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM decision_v3_tasks').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT count(*) FROM decision_v3_active').fetchone()[0],0)

    def test_disabled_pilot_does_not_create_ledger(self):
        update('off',self.settings)
        self.assertIsNone(handle_prompt(self.event,self.workspace,self.settings))
        self.assertFalse((self.workspace/'.buildchoice_audit').exists())

    def test_out_of_scope_message_does_not_create_ledger(self):
        outside=self.workspace.parent/('buildchoice-other-'+uuid.uuid4().hex)
        self.assertIsNone(handle_prompt({**self.event,'cwd':str(outside)},self.workspace,self.settings))
        self.assertFalse((self.workspace/'.buildchoice_audit').exists())

    def test_empty_candidates_persist_uncertain_coverage_without_a_card(self):
        request=self.request([],coverage=[{'dimension':'failure_recovery','status':'uncertain','reason':'No current recovery requirement.'}])
        response=self.service.screen(request)
        self.assertEqual(response['decisions'],[])
        self.assertTrue(response['coverage']['does_not_establish_completeness'])
        self.assertEqual(response['coverage']['provenance'],'agent_declared')
        self.assertEqual(self.service.status(response['task_id'])['coverage'],response['coverage'])
        with DecisionStore(self.workspace).connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM decision_v3_active').fetchone()[0],0)

    def test_coverage_does_not_change_routing(self):
        for state in ('resolved','candidate','not_applicable','uncertain'):
            response=self.service.screen(self.request(coverage=[{'dimension':'access_visibility','status':state,'reason':'Caller interpretation.'}]))
            self.assertEqual(response['decisions'][0]['status'],'ASK_NOW')

    def test_source_binding_and_changes_remain_separate_from_declared_resolution(self):
        path=self.workspace/'requirements.txt'
        path.write_text('Only the owner can read profiles.',encoding='utf-8')
        ledger=Ledger(self.workspace)
        session=ledger.start('Source check','Profile requirement')
        source=ledger.read(session['id'],'requirements.txt')
        coverage=[{'dimension':'access_visibility','status':'resolved','reason':'Private access is stated.',
            'evidence_refs':[{'source_id':source['id'],'quote':'Only the owner'}]}]
        result=self.service.screen(self.request([],coverage=coverage))
        self.assertEqual(result['coverage']['entries'][0]['source_status'],'bound_for_review')
        path.write_text('Public access.',encoding='utf-8')
        result=self.service.screen(self.request([],coverage=coverage))
        entry=result['coverage']['entries'][0]
        self.assertEqual(entry['status'],'resolved')
        self.assertEqual(entry['source_status'],'unverified_or_changed')

    def test_fabricated_source_stays_unverified_and_cannot_clear_candidate(self):
        coverage=[{'dimension':'access_visibility','status':'resolved','reason':'Declared by caller.',
            'evidence_refs':[{'source_id':'src-not-real','quote':'Private'}]}]
        response=self.service.screen(self.request(coverage=coverage))
        self.assertEqual(response['coverage']['entries'][0]['source_status'],'unverified_or_changed')
        self.assertEqual(response['decisions'][0]['status'],'ASK_NOW')

    def test_old_request_explicitly_reports_no_coverage(self):
        response=self.service.screen(self.request([]))
        self.assertFalse(response['coverage']['reported'])
        self.assertEqual(response['coverage']['entries'],[])
        self.assertNotIn('model_diagnostics',response)

    def test_idempotent_coverage_and_latest_status(self):
        request=self.request([],coverage=[{'dimension':'external_cost','status':'not_applicable','reason':'Local display edit.'}])
        response=self.service.screen(request)
        self.assertEqual(self.service.screen(request),response)
        with DecisionStore(self.workspace).connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM decision_v3_events WHERE event_type='COVERAGE_RECORDED'").fetchone()[0],1)
        second=self.service.screen(self.request([],coverage=[]))
        self.assertTrue(second['coverage']['reported'])
        self.assertEqual(self.service.status(second['task_id'])['coverage'],second['coverage'])

    def test_coverage_contract_rejects_duplicates_unknown_candidates_and_excess_length(self):
        entry={'dimension':'external_cost','status':'uncertain','reason':'Not yet established.'}
        cases=[[entry,entry],[{**entry,'candidate_ids':['unknown']}],[{**entry,'reason':'x'*301}]]
        for coverage in cases:
            with self.subTest(coverage=coverage), self.assertRaises(Exception):
                validate('ScreenRequest',self.request([],coverage=coverage))

    def test_strict_reply_confirmation_and_revision_are_preserved(self):
        handle=self.context()
        response=self.service.screen(self.request(session_handle=handle))
        item=response['decisions'][0]
        active=self.service.activate(response['task_id'],item['decision_id'],1,'activate',handle)
        self.assertIn('BuildChoice',active['message'])
        store=DecisionStore(self.workspace)
        explanation=store.observe_hook({**self.event,'turn_id':'2','prompt':'解释一下'})
        self.assertEqual(explanation['confirmation_status'],'awaiting_user')
        confirmed=store.observe_hook({**self.event,'turn_id':'3','prompt':'A'})
        self.assertEqual(confirmed['confirmation_status'],'user_message_observed')
        status=self.service.status(response['task_id'],confirmed['session_handle'])
        self.assertEqual(status['decisions'][0]['status'],'PROCEED')
        self.service.prepare_revision(response['task_id'],item['decision_id'],1,candidate(),'New preference',confirmed['session_handle'])
        status=self.service.status(response['task_id'],confirmed['session_handle'])
        self.assertEqual(status['decisions'][0]['status'],'ASK_NOW')
        self.assertTrue(status['decisions'][0]['needs_recheck'])

    def test_expired_card_releases_slot_without_confirming_old_choice(self):
        handle=self.context()
        first=self.service.screen(self.request(session_handle=handle));item=first['decisions'][0]
        self.service.activate(first['task_id'],item['decision_id'],1,'activate',handle)
        store=DecisionStore(self.workspace)
        with patch('buildchoice.desktop.decision_store.time.time',return_value=time.time()+901):
            reply=store.observe_hook({**self.event,'turn_id':'2','prompt':'A'})
            self.assertEqual(reply['confirmation_status'],'not_confirmed')
            next_event={**self.event,'turn_id':'3','prompt':'Implement invoice access'}
            next_handle=store.observe_hook(next_event)['session_handle']
            second=self.service.screen(self.request(task_text=next_event['prompt'],session_handle=next_handle))
            self.service.activate(second['task_id'],second['decisions'][0]['decision_id'],1,'new-card',next_handle)
            prior=self.service.status(first['task_id'],next_handle)
        self.assertEqual(prior['confirmation_history'],[])
        self.assertEqual(prior['decisions'][0]['state'],'screened')

    def test_activation_cleans_expired_slot_even_without_another_hook(self):
        first=self.service.screen(self.request());item=first['decisions'][0]
        self.service.activate(first['task_id'],item['decision_id'],1,'activate')
        second=self.service.screen(self.request(task_text='Implement invoice access'))
        new_item=second['decisions'][0]
        with self.assertRaisesRegex(ValueError,'Another card is already active'):
            self.service.activate(second['task_id'],new_item['decision_id'],1,'blocked')
        with patch('buildchoice.desktop.decision_store.time.time',return_value=time.time()+901):
            self.service.activate(second['task_id'],new_item['decision_id'],1,'activate-new')
        self.assertEqual(self.service.status(first['task_id'])['confirmation_history'],[])

    def test_new_observed_scope_suspends_pending_card_and_can_resume_it(self):
        handle=self.context()
        first=self.service.screen(self.request(session_handle=handle));item=first['decisions'][0]
        self.service.activate(first['task_id'],item['decision_id'],1,'activate',handle)
        store=DecisionStore(self.workspace)
        event={**self.event,'turn_id':'2','prompt':'先放下用户资料，改做发票功能'}
        next_handle=store.observe_hook(event)['session_handle']
        # A fabricated new scope cannot consume the context or clear the old card.
        with self.assertRaises(ValueError):
            self.service.screen(self.request(task_text='Not the user message',session_handle=next_handle))
        self.assertEqual(self.service.status(first['task_id'],next_handle)['decisions'][0]['state'],'needs_explanation')
        second=self.service.screen(self.request(task_text=event['prompt'],session_handle=next_handle))
        self.assertNotEqual(first['task_id'],second['task_id'])
        self.assertEqual(self.service.status(first['task_id'],next_handle)['confirmation_history'],[])
        self.service.activate(second['task_id'],second['decisions'][0]['decision_id'],1,'new-card',next_handle)
        answer=store.observe_hook({**self.event,'turn_id':'3','prompt':'A'})
        self.assertEqual(answer['decision_id'],second['decisions'][0]['decision_id'])
        # The suspended decision remains unconfirmed and can be explicitly shown again.
        self.service.activate(first['task_id'],item['decision_id'],1,'resume-card',answer['session_handle'])
        resumed=store.observe_hook({**self.event,'turn_id':'4','prompt':'B'})
        self.assertEqual(resumed['decision_id'],item['decision_id'])
        self.assertEqual(resumed['choice_id'],'B')

    def test_discussion_preserves_card_and_strict_choice_cannot_become_new_scope(self):
        handle=self.context()
        first=self.service.screen(self.request(session_handle=handle));item=first['decisions'][0]
        self.service.activate(first['task_id'],item['decision_id'],1,'activate',handle)
        store=DecisionStore(self.workspace)
        reply=store.observe_hook({**self.event,'turn_id':'2','prompt':'解释一下'})
        prior=self.service.status(first['task_id'],reply['session_handle'])
        self.assertEqual(prior['decisions'][0]['state'],'needs_explanation')
        self.assertEqual(prior['confirmation_history'],[])
        answered=store.observe_hook({**self.event,'turn_id':'3','prompt':'A'})
        with self.assertRaises(ValueError):
            self.service.screen(self.request(task_text='A',session_handle=answered['session_handle']))
        self.assertEqual(self.service.status(first['task_id'],answered['session_handle'])['confirmation_history'][0]['choice_id'],'A')

    def test_activation_retry_is_idempotent_only_while_the_same_card_is_current(self):
        handle=self.context()
        first=self.service.screen(self.request(session_handle=handle));item=first['decisions'][0]
        shown=self.service.activate(first['task_id'],item['decision_id'],1,'show-profile',handle)
        store=DecisionStore(self.workspace)
        with store.connect() as db:
            initial_expiry=db.execute('SELECT expires FROM decision_v3_active').fetchone()[0]
        self.assertEqual(self.service.activate(first['task_id'],item['decision_id'],1,'show-profile',handle),shown)
        discussion=store.observe_hook({**self.event,'turn_id':'2','prompt':'解释一下'})
        self.assertEqual(self.service.activate(first['task_id'],item['decision_id'],1,'show-profile',discussion['session_handle']),shown)
        with store.connect() as db:
            self.assertEqual(db.execute('SELECT expires FROM decision_v3_active').fetchone()[0],initial_expiry)
            self.assertEqual(db.execute("SELECT count(*) FROM decision_v3_events WHERE event_type='CARD_ACTIVATED'").fetchone()[0],1)
        answer=store.observe_hook({**self.event,'turn_id':'3','prompt':'A'})
        with self.assertRaises(ValueError):
            self.service.activate(first['task_id'],item['decision_id'],1,'show-profile',answer['session_handle'])
        self.assertEqual(len(self.service.status(first['task_id'],answer['session_handle'])['confirmation_history']),1)

    def test_old_activation_retry_cannot_show_another_card_or_change_its_confirmation(self):
        handle=self.context()
        first=self.service.screen(self.request(session_handle=handle));item=first['decisions'][0]
        self.service.activate(first['task_id'],item['decision_id'],1,'show-profile',handle)
        store=DecisionStore(self.workspace)
        event={**self.event,'turn_id':'2','prompt':'先做发票的可见性设置'}
        next_handle=store.observe_hook(event)['session_handle']
        invoice={**candidate(),'candidate_id':'invoice','field':'Invoice visibility','question':'Who can see invoices?'}
        second=self.service.screen(self.request([invoice],task_text=event['prompt'],session_handle=next_handle))
        other=second['decisions'][0]
        self.service.activate(second['task_id'],other['decision_id'],1,'show-invoice',next_handle)
        with self.assertRaises(ValueError):
            self.service.activate(first['task_id'],item['decision_id'],1,'show-profile',next_handle)
        with store.connect() as db:
            self.assertEqual(db.execute('SELECT decision_id FROM decision_v3_active').fetchone()[0],other['decision_id'])
        answer=store.observe_hook({**self.event,'turn_id':'3','prompt':'B'})
        self.assertEqual(answer['decision_id'],other['decision_id'])
        self.assertEqual(self.service.status(first['task_id'],answer['session_handle'])['confirmation_history'],[])

    def test_activation_retry_rejects_expiry_revision_and_changed_card_content(self):
        first=self.service.screen(self.request());item=first['decisions'][0]
        args=(first['task_id'],item['decision_id'],1,'show')
        self.service.activate(*args)
        with patch('buildchoice.desktop.decision_store.time.time',return_value=time.time()+901):
            with self.assertRaises(ValueError):self.service.activate(*args)
        self.service.prepare_revision(first['task_id'],item['decision_id'],1,candidate(),'New preference')
        with self.assertRaises(ValueError):self.service.activate(*args)
        # A re-screen can change a rendered question without changing the options/revision.
        separate=self.service.screen(self.request(task_text='Another task'))
        second=separate['decisions'][0]
        self.service.activate(separate['task_id'],second['decision_id'],1,'second')
        changed={**candidate(),'question':'Who can read the updated profile?'}
        self.service.screen(self.request([changed],task_text='Another task',task_id=separate['task_id']))
        with self.assertRaises(ValueError):
            self.service.activate(separate['task_id'],second['decision_id'],1,'second')

    def test_four_routes_use_evidence_and_dependency(self):
        self.assertEqual(route(candidate(),{})['status'],'ASK_NOW')
        self.assertEqual(route(candidate(),{'unread':True})['status'],'INSPECT')
        self.assertEqual(route({**candidate(),'current_dependency':'no'},{})['status'],'DEFER')
        self.assertEqual(route({**candidate(),'risk_flags':[],'engineering_detail':True},{})['status'],'PROCEED')

    def test_legacy_model_configuration_is_read_without_model_capability(self):
        legacy={'config_version':1,'mode':'pilot','model_check':'on','context_ttl_seconds':900,
            'model_runtime':{'python':'retired','root':'retired','config':'retired'}}
        self.settings.write_text(json.dumps(legacy),encoding='utf-8')
        self.assertEqual(read(self.settings),{'config_version':2,'mode':'pilot','context_ttl_seconds':900})
        response=self.service.screen(self.request())
        self.assertNotIn('model_fields',response['decisions'][0])
        update('off',self.settings)
        self.assertNotIn('model_runtime',json.loads(self.settings.read_text(encoding='utf-8')))

    def test_old_ledger_history_survives_and_retired_fields_leave_status(self):
        response=self.service.screen(self.request())
        store=DecisionStore(self.workspace)
        with store.connect() as db:
            row=db.execute('SELECT * FROM decision_v3_items').fetchone()
            routing=json.loads(row['routing_json'])
            routing.update(model_status='OK',model_fields={'required':True,'resolved':False,'indexed':False})
            db.execute('UPDATE decision_v3_items SET routing_json=?',(json.dumps(routing),))
            store.event(db,response['task_id'],'MODEL_CHECK_RECORDED',{'historical':True})
        status=self.service.status(response['task_id'])
        self.assertNotIn('model_status',status['decisions'][0])
        with store.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM decision_v3_events WHERE event_type='MODEL_CHECK_RECORDED'").fetchone()[0],1)

    def test_global_off_suppresses_prompt_and_decision_context(self):
        spec=importlib.util.spec_from_file_location('buildchoice_hook',ROOT/'scripts/buildchoice_hook.py')
        module=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        old_read,old_workspace=module.read,module.WORKSPACE
        try:
            module.read=lambda:{'mode':'off'}
            module.WORKSPACE=self.workspace
            self.assertIsNone(module.handle_event(self.event))
            self.assertFalse((self.workspace/'.buildchoice_audit').exists())
        finally:
            module.read,module.WORKSPACE=old_read,old_workspace

    def test_implementation_link_uses_actual_file_and_is_idempotent(self):
        response=self.service.screen(self.request())
        item=response['decisions'][0]
        (self.workspace/'profile.py').write_text('visibility = "private"\n',encoding='utf-8')
        args=(response['task_id'],item['decision_id'],1,'profile.py','Implements private visibility',1,1)
        linked=self.service.link_implementation(*args)
        self.assertEqual(self.service.link_implementation(*args),linked)
        self.assertTrue(linked['does_not_prove_correctness'])
        status=self.service.status(response['task_id'])['implementations']
        self.assertEqual(len(status),1)
        self.assertEqual(status[0]['file_status'],'unchanged')
        self.assertFalse(status[0]['needs_recheck'])
        with DecisionStore(self.workspace).connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM decision_v3_events WHERE event_type='IMPLEMENTATION_LINKED'").fetchone()[0],1)

    def test_changed_file_and_decision_revision_mark_link_for_review(self):
        response=self.service.screen(self.request())
        item=response['decisions'][0]
        path=self.workspace/'profile.py';path.write_text('private\n',encoding='utf-8')
        self.service.link_implementation(response['task_id'],item['decision_id'],1,'profile.py','Selected access rule')
        path.write_text('public\n',encoding='utf-8')
        self.assertTrue(self.service.status(response['task_id'])['implementations'][0]['needs_recheck'])
        path.write_text('private\n',encoding='utf-8')
        self.service.prepare_revision(response['task_id'],item['decision_id'],1,candidate(),'Preference changed')
        linked=self.service.status(response['task_id'])['implementations'][0]
        self.assertEqual(linked['file_status'],'unchanged')
        self.assertEqual(linked['reason_codes'],['DECISION_REVISION_CHANGED'])
        self.assertTrue(linked['needs_recheck'])

    def test_implementation_rejects_private_escaping_and_invalid_lines(self):
        response=self.service.screen(self.request());item=response['decisions'][0]
        (self.workspace/'profile.py').write_text('private\n',encoding='utf-8')
        for path,start,end in [('../secret',None,None),('.buildchoice_audit/ledger.sqlite3',None,None),
                               ('profile.py',2,None),('profile.py',None,1),('profile.py',True,None)]:
            with self.subTest(path=path,start=start,end=end),self.assertRaises((ValueError,OSError)):
                self.service.link_implementation(response['task_id'],item['decision_id'],1,path,'Code relation',start,end)

    def test_implementation_rejects_stale_revision_or_another_session(self):
        handle=self.context()
        response=self.service.screen(self.request(session_handle=handle));item=response['decisions'][0]
        (self.workspace/'profile.py').write_text('private\n',encoding='utf-8')
        other=DecisionService(self.workspace,'other-owner',settings_path=self.settings)
        with self.assertRaises(ValueError):
            other.link_implementation(response['task_id'],item['decision_id'],1,'profile.py','Other session')
        self.service.prepare_revision(response['task_id'],item['decision_id'],1,candidate(),'New rule',handle)
        with self.assertRaises(ValueError):
            self.service.link_implementation(response['task_id'],item['decision_id'],1,'profile.py','Old revision',session_handle=handle)

    def test_removed_implementation_file_is_reported_unavailable(self):
        response=self.service.screen(self.request());item=response['decisions'][0]
        path=self.workspace/'profile.py';path.write_text('private\n',encoding='utf-8')
        self.service.link_implementation(response['task_id'],item['decision_id'],1,'profile.py','Access rule')
        path.rename(self.workspace/'profile-renamed.py')
        linked=self.service.status(response['task_id'])['implementations'][0]
        self.assertEqual(linked['file_status'],'missing_or_unreadable')
        self.assertTrue(linked['needs_recheck'])


if __name__=='__main__':unittest.main()
