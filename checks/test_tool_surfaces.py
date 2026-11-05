"""One live contract, bounded Hook bootstrap, old rows and explicit tool profiles."""
import json
import unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from buildchoice.desktop.decision_contracts import SCHEMA,input_schema,validate
from buildchoice.desktop.decision_hook import handle_prompt
from buildchoice.desktop.decision_settings import read,update
from buildchoice.desktop.decision_store import fingerprint
import test_context_workflow as context_fixture
from test_guidance import candidate
from test_mcp_notifications import Connection


class ToolSurfaceTests(unittest.TestCase):
    def fixture(self):
        fixture=context_fixture.ContextWorkflowTests();fixture.setUp();return fixture

    def connect(self,native=True):
        connection=Connection(native,profile='core');self.addCleanup(connection.close);return connection

    def test_default_profile_preserves_old_settings_and_rejects_invalid_profiles(self):
        f=self.fixture()
        self.assertEqual(read(f.settings)['tool_profile'],'core')
        update(tool_profile='full',path=f.settings)
        self.assertEqual(read(f.settings)['mode'],'pilot')
        self.assertEqual(read(f.settings)['tool_profile'],'full')
        with self.assertRaises(ValueError):update(tool_profile='anything',path=f.settings)

    def test_advertised_and_enforced_candidate_contract_are_identical(self):
        schema=input_schema('ScreenRequest')
        self.assertEqual(schema['$defs']['Candidate'],SCHEMA['$defs']['Candidate'])
        minimal={k:v for k,v in candidate().items() if k in SCHEMA['$defs']['Candidate']['required']}
        self.assertEqual(len(minimal),7)
        validate('Candidate',minimal)
        missing={k:v for k,v in minimal.items() if k!='suggested_action'}
        with self.assertRaisesRegex(ValueError,'suggested_action'):validate('Candidate',missing)
        for key in ('needs_user_choice','current_dependency','engineering_detail','relevance','why_user_choice'):
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'Additional properties'):
                validate('Candidate',minimal|{key:'yes'})

    def test_invalid_new_input_writes_nothing_and_does_not_guess_action(self):
        f=self.fixture();before=f.counts();missing=candidate();missing.pop('suggested_action')
        with self.assertRaisesRegex(ValueError,'suggested_action'):f.screen(missing)
        self.assertEqual(before,f.counts())

    def test_old_stored_candidate_keeps_hash_and_confirmed_choice_on_read(self):
        f=self.fixture();screened=f.screen();f.activate(screened)
        f.handle=f.hook('A');item=screened['decisions'][0]
        with f.store.connect() as db:
            row=db.execute('SELECT * FROM decision_v3_items WHERE id=?',(item['decision_id'],)).fetchone()
            old=json.loads(row['candidate_json']);old.update(needs_user_choice='yes',current_dependency='yes',
                engineering_detail=False,relevance='yes',why_user_choice='Legacy declaration')
            raw=json.dumps(old,ensure_ascii=False)
            db.execute('UPDATE decision_v3_items SET candidate_json=? WHERE id=?',(raw,item['decision_id']))
        before=fingerprint(old)
        self.assertEqual(f.service.context_bundle(f.handle)['memory'][0]['revision'],1)
        self.assertTrue(f.service.status(screened['task_id'],f.handle)['decisions'][0]['confirmation']['applicable'])
        self.assertTrue(f.service.decision_document(f.handle)['decisions'][0]['choice'])
        with f.store.connect() as db:
            after=json.loads(db.execute('SELECT candidate_json FROM decision_v3_items WHERE id=?',(item['decision_id'],)).fetchone()[0])
        self.assertEqual(fingerprint(after),before)

    def test_hook_injects_only_state_and_skill_routing(self):
        f=self.fixture()
        event={'hook_event_name':'UserPromptSubmit','cwd':str(f.workspace),'session_id':'new','turn_id':'1','prompt':'给现有项目加登录'}
        text=handle_prompt(event,f.workspace,f.settings)['hookSpecificOutput']['additionalContext']
        self.assertIn('buildchoice-v3-ctx-',text)
        self.assertIn('decision-discovery',text);self.assertIn('decision-memory',text)
        for detail in ('buildchoice_context','buildchoice_reply_interpret','coverage','suggested_action','一次一张'):
            self.assertNotIn(detail,text)
        self.assertLess(len(text),350)

    def test_core_full_native_notifications_and_call_time_guard(self):
        c=self.connect();self.assertEqual(len(c.tools()),4)
        c.update(decision_guidance='试用')
        names=c.tools();self.assertEqual(len(names),14)
        self.assertIn('buildchoice_record_instruction',names);self.assertIn('buildchoice_decision_document',names)
        self.assertNotIn('buildchoice_acceptance_prepare',names)
        denied=c.send('tools/call',{'name':'buildchoice_audit_start','arguments':{'title':'Hidden','task':'No audit'}})
        self.assertTrue(denied.get('isError'));self.assertFalse((c.workspace/'.buildchoice_audit').exists())
        count=c.change_count();c.update(tool_profile='完整')
        self.assertEqual(len(c.tools()),24);self.assertEqual(c.change_count(),count+1)
        count=c.change_count();c.update(tool_profile='完整');self.assertEqual(c.change_count(),count)
        c.update(tool_profile='日常');self.assertEqual(len(c.tools()),14)
        c.update(mode='完全关闭',tool_profile='完整');self.assertEqual(len(c.tools()),4)
        self.assertTrue(c.send('tools/call',{'name':'buildchoice_audit_start','arguments':{'title':'Off','task':'No write'}}).get('isError'))

    def test_cli_switches_non_native_tool_surface(self):
        c=self.connect(native=False);self.assertEqual(len(c.tools()),1)
        c.cli('buildchoice_decisions.py','pilot');c.await_change();self.assertEqual(len(c.tools()),11)
        c.cli('buildchoice_decisions.py','full');c.await_change();self.assertEqual(len(c.tools()),21)
        c.cli('buildchoice_decisions.py','core');c.await_change();self.assertEqual(len(c.tools()),11)
        c.cli('buildchoice_decisions.py','off');c.await_change();self.assertEqual(len(c.tools()),1)
