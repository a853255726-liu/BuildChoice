"""Generation, repair, current risk sources and compact native display as one pipeline."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from jsonschema import Draft202012Validator
from buildchoice.desktop.audit import Ledger
from buildchoice.desktop.decision_content import VERSION, require_current
from buildchoice.desktop.decision_contracts import input_schema,validate
from buildchoice.desktop.decision_store import fingerprint
from test_guidance import candidate
import test_context_workflow as context_fixtures


def structured_candidate():
    value=candidate();value['content_version']=VERSION
    value.update(question='你希望怎样打开记账界面？',impact='影响启动方式和操作体验。',risk_flags=[])
    value['options']=[
        {'id':'A','label':'桌面窗口','tradeoff':'直接打开独立窗口操作。',
         'risk_assessment':{'status':'no_specific_risk','reason':'本轮只比较本机打开方式，未发现额外的数据处理后果。'}},
        {'id':'B','label':'本机浏览器','tradeoff':'先启动本机服务，再用浏览器操作。',
         'risk_assessment':{'status':'not_assessed','reason':'尚未核对本机服务的绑定方式。'}}]
    return value


class DecisionContentTests(unittest.TestCase):
    def fixture(self):
        f=context_fixtures.ContextWorkflowTests();f.setUp();return f

    def source(self,f,text='The server exposes records on a public interface.'):
        (f.workspace/'risk.txt').write_text(text,encoding='utf8')
        ledger=Ledger(f.workspace);session=ledger.start('risk fixture','Synthetic source')
        return ledger.read(session['id'],'risk.txt')

    def test_advertised_contract_requires_version_and_assessment_but_legacy_reads_remain_valid(self):
        validator=Draft202012Validator(input_schema('Candidate'))
        validator.validate(structured_candidate())
        self.assertTrue(list(validator.iter_errors(candidate())))
        with self.assertRaisesRegex(ValueError,'CONTENT_REPAIR_REQUIRED'):require_current([candidate()])
        self.assertTrue(validate('Candidate',candidate()))

    def test_bad_content_has_field_errors_and_writes_no_decision_or_confirmation(self):
        f=self.fixture();before=f.counts()
        variants=[]
        for field,text in [('question','q'*91),('question','Question\n产品影响：extra'),('impact',' '),
                           ('question','ASK_NOW please')]:
            value=structured_candidate();value[field]=text;variants.append(value)
        for field,text in [('label','A. 桌面窗口'),('label','桌面窗口（推荐）'),('tradeoff','x'*141)]:
            value=structured_candidate();value['options'][0][field]=text;variants.append(value)
        value=structured_candidate();value['options'][0].pop('risk_assessment');variants.append(value)
        value=structured_candidate();value['options'][1]['label']=value['options'][0]['label'];variants.append(value)
        value=structured_candidate();value['options'][1]['tradeoff']=value['options'][0]['tradeoff'];variants.append(value)
        value=structured_candidate();value.update(recommended_option_id='A',recommendation_reason=value['options'][0]['tradeoff']);variants.append(value)
        value=structured_candidate();value['options'][0].update(risk_level='low',risk_warning='Specific consequence');variants.append(value)
        value=structured_candidate();value['options'][0].update(
            risk_assessment={'status':'risks_identified','reason':'Conditional concern'},
            risk_level='medium',risk_warning='A specific consequence',risk_basis='potential',
            risk_condition='First line\nUnwanted section',risk_reason='Specific mechanism');variants.append(value)
        for value in variants:
            with self.subTest(value=value),self.assertRaises(ValueError) as error:f.screen(value)
            result=json.loads(str(error.exception))
            self.assertEqual(result['code'],'CONTENT_REPAIR_REQUIRED')
            self.assertTrue(result['issues'][0]['field'])
            self.assertFalse(result['semantic_verified_by_program'])
            self.assertEqual(f.counts(),before)

    def test_fixed_native_template_has_only_question_and_outcomes_with_details_retained(self):
        f=self.fixture();value=structured_candidate()
        value.update(recommended_option_id='A',recommendation_reason='用户已明确希望打开后直接操作。')
        result=f.screen(value);card=result['decisions'][0]['card'];before=fingerprint(card)
        shown=f.activate(result);form=shown['presentation'];question=form['native_request']['questions'][0]
        self.assertEqual(question['title'],value['question'])
        self.assertEqual(len(question['title'].splitlines()),1)
        self.assertEqual(question['options'][0],'桌面窗口（推荐）：直接打开独立窗口操作。')
        self.assertEqual(form['details'][0]['recommendation']['reason'],value['recommendation_reason'])
        self.assertEqual([a['status'] for a in form['details'][0]['risk_assessments']],['no_specific_risk','not_assessed'])
        self.assertFalse(form['details'][0]['risk_assessments'][0]['semantic_verified_by_program'])
        self.assertEqual(form['bindings'][0]['answers'][1]['choice_id'],'B')
        self.assertEqual(fingerprint(card),before)
        self.assertEqual(f.counts()['decision_v3_confirmations'],0)

    def test_concrete_potential_risks_of_each_severity_keep_consequence_and_condition(self):
        for severity in ('low','medium','high'):
            f=self.fixture();value=structured_candidate()
            value['options'][1].update(risk_assessment={'status':'risks_identified','reason':'本机端口可能已被占用。'},
                risk_level=severity,risk_basis='potential',risk_warning='页面可能无法打开。',
                risk_condition='启动端口已被其他程序占用时',risk_reason='本机服务需要可用端口。')
            shown=f.activate(f.screen(value));option=shown['presentation']['native_request']['questions'][0]['options'][1]
            self.assertIn('页面可能无法打开。',option)
            self.assertIn('启动端口已被其他程序占用时',option)
            self.assertIn('页面可能无法打开。',shown['message'])

    def test_invalid_risk_basis_prevents_a_new_card_instead_of_hiding_the_warning(self):
        f=self.fixture();value=structured_candidate()
        value['options'][1].update(risk_assessment={'status':'risks_identified','reason':'资料中的后果。'},
            risk_level='medium',risk_basis='observed',risk_warning='记录可能被其他电脑读取。',
            risk_evidence_refs=[{'source_id':'invented','quote':'Missing quote'}])
        result=f.screen(value);item=result['decisions'][0]
        self.assertEqual(item['status'],'INSPECT');self.assertIsNone(item['card'])
        with self.assertRaises(ValueError):f.activate(result)
        self.assertEqual(f.counts()['decision_v3_confirmations'],0)

    def test_changed_risk_source_blocks_activation_and_revision_before_persisting_them(self):
        f=self.fixture();source=self.source(f);value=structured_candidate()
        value['options'][1].update(risk_assessment={'status':'risks_identified','reason':'资料记载了公开接口。'},
            risk_level='medium',risk_basis='observed',risk_warning='其他电脑可能读取记录。',
            risk_evidence_refs=[{'source_id':source['id'],'quote':'public interface'}])
        result=f.screen(value);item=result['decisions'][0]
        (f.workspace/'risk.txt').write_text('Changed source',encoding='utf8')
        before=f.counts()
        with self.assertRaisesRegex(ValueError,'CONTENT_EVIDENCE_RECHECK_REQUIRED'):f.activate(result)
        with self.assertRaisesRegex(ValueError,'CONTENT_EVIDENCE_RECHECK_REQUIRED'):
            f.service.prepare_revision(result['task_id'],item['decision_id'],1,value,'Revise',f.handle)
        self.assertEqual(f.counts(),before)

    def test_repaired_candidate_can_be_shown_and_actual_native_reply_is_bound_to_frozen_choice(self):
        f=self.fixture();value=structured_candidate();value['question']+='\nAdditional paragraph'
        with self.assertRaisesRegex(ValueError,'CONTENT_REPAIR_REQUIRED'):f.screen(value)
        value['question']='你希望怎样打开记账界面？'
        result=f.screen(value);shown=f.activate(result)
        answer=shown['presentation']['native_request']['questions'][0]['options'][1]
        f.handle=f.hook(json.dumps([{'question':value['question'],'answer':answer}],ensure_ascii=False))
        item=result['decisions'][0]
        confirmed=f.service.interpret_reply(result['task_id'],item['decision_id'],1,'B',answer,
            '当前原生回答明确对应冻结的本机浏览器选项',f.handle)
        self.assertEqual(confirmed['confirmation']['choice_id'],'B')
        self.assertEqual(f.counts()['decision_v3_confirmations'],1)


if __name__=='__main__':unittest.main()
