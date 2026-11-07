"""Source/version boundaries. Hook messages here are isolated synthetic fixtures only."""
import unittest
import test_product_workflow as fixtures
from test_feedback_report import finding, report
from test_mcp_notifications import Connection
from buildchoice.desktop import product_store as ps


class IndependentReviewTests(unittest.TestCase):
    def fixture(self, policy='independent'):
        f=fixtures.ProductWorkflowTests();f.setUp();self.addCleanup(f.env.stop)
        f.call('experience','enable',task_text=f.text,purpose='feedback',review_policy=policy)
        (f.workspace/'app.py').write_text('summary_follows_search = False\nwindow_title = "Demo ledger"\n',encoding='utf8')
        snap=f.call('workspace_snapshot','inspect',scopes=['app.py'])
        return f,snap

    def goal(self,f):
        return {'fact_id':'goal','scope':'goal','role':'requirement',
                'source':{'kind':'task','task_id':f.task,'task_text':'做小票识别，核对后保存','quote':'核对后保存'}}

    def packet(self,f,snap,**extra):
        return f.call('behavior_review','prepare_independent',current_snapshot_id=snap['id'],
                      facts=extra.pop('facts',[self.goal(f)]),artifacts=extra.pop('artifacts',[{'path':'app.py'}]),**extra)

    def issue(self,ident='scope'):
        return {'issue_id':ident,'title':'汇总未跟随搜索','observation':'列表筛选时汇总仍是全部数据。',
            'effect':'用户可能把两者理解成同一范围。','basis_fact_ids':['goal'],
            'artifacts':[{'path':'app.py','start_line':1,'end_line':1,'quote':'summary_follows_search = False'}]}

    def submit(self,f,p,issues=None,questions=None):
        return f.call('behavior_review','submit_independent',packet_id=p['id'],
            reviewer={'agent_id':'synthetic-fixture-agent','fork_turns':'none','model_policy':'inherit','permissions':'inherit_host'},
            issues=issues if issues is not None else [self.issue()],questions=questions or [])

    def question(self):return {'question_id':'why','question':'当前汇总范围是否有其他已确认要求？','issue_ids':['scope']}

    def background(self,f,review,**extra):
        fact={'fact_id':'explanation','scope':'product','role':'explanation','source':{'kind':'ai','note':'执行者认为固定总额方便对照。'}}
        return f.call('behavior_review','provide_background',independent_review_id=review['id'],expected_revision=review['revision'],
                      answers=extra.pop('answers',[{'question_id':'why','facts':[fact]}]),**extra)

    def publish(self,f,snap,review=None,dispositions=None):
        extra={}
        if review:extra['independent_review']={'id':review['id'],'revision':review['revision'],
            'dispositions':dispositions if dispositions is not None else [{'issue_id':'scope','action':'include','finding_id':'search'}]}
        return f.call('behavior_review','supplement',current_snapshot_id=snap['id'],findings=[finding()],report=report(),**extra)

    def test_packet_has_original_goal_and_actual_sections_no_executor_history(self):
        f,snap=self.fixture();p=self.packet(f,snap,artifacts=[{'path':'app.py','start_line':2,'end_line':2}])
        self.assertEqual(p['payload']['artifacts'][0]['text'],'window_title = "Demo ledger"')
        self.assertNotIn('task_text',p['payload']['facts'][0]['source'])
        self.assertEqual(p['host_action']['fork_turns'],'none')
        self.assertIn('response_contract',p['payload'])
        self.assertEqual(p['workflow']['stage'],'needs_independent_reviewer')
        self.assertFalse(p['semantic_judgment_by']=='program')

    def test_task_and_current_user_source_cannot_be_fabricated(self):
        f,snap=self.fixture();bad=self.goal(f);bad['source']['task_text']='伪造任务 核对后保存'
        with self.assertRaisesRegex(ValueError,'actual observed'):self.packet(f,snap,facts=[bad])
        good={'fact_id':'current','scope':'goal','role':'requirement','source':{'kind':'user',**f.user()}}
        self.packet(f,snap,facts=[good]);good['source']['user_message']='捏造'
        with self.assertRaisesRegex(ValueError,'actual current Hook'):self.packet(f,snap,facts=[good])

    def test_original_task_fact_recovers_across_chats_but_unverified_input_does_not(self):
        f,snap=self.fixture();f.hook('继续核对原任务',host='second-chat')
        self.packet(f,snap)
        with f.store.transaction() as db:
            db.execute("UPDATE decision_v3_tasks SET binding_status='unverified' WHERE id=?",(f.task,))
        with self.assertRaisesRegex(ValueError,'actual observed'):self.packet(f,snap)

    def test_explanation_and_current_project_cannot_become_first_pass_requirements(self):
        f,snap=self.fixture();given={'fact_id':'ai','scope':'product','role':'explanation','source':{'kind':'ai','note':'方便测试'}}
        with self.assertRaisesRegex(ValueError,'executor explanations'):self.packet(f,snap,facts=[self.goal(f),given])
        (f.workspace/'brief.md').write_text('Use synthetic receipts only.',encoding='utf8')
        src=f.service.context_bundle(f.handle,paths=['brief.md'])['sources'][0]
        given.update(role='requirement',source={'kind':'project','source_id':src['source_id'],'quote':'synthetic receipts only'})
        with self.assertRaisesRegex(ValueError,'not a confirmed user'):self.packet(f,snap,facts=[self.goal(f),given])
        given.update(role='constraint',scope='data');p=self.packet(f,snap,facts=[self.goal(f),given])
        self.assertEqual(p['payload']['facts'][1]['scope'],'data')
        (f.workspace/'brief.md').write_text('Changed constraint.',encoding='utf8')
        with self.assertRaisesRegex(ValueError,'materials changed'):self.submit(f,p)

    def test_safe_artifact_ranges_budget_and_exact_issue_quotes(self):
        f,snap=self.fixture()
        for artifact in ({'path':'missing.py'},{'path':'app.py','end_line':99},{'path':'../app.py'}):
            with self.subTest(artifact=artifact),self.assertRaises(ValueError):self.packet(f,snap,artifacts=[artifact])
        with self.assertRaisesRegex(ValueError,'exceeds budget'):self.packet(f,snap,max_chars=2000)
        p=self.packet(f,snap,artifacts=[{'path':'app.py','start_line':1,'end_line':1}])
        bad=self.issue();bad['artifacts'][0]['quote']='made up'
        with self.assertRaisesRegex(ValueError,'quote does not match'):self.submit(f,p,[bad])
        bad=self.issue();bad['artifacts'][0].update(start_line=2,end_line=2)
        with self.assertRaisesRegex(ValueError,'outside disclosed'):self.submit(f,p,[bad])
        bad=self.issue();bad['basis_fact_ids']=['imaginary']
        with self.assertRaisesRegex(ValueError,'unavailable fact'):self.submit(f,p,[bad])

    def test_policy_blocks_feedback_and_requires_explained_adoption(self):
        f,snap=self.fixture()
        with self.assertRaisesRegex(ValueError,'required before publishing'):self.publish(f,snap)
        p=self.packet(f,snap);r=self.submit(f,p)
        with self.assertRaisesRegex(ValueError,'every independent'):self.publish(f,snap,r,[])
        with self.assertRaisesRegex(ValueError,'explicit reason'):self.publish(f,snap,r,[{'issue_id':'scope','action':'exclude'}])
        with self.assertRaisesRegex(ValueError,'submitted finding'):self.publish(f,snap,r,[{'issue_id':'scope','action':'include','finding_id':'fake'}])
        saved=self.publish(f,snap,r)
        self.assertEqual(saved['independent_review']['revision'],1)
        self.assertEqual(saved['workflow']['stage'],'current_review_recorded')

    def test_standard_policy_remains_compatible_and_reenable_preserves_independent_policy(self):
        f,snap=self.fixture('standard');self.publish(f,snap)
        f.call('experience','enable',task_text=f.text,review_policy='independent')
        again=f.call('experience','enable',task_text=f.text,purpose='feedback')
        self.assertEqual(again['workflow']['review_policy'],'independent')
        with self.assertRaisesRegex(ValueError,'required before publishing'):self.publish(f,snap)

    def test_only_pending_questions_accept_background_and_full_disposition_is_required(self):
        f,snap=self.fixture();p=self.packet(f,snap);r=self.submit(f,p,questions=[self.question()])
        with self.assertRaisesRegex(ValueError,'specific pending'):self.background(f,r,answers=[{'question_id':'invented','facts':[self.goal(f)]}])
        b=self.background(f,r)
        self.assertEqual(b['host_action']['agent_id'],'synthetic-fixture-agent')
        with self.assertRaisesRegex(ValueError,'already supplied'):self.background(f,r)
        with self.assertRaisesRegex(ValueError,'reconsideration is still pending'):self.publish(f,snap,r)
        args={'independent_review_id':r['id'],'expected_revision':1,'background_id':b['id'],'issues':[],'questions':[]}
        with self.assertRaisesRegex(ValueError,'Every old/new'):f.call('behavior_review','reconsider_independent',changes=[],**args)
        with self.assertRaisesRegex(ValueError,'does not match'):f.call('behavior_review','reconsider_independent',changes=[{'issue_id':'scope','action':'keep','reason':'same'}],**args)
        changed=f.call('behavior_review','reconsider_independent',changes=[{'issue_id':'scope','action':'withdraw','reason':'新背景改变了此问题的适用条件。'}],**args)
        self.assertEqual(changed['revision'],2);self.assertEqual(changed['history'][0]['issues'],[self.issue()])
        self.assertEqual(changed['issues'],[]);self.assertEqual(changed['backgrounds'][0]['answers'][0]['facts'][0]['role'],'explanation')
        with self.assertRaisesRegex(ValueError,'version changed'):self.background(f,r)
        with self.assertRaisesRegex(ValueError,'stale'):self.publish(f,snap,r)
        self.publish(f,snap,changed,[])
        doc=f.call('experience','document')['markdown'];self.assertIn('第 1 版',doc);self.assertIn('withdraw',doc)

    def test_revise_keep_add_and_no_silent_issue_loss(self):
        f,snap=self.fixture();p=self.packet(f,snap);r=self.submit(f,p,questions=[self.question()]);b=self.background(f,r)
        revised=self.issue();revised['effect']='补充范围说明仍然有帮助。';added=self.issue('other')
        args={'independent_review_id':r['id'],'expected_revision':1,'background_id':b['id'],'issues':[revised,added],'questions':[self.question()]}
        current=f.call('behavior_review','reconsider_independent',**args,changes=[{'issue_id':'scope','action':'revise','reason':'区分条件。'},{'issue_id':'other','action':'add','reason':'发现另一处影响。'}])
        fact={'fact_id':'more','scope':'runtime','role':'explanation','source':{'kind':'ai','note':'没有其他运行证据。'}}
        b2=self.background(f,current,answers=[{'question_id':'why','facts':[fact]}])
        last=f.call('behavior_review','reconsider_independent',independent_review_id=r['id'],expected_revision=2,background_id=b2['id'],
            issues=[revised,added],questions=[],changes=[{'issue_id':i['issue_id'],'action':'keep','reason':'额外信息未改变判断。'} for i in [revised,added]])
        self.assertEqual(len(last['history']),3)

    def test_zero_issue_review_needs_no_background_round(self):
        f,snap=self.fixture();p=self.packet(f,snap);r=self.submit(f,p,issues=[])
        self.assertEqual(r['workflow']['stage'],'needs_review_adoption')
        self.publish(f,snap,r,[])

    def test_stale_code_new_inspection_and_closed_task_read_only_status(self):
        f,snap=self.fixture();p=self.packet(f,snap);r=self.submit(f,p)
        new=f.call('workspace_snapshot','inspect',scopes=['app.py'])
        with self.assertRaisesRegex(ValueError,'another inspection'):self.publish(f,new,r)
        (f.workspace/'app.py').write_text('changed = True\n',encoding='utf8')
        with self.assertRaisesRegex(ValueError,'materials changed'):self.submit(f,p)
        args={'action':'independent_status','session_handle':f.handle,'task_id':f.task,'independent_review_id':r['id']}
        status=f.service.behavior_review(args)
        self.assertEqual(status['validity'],'needs_recheck')
        f.call('experience','close')
        f.service.behavior_review(args)
        with self.assertRaisesRegex(ValueError,'closed'):self.submit(f,p)

    def test_stdio_advertises_new_actions_without_extra_tools(self):
        c=Connection(profile='core');self.addCleanup(c.close);c.update(decision_guidance='试用')
        tools=c.send('tools/list',{})['tools'];self.assertEqual(len(tools),14)
        tool=next(t for t in tools if t['name']=='buildchoice_behavior_review')
        serialized=str(tool['inputSchema']);self.assertIn('prepare_independent',serialized);self.assertIn('reconsider_independent',serialized)
        self.assertIn('review_topics',serialized)
        self.assertIn('uniqueItems',serialized)
        c.update(tool_profile='完整');self.assertEqual(len(c.tools()),24)
