"""Regression fixtures for native-answer source gaps; never real user confirmations."""
from copy import deepcopy
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from buildchoice.desktop.decision_service import DecisionService
from buildchoice.desktop.decision_store import DecisionStore
from buildchoice.desktop.conversation_ui import decision_presentation
from buildchoice.desktop.choice_reply import parse_choice
from buildchoice.desktop.reply_binding import ReplyBindingError, recording_result
from buildchoice.desktop.hook_diagnostics import record_failure, MAX_BYTES
from test_guidance import candidate
from test_mcp_notifications import Connection


class ReplyBindingTests(unittest.TestCase):
    def setUp(self):
        base = Path(os.environ.get('BUILDCHOICE_CHECK_ROOT', tempfile.gettempdir()))
        self.folder = self.enterContext(tempfile.TemporaryDirectory(prefix='binding-', dir=base))
        self.workspace = Path(self.folder)
        settings = self.workspace / 'v3.json'
        settings.write_text(json.dumps({'config_version': 2, 'mode': 'pilot',
                                       'context_ttl_seconds': 900}), encoding='utf-8')
        self.service = DecisionService(self.workspace, 'binding-fixture', settings)
        self.store = DecisionStore(self.workspace)
        self.event = {'hook_event_name': 'UserPromptSubmit', 'cwd': str(self.workspace),
                      'session_id': 'synthetic-chat', 'turn_id': '1', 'prompt': '实现虚构记录界面'}
        self.handle = self.store.observe_hook(self.event)['session_handle']
        self.screen = self.service.screen({'task_text': self.event['prompt'], 'next_step': '实现界面',
            'candidates': [candidate()], 'session_handle': self.handle, 'idempotency_key': 'screen'})
        self.item = self.screen['decisions'][0]
        self.card = self.service.activate(self.screen['task_id'], self.item['decision_id'], 1,
                                          'activate', self.handle)['card']
        self.option = decision_presentation([{'decision_id': self.item['decision_id'],
            'revision': 1, 'card': self.card}])['native_request']['questions'][0]['options'][0]

    def envelope(self, **changes):
        item = {'questionItemId': json.dumps(['request_user_input_async', 'call_fixture', 0]),
                'question': self.card['question'], 'answer': self.option}
        item.update(changes)
        return '<send_user_message_question_reply>\n' + json.dumps([item], ensure_ascii=False) + '\n</send_user_message_question_reply>'

    def count(self):
        with self.store.connect() as db:
            return db.execute('SELECT count(*) FROM decision_v3_confirmations').fetchone()[0]

    def interpret(self, quote=None, handle=None):
        return self.service.interpret_reply(self.screen['task_id'], self.item['decision_id'],
            1, 'A', quote or self.option, 'Synthetic source-bound interpretation', handle or self.handle)

    def test_missing_async_hook_is_visible_before_recording(self):
        context = self.service.context_bundle(self.handle)
        self.assertEqual(context['reply_binding']['status'], 'awaiting_new_hook_message')
        self.assertFalse(context['reply_binding']['can_interpret_reply'])
        self.assertNotIn('pending_reply', context)
        result = recording_result(self.interpret)
        self.assertEqual(result['code'], 'NO_OBSERVED_REPLY')
        self.assertFalse(result['recorded'])
        self.assertFalse(result['recovery']['retry_with_same_handle'])
        self.assertFalse(result['recovery']['switch_recording_interface'])
        self.assertEqual(self.count(), 0)

    def test_switching_to_instruction_does_not_bypass_old_message_hash(self):
        result = recording_result(lambda: self.service.record_instruction({
            'session_handle': self.handle, 'decision_id': self.item['decision_id'],
            'expected_revision': 1, 'choice_id': 'A', 'idempotency_key': 'unsafe-fallback',
            'user_message': self.envelope(), 'quote': self.option, 'reason': 'Synthetic UI reply'}))
        self.assertEqual(result['code'], 'USER_MESSAGE_CONTEXT_MISMATCH')
        self.assertFalse(result['recorded'])
        self.assertEqual(self.count(), 0)

    def test_trusted_native_reply_records_exact_option_once(self):
        text = self.envelope()
        reply = self.store.observe_hook({**self.event, 'turn_id': '2', 'prompt': text})
        replay = self.store.observe_hook({**self.event, 'turn_id': '2', 'prompt': text})
        self.assertEqual(reply, replay)
        self.assertEqual(reply['confirmation_status'], 'user_message_observed')
        self.assertEqual(reply['reply_method'], 'explicit_native_option_expression')
        context = self.service.context_bundle(reply['session_handle'])
        self.assertEqual(context['reply_binding']['status'], 'already_recorded')
        self.assertFalse(context['reply_binding']['can_interpret_reply'])
        self.assertEqual(self.count(), 1)

    def test_custom_answer_uses_fresh_source_and_explicit_interpretation(self):
        answer = '采用第一个方案，并保留原有数据范围'
        reply = self.store.observe_hook({**self.event, 'turn_id': '2',
                                         'prompt': self.envelope(answer=answer)})
        self.assertEqual(reply['confirmation_status'], 'awaiting_user')
        context = self.service.context_bundle(reply['session_handle'])
        self.assertTrue(context['reply_binding']['can_interpret_reply'])
        self.assertEqual(self.count(), 0)
        recorded = self.interpret(answer, reply['session_handle'])
        self.assertEqual(recorded['confirmation']['provenance'], 'llm_interpreted_user_reply')
        self.assertFalse(recorded['semantic_verified_by_program'])
        self.assertEqual(self.count(), 1)

    def test_native_question_full_answer_and_shape_must_match(self):
        cases = [self.envelope(question='其他问题'), self.envelope(answer='A'),
                 self.envelope(answer=self.option + '，但新增条件'),
                 self.envelope(questionItemId=json.dumps(['request_user_input_async', 'call_fixture', 1])),
                 self.envelope(questionItemId=json.dumps(['request_user_input_async', 'call_fixture', False])),
                 self.envelope(questionItemId=json.dumps(['other_tool', 'call_fixture', 0])),
                 self.envelope(answer=['A']), self.envelope(extra='unexpected')]
        for text in cases:
            with self.subTest(text=text):
                self.assertIsNone(parse_choice(text, self.card))
        self.assertIsNone(parse_choice(self.envelope().replace('"answer":', '"answer":"B","answer":'), self.card))
        self.assertIsNone(parse_choice('Quoted example: ' + self.envelope(), self.card))
        self.assertIsNone(parse_choice(self.envelope() + ' extra instructions', self.card))
        self.assertEqual(self.count(), 0)

    def test_changed_card_or_batch_never_uses_single_native_parser(self):
        changed = deepcopy(self.card)
        changed['options'][0]['tradeoff'] += ' changed behavior'
        self.assertIsNone(parse_choice(self.envelope(), changed))
        body = json.loads(self.envelope().split('\n')[1])
        self.assertIsNone(parse_choice('<send_user_message_question_reply>\n' +
            json.dumps(body + body) + '\n</send_user_message_question_reply>', self.card))

    def test_expired_card_never_accepts_late_native_reply(self):
        with self.store.connect() as db:
            db.execute('UPDATE decision_v3_active SET expires=?', (time.time() - 1,))
        reply = self.store.observe_hook({**self.event, 'turn_id': '2', 'prompt': self.envelope()})
        self.assertEqual(reply['confirmation_status'], 'not_confirmed')
        self.assertEqual(self.count(), 0)

    def test_expired_context_has_recovery_and_source_check_still_rejects(self):
        with self.store.connect() as db:
            db.execute('UPDATE decision_v3_contexts SET expires=?', (time.time() - 1,))
        result = recording_result(self.interpret)
        self.assertEqual(result['code'], 'HOOK_CONTEXT_UNAVAILABLE')
        self.assertFalse(result['recorded'])
        self.assertEqual(self.count(), 0)

    def test_unrelated_programming_errors_are_not_converted_to_success(self):
        with self.assertRaisesRegex(ValueError, 'invalid schema'):
            recording_result(lambda: (_ for _ in ()).throw(ValueError('invalid schema')))


class HookDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        base = Path(os.environ.get('BUILDCHOICE_CHECK_ROOT', tempfile.gettempdir()))
        self.folder = self.enterContext(tempfile.TemporaryDirectory(prefix='hook-diagnostics-', dir=base))
        self.workspace = Path(self.folder)
        self.enterContext(patch.dict(os.environ, BUILDCHOICE_DATA=str(self.workspace / 'data')))
        spec = importlib.util.spec_from_file_location('binding_hook_fixture', ROOT / 'scripts/buildchoice_hook.py')
        self.hook = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.hook)

    def test_diagnostics_omit_message_path_and_identifiers_and_rotate(self):
        event = {'hook_event_name': 'UserPromptSubmit', 'prompt': 'PRIVATE_PROMPT',
                 'session_id': 'PRIVATE_ID', 'cwd': 'PRIVATE_PATH'}
        output = io.StringIO()
        with patch('sys.stderr', output):
            record_failure(ValueError('PRIVATE_EXCEPTION'), self.workspace, event, 'decision_prompt')
        path = next((self.workspace / 'data').rglob('hooks.jsonl'))
        entry = json.loads(path.read_text())
        self.assertEqual(entry['stage'], 'decision_prompt')
        self.assertEqual(entry['error_type'], 'ValueError')
        for secret in ('PRIVATE_PROMPT', 'PRIVATE_ID', 'PRIVATE_PATH', 'PRIVATE_EXCEPTION'):
            self.assertNotIn(secret, path.read_text() + output.getvalue())
        path.write_text('x' * MAX_BYTES)
        with patch('sys.stderr', io.StringIO()):
            record_failure(OSError('private'), self.workspace, event)
        self.assertLess(path.stat().st_size, MAX_BYTES)
        self.assertTrue(path.with_suffix('.jsonl.1').exists())

    def test_logging_failure_is_nonblocking(self):
        with patch('pathlib.Path.mkdir', side_effect=PermissionError('private')), patch('sys.stderr', io.StringIO()):
            record_failure(ValueError('private'), self.workspace)

    def test_policy_failure_does_not_prevent_message_identity_hook(self):
        expected = {'hookSpecificOutput': {'hookEventName': 'UserPromptSubmit', 'additionalContext': 'NEW_HANDLE'}}
        with patch.object(self.hook, 'read', return_value={'mode': 'prompt'}), \
             patch('buildchoice.desktop.prompt_policy.handle_prompt', side_effect=ValueError('private')), \
             patch('buildchoice.desktop.decision_hook.handle_prompt', return_value=expected) as decision, \
             patch.object(self.hook, 'record_failure') as diagnostic:
            result = self.hook.handle_event({'hook_event_name': 'UserPromptSubmit'})
        self.assertEqual(result, expected)
        decision.assert_called_once()
        self.assertEqual(diagnostic.call_args.args[-1], 'prompt_policy')

    def test_decision_hook_failure_gives_actionable_context(self):
        with patch.object(self.hook, 'read', return_value={'mode': 'prompt'}), \
             patch('buildchoice.desktop.prompt_policy.handle_prompt', return_value=None), \
             patch('buildchoice.desktop.decision_hook.handle_prompt', side_effect=ValueError('private')), \
             patch.object(self.hook, 'record_failure'):
            result = self.hook.handle_event({'hook_event_name': 'UserPromptSubmit'})
        message = result['hookSpecificOutput']['additionalContext']
        self.assertIn('不要复用旧句柄', message)
        self.assertNotIn('private', message)


class ReplyBindingMCPTests(unittest.TestCase):
    def test_real_stdio_returns_unbound_receipt_then_accepts_fresh_native_message(self):
        connection = Connection(profile='core')
        self.addCleanup(connection.close)
        connection.update(decision_guidance='试用')

        def call(name, arguments):
            response = connection.send('tools/call', {'name': name, 'arguments': arguments})
            self.assertFalse(response.get('isError'), response)
            return response['structuredContent']

        store = DecisionStore(connection.workspace)
        event = {'hook_event_name': 'UserPromptSubmit', 'cwd': str(connection.workspace),
                 'session_id': 'synthetic-stdio', 'turn_id': '1', 'prompt': '实现虚构记录界面'}
        handle = store.observe_hook(event)['session_handle']
        value = candidate()
        value['content_version'] = 'decision-content.v1'
        for option in value['options']:
            option['risk_assessment'] = {'status': 'not_assessed', 'reason': 'Synthetic transport fixture only.'}
        screened = call('buildchoice_screen_candidates', {'request': {
            'session_handle': handle, 'task_text': event['prompt'], 'next_step': '实现界面',
            'candidates': [value], 'idempotency_key': 'screen'}})
        item = screened['decisions'][0]
        active = call('buildchoice_card_activate', {'task_id': screened['task_id'],
            'decision_id': item['decision_id'], 'revision': 1, 'idempotency_key': 'activate',
            'session_handle': handle})
        question = active['presentation']['native_request']['questions'][0]
        option_text = question['options'][0]
        context = call('buildchoice_context', {'session_handle': handle})
        self.assertFalse(context['reply_binding']['can_interpret_reply'])
        gap = call('buildchoice_reply_interpret', {'task_id': screened['task_id'],
            'decision_id': item['decision_id'], 'revision': 1, 'choice_id': 'A',
            'quote': option_text, 'reason': 'Synthetic same-turn callback', 'session_handle': handle})
        self.assertEqual((gap['status'], gap['recorded'], gap['code']),
                         ('unbound', False, 'NO_OBSERVED_REPLY'))
        envelope = '<send_user_message_question_reply>\n' + json.dumps([{
            'questionItemId': json.dumps(['request_user_input_async', 'call_stdio', 0]),
            'question': question['title'], 'answer': option_text}], ensure_ascii=False) + '\n</send_user_message_question_reply>'
        mismatch = call('buildchoice_record_instruction', {'request': {
            'session_handle': handle, 'decision_id': item['decision_id'], 'expected_revision': 1,
            'choice_id': 'A', 'user_message': envelope, 'quote': option_text,
            'reason': 'Synthetic fallback', 'idempotency_key': 'fallback'}})
        self.assertEqual(mismatch['code'], 'USER_MESSAGE_CONTEXT_MISMATCH')
        self.assertFalse(mismatch['recorded'])
        reply = store.observe_hook({**event, 'turn_id': '2', 'prompt': envelope})
        context = call('buildchoice_context', {'session_handle': reply['session_handle']})
        self.assertEqual(context['reply_binding']['status'], 'already_recorded')
        with store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM decision_v3_confirmations').fetchone()[0], 1)


if __name__ == '__main__':
    unittest.main()
