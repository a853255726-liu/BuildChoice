"""Real MCP STDIO and real Hook launcher with synthetic host events for product tasks."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch
from test_mcp_notifications import Connection, ROOT
from buildchoice.desktop.product_contracts import input_schema


class ProductMCPTests(unittest.TestCase):
    def setUp(self):
        storage = Path(os.environ.get('BUILDCHOICE_CHECK_ROOT', tempfile.gettempdir())) / ('product-mcp-data-' + uuid.uuid4().hex)
        self.env = patch.dict(os.environ, {'BUILDCHOICE_DATA': str(storage)}); self.env.start(); self.addCleanup(self.env.stop)
        self.c = Connection(profile='core'); self.addCleanup(self.c.close); self.c.update(decision_guidance='试用')
        self.turn = 0; self.hook('核对后保存小票，并审阅产品行为')

    def hook(self, text):
        self.turn += 1; self.text = text
        event = {'hook_event_name': 'UserPromptSubmit', 'cwd': str(self.c.workspace),
            'session_id': 'product-mcp', 'turn_id': str(self.turn), 'prompt': text}
        env = {**self.c.env, 'BUILDCHOICE_SETTINGS': str(self.c.settings)}
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/buildchoice_hook.py')],
            input=json.dumps(event, ensure_ascii=False), text=True, encoding='utf-8', env=env,
            capture_output=True, check=True, timeout=20)
        self.handle = re.search(r'buildchoice-v3-ctx-[A-Za-z0-9_-]+', result.stdout)[0]

    def call(self, tool, action, **extra):
        request = {'action': action, 'session_handle': self.handle}
        if hasattr(self, 'task'): request['task_id'] = self.task
        if action not in ('status', 'document'): request['idempotency_key'] = uuid.uuid4().hex
        request.update(extra)
        result = self.c.send('tools/call', {'name': 'buildchoice_' + tool, 'arguments': {'request': request}})
        self.assertFalse(result.get('isError'), result)
        return result.get('structuredContent') or json.loads(result['content'][0]['text'])

    def test_product_end_to_end_and_dynamic_off_guard(self):
        listed = {t['name']: t for t in self.c.send('tools/list', {})['tools']}
        for tool, kind in [('experience', 'experience'), ('workspace_snapshot', 'snapshot'), ('behavior_review', 'review'), ('batch_decisions', 'batch')]:
            self.assertEqual(listed['buildchoice_' + tool]['inputSchema']['properties']['request'], input_schema(kind))
        self.task = self.call('experience', 'enable', task_text=self.text)['task_id']
        scenario = self.call('experience', 'save', scenarios=[{
            'title': '核对小票后保存', 'trigger': '完成识别', 'action': '用户确认', 'scope': '当前任务', 'expected_revision': 0,
            'behaviors': [{'behavior_id': 'save', 'text': '确认前不保存', 'source': {'kind': 'user',
                'user_message': self.text, 'quote': '核对后保存小票', 'reason': '用户明确的产品要求'}}]}])['scenarios'][0]
        shown = self.call('experience', 'present')
        self.hook('认可刚才展示的小票核对方案')
        self.call('experience', 'acknowledge', presentation_id=shown['id'], scenarios=[{'id': scenario['id'], 'revision': 1, 'status': 'accepted'}],
            user_message=self.text, quote=self.text, reason='用户认可具体展示版本')
        expected = self.call('experience', 'freeze')
        (self.c.workspace / 'app.py').write_text('save_after_confirmation = True\n', encoding='utf-8')
        baseline = self.call('workspace_snapshot', 'capture', expectation_id=expected['id'], scopes=['app.py'])
        (self.c.workspace / 'app.py').write_text('save_after_confirmation = False\n', encoding='utf-8')
        comp = self.call('workspace_snapshot', 'compare', baseline_id=baseline['id'])
        self.assertIn('-save_after_confirmation = True', comp['changes'][0]['diff'])
        review = self.call('behavior_review', 'create', comparison_id=comp['id'], findings=[{
            'finding_id': 'saving', 'scenario': {'id': scenario['id'], 'revision': 1}, 'behavior_ids': ['save'],
            'judgment': 'possibly_deviates', 'summary': '确认之前可能已经保存', 'importance': 'high',
            'evidence': [{'kind': 'file', 'path': 'app.py', 'quote': 'False', 'note': '当前保存规则'}],
            'limits': '仅检查代码，尚未实际运行'}])
        self.hook('修正保存行为，保持核对后保存的要求')
        self.call('behavior_review', 'feedback', review_id=review['id'], feedback=[{
            'finding_id': 'saving', 'action': 'fix', 'note': '保留原预期', 'expected_feedback_revision': 0}],
            user_message=self.text, quote=self.text, reason='用户要求修正实现')
        doc = self.call('experience', 'document')
        self.assertEqual(doc['document']['status'], 'synchronized'); self.assertIn('可能偏离预期', doc['markdown'])
        self.c.update(mode='完全关闭')
        for tool in ('experience', 'workspace_snapshot', 'behavior_review', 'batch_decisions'):
            result = self.c.send('tools/call', {'name': 'buildchoice_' + tool, 'arguments': {'request': {
                'action': 'status', 'session_handle': self.handle, 'task_id': self.task}}})
            self.assertTrue(result.get('isError'))
        self.assertEqual(len(self.c.tools()), 4)


if __name__ == '__main__': unittest.main()
