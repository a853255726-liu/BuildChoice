"""Behavior checks for discovery, declared coverage and retained decision history."""
import gc
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
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


if __name__=='__main__':unittest.main()
