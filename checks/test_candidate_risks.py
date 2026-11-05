"""Candidate semantics, source checks, product engineering risks and option warnings."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'checks'))
from verification_helpers import setup_fixture
from buildchoice.desktop.audit import Ledger
from buildchoice.desktop.candidate_policy import deduplicate,route
from buildchoice.desktop.decision_cards import render
from buildchoice.desktop.decision_contracts import validate
from test_choice_and_retrieval import confirm_rule,candidate as keyed_candidate,screen as keyed_screen


def engineering(product='yes',severity='high',direction='data_integrity'):
    return {'direction':direction,'severity':severity,'condition':'Multiple users edit the same record',
        'consequence':'One user may overwrite another user\'s changes','recoverability':'costly','product_choice':product}


def warning(text='Clearing browser data may remove all saved records.'):
    return {'risk_level':'high','risk_warning':text,'risk_basis':'potential',
        'risk_condition':'If records are saved only in this browser and site data is cleared',
        'risk_reason':'The browser holds the only copy; there is no independent backup.'}


class CandidateRiskTests(unittest.TestCase):
    def setUp(self):
        self.f=setup_fixture();self.service=self.f['service'];self.store=self.f['store']
        self.candidate=deepcopy(self.f['candidate'])

    def screen(self,candidate=None,**extra):
        prompt='Implement relevant behavior '+uuid.uuid4().hex
        event={**self.f['event'],'session_id':uuid.uuid4().hex,'turn_id':'1','prompt':prompt}
        handle=self.store.observe_hook(event)['session_handle']
        request={'task_text':prompt,'phase':'before_implementation','next_step':'Implement behavior',
            'candidates':[deepcopy(self.candidate if candidate is None else candidate)],
            'session_handle':handle,'idempotency_key':uuid.uuid4().hex,**extra}
        return self.service.screen(request),request,event

    def source(self,name,text):
        (self.f['workspace']/name).write_text(text,encoding='utf-8')
        ledger=Ledger(self.f['workspace']);session=ledger.start('Candidate fixture','Synthetic source')
        return ledger.read(session['id'],name)

    def rescreen_confirmed(self,candidate,key=None):
        return self.service.screen({'task_text':self.f['event']['prompt'],'task_id':self.f['task']['id'],
            'phase':'during_implementation','next_step':'Continue existing behavior','candidates':[candidate],
            'session_handle':self.f['handle'],'idempotency_key':key or uuid.uuid4().hex})

    def test_similar_names_are_retrieved_but_ordinary_references_do_not_authorize_reuse(self):
        result=self.service.memory('核对 保存',False,self.f['handle'])
        entry=result['entries'][0]
        self.assertEqual(entry['tier'],'reference')
        self.assertEqual(self.service.memory('直接',False,self.f['handle'])['entries'][0]['memory_id'],entry['memory_id'])
        other=deepcopy(self.candidate);other.update(field='Related review timing',decision_key='another.policy',memory_intent='reuse',
            history_matches=[{'memory_id':entry['memory_id'],'revision':entry['revision'],'relation':'related','rationale':'Both mention review before saving, but different behavior scope.'}])
        screened,_,_=self.screen(other)
        self.assertEqual(screened['decisions'][0]['status'],'ASK_NOW')
        self.assertFalse(screened['history_review'][0]['can_authorize_reuse'])
        self.assertFalse(screened['history_review'][0]['stable_identity_matches'])

    def test_scope_versions_and_semantic_claims_cannot_override_rule_identity(self):
        value=keyed_candidate(self.f);_,_,entry,_=confirm_rule(self.f,value)
        for change in [{'scope_key':'team-only'},{'material_change':True},
                       {'history_matches':[{'memory_id':entry['memory_id'],'revision':99,'relation':'same','rationale':'Agent says same'}]}]:
            with self.subTest(change=change):
                item=keyed_screen(self.f,{**value,**change})[3]
                self.assertNotEqual(item['confirmation_status'],'project_rule_reused')

    def test_structured_constraint_and_quote_are_both_checked_without_fabricating_confirmation(self):
        doc=json.dumps({'field':self.candidate['field'],'chosen':self.candidate['options'][0]['label']})
        src=self.source('policy.json',doc)
        value=deepcopy(self.candidate);value['evidence_refs']=[{'source_id':src['id'],'pointer':'/chosen',
            'quote':doc,'relation':'constraint','interpretation':'This exact chosen value defines the current policy.'}]
        value['suggested_action']='PROCEED'
        result,_,_=self.screen(value)
        self.assertEqual(result['decisions'][0]['status'],'PROCEED')
        self.assertEqual(result['decisions'][0]['confirmation_status'],'awaiting_user')
        value['evidence_refs'][0]['quote']='Text not present in the source'
        self.assertEqual(self.screen(value)[0]['decisions'][0]['status'],'INSPECT')

    def test_natural_language_claim_is_interpretation_not_a_literal_constraint(self):
        src=self.source('requirements.md','Prefer a simple and safe workflow.')
        value=deepcopy(self.candidate);value.update(suggested_action='PROCEED')
        value['evidence_refs']=[{'source_id':src['id'],'quote':'Prefer a simple and safe workflow.',
            'relation':'constraint','interpretation':'The user already approved automatic saving.'}]
        evidence=self.service.evidence(self.store,value,[])
        self.assertFalse(evidence['applicable_constraint'])
        self.assertFalse(evidence['interpretations'][0]['semantic_validity_independently_verified'])
        self.assertEqual(self.screen(value)[0]['decisions'][0]['status'],'PROCEED')

    def test_structured_value_disagreement_is_reported_without_choosing_the_action(self):
        refs=[]
        for i,o in enumerate(self.candidate['options']):
            src=self.source('rule'+str(i)+'.json',json.dumps({'field':self.candidate['field'],'chosen':o['label']}))
            refs.append({'source_id':src['id'],'pointer':'/chosen','relation':'constraint'})
        value={**self.candidate,'evidence_refs':refs}
        self.assertTrue(self.service.evidence(self.store,value,[])['conflict'])
        self.assertEqual(self.screen(value)[0]['decisions'][0]['status'],'ASK_NOW')

    def test_unrelated_fact_pointers_do_not_create_false_constraint_conflicts(self):
        src=self.source('facts.json','{"count": 12, "version": 2}')
        value={**self.candidate,'evidence_refs':[{'source_id':src['id'],'pointer':'/count','relation':'fact'},
            {'source_id':src['id'],'pointer':'/version','relation':'fact'}]}
        self.assertFalse(self.service.evidence(self.store,value,[])['conflict'])
        self.assertEqual(self.screen(value)[0]['decisions'][0]['status'],'ASK_NOW')

    def test_product_engineering_tradeoff_uses_explicit_model_action(self):
        value={**self.candidate,'category':'engineering',
            'engineering_risks':[engineering()],'suggested_action':'ASK_NOW'}
        self.assertEqual(self.screen(value)[0]['decisions'][0]['status'],'ASK_NOW')
        value.update(suggested_action='DEFER')
        self.assertEqual(self.screen(value)[0]['decisions'][0]['status'],'DEFER')

    def test_ordinary_or_irrelevant_engineering_risks_do_not_force_questions(self):
        value={**self.candidate,'suggested_action':'PROCEED','engineering_risks':[engineering('no','low')]}
        self.assertEqual(self.screen(value)[0]['decisions'][0]['status'],'PROCEED')
        value['engineering_risks']=[engineering()]
        self.assertEqual(self.screen(value)[0]['decisions'][0]['status'],'PROCEED')
        value.update(risk_flags=['payment'],suggested_action='ASK_NOW')
        self.assertEqual(self.screen(value)[0]['decisions'][0]['status'],'ASK_NOW')

    def test_keyword_signal_does_not_invent_a_business_decision(self):
        result,_,_=self.screen(candidates=[],next_step='Run DROP TABLE records')
        self.assertEqual(result['decisions'],[])
        self.assertEqual(result['screen_status'],'PROCEED')
        self.assertEqual(result['diagnostics'],[])
        self.assertEqual(result['semantic_judgment_by'],'llm')
        self.assertFalse(result['risk_review']['coverage_complete'])

    def test_zero_candidates_without_signals_does_not_claim_risk_free(self):
        result,_,_=self.screen(candidates=[],next_step='Adjust a button margin')
        self.assertEqual(result['screen_status'],'PROCEED')
        self.assertTrue(result['risk_review']['no_signal_does_not_establish_no_risk'])

    def test_uncertain_product_impact_or_unread_resources_are_inspected_without_forcing_a_card(self):
        value={**self.candidate,'engineering_risks':[engineering('uncertain')],'suggested_action':'INSPECT'}
        result,_,_=self.screen(value)
        self.assertEqual(result['decisions'][0]['status'],'INSPECT')
        self.assertIsNone(result['decisions'][0]['card'])
        self.source('unread.txt','More requirements')
        result,_,_=self.screen(candidates=[],resources=[{'path':'unread.txt','covers':['Saving']}])
        self.assertEqual(result['screen_status'],'INSPECT')

    def test_prose_interpretation_does_not_revoke_an_existing_choice(self):
        src=self.source('ambiguous.md','We may want a different workflow.')
        updated=deepcopy(self.candidate);updated['evidence_refs']=[{'source_id':src['id'],
            'quote':'We may want a different workflow.','relation':'constraint','interpretation':'Assume this settles everything.'}]
        result=self.rescreen_confirmed(updated)['decisions'][0]
        self.assertEqual(result['status'],'PROCEED')
        self.assertEqual(result['confirmation_status'],'user_message_observed')

    def test_static_checks_use_only_cited_current_excerpts_and_keep_cache_fresh(self):
        src=self.source('migration.py','DROP TABLE records')
        coverage=[{'dimension':'data_storage','status':'uncertain','reason':'Read the migration step.',
                   'evidence_refs':[{'source_id':src['id'],'quote':'DROP TABLE records','relation':'fact'}]}]
        result,request,_=self.screen(candidates=[],coverage=coverage)
        self.assertEqual(result['screen_status'],'PROCEED')
        self.assertEqual(result['coverage']['entries'][0]['source_status'],'bound_for_review')
        (self.f['workspace']/'migration.py').write_text('Different',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'CACHED_SCREEN_STALE'):self.service.screen(request)
        unrelated=self.source('unrelated.py','DROP TABLE records')
        self.assertEqual(self.screen(candidates=[])[0]['screen_status'],'PROCEED')

    def test_conditional_high_risk_option_is_displayed_and_still_selectable(self):
        value=deepcopy(self.candidate);value['options'][0].update(warning())
        value.update(recommended_option_id='A',recommendation_reason='The user needs a local prototype.')
        result,request,event=self.screen(value);item=result['decisions'][0]
        shown=self.service.activate(result['task_id'],item['decision_id'],1,'show',request['session_handle'])
        self.assertIn('风险提示（可能发生）',shown['message'])
        self.assertIn('A. '+value['options'][0]['label']+'（推荐）',shown['message'])
        self.assertEqual(shown['message'].count('风险提示'),1)
        answer=self.store.observe_hook({**event,'turn_id':'2','prompt':'我选第一个方案'})
        self.assertEqual(answer['confirmation_status'],'user_message_observed')
        self.assertEqual(answer['choice_id'],'A')

    def test_observed_warning_requires_a_real_quote_and_invalid_claim_is_not_displayed(self):
        src=self.source('risk.md','This migration drops existing records.')
        value=deepcopy(self.candidate)
        value['options'][0].update(risk_level='high',risk_warning='Existing records can be lost.',risk_basis='observed',
            risk_evidence_refs=[{'source_id':src['id'],'quote':'drops existing records','relation':'fact'}])
        item=self.screen(value)[0]['decisions'][0]
        self.assertIn('风险提示（项目资料中的风险）',render(item['card']))
        value['options'][0]['risk_evidence_refs'][0]['source_id']='invented'
        result,_,_=self.screen(value)
        self.assertNotIn('风险提示',render(result['decisions'][0]['card']))
        self.assertEqual(result['screen_status'],'INSPECT')

    def test_medium_and_legacy_options_keep_original_display(self):
        plain=self.screen()[0]['decisions'][0]['card']
        changed=deepcopy(plain);changed['options'][0].update(risk_level='medium',risk_warning='An ordinary concern.')
        self.assertEqual(render(plain),render(changed))

    def test_risk_copy_does_not_change_deduplication_or_confirmed_identity(self):
        updated=deepcopy(self.candidate);updated['options'][0].update(warning())
        duplicate=deepcopy(updated);duplicate['candidate_id']='second'
        duplicate['options'][0]['risk_warning']='If browser data is cleared, records may disappear.'
        self.assertEqual(len(deduplicate([updated,duplicate])),1)
        first=self.rescreen_confirmed(updated)['decisions'][0]
        self.assertEqual(first['revision'],1)
        self.assertEqual(first['confirmation_status'],'user_message_observed')
        again=self.rescreen_confirmed(duplicate)['decisions'][0]
        self.assertEqual(again['revision'],1)
        self.assertEqual(again['decision_id'],self.f['item']['decision_id'])
        self.assertEqual(self.service.status(self.f['task']['id'],self.f['handle'])['confirmation_history'][0]['choice_id'],'A')

    def test_changed_behavior_value_or_applicability_rechecks_current_confirmation(self):
        for mutation in ('value','behavior','conditions','scope_key','material_change'):
            f=setup_fixture();candidate=deepcopy(f['candidate'])
            if mutation in ('scope_key','material_change'):candidate[mutation]='team' if mutation=='scope_key' else True
            else:candidate['options'][0][mutation]=['online only'] if mutation=='conditions' else 'Different behavior'
            result=f['service'].screen({'task_id':f['task']['id'],'task_text':f['event']['prompt'],
                'phase':'during_implementation','next_step':'Implement changed behavior','candidates':[candidate],
                'session_handle':f['handle'],'idempotency_key':uuid.uuid4().hex})
            self.assertEqual(result['decisions'][0]['revision'],2)
            self.assertNotEqual(result['decisions'][0]['confirmation_status'],'user_message_observed')

    def test_option_risk_source_mutation_invalidates_screen_cache(self):
        src=self.source('warning.txt','Known consequence')
        value=deepcopy(self.candidate);value['options'][0].update(risk_level='high',risk_basis='observed',risk_warning='Records may be lost.',
            risk_evidence_refs=[{'source_id':src['id'],'quote':'Known consequence'}])
        _,request,_=self.screen(value)
        (self.f['workspace']/'warning.txt').write_text('Changed',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'CACHED_SCREEN_STALE'):self.service.screen(request)

    def test_risk_annotations_do_not_break_cross_chat_keyed_rule_reuse(self):
        value=keyed_candidate(self.f);_,_,entry,_=confirm_rule(self.f,value)
        changed=deepcopy(value);changed.update(suggested_action='PROCEED');changed['options'][0].update(warning())
        item=keyed_screen(self.f,changed)[3]
        self.assertEqual(item['confirmation_status'],'project_rule_reused')
        self.assertEqual(item['memory']['source_confirmation_id'],entry['confirmation_id'])


if __name__=='__main__':unittest.main()
