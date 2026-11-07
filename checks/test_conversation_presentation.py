"""Native question payloads and user-facing feedback, with unchanged trusted confirmation gates."""
import json
import sys
from pathlib import Path
import unittest
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from buildchoice.desktop.conversation_ui import decision_presentation
from buildchoice.desktop.decision_cards import make_card,render
from buildchoice.desktop.decision_store import fingerprint
from test_guidance import candidate
import test_context_workflow as context_fixtures
import test_product_workflow as product_fixtures


class ConversationPresentationTests(unittest.TestCase):
    def fixture(self):
        f=context_fixtures.ContextWorkflowTests();f.setUp();return f

    def product_fixture(self,batch=False):
        f=(product_fixtures.BatchDecisionTests() if batch else product_fixtures.ProductWorkflowTests())
        f.setUp();self.addCleanup(f.env.stop);return f

    def test_recommendation_cleanup_is_display_only_and_preserves_all_consequences(self):
        value=candidate();value['options'][0]['label']='持续保留（推荐）（推荐）'
        value.update(recommended_option_id='A',recommendation_reason='避免到期丢失')
        card=make_card('decision-12345678',1,value);before=fingerprint(card)
        ui=decision_presentation([{'decision_id':'decision-12345678','revision':1,'card':card}])
        question=ui['native_request']['questions'][0]
        self.assertEqual(set(question),{'title','options'})
        self.assertEqual(question['options'][0].count('（推荐）'),1)
        self.assertIn(value['options'][0]['tradeoff'],question['options'][0])
        self.assertEqual(question['title'],value['question'])
        self.assertFalse(question['options'][0].startswith('A.'))
        self.assertEqual(ui['details'][0]['impact'],value['impact'])
        self.assertEqual(ui['details'][0]['recommendation']['reason'],value['recommendation_reason'])
        self.assertNotIn('D12345678',json.dumps(ui['native_request']))
        self.assertEqual(fingerprint(card),before)
        self.assertEqual(ui['bindings'][0]['answers'][0]['choice_id'],'A')
        self.assertEqual(render(card).count('（推荐）'),1)

    def test_native_display_alone_never_confirms_and_real_wrapped_reply_can_be_bound(self):
        f=self.fixture();screen=f.screen();shown=f.activate(screen)
        form=shown['presentation'];answer=form['native_request']['questions'][0]['options'][1]
        self.assertEqual(shown['workflow']['mode'],'standard')
        self.assertFalse(form['user_confirmed'])
        with f.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM decision_v3_confirmations').fetchone()[0],0)
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='product_tasks'").fetchone())
        f.handle=f.hook(json.dumps([{'question':'visibility','answer':answer}],ensure_ascii=False))
        item=screen['decisions'][0]
        result=f.service.interpret_reply(screen['task_id'],item['decision_id'],1,'B',answer,'用户原生选项对应冻结方案 B',f.handle)
        self.assertEqual(result['confirmation']['choice_id'],'B')
        self.assertFalse(result['semantic_verified_by_program'])

    def test_form_binding_cannot_be_used_without_a_new_actual_reply(self):
        f=self.fixture();screen=f.screen();shown=f.activate(screen);item=screen['decisions'][0]
        answer=shown['presentation']['native_request']['questions'][0]['options'][0]
        with self.assertRaisesRegex(ValueError,'pending user reply'):
            f.service.interpret_reply(screen['task_id'],item['decision_id'],1,'A',answer,'还没有用户回答',f.handle)

    def test_batch_payload_keeps_question_order_and_partial_answers_atomic(self):
        f=self.product_fixture(batch=True);refs=f.batch(3)
        shown=f.call('batch_decisions','present',decisions=refs)
        form=shown['presentation']
        self.assertEqual(len(form['native_request']['questions']),3)
        self.assertEqual([b['decision_id'] for b in form['bindings']],[r['decision_id'] for r in refs])
        answer=form['native_request']['questions'][0]['options'][1]
        f.hook('第一项：'+answer+'；其余先讨论')
        result=f.call('batch_decisions','submit',batch_id=shown['id'],answers=[
            {**refs[0],'status':'selected','choice_id':'B'},{**refs[1],'status':'discuss'}],**f.user())
        self.assertEqual([r['status'] for r in result['decisions']],['confirmed','discuss','unanswered'])

    def test_representing_an_active_batch_retains_the_same_frozen_cards_and_no_confirmation(self):
        f=self.product_fixture(batch=True);refs=f.batch(2)
        first=f.call('batch_decisions','present',decisions=refs)
        second=f.call('batch_decisions','present',decisions=refs)
        self.assertTrue(second['already_active'])
        self.assertEqual(first['presentation'],second['presentation'])
        self.assertTrue(all(entry['card'] for entry in second['decisions']))
        self.assertFalse(second['presentation']['user_confirmed'])

    def test_native_question_contains_the_same_grounded_risk_as_text_fallback(self):
        value=candidate();value['options'][0].update(risk_level='high',risk_warning='可能影响共享记录',risk_basis='potential')
        card=make_card('decision-12345678',1,value)
        native=decision_presentation([{'decision_id':'decision-12345678','revision':1,'card':card}])
        self.assertIn('可能影响共享记录',native['native_request']['questions'][0]['options'][0])
        self.assertIn('可能影响共享记录',render(card))

    def test_product_workflow_exposes_missing_stages_without_inventing_a_baseline(self):
        f=self.product_fixture()
        self.assertEqual(f.call('experience','status')['workflow']['stage'],'needs_scenarios')
        scenes=f.save()
        self.assertEqual(f.call('experience','status')['workflow']['stage'],'needs_expectation_review')
        expected=f.call('experience','freeze')
        self.assertEqual(expected['workflow']['stage'],'needs_code_baseline')
        (f.workspace/'app.py').write_text('save_after_review = True\n',encoding='utf8')
        baseline=f.call('workspace_snapshot','capture',expectation_id=expected['id'],scopes=['app.py'])
        self.assertEqual(baseline['workflow']['stage'],'ready_for_implementation')
        comp=f.call('workspace_snapshot','compare',baseline_id=baseline['id'])
        self.assertEqual(comp['workflow']['stage'],'needs_behavior_review')
        review=f.call('behavior_review','create',comparison_id=comp['id'],findings=[])
        self.assertEqual(review['workflow']['stage'],'review_recorded')
        f.hook('修订场景')
        f.save([f.scenario(scenario_id=scenes[0]['id'],expected_revision=1)])
        self.assertEqual(f.call('experience','status')['workflow']['stage'],'needs_expectation_review')

    def test_feedback_uses_original_frozen_behavior_and_keeps_commands_out_of_primary_message(self):
        f=self.product_fixture();scene,baseline,comp,review=f.review()
        self.assertEqual(review['findings'][0]['expected_behavior'],['核对后才保存消费记录'])
        message=review['message']
        self.assertIn('核对后才保存消费记录',message)
        self.assertIn(review['findings'][0]['summary'],message)
        self.assertIn('已查看相关资料',message)
        self.assertNotIn(review['findings'][0]['limits'],message)
        for technical in ('```','powershell','app.py:','finding_id','tested_behaviors','USER_CHOICE','记录编号'):
            self.assertNotIn(technical,message)
        self.assertEqual(review['findings'][0]['evidence'][0]['path'],'app.py')

    def test_llm_only_match_is_presented_as_unverified_instead_of_verified_agreement(self):
        f=self.product_fixture();scene,expected,baseline,comp=f.comparison()
        result=f.call('behavior_review','create',comparison_id=comp['id'],findings=[
            f.finding(scene,'possibly_matches',evidence=[{'kind':'llm','note':'模型推断'}])])
        self.assertTrue(result['findings'][0]['requires_followup'])
        message=result['message']
        self.assertIn(result['findings'][0]['summary'],message)
        self.assertIn('待检查',message)
        self.assertNotIn('已做相关测试',message)


if __name__=='__main__':unittest.main()
