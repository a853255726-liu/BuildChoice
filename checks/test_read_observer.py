"""Necessary receipt boundaries, range/version checks and INSPECT reuse."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from buildchoice.desktop.decision_store import DecisionStore,message_digest
from buildchoice.desktop.decision_service import DecisionService
from buildchoice.desktop.read_observer import observe
from test_guidance import candidate


class ReadObserverTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory(prefix='buildchoice-read-')
        self.addCleanup(self.temporary.cleanup)
        self.workspace=Path(self.temporary.name).resolve()
        self.settings=self.workspace/'v3.json'
        self.settings.write_text('{"config_version":2,"mode":"pilot","context_ttl_seconds":900}',encoding='utf-8')
        self.store=DecisionStore(self.workspace)
        self.service=DecisionService(self.workspace,'reader',self.settings)
        self.prompt={'hook_event_name':'UserPromptSubmit','cwd':str(self.workspace),'session_id':'read-chat','turn_id':'1','prompt':'Inspect project guidance'}
        self.handle=self.store.observe_hook(self.prompt)['session_handle']
        self.path=self.workspace/'notes.txt';self.path.write_text('first\nactual guidance\nlast\n',encoding='utf-8')

    def event(self,**updates):
        return {**self.prompt,'hook_event_name':'PostToolUse','tool_name':'mcp__filesystem__read_text_file',
            'tool_use_id':uuid.uuid4().hex,'tool_input':{'path':str(self.path)},
            'tool_response':{'content':[{'type':'text','text':self.path.read_text(encoding='utf-8')}]},**updates}

    def receipts(self,session='read-chat'):
        return self.store.ledger.observed_reads(message_digest(session))

    def record(self,event=None):
        result=observe(event or self.event(),self.workspace,self.settings)
        self.assertEqual(result['hookSpecificOutput']['hookEventName'],'PostToolUse')
        return self.receipts()[0]

    def test_full_receipt_reuses_inspect_without_storing_output_and_invalidates_cache(self):
        request={'task_text':self.prompt['prompt'],'phase':'before_implementation','next_step':'Inspect guidance',
            'session_handle':self.handle,'idempotency_key':'before','candidates':[],
            'resources':[{'path':'notes.txt','covers':['Profile visibility']} ]}
        response=self.service.screen(request)
        self.assertEqual(response['screen_status'],'INSPECT')
        event=self.event();receipt=self.record(event)
        self.record(event)
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM sources').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT content FROM sources').fetchone()[0],'')
            self.assertNotIn('actual guidance',db.execute("SELECT data FROM events WHERE kind='TOOL_READ_OBSERVED'").fetchone()[0])
        self.assertTrue(receipt['full_file'])
        self.assertEqual(self.service.status(session_handle=self.handle)['observed_reads'][0]['source_id'],receipt['source_id'])
        with self.assertRaisesRegex(ValueError,'CACHED_SCREEN_STALE'):self.service.screen(request)
        request.update(idempotency_key='after',task_id=response['task_id'])
        self.assertEqual(self.service.screen(request)['screen_status'],'PROCEED')

    def test_partial_shell_receipt_only_supports_returned_quotes_not_full_json(self):
        event=self.event(tool_name='Bash',tool_input={'command':"Get-Content -LiteralPath 'notes.txt' | Select-Object -Skip 1 -First 1"},
            tool_response={'exit_code':0,'output':'actual guidance\n'})
        receipt=self.record(event)
        self.assertEqual((receipt['start_line'],receipt['end_line'],receipt['full_file']),(2,2,False))
        cand=candidate();resources=[{'path':'notes.txt','covers':[cand['field']]}]
        self.assertTrue(self.service.evidence(self.store,cand,resources,message_digest('read-chat'))['unread'])
        cand['evidence_refs']=[{'source_id':receipt['source_id'],'quote':'actual guidance'}]
        proof=self.service.evidence(self.store,cand,resources,message_digest('read-chat'))
        self.assertFalse(proof['invalid']);self.assertFalse(proof['unread'])
        cand['evidence_refs'][0]['quote']='first'
        self.assertTrue(self.service.evidence(self.store,cand,[])['invalid'])
        cand['evidence_refs']=[{'source_id':receipt['source_id'],'pointer':'/chosen'}]
        self.assertTrue(self.service.evidence(self.store,cand,[])['invalid'])
        native=self.event(tool_name='Bash',tool_input={'command':'cat -- notes.txt'},
            tool_response='Chunk ID: synthetic\nWall time: 0.1 seconds\nProcess exited with code 0\nOutput:\n'+self.path.read_text())
        self.assertTrue(self.record(native)['full_file'])

    def test_failed_unknown_script_running_and_truncated_outputs_are_not_reads(self):
        base=self.event(tool_name='Bash',tool_input={'command':'Get-Content notes.txt'})
        cases=[{'tool_response':{'exit_code':1,'output':'first\nactual guidance\nlast\n'}},
            {'tool_response':{'exit_code':0,'output':'first\n... truncated ...'}},
            {'tool_response':{'exit_code':0,'output':'claimed read without content'}},
            {'tool_response':{'exit_code':0,'session_id':7,'output':self.path.read_text()}},
            {'tool_response':{'exit_code':0,'output':self.path.read_text(),'stderr':'failure'}},
            {'tool_input':{'command':"python -c \"print(open('notes.txt').read())\""},'tool_response':{'exit_code':0,'output':self.path.read_text()}},
            {'tool_input':{'command':'cat notes.txt; echo other'},'tool_response':{'exit_code':0,'output':self.path.read_text()}},
            {'tool_name':'apply_patch'}, {'tool_name':'mcp__unknown__read_file'},
            {'tool_name':'mcp__filesystem__read_text_file','tool_input':{'path':str(self.path)},
             'tool_response':{'isError':True,'content':[{'type':'text','text':self.path.read_text()}]}}]
        for update in cases:
            with self.subTest(update=update):self.assertIsNone(observe({**base,**update},self.workspace,self.settings))
        self.assertEqual(self.receipts(),[])

    def test_private_paths_other_chat_and_disabled_observation_do_not_supply_receipts(self):
        private=self.workspace/'.env';private.write_text('secret=hidden',encoding='utf-8')
        event=self.event(tool_input={'path':str(private)},tool_response={'content':[{'type':'text','text':'secret=hidden'}]})
        self.assertIsNone(observe(event,self.workspace,self.settings))
        event=self.event(tool_input={'path':'../outside.txt'})
        self.assertIsNone(observe(event,self.workspace,self.settings))
        self.record()
        self.assertEqual(self.receipts('other-chat'),[])
        self.settings.write_text('{"config_version":2,"mode":"off","context_ttl_seconds":900}',encoding='utf-8')
        self.assertIsNone(observe(self.event(),self.workspace,self.settings))

    def test_changed_file_and_partial_json_cannot_supply_current_constraints(self):
        value={'field':'Profile visibility','chosen':'Private'}
        self.path.write_text(json.dumps(value),encoding='utf-8')
        receipt=self.record()
        cand=candidate();cand['evidence_refs']=[{'source_id':receipt['source_id'],'pointer':'/chosen','relation':'constraint'}]
        self.assertTrue(self.service.evidence(self.store,cand,[])['applicable_constraint'])
        self.path.write_text(json.dumps({**value,'chosen':'Shared'}),encoding='utf-8')
        self.assertFalse(self.receipts()[0]['current'])
        self.assertTrue(self.service.evidence(self.store,cand,[])['invalid'])

    def test_prompt_hook_dispatch_remains_separate_from_tool_observation(self):
        import importlib.util
        from unittest.mock import patch
        root=Path(__file__).resolve().parents[1]
        spec=importlib.util.spec_from_file_location('read_hook',root/'scripts/buildchoice_hook.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with patch.object(module,'WORKSPACE',self.workspace),patch.object(module,'read',return_value={'mode':'prompt'}),\
                patch('buildchoice.desktop.read_observer.read_settings',return_value={'mode':'pilot'}):
            result=module.handle_event(self.event())
            self.assertEqual(result['hookSpecificOutput']['hookEventName'],'PostToolUse')
        with patch.object(module,'read',return_value={'mode':'off'}):
            self.assertIsNone(module.handle_event(self.event()))


if __name__=='__main__':unittest.main()
