"""Installation isolation, project dispatch and actual private Hook launch."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

ROOT=Path(__file__).resolve().parents[1]
PACKAGE=ROOT/'plugins/buildchoice'
sys.path.insert(0,str(PACKAGE/'scripts'))
sys.path.insert(0,str(PACKAGE))
import launch
from installation import configure_runtime
spec=importlib.util.spec_from_file_location('isolated_buildchoice_setup',PACKAGE/'setup.py')
setup=importlib.util.module_from_spec(spec);spec.loader.exec_module(setup)


class ProjectInstallationTests(unittest.TestCase):
    def setUp(self):
        base=Path(os.environ.get('BUILDCHOICE_CHECK_ROOT',tempfile.gettempdir())).resolve()
        self.root=base/('buildchoice-install-'+uuid.uuid4().hex);self.root.mkdir()
        self.home=self.root/'home';self.a=self.root/'project-a';self.b=self.root/'project-b'
        self.a.mkdir();self.b.mkdir()

    def initialize(self,path,mode='pilot'):
        with patch.object(setup,'prepare_python',return_value=Path(sys.executable)):
            return setup.initialize(path,runtime_root=ROOT,home=self.home,decision_mode=mode)

    def test_initialize_does_not_change_source_configs_and_private_copy_is_used(self):
        protected=[p for p in PACKAGE.rglob('*') if p.is_file() and '__pycache__' not in p.parts]
        protected.append(ROOT/'.claude-plugin/marketplace.json')
        before={p:hashlib.sha256(p.read_bytes()).hexdigest() for p in protected}
        value=self.initialize(self.a)
        self.assertEqual(before,{p:hashlib.sha256(p.read_bytes()).hexdigest() for p in protected})
        private=Path(value['plugin_root'])
        self.assertTrue(private.is_relative_to(self.home/'installations'))
        config=json.loads((private/'.mcp.json').read_text())['mcpServers']['buildchoice']
        self.assertEqual(config['args'][0],str(private/'scripts/launch.py'))
        self.assertNotIn('cwd',config)
        self.assertEqual(config['args'][-1],str(self.home))
        with self.assertRaises(ValueError):configure_runtime(PACKAGE,value,self.home)

    def test_multiple_projects_persist_and_switch_without_overwriting_settings(self):
        a=self.initialize(self.a,'pilot');b=self.initialize(self.b,'off')
        self.assertEqual(len(launch.projects(self.home)['projects']),2)
        selected=launch.select_project(self.a,self.home)
        self.assertEqual(selected['workspace'],str(self.a))
        self.assertEqual(launch.projects(self.home)['active_project'],a['project_id'])
        self.assertEqual(json.loads((Path(a['profile_home'])/'configs/decision_v3.json').read_text())['mode'],'pilot')
        self.assertEqual(json.loads((Path(b['profile_home'])/'configs/decision_v3.json').read_text())['mode'],'off')
        child=self.b/'src';child.mkdir()
        self.assertEqual(launch.binding(self.home,child)['workspace'],str(self.b))
        with self.assertRaises(ValueError):launch.binding(self.home,self.root/'unknown')

    def test_parent_and_nested_projects_choose_the_most_specific_binding(self):
        self.initialize(self.root);self.initialize(self.a)
        child=self.a/'child';child.mkdir()
        self.assertEqual(launch.binding(self.home,child)['workspace'],str(self.a))

    def test_legacy_binding_is_preserved_when_registering_a_second_project(self):
        self.home.mkdir()
        old={'binding_version':1,'workspace':str(self.a),'runtime_root':str(ROOT),'python':sys.executable}
        launch.write_json(self.home/'binding.json',old)
        self.assertEqual(launch.binding(self.home)['workspace'],str(self.a))
        self.initialize(self.b)
        self.assertEqual(len(launch.projects(self.home)['projects']),2)
        self.assertEqual(launch.binding(self.home,self.a)['workspace'],str(self.a))

    def test_data_home_inside_source_is_rejected_before_writing(self):
        target=PACKAGE/('forbidden-'+uuid.uuid4().hex)
        with self.assertRaises(ValueError):
            setup.initialize(self.a,runtime_root=ROOT,home=target,reuse_python=sys.executable)
        self.assertFalse(target.exists())

    def test_persisted_path_aliases_match_the_resolved_workspace(self):
        from buildchoice.desktop.project_settings import selected_binding
        self.initialize(self.a)
        registry=launch.projects(self.home)
        ident=launch.project_id(self.a)
        alias=str(self.a/'..'/'project-a')
        registry['projects'][ident]['workspace']=alias
        launch.write_json(self.home/'projects.json',registry)
        self.assertEqual(launch.binding(self.home,self.a)['workspace'],alias)
        self.assertEqual(selected_binding(self.home,self.a)['workspace'],alias)

    def test_private_hook_dispatches_by_event_project_not_active_project(self):
        a=self.initialize(self.a,'pilot');self.initialize(self.b,'off')
        command=[sys.executable,str(Path(a['plugin_root'])/'scripts/buildchoice_plugin_hook.py'),
                 '--data-home',str(self.home)]
        event={'hook_event_name':'UserPromptSubmit','cwd':str(self.a),'session_id':'project-hook','turn_id':'1','prompt':'给项目加登录'}
        completed=subprocess.run(command,input=json.dumps(event),capture_output=True,text=True,
            encoding='utf-8',cwd=self.b,check=True,timeout=20)
        self.assertIn('buildchoice-v3-ctx-',completed.stdout)
        self.assertTrue((self.a/'.buildchoice_audit/ledger.sqlite3').exists())
        self.assertFalse((self.b/'.buildchoice_audit').exists())

    def test_cli_changes_only_the_selected_project_settings(self):
        a=self.initialize(self.a,'pilot');b=self.initialize(self.b,'pilot')
        env={key:value for key,value in os.environ.items() if key not in ('BUILDCHOICE_V3_SETTINGS','BUILDCHOICE_SETTINGS')}
        completed=subprocess.run([sys.executable,str(ROOT/'scripts/buildchoice_decisions.py'),'off',
            '--workspace',str(self.a),'--data-home',str(self.home)],env=env,
            capture_output=True,text=True,encoding='utf-8',check=True,timeout=20)
        self.assertEqual(json.loads(completed.stdout)['mode'],'off')
        self.assertEqual(json.loads((Path(b['profile_home'])/'configs/decision_v3.json').read_text())['mode'],'pilot')
        self.assertEqual(json.loads((Path(a['profile_home'])/'configs/decision_v3.json').read_text())['mode'],'off')

    def test_private_mcp_launcher_uses_the_current_project_profile(self):
        import queue
        import threading
        a=self.initialize(self.a,'pilot');self.initialize(self.b,'off')
        config=json.loads((Path(a['plugin_root'])/'.mcp.json').read_text())['mcpServers']['buildchoice']
        for directory,count in ((self.a,15),(self.b,8)):
            env={key:value for key,value in os.environ.items() if key not in ('BUILDCHOICE_WORKSPACE','BUILDCHOICE_V3_SETTINGS','BUILDCHOICE_SETTINGS')}
            process=subprocess.Popen([config['command'],*config['args']],cwd=directory,env=env,
                stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf-8')
            replies=queue.Queue()
            def collect(stream=process.stdout):
                for line in stream:replies.put(json.loads(line))
            threading.Thread(target=collect,daemon=True).start()
            def send(ident,method,params):
                process.stdin.write(json.dumps({'jsonrpc':'2.0','id':ident,'method':method,'params':params})+'\n');process.stdin.flush()
                while True:
                    reply=replies.get(timeout=20)
                    if reply.get('id')==ident:return reply['result']
            try:
                send(1,'initialize',{'protocolVersion':'2024-11-05','capabilities':{},'clientInfo':{'name':'profile-check','version':'1'}})
                process.stdin.write('{"jsonrpc":"2.0","method":"notifications/initialized"}\n');process.stdin.flush()
                self.assertEqual(len(send(2,'tools/list',{})['tools']),count)
            finally:
                process.stdin.close()
                try:process.wait(timeout=5)
                except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
                process.stdout.close()
