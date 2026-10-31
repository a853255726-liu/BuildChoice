"""Same real-browser suite for correct, early-save and ignored-edit variants."""
import json
import os
from pathlib import Path
import unittest
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]


class ReceiptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright=sync_playwright().start()
        cls.browser=cls.playwright.chromium.launch(headless=True,
            chromium_sandbox=os.environ.get('BUILDCHOICE_TEST_BROWSER_NO_SANDBOX') != '1',
            executable_path=os.environ.get('BUILDCHOICE_TEST_BROWSER'),timeout=15000)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close();cls.playwright.stop()

    def setUp(self):
        self.context=self.browser.new_context()
        self.context.route('**/*',lambda route:route.continue_() if route.request.url.startswith('file:') else route.abort())
        fixture=json.loads((ROOT/'receipt.json').read_text(encoding='utf-8'))
        config=json.loads((ROOT/'config.json').read_text(encoding='utf-8'))
        self.context.add_init_script('window.receiptFixture='+json.dumps(fixture)+'; window.receiptConfig='+json.dumps(config)+';')
        self.page=self.context.new_page();self.page.set_default_timeout(3000)
        self.page.goto((ROOT/'index.html').as_uri())
        self.page.get_by_role('button',name='识别示例小票').click()

    def tearDown(self):self.context.close()
    def ledger(self):return self.page.evaluate("JSON.parse(localStorage.getItem('formal-ledger') || '[]')")

    def test_display(self):
        self.assertTrue(self.page.get_by_role('heading',name='核对识别结果').is_visible())
        self.assertEqual(self.page.get_by_label('金额').input_value(),'38.5')
        self.assertEqual(self.page.get_by_label('日期').input_value(),'2026-10-30')
        self.assertEqual(self.page.get_by_label('类别').input_value(),'餐饮')

    def test_edit(self):
        self.page.get_by_label('金额').fill('42.75')
        self.page.get_by_label('日期').fill('2026-10-29')
        self.page.get_by_label('类别').fill('日用品')
        self.page.get_by_role('button',name='确认并正式保存').click()
        self.assertEqual(self.ledger()[-1],{'amount':42.75,'date':'2026-10-29','category':'日用品'})

    def test_before_confirm(self):
        self.assertEqual(self.ledger(),[])
        self.page.get_by_label('金额').fill('80')
        self.assertEqual(self.ledger(),[])
        self.page.get_by_role('button',name='确认并正式保存').click()
        self.assertEqual(len(self.ledger()),1)

    def test_cancel(self):
        self.page.get_by_label('类别').fill('其他')
        self.page.get_by_role('button',name='取消',exact=True).click()
        self.assertEqual(self.ledger(),[])
