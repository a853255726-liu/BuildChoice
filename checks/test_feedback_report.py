"""Concrete post-change feedback with honest evidence and no retroactive expectation approval."""
import unittest
import uuid
import test_product_workflow as fixtures
from buildchoice.desktop import product_store as ps
from buildchoice.desktop.product_observer import observe


def report():return {'version':'behavior-feedback.v1','overview':['search']}


def finding():
    return {'finding_id':'search','judgment':'extra','summary':'搜索会筛选明细，顶部汇总仍统计全部正常记录。',
            'importance':'high','change_origin':'uncertain',
            'display':{'title':'搜索与汇总范围不同','check':'read','impact':'筛选后，列表与顶部金额可能对应不同范围。'},
            'evidence':[{'kind':'file','path':'app.py','quote':'summary_follows_search = False','note':'当前汇总范围'}],
            'limits':'只有代码资料，无法据此证明运行路径完全正确；此处留作详细检查记录。'}


class FeedbackReportTests(unittest.TestCase):
    def fixture(self):
        f=fixtures.ProductWorkflowTests();f.setUp();self.addCleanup(f.env.stop);return f

    def inspect(self,f):
        started=f.call('experience','enable',task_text=f.text,purpose='feedback')
        self.assertEqual(started['workflow']['stage'],'needs_current_inspection')
        (f.workspace/'app.py').write_text('summary_follows_search = False\n',encoding='utf8')
        return f.call('workspace_snapshot','inspect',scopes=['app.py'])

    def supplement(self,f,snapshot,value=None):
        return f.call('behavior_review','supplement',current_snapshot_id=snapshot['id'],
                      findings=[value or finding()],report=report())

    def test_completed_work_enters_current_feedback_without_creating_scenarios_or_baselines(self):
        f=self.fixture();snapshot=self.inspect(f);result=self.supplement(f,snapshot)
        self.assertEqual(result['workflow']['stage'],'current_review_recorded')
        self.assertFalse(result['presentation']['has_frozen_baseline'])
        self.assertEqual(snapshot['phase'],'current_review');self.assertIsNone(snapshot['expectation_id'])
        with f.store.connect() as db:
            self.assertEqual(ps.objects(db,f.task,'expectation'),[])
            self.assertEqual(ps.objects(db,f.task,'scenario'),[])
        self.assertNotIn('产品体验预期',result['message'])
        self.assertNotIn('认可当前',result['message'])
        self.assertIn('如何表达修改意见',result['message'])

    def test_no_material_gap_omits_third_section_and_keeps_limits_in_detail(self):
        f=self.fixture();snapshot=self.inspect(f);result=self.supplement(f,snapshot)
        self.assertIn('优先值得你看的地方',result['message'])
        self.assertNotIn('还有什么具体情况需要确认',result['message'])
        self.assertNotIn(finding()['limits'],result['message'])
        self.assertEqual(result['findings'][0]['limits'],finding()['limits'])
        self.assertIn('已查看相关资料',result['message'])
        self.assertEqual(result['message'].count('不包含正式的前后行为对照'),1)
        self.assertNotIn('缺少改动前记录',result['message'])

    def test_material_gap_names_operation_effect_next_step_and_owner_once(self):
        f=self.fixture();snapshot=self.inspect(f);value=finding()
        value['display']['gap']={'situation':'窗口的中文显示和排版还没查看',
            'effect':'暂不能判断文字是否完整显示。','next_step':'打开实际窗口检查中文标签和按钮排版。','owner':'agent'}
        result=self.supplement(f,snapshot,value);message=result['message']
        self.assertIn('还有什么具体情况需要确认',message)
        self.assertEqual(message.count(value['display']['gap']['situation']),1)
        self.assertIn('下一步（我来处理）',message)
        self.assertNotIn('LLM',message)

    def test_vague_or_excessive_content_is_rejected_without_persisting_a_report(self):
        f=self.fixture();snapshot=self.inspect(f)
        for mutation in ('vague','overlong','unsupported','unknown_reference'):
            value=finding();view=value['display']
            if mutation=='vague':view['gap']={'situation':'尚未验证','effect':'有影响','next_step':'进一步验证','owner':'agent'}
            elif mutation=='overlong':value['summary']='长'*181
            elif mutation=='unsupported':view['check']='tested'
            else:value['finding_id']='not-offered-in-overview'
            with self.subTest(mutation=mutation),self.assertRaisesRegex(ValueError,'FEEDBACK_CONTENT_REPAIR_REQUIRED'):
                self.supplement(f,snapshot,value)
            with f.store.connect() as db:self.assertEqual(ps.objects(db,f.task,'behavior_review'),[])

    def test_high_important_unchecked_behavior_requires_concrete_gap(self):
        f=self.fixture();snapshot=self.inspect(f);value=finding()
        value.update(judgment='unknown',evidence=[]);value['display']['check']='not_checked'
        with self.assertRaisesRegex(ValueError,'important_unchecked_behavior'):
            self.supplement(f,snapshot,value)

    def test_current_inspection_cannot_be_used_as_a_fake_pre_edit_comparison(self):
        f=self.fixture();snapshot=self.inspect(f)
        with self.assertRaisesRegex(ValueError,'pre-edit baseline'):
            f.call('workspace_snapshot','compare',baseline_id=snapshot['id'])
        value=finding();value['change_origin']='observed_change'
        with self.assertRaisesRegex(ValueError,'origin must remain uncertain'):
            self.supplement(f,snapshot,value)
        value=finding();value['judgment']='possibly_deviates'
        with self.assertRaisesRegex(ValueError,'requires an actual reference'):
            self.supplement(f,snapshot,value)

    def test_code_changes_downgrade_visible_check_and_keep_old_report_immutable(self):
        f=self.fixture();snapshot=self.inspect(f);result=self.supplement(f,snapshot)
        with f.store.connect() as db:before=ps.get(db,result['id'])['data']
        (f.workspace/'app.py').write_text('summary_follows_search = True\n',encoding='utf8')
        current=f.call('behavior_review','status',review_id=result['id'])
        self.assertEqual(current['validity'],'needs_recheck')
        self.assertNotIn('已查看相关资料',current['message']);self.assertIn('待检查',current['message'])
        self.assertEqual(current['message'].count('当前产品已有后续变化'),1)
        with f.store.connect() as db:self.assertEqual(ps.get(db,result['id'])['data'],before)

    def test_formal_review_retains_frozen_agreement_and_rejects_omitted_behaviors(self):
        f=self.fixture();scene,expected,baseline,comp=f.comparison()
        value=f.finding(scene);value['display']={'title':'保存时机','check':'read','impact':'错误金额可能先进入账本。'}
        result=f.call('behavior_review','create',comparison_id=comp['id'],findings=[value],
                      report={'version':'behavior-feedback.v1','overview':['saving']})
        self.assertIn('原约定：核对后才保存消费记录',result['message'])
        self.assertTrue(result['presentation']['has_frozen_baseline'])
        with self.assertRaisesRegex(ValueError,'cover_each_frozen_behavior'):
            f.call('behavior_review','create',comparison_id=comp['id'],findings=[],
                   report={'version':'behavior-feedback.v1','overview':['saving']})

    def test_current_feedback_accepts_natural_language_fix_and_preserves_report(self):
        f=self.fixture();snapshot=self.inspect(f);result=self.supplement(f,snapshot)
        f.hook('搜索后顶部金额也跟着变')
        saved=f.call('behavior_review','feedback',review_id=result['id'],feedback=[{
            'finding_id':'search','action':'fix','note':'汇总跟随筛选范围',
            'expected_feedback_revision':0}],**f.user())
        self.assertTrue(saved['recorded'])
        self.assertEqual(saved['feedback'][0]['finding_id'],'search')
        self.assertEqual(saved['feedback'][0]['source']['quote'],f.text)
        self.assertTrue(saved['feedback'][0]['original_expectation_retained'])
        self.assertIn('接下来处理该行为并复查',saved['message'])
        self.assertNotIn('已修正',saved['message'])

    def test_current_reference_uses_real_project_text_and_changes_require_recheck(self):
        f=self.fixture();snapshot=self.inspect(f)
        (f.workspace/'brief.md').write_text('搜索仅筛选明细，不改变顶部汇总。',encoding='utf8')
        from buildchoice.desktop.audit import Ledger
        ledger=Ledger(f.workspace);session=ledger.start('Reference fixture','Synthetic project text')
        source=ledger.read(session['id'],'brief.md')
        value=finding();value['judgment']='possibly_matches'
        value['reference']={'text':'搜索仅筛选明细，不改变顶部汇总。',
            'source':{'kind':'project','source_id':source['id'],'quote':'搜索仅筛选明细'}}
        result=self.supplement(f,snapshot,value)
        self.assertEqual(result['validity'],'current')
        self.assertEqual(result['findings'][0]['reference']['source']['kind'],'project')
        (f.workspace/'brief.md').write_text('汇总也跟随搜索变化。',encoding='utf8')
        current=f.call('behavior_review','status',review_id=result['id'])
        self.assertEqual(current['validity'],'needs_recheck')

    def test_log_file_does_not_upgrade_a_report_to_actual_test_execution(self):
        f=self.fixture();snapshot=self.inspect(f);value=finding()
        value['evidence']=[{'kind':'test','path':'app.py','quote':'summary_follows_search',
                           'note':'仅有文件报告','tested_behaviors':['search'],'limits':'未捕获执行回调'}]
        value['display']['check']='tested'
        with self.assertRaisesRegex(ValueError,'check_claim_exceeds'):
            self.supplement(f,snapshot,value)
        value['display']['check']='read'
        result=self.supplement(f,snapshot,value)
        self.assertIn('已查看相关资料',result['message']);self.assertNotIn('已做相关测试',result['message'])

    def test_observed_check_requires_real_tool_receipt_and_complete_behavior_mapping(self):
        f=self.fixture();snapshot=self.inspect(f)
        event={'hook_event_name':'PostToolUse','cwd':str(f.workspace),'session_id':f.host,'turn_id':str(f.turn),
               'tool_use_id':'check-'+uuid.uuid4().hex,'tool_name':'exec_command',
               'tool_input':{'cmd':'synthetic application check'},'tool_response':{'exit_code':0,'output':'search view checked'}}
        self.assertIsNotNone(observe(event,f.workspace,f.config))
        with f.store.connect() as db:receipt=ps.objects(db,f.task,'tool_observation')[-1]['id']
        value=finding();value['display']['check']='observed'
        value['evidence']=[{'kind':'runtime','note':'核对搜索操作','observation_id':receipt,
            'quote':'search view checked','outcome':'passed','tested_behaviors':['search'],'limits':'仅核对搜索'}]
        result=self.supplement(f,snapshot,value)
        self.assertIn('已做操作检查',result['message'])
        value['evidence'][0]['tested_behaviors']=[]
        with self.assertRaisesRegex(ValueError,'coverage'):
            self.supplement(f,snapshot,value)


if __name__=='__main__':unittest.main()
