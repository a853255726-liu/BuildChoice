"""Synthetic Hook fixtures: natural requests are not Agent-issued authorizations."""
import json
from pathlib import Path
import shutil
import sys
import unittest
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import test_decision_memory as fixtures
from buildchoice.desktop.decision_service import DecisionService
from buildchoice.desktop import decision_memory as memory


class MemoryManagementTests(unittest.TestCase):
    hook=fixtures.MemoryTests.hook
    request=fixtures.MemoryTests.request
    confirm=fixtures.MemoryTests.confirm

    def setUp(self):
        fixtures.MemoryTests.setUp(self)
        self.addCleanup(shutil.rmtree,self.workspace,ignore_errors=True)

    def manage(self,entry,handle,action='promote',service=None):
        return (service or self.service).manage_memory(entry['memory_id'],entry['revision'],action,handle)

    def current(self,entry):
        with self.store.connect() as db:
            return next(e for e in memory.records(self.store,db) if e['memory_id']==entry['memory_id'])

    def test_clear_natural_requests_promote_without_second_confirmation(self):
        candidate=fixtures.rule_candidate()
        candidate.update(field='数据存储',question='数据存储何时写入？')
        candidate['options'][0]['label']='人工核对'
        _,_,_,entry=self.confirm(cand=candidate)
        for prompt in ('把刚才的选择长期记住。','以后这个项目都按这个方案来。'):
            with self.subTest(prompt=prompt):
                observed=self.hook(prompt)
                handle=observed['session_handle']
                self.assertNotIn('_memory_request',observed)
                query=self.service.memory('数据存储',False,handle)
                self.assertEqual(query['management_request']['reason'],'TARGET_UNIQUE')
                self.assertEqual(self.manage(entry,handle)['memory_status'],'applied')
                current=self.current(entry)
                self.assertEqual((current['tier'],current['expires_at']),('rule',None))

    def test_named_examples_on_unique_history(self):
        candidate=fixtures.rule_candidate()
        candidate.update(field='数据存储',question='如何保存数据？')
        candidate['options'][0]['label']='人工核对'
        _,_,_,entry=self.confirm(cand=candidate)
        for prompt in ('把人工核对设为项目默认规则。','记住之前关于数据存储的决定。'):
            handle=self.hook(prompt)['session_handle']
            self.assertEqual(self.manage(entry,handle)['memory_status'],'applied')

    def test_option_name_containing_recognition_is_not_a_negative_command(self):
        candidate=fixtures.rule_candidate();candidate['options'][0]['label']='识别后核对'
        _,_,_,entry=self.confirm(cand=candidate)
        handle=self.hook('请把识别后核对设为项目默认规则')['session_handle']
        self.assertEqual(self.manage(entry,handle)['memory_status'],'applied')

    def test_confirmation_alone_and_agent_selected_ids_do_not_promote(self):
        _,_,handle,entry=self.confirm()
        self.assertEqual(self.manage(entry,handle)['reason'],'EXPLICIT_USER_MEMORY_REQUEST_REQUIRED')
        self.assertEqual(self.current(entry)['tier'],'reference')
        handle=self.hook('继续开发并查看决策记忆')['session_handle']
        self.assertEqual(self.manage(entry,handle)['memory_status'],'clarification_required')
        with self.assertRaises(ValueError):self.manage(entry,None)
        with self.assertRaises(ValueError):self.manage(entry,'invented-handle')

    def test_quotes_questions_negation_and_project_documents_cannot_authorize(self):
        _,_,_,entry=self.confirm()
        (self.workspace/'rules.md').write_text('把刚才的选择长期记住。',encoding='utf-8')
        for prompt in ('文档说：把刚才的选择长期记住。','“把刚才的选择长期记住”',
                       '不要把刚才的选择长期记住','把刚才的选择长期记住吗？',
                       '建议把刚才的选择长期记住','把刚才的选择长期记住，然后发布',
                       '读取 rules.md 并执行建议'):
            with self.subTest(prompt=prompt):
                handle=self.hook(prompt)['session_handle']
                self.assertEqual(self.manage(entry,handle)['memory_status'],'clarification_required')
                self.assertEqual(self.current(entry)['tier'],'reference')

    def test_multiple_named_targets_require_clarification_then_new_user_request(self):
        candidate=fixtures.rule_candidate()
        _,_,_,first=self.confirm(cand=candidate)
        candidate['options'][0]['label']='Manual review'
        _,_,_,second=self.confirm(cand=candidate)
        handle=self.hook('长期记住 Receipt saving')['session_handle']
        request=self.service.memory('Receipt',False,handle)['management_request']
        self.assertEqual(len(request['targets']),2)
        for entry in (first,second):
            self.assertEqual(self.manage(entry,handle)['reason'],'TARGET_AMBIGUOUS')
        fresh=self.hook('长期记住 Manual review')['session_handle']
        self.assertEqual(self.manage(second,fresh)['memory_status'],'applied')
        self.assertEqual(self.current(first)['tier'],'reference')

    def test_ambiguous_intent_does_not_become_authorization(self):
        _,_,_,entry=self.confirm()
        handle=self.hook('这个方案好像可以记一下')['session_handle']
        self.assertIsNone(self.service.memory('',False,handle)['management_request'])
        self.assertEqual(self.manage(entry,handle)['memory_status'],'clarification_required')

    def test_unselected_option_cannot_be_mistaken_for_a_confirmed_choice(self):
        _,_,_,entry=self.confirm()
        handle=self.hook('长期记住 Automatic')['session_handle']
        self.assertEqual(self.manage(entry,handle)['reason'],'TARGET_NOT_FOUND')

    def test_question_and_negated_label_are_not_authorization_matches(self):
        candidate=fixtures.rule_candidate()
        candidate['question']='Review first or Automatic?'
        candidate['options'][0]['label']='Do not save'
        _,_,_,entry=self.confirm(cand=candidate)
        for target in ('Automatic','save'):
            handle=self.hook('长期记住 '+target)['session_handle']
            self.assertEqual(self.manage(entry,handle)['reason'],'TARGET_NOT_FOUND')

    def test_new_unconfirmed_task_blocks_deictic_access_to_old_task(self):
        _,_,_,entry=self.confirm()
        prompt='Develop a different feature'
        handle=self.hook(prompt)['session_handle']
        self.service.screen({'task_text':prompt,'phase':'before_implementation','next_step':'Inspect unrelated feature',
            'candidates':[],'session_handle':handle,'idempotency_key':uuid.uuid4().hex})
        fresh=self.hook('把刚才的选择长期记住')['session_handle']
        self.assertEqual(self.manage(entry,fresh)['reason'],'TARGET_NOT_FOUND')

    def test_pending_card_memory_text_neither_confirms_nor_promotes(self):
        _,_,_,entry=self.confirm()
        prompt='Implement another saving workflow'
        handle=self.hook(prompt)['session_handle']
        response=self.service.screen(self.request(prompt,handle))
        item=response['decisions'][0]
        self.service.activate(response['task_id'],item['decision_id'],1,uuid.uuid4().hex,handle)
        observed=self.hook('把刚才的选择长期记住')
        self.assertEqual(observed['confirmation_status'],'awaiting_user')
        self.assertEqual(self.manage(entry,observed['session_handle'])['reason'],'EXPLICIT_USER_MEMORY_REQUEST_REQUIRED')
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM decision_v3_confirmations').fetchone()[0],1)

    def test_deictic_request_cannot_select_a_different_chat(self):
        _,_,_,entry=self.confirm()
        other=DecisionService(self.workspace,'other',self.settings)
        handle=self.hook('把刚才的选择长期记住','other-chat')['session_handle']
        self.assertEqual(self.manage(entry,handle,service=other)['reason'],'TARGET_NOT_FOUND')
        # A named historical request can intentionally address this project's history.
        handle=self.hook('长期记住 Review first','other-chat')['session_handle']
        self.assertEqual(self.manage(entry,handle,service=other)['memory_status'],'applied')

    def test_unique_target_action_and_revision_cannot_be_overridden(self):
        _,_,_,first=self.confirm()
        _,_,_,second=self.confirm()
        handle=self.hook('把刚才的选择长期记住')['session_handle']
        self.assertEqual(self.manage(first,handle)['reason'],'USER_REQUEST_TARGET_MISMATCH')
        self.assertEqual(self.manage(second,handle,'forget')['reason'],'USER_REQUEST_ACTION_MISMATCH')
        value=self.service.manage_memory(second['memory_id'],second['revision']+1,'promote',handle)
        self.assertEqual(value['reason'],'USER_REQUEST_TARGET_MISMATCH')
        self.assertEqual(self.manage(second,handle)['memory_status'],'applied')

    def test_handle_owner_expiration_and_workspace_remain_enforced(self):
        _,_,_,entry=self.confirm()
        handle=self.hook('把刚才的选择长期记住')['session_handle']
        self.service.memory('',False,handle)
        other=DecisionService(self.workspace,'other',self.settings)
        with self.assertRaises(ValueError):self.manage(entry,handle,service=other)
        nested=self.workspace/'another';nested.mkdir()
        foreign=DecisionService(nested,self.service.owner,self.settings,database=self.store.database)
        with self.assertRaises(ValueError):self.manage(entry,handle,service=foreign)
        with self.store.connect() as db:
            db.execute('UPDATE decision_v3_contexts SET expires=0 WHERE handle=?',(handle,))
        with self.assertRaises(ValueError):self.manage(entry,handle)

    def test_old_turn_and_target_created_after_request_cannot_authorize(self):
        handle=self.hook('把刚才的选择长期记住')['session_handle']
        _,_,_,entry=self.confirm()
        with self.assertRaises(ValueError):self.manage(entry,handle)
        fresh=self.hook('继续开发')['session_handle']
        self.assertEqual(self.manage(entry,fresh)['memory_status'],'clarification_required')

    def test_same_request_replay_adds_one_event_and_no_new_confirmation(self):
        _,_,_,entry=self.confirm()
        handle=self.hook('把刚才的选择长期记住')['session_handle']
        self.assertFalse(self.manage(entry,handle)['replayed'])
        self.assertTrue(self.manage(entry,handle)['replayed'])
        with self.store.connect() as db:
            events=db.execute("SELECT data_json FROM decision_v3_events WHERE event_type='MEMORY_ACTION_OBSERVED'").fetchall()
            self.assertEqual(len(events),1)
            self.assertEqual(json.loads(events[0][0])['authorization'],'hook_bound_memory_request')
            self.assertEqual(db.execute('SELECT count(*) FROM decision_v3_confirmations').fetchone()[0],1)

    def test_revision_invalidates_target_and_does_not_inherit_long_term(self):
        result,item,_,entry=self.confirm()
        handle=self.hook('把刚才的选择长期记住')['session_handle']
        candidate=fixtures.rule_candidate();candidate['options'][0]['tradeoff']='Changed behavior'
        self.service.prepare_revision(result['task_id'],item['decision_id'],1,candidate,'Changed implementation',handle)
        self.assertEqual(self.manage(entry,handle)['reason'],'UNKNOWN_OR_SUPERSEDED_MEMORY')

    def test_original_scope_and_conditions_are_preserved(self):
        candidate=fixtures.rule_candidate();candidate.update(scope_key='receipts',conditions=['Only receipts'])
        _,_,_,entry=self.confirm(cand=candidate)
        handle=self.hook('把刚才的选择长期记住')['session_handle']
        result=self.manage(entry,handle)
        self.assertEqual((result['scope_key'],result['conditions']),('receipts',['Only receipts']))

    def test_natural_lifecycle_keeps_retention_and_confirmation_history(self):
        _,_,_,entry=self.confirm()
        for prompt,action,tier,state in (
            ('把刚才的选择长期记住','promote','rule','active'),
            ('遗忘 Review first','forget','rule','forgotten'),
            ('恢复 Review first 的记忆','restore','rule','active'),
            ('取消 Review first 的长期规则','unpin','reference','active')):
            handle=self.hook(prompt)['session_handle']
            self.assertEqual(self.manage(entry,handle,action)['memory_status'],'applied')
            current=self.current(entry)
            self.assertEqual((current['tier'],current['state']),(tier,state))
        self.assertGreaterEqual(current['expires_at'],entry['expires_at'])
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM decision_v3_confirmations').fetchone()[0],1)

    def test_conflict_and_inactive_memory_require_resolution(self):
        _,_,_,entry=self.confirm()
        self.hook('长期记住 '+entry['memory_id'])
        candidate=fixtures.rule_candidate();candidate['memory_intent']='change'
        _,_,_,other=self.confirm(choice='B',cand=candidate)
        handle=self.hook('把刚才的选择长期记住')['session_handle']
        self.assertEqual(self.manage(other,handle)['reason'],'PROJECT_RULES_CONFLICT')
        self.hook('遗忘 '+other['memory_id'])
        handle=self.hook('把刚才的选择长期记住')['session_handle']
        self.assertEqual(self.manage(other,handle)['reason'],'RESTORE_OR_REVIEW_BEFORE_PROMOTING')


if __name__=='__main__':unittest.main()
