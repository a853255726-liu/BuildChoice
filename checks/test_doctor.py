import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import uuid
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from buildchoice.desktop.doctor import diagnose,_run_json,probe_host


class DoctorTests(unittest.TestCase):
    def setUp(self):
        import os
        self.workspace=Path(os.environ.get('BUILDCHOICE_CHECK_ROOT',tempfile.gettempdir()))/('buildchoice-doctor-'+uuid.uuid4().hex)
        self.workspace.mkdir()
        self.home=self.workspace/'installation';self.home.mkdir()
        self.deps={'version':[3,13,2],'modules':{'mcp':True,'jsonschema':True,'openai_codex':True},'packages':{}}

    def bind(self):
        (self.home/'binding.json').write_text(json.dumps({'binding_version':1,'workspace':str(self.workspace.resolve()),
            'runtime_root':str(ROOT),'python':sys.executable}),encoding='utf-8')

    def test_missing_binding_does_not_initialize_or_trust_anything(self):
        with patch('buildchoice.desktop.doctor.probe_python',return_value=self.deps),patch('buildchoice.desktop.doctor.probe_mcp',return_value={'server':'buildchoice','tools':['buildchoice_decision_status']}):
            result=diagnose(self.home,self.workspace)
        self.assertEqual(result['overall'],'needs_attention')
        self.assertFalse((self.home/'binding.json').exists())
        self.assertFalse((self.workspace/'.buildchoice_audit').exists())
        self.assertTrue(result['read_only'])
        self.assertFalse(result['hook_trust_modified'])

    def test_local_checks_do_not_claim_host_health(self):
        self.bind()
        before=(self.home/'binding.json').read_bytes()
        with patch('buildchoice.desktop.doctor.probe_python',return_value=self.deps),patch('buildchoice.desktop.doctor.probe_mcp',return_value={'server':'buildchoice','tools':['buildchoice_decision_status']}):
            result=diagnose(self.home)
        checks={c['name']:c for c in result['checks']}
        self.assertEqual(checks['local_mcp']['status'],'pass')
        self.assertEqual(checks['hook_trust']['status'],'unknown')
        self.assertEqual(checks['host_plugin']['status'],'unknown')
        self.assertEqual(result['overall'],'unverified')
        self.assertEqual((self.home/'binding.json').read_bytes(),before)

    def test_different_workspace_is_rejected(self):
        self.bind()
        with patch('buildchoice.desktop.doctor.probe_python',return_value=self.deps),patch('buildchoice.desktop.doctor.probe_mcp') as probe:
            result=diagnose(self.home,ROOT)
        self.assertFalse(probe.called)
        self.assertEqual(next(c['status'] for c in result['checks'] if c['name']=='workspace'),'fail')

    def test_missing_dependencies_do_not_start_mcp(self):
        self.bind()
        deps={**self.deps,'modules':{'mcp':False}}
        with patch('buildchoice.desktop.doctor.probe_python',return_value=deps),patch('buildchoice.desktop.doctor.probe_mcp') as probe:
            result=diagnose(self.home)
        self.assertFalse(probe.called)
        self.assertEqual(result['overall'],'needs_attention')

    def test_host_timeout_stays_unknown(self):
        self.bind()
        with patch('buildchoice.desktop.doctor.probe_python',return_value=self.deps),patch('buildchoice.desktop.doctor.probe_mcp',return_value={'server':'buildchoice','tools':['buildchoice_decision_status']}),patch('buildchoice.desktop.doctor._run_json',side_effect=ValueError('unavailable')):
            result=diagnose(self.home,host=True)
        self.assertEqual(result['overall'],'unverified')
        self.assertEqual(next(c['status'] for c in result['checks'] if c['name']=='hook_trust'),'unknown')

    def test_host_probe_matches_sdk_event_enum_and_excludes_unrelated_hooks(self):
        from openai_codex.generated.v2_all import HookEventName
        plugin=SimpleNamespace(summary=SimpleNamespace(id='buildchoice@buildchoice-local',installed=True,enabled=True),
            mcp_servers=['buildchoice'],hooks=[SimpleNamespace(key='prompt-key',event_name=HookEventName.user_prompt_submit)])
        def hook(key='prompt-key',plugin_id=plugin.summary.id,event=HookEventName.user_prompt_submit):
            return SimpleNamespace(root=SimpleNamespace(key=key,plugin_id=plugin_id,event_name=event,
                enabled=True,trust_status=SimpleNamespace(value='trusted')))
        listing=SimpleNamespace(data=[SimpleNamespace(cwd=str(self.workspace),hooks=[hook(),
            hook(key='other'),hook(plugin_id='other-plugin'),hook(event=HookEventName.stop)]),
            SimpleNamespace(cwd=str(ROOT),hooks=[hook()])])
        with patch('openai_codex.client.CodexClient') as factory:
            client=factory.return_value.__enter__.return_value
            client.request.side_effect=[SimpleNamespace(plugin=plugin),listing]
            result=probe_host(self.workspace,ROOT/'.claude-plugin/marketplace.json')
        self.assertEqual(result['hooks'],[{'enabled':True,'trust_status':'trusted'}])
        self.assertEqual([call.args[0] for call in client.request.call_args_list],['plugin/read','hooks/list'])

    def test_diagnosis_reports_trusted_host_without_claiming_chat_callback(self):
        self.bind()
        observed={'installed':True,'enabled':True,'server_declared':True,
                  'hooks':[{'enabled':True,'trust_status':'trusted'}]}
        with patch('buildchoice.desktop.doctor.probe_python',return_value=self.deps),patch('buildchoice.desktop.doctor.probe_mcp',return_value={'server':'buildchoice','tools':['buildchoice_decision_status']}),patch('buildchoice.desktop.doctor._run_json',return_value=observed):
            result=diagnose(self.home,host=True)
        self.assertEqual(result['overall'],'pass')
        self.assertEqual(next(c['status'] for c in result['checks'] if c['name']=='hook_trust'),'pass')
        self.assertFalse(result['hook_trust_modified'])
        self.assertIn('回调',result['scope'])

    def test_probe_timeout_is_bounded(self):
        import subprocess
        import time
        start=time.monotonic()
        with self.assertRaises(subprocess.TimeoutExpired):
            _run_json([sys.executable,'-c','import time; time.sleep(20)'],1)
        self.assertLess(time.monotonic()-start,8)


if __name__=='__main__':unittest.main()
