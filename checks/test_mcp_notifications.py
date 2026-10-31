"""Observe real list-changed messages; manual tools/list alone is not a refresh test."""
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import unittest
import uuid

ROOT=Path(__file__).resolve().parents[1]


class Connection:
    def __init__(self,native=True):
        self.workspace=Path(os.environ.get('BUILDCHOICE_CHECK_ROOT',tempfile.gettempdir()))/('buildchoice-notify-'+uuid.uuid4().hex)
        self.workspace.mkdir()
        self.settings=self.workspace/'settings.json'
        self.settings.write_text('{"config_version":1,"mode":"prompt"}',encoding='utf-8')
        self.decisions=self.workspace/'decision_v3.json'
        self.decisions.write_text('{"config_version":2,"mode":"off","context_ttl_seconds":900}',encoding='utf-8')
        self.env={**os.environ,'BUILDCHOICE_WORKSPACE':str(self.workspace),
            'BUILDCHOICE_V3_SETTINGS':str(self.decisions),'PYTHONUTF8':'1','PYTHONIOENCODING':'utf-8'}
        self.log=(self.workspace/'server.log').open('w',encoding='utf-8')
        args=[sys.executable,str(ROOT/'scripts/buildchoice_mcp.py'),'--settings',str(self.settings)]
        if native:args.append('--native-settings')
        self.process=subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.log,
            text=True,encoding='utf-8',env=self.env)
        self.messages=queue.Queue();self.notifications=[];self.ident=0
        def read():
            for line in self.process.stdout:self.messages.put(json.loads(line))
            self.messages.put({'closed':True})
        self.reader=threading.Thread(target=read,daemon=True);self.reader.start()
        self.init=self.send('initialize',{'protocolVersion':'2024-11-05','capabilities':{},
            'clientInfo':{'name':'notification-regression','version':'1'}})
        self.process.stdin.write('{"jsonrpc":"2.0","method":"notifications/initialized"}\n')
        self.process.stdin.flush()

    def send(self,method,params):
        self.ident+=1
        self.process.stdin.write(json.dumps({'jsonrpc':'2.0','id':self.ident,'method':method,'params':params},ensure_ascii=False)+'\n')
        self.process.stdin.flush()
        while True:
            message=self.messages.get(timeout=10)
            if message.get('closed'):raise AssertionError('MCP closed; inspect '+str(self.workspace))
            if message.get('id')==self.ident:
                if 'error' in message:raise AssertionError(message)
                return message['result']
            self.notifications.append(message)

    def tools(self):return {tool['name'] for tool in self.send('tools/list',{})['tools']}

    def update(self,**values):
        result=self.send('tools/call',{'name':'buildchoice_settings_update','arguments':{'set':values}})
        if result.get('isError'):raise AssertionError(result)

    def change_count(self):
        return sum(n.get('method')=='notifications/tools/list_changed' for n in self.notifications)

    def await_change(self):
        # External CLI changes are detected without sending any MCP request.
        message=self.messages.get(timeout=5)
        if message.get('method')!='notifications/tools/list_changed':raise AssertionError(message)
        self.notifications.append(message)

    def cli(self,script,*args):
        subprocess.run([sys.executable,str(ROOT/'scripts'/script),*args],env=self.env,
            stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,check=True,timeout=10)

    def close(self):
        self.process.stdin.close()
        try:self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:self.process.kill();self.process.wait(timeout=5)
        self.reader.join(timeout=2)
        self.process.stdout.close();self.log.close()


class ToolNotificationTests(unittest.TestCase):
    def connect(self,native=True):
        connection=Connection(native)
        self.addCleanup(connection.close)
        return connection

    def test_native_changes_refresh_tools_and_disabled_calls_stay_blocked(self):
        c=self.connect()
        self.assertTrue(c.init['capabilities']['tools']['listChanged'])
        self.assertEqual(len(c.tools()),8)
        c.update(decision_guidance='试用')
        self.assertEqual(c.change_count(),1)
        self.assertEqual(len(c.tools()),14)
        c.update(decision_guidance='试用')
        self.assertEqual(c.change_count(),1)
        c.update(mode='完全关闭')
        self.assertEqual(c.change_count(),2)
        self.assertEqual(len(c.tools()),4)
        c.update(decision_guidance='关闭')  # Hidden tools did not change.
        self.assertEqual(c.change_count(),2)
        blocked=c.send('tools/call',{'name':'buildchoice_audit_start','arguments':{'title':'Blocked','task':'No write'}})
        self.assertTrue(blocked.get('isError'))
        self.assertFalse((c.workspace/'.buildchoice_audit').exists())
        c.update(mode='Prompt 优先')
        self.assertEqual(c.change_count(),3)
        self.assertEqual(len(c.tools()),8)
        c.update(decision_guidance='试用')
        self.assertEqual(c.change_count(),4)
        self.assertIn('buildchoice_card_activate',c.tools())

    def test_cli_changes_notify_without_manual_polling_in_both_server_modes(self):
        for native in (True,False):
            with self.subTest(native=native):
                c=self.connect(native)
                self.assertTrue(c.init['capabilities']['tools']['listChanged'])
                self.assertEqual(len(c.tools()),8 if native else 5)
                c.cli('buildchoice_decisions.py','pilot')
                c.await_change()
                self.assertEqual(len(c.tools()),14 if native else 11)
                c.cli('buildchoice_settings.py','off','--config',str(c.settings))
                c.await_change()
                self.assertEqual(len(c.tools()),4 if native else 1)
                c.cli('buildchoice_settings.py','prompt','--config',str(c.settings))
                c.await_change()
                self.assertEqual(len(c.tools()),14 if native else 11)
                c.cli('buildchoice_decisions.py','off')
                c.await_change()
                self.assertEqual(len(c.tools()),8 if native else 5)


if __name__=='__main__':unittest.main()
