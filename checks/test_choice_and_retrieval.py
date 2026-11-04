"""Whole-message natural choice parsing and stable cross-task memory identities."""
from copy import deepcopy
import unittest
import uuid
from verification_helpers import setup_fixture
from buildchoice.desktop.choice_reply import parse_choice
from buildchoice.desktop.decision_contracts import validate


def candidate(f):
    value=deepcopy(f['candidate'])
    value.update(decision_key='receipt.saving.policy',field='小票保存方式',memory_intent='reuse')
    value['options'][0]['option_key']='review.before.save'
    value['options'][1]['option_key']='save.automatically'
    return value


def screen(f,value):
    event={**f['event'],'session_id':uuid.uuid4().hex,'turn_id':'1','prompt':'实现相关功能 '+uuid.uuid4().hex}
    handle=f['store'].observe_hook(event)['session_handle']
    result=f['service'].screen({'task_text':event['prompt'],'phase':'before_implementation',
        'next_step':'实现保存','candidates':[value],'session_handle':handle,'idempotency_key':uuid.uuid4().hex})
    return event,handle,result,result['decisions'][0]


def confirm_rule(f,value,choice='A'):
    event,handle,result,item=screen(f,value)
    f['service'].activate(result['task_id'],item['decision_id'],1,uuid.uuid4().hex,handle)
    reply=f['store'].observe_hook({**event,'turn_id':'2','prompt':choice})
    entries=f['service'].memory('',False,reply['session_handle'])['entries']
    entry=next(e for e in entries if e['decision_id']==item['decision_id'])
    promoted=f['store'].observe_hook({**event,'turn_id':'3','prompt':'长期记住 '+entry['memory_id']})
    return result,item,entry,promoted['session_handle']


class NaturalChoiceTests(unittest.TestCase):
    def setUp(self):
        self.card={'display_id':'D12345678','options':[
            {'id':'A','label':'直接保存'},{'id':'B','label':'核对后保存'}],
            'recommendation':{'option_id':'B','reason':'Review'}}

    def test_clear_natural_choices_resolve_current_card(self):
        cases={'我选第二个':'B','就用第二个方案':'B','选择方案B':'B','我选 B 吧':'B',
            '核对后保存':'B','核对后保存吧':'B','采用核对后保存':'B','第一项':'A',
            '按你推荐的来':'B','D12345678 我选择 B':'B','choose B':'B','b':'B'}
        # The renderer uses 第一个/第二项 for ordinal expressions.
        cases['第一个']='A';cases.pop('第一项')
        for text,expected in cases.items():
            with self.subTest(text=text):self.assertEqual(parse_choice(text,self.card)['choice_id'],expected)

    def test_questions_quotes_negations_and_additional_instructions_do_not_confirm(self):
        for text in ['B?','“B”','如果选B呢','我不选B','A或B','我选B，然后直接发布','好','可以',
                     '别人说选B','D87654321 B','推荐方案吗','核对后保存？']:
            with self.subTest(text=text):self.assertIsNone(parse_choice(text,self.card))
        self.card['options'][0]['label']='核对后保存'
        self.assertIsNone(parse_choice('核对后保存',self.card))

    def test_actual_hook_records_natural_reply_and_keeps_ambiguous_reply_pending(self):
        f=setup_fixture()
        event,handle,result,item=screen(f,candidate(f))
        f['service'].activate(result['task_id'],item['decision_id'],1,'activate',handle)
        ambiguous=f['store'].observe_hook({**event,'turn_id':'2','prompt':'可以'})
        self.assertEqual(ambiguous['confirmation_status'],'awaiting_user')
        self.assertIn('reply_hint',ambiguous)
        reply=f['store'].observe_hook({**event,'turn_id':'3','prompt':'我选第二个方案'})
        self.assertEqual(reply['confirmation_status'],'user_message_observed')
        self.assertEqual(reply['choice_id'],'B')
        self.assertEqual(reply['reply_method'],'explicit_option_expression')


class RetrievalIdentityTests(unittest.TestCase):
    def setUp(self):self.f=setup_fixture()

    def test_stable_decision_and_option_keys_survive_label_rewording_and_reordered_ids(self):
        f=self.f;value=candidate(f)
        _,_,entry,_=confirm_rule(f,value)
        changed=deepcopy(value);changed['field']='正式入账时机'
        changed['options'][0].update(id='B',label='先核验再存档',tradeoff='核验完成才产生账目')
        changed['options'][1]['id']='A'
        _,_,_,item=screen(f,changed)
        self.assertEqual(item['status'],'PROCEED')
        self.assertEqual(item['memory']['choice_id'],'B')
        self.assertEqual(item['memory']['source_confirmation_id'],entry['confirmation_id'])

    def test_stable_identity_preserves_decision_id_during_a_display_name_revision(self):
        f=self.f;value=candidate(f)
        result,item,_,handle=confirm_rule(f,value)
        changed=deepcopy(value);changed['field']='小票正式入账时机'
        revised=f['service'].prepare_revision(result['task_id'],item['decision_id'],1,changed,'调整描述',handle)
        self.assertEqual(revised['decision_id'],item['decision_id'])
        self.assertEqual(revised['revision'],2)
        changed['decision_key']='receipt.other.policy'
        with self.assertRaises(ValueError):
            f['service'].prepare_revision(result['task_id'],item['decision_id'],2,changed,'不同决定',handle)

    def test_changed_option_key_and_conflicting_rules_still_need_a_choice(self):
        f=self.f;value=candidate(f)
        confirm_rule(f,value)
        changed=deepcopy(value);changed['options'][0]['option_key']='different.behavior'
        self.assertEqual(screen(f,changed)[3]['status'],'ASK_NOW')
        other=deepcopy(value);other['memory_intent']='change'
        confirm_rule(f,other,'B')
        item=screen(f,value)[3]
        self.assertEqual(item['status'],'ASK_NOW')
        self.assertIn('PROJECT_RULES_CONFLICT',item['reason_codes'])

    def test_chinese_phrases_rank_related_choice_and_single_character_noise_is_excluded(self):
        f=self.f;value=candidate(f)
        _,_,entry,handle=confirm_rule(f,value)
        recalled=f['service'].memory('小票保存',False,handle)
        self.assertEqual(recalled['entries'][0]['memory_id'],entry['memory_id'])
        self.assertEqual(f['service'].memory('入学',False,handle)['entries'],[])
        self.assertEqual(f['service'].memory('小',False,handle)['entries'],[])
        for query in (entry['memory_id'],entry['decision_key'],entry['decision_id']):
            self.assertEqual(f['service'].memory(query,False,handle)['entries'][0]['memory_id'],entry['memory_id'])

    def test_duplicate_stable_option_keys_are_rejected(self):
        value=candidate(self.f)
        value['options'][1]['option_key']=value['options'][0]['option_key']
        with self.assertRaises(ValueError):validate('Candidate',value)

    def test_stable_option_key_does_not_hide_a_changed_explicit_value(self):
        value=candidate(self.f);value['options'][0]['value']='review'
        confirm_rule(self.f,value)
        changed=deepcopy(value);changed['options'][0]['value']='automatic'
        self.assertEqual(screen(self.f,changed)[3]['status'],'ASK_NOW')
