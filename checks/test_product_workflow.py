"""Product-task acceptance: real source boundary, frozen history, dirty/non-Git files and batches.

Hook inputs here are synthetic host fixtures, not proof of a live Codex UI interaction.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from buildchoice.desktop.decision_service import DecisionService
from buildchoice.desktop.decision_store import DecisionStore
from buildchoice.desktop import product_store as ps, workspace_snapshot as ws
from buildchoice.desktop.product_contracts import CONTRACTS
from buildchoice.desktop.product_observer import observe
from jsonschema import Draft202012Validator
from test_guidance import candidate


class ProductWorkflowTests(unittest.TestCase):
    def setUp(self):
        base = Path(os.environ.get('BUILDCHOICE_CHECK_ROOT', tempfile.gettempdir()))
        self.root = base / ('buildchoice-product-' + uuid.uuid4().hex); self.root.mkdir()
        self.workspace = self.root / 'project'; self.workspace.mkdir()
        self.config = self.root / 'mode.json'
        self.config.write_text('{"config_version":2,"mode":"pilot","context_ttl_seconds":900}', encoding='utf-8')
        self.env = patch.dict(os.environ, {'BUILDCHOICE_DATA': str(self.root / 'local-data')}); self.env.start(); self.addCleanup(self.env.stop)
        self.service = DecisionService(self.workspace, 'owner', self.config); self.store = DecisionStore(self.workspace)
        self.turn = 0; self.hook('做小票识别，核对后保存')
        self.task = self.call('experience', 'enable', task_text=self.text)['task_id']

    def hook(self, text, host='chat'):
        self.turn += 1; self.text = text; self.host = host
        self.handle = self.store.observe_hook({'hook_event_name': 'UserPromptSubmit', 'cwd': str(self.workspace),
            'session_id': host, 'turn_id': str(self.turn), 'prompt': text})['session_handle']
        return self.handle

    def call(self, method, action, **kwargs):
        req = {'action': action, 'session_handle': self.handle}
        if hasattr(self, 'task'): req['task_id'] = self.task
        if action not in ('status', 'document'): req['idempotency_key'] = uuid.uuid4().hex
        req.update(kwargs)
        return getattr(self.service, method)(req)

    def user(self): return {'user_message': self.text, 'quote': self.text, 'reason': '当前用户明确表达的要求'}

    def scenario(self, source='ai', **extra):
        origin = {'kind': 'ai', 'note': '根据任务推导'} if source == 'ai' else {'kind': 'user', **self.user()}
        return {'expected_revision': 0, 'title': '核对后保存小票', 'trigger': '识别完成后', 'action': '用户点击确认',
            'scope': '当前任务', 'behaviors': [{'behavior_id': 'save', 'text': '核对后才保存消费记录', 'source': origin}], **extra}

    def save(self, scenarios=None):
        return self.call('experience', 'save', scenarios=scenarios or [self.scenario()])['scenarios']

    def prepare(self):
        scenario = self.save()[0]
        expectation = self.call('experience', 'freeze')
        (self.workspace / 'app.py').write_text('save_after_review = True\n', encoding='utf-8')
        baseline = self.call('workspace_snapshot', 'capture', expectation_id=expectation['id'], scopes=['app.py'])
        return scenario, expectation, baseline

    def comparison(self):
        scenario, expectation, baseline = self.prepare()
        (self.workspace / 'app.py').write_text('save_after_review = False\n', encoding='utf-8')
        comparison = self.call('workspace_snapshot', 'compare', baseline_id=baseline['id'])
        return scenario, expectation, baseline, comparison

    def finding(self, scenario, judgment='possibly_deviates', **extra):
        return {'finding_id': 'saving', 'scenario': {'id': scenario['id'], 'revision': scenario['revision']},
            'behavior_ids': ['save'], 'judgment': judgment, 'summary': '识别结果可能直接进入账本',
            'importance': 'high', 'evidence': [{'kind': 'file', 'path': 'app.py', 'quote': 'save_after_review', 'note': '检查当前保存规则'}],
            'limits': '仅检查代码，尚无实际运行证据', **extra}

    def review(self):
        scenario, expectation, baseline, comp = self.comparison()
        review = self.call('behavior_review', 'create', comparison_id=comp['id'], findings=[self.finding(scenario)])
        return scenario, baseline, comp, review

    def test_advertised_contracts_are_valid_and_reject_unknown_fields(self):
        for schema in CONTRACTS.values(): Draft202012Validator.check_schema(schema)
        with self.assertRaisesRegex(ValueError, 'INVALID_PRODUCT_CONTRACT'):
            self.call('experience', 'freeze', hidden_approval=True)

    def test_mixed_origins_generation_display_and_acceptance_are_distinct(self):
        scenario = self.scenario('user')
        scenario['behaviors'].append({'behavior_id': 'image', 'text': '原图保留三十天', 'source': {'kind': 'ai', 'note': 'AI 推导'}})
        row = self.save([scenario])[0]
        first = self.call('experience', 'status')['scenarios'][0]
        self.assertEqual(first['review_status'], 'generated')
        shown = self.call('experience', 'present')
        self.assertIn('AI 建议或推导', shown['message'])
        self.assertEqual(self.call('experience', 'status')['scenarios'][0]['review_status'], 'displayed')
        with self.assertRaisesRegex(ValueError, 'later|Re-present'):
            self.call('experience', 'acknowledge', presentation_id=shown['id'], scenarios=[{'id': row['id'], 'revision': 1, 'status': 'accepted'}], **self.user())
        self.hook('认可当前展示的体验方案')
        self.call('experience', 'acknowledge', presentation_id=shown['id'], scenarios=[{'id': row['id'], 'revision': 1, 'status': 'accepted'}], **self.user())
        state = self.call('experience', 'status')['scenarios'][0]
        self.assertEqual(state['review_status'], 'accepted')
        self.assertEqual([b['source']['kind'] for b in state['behaviors']], ['user', 'ai'])

    def test_user_origin_and_acknowledgement_reject_fabricated_message(self):
        scenario = self.scenario('user'); scenario['behaviors'][0]['source']['user_message'] = '捏造的指令'
        with self.assertRaisesRegex(ValueError, 'actual current Hook'):
            self.save([scenario])
        self.assertEqual(self.call('experience', 'status')['scenarios'], [])

    def test_save_retries_and_version_conflict_are_atomic(self):
        scenario = self.scenario(); key = 'same'
        first = self.call('experience', 'save', scenarios=[scenario], idempotency_key=key)
        retry = self.call('experience', 'save', scenarios=[scenario], idempotency_key=key)
        self.assertTrue(retry['replayed']); self.assertEqual(first['scenarios'], retry['scenarios'])
        row = first['scenarios'][0]; self.hook('把保存行为改成自动保存')
        bad = self.scenario(scenario_id=row['id'], expected_revision=0)
        with self.assertRaisesRegex(ValueError, 'VERSION_CONFLICT'): self.save([bad])
        self.assertEqual(self.call('experience', 'status')['scenarios'][0]['revision'], 1)

    def test_unshown_stale_or_cross_chat_content_cannot_be_acknowledged(self):
        row = self.save()[0]; shown = self.call('experience', 'present')
        self.hook('认可方案', host='new-chat')
        args = {'presentation_id': shown['id'], 'scenarios': [{'id': row['id'], 'revision': 1, 'status': 'accepted'}]}
        with self.assertRaisesRegex(ValueError, 'this chat'): self.call('experience', 'acknowledge', **args, **self.user())
        restored = self.call('experience', 'status'); self.assertEqual(restored['scenarios'][0]['id'], row['id'])
        reshown = self.call('experience', 'present'); self.hook('认可本次展示的方案', host='new-chat')
        self.call('experience', 'acknowledge', **{**args, 'presentation_id': reshown['id']}, **self.user())
        self.assertEqual(self.call('experience', 'status')['scenarios'][0]['review_status'], 'accepted')

    def test_revised_scene_keeps_old_frozen_version_and_marks_review_stale(self):
        row, baseline, comp, review = self.review(); self.hook('改成自动保存')
        new = self.scenario(scenario_id=row['id'], expected_revision=1, title='自动保存小票')
        self.save([new])
        result = self.call('behavior_review', 'status', review_id=review['id'])
        self.assertEqual(result['validity'], 'needs_recheck')
        self.assertEqual(result['findings'][0]['scenario']['revision'], 1)
        with self.store.connect() as db:
            old = ps.get(db, row['id'], revision=1)
        self.assertEqual(old['data']['title'], '核对后保存小票')

    def test_project_origin_requires_read_quote_and_rechecks_file(self):
        (self.workspace / 'policy.md').write_text('确认后保存', encoding='utf-8')
        source = self.service.context_bundle(self.handle, paths=['policy.md'])['sources'][0]
        scenario = self.scenario(); scenario['behaviors'][0]['source'] = {'kind': 'project', 'source_id': source['source_id'], 'quote': '确认后保存'}
        self.save([scenario]); expected = self.call('experience', 'freeze')
        (self.workspace / 'policy.md').write_text('自动保存', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'stale'):
            self.call('workspace_snapshot', 'capture', expectation_id=expected['id'], scopes=['policy.md'])

    def test_non_git_starting_content_diff_additions_and_deletions(self):
        self.save(); expected = self.call('experience', 'freeze')
        src = self.workspace / 'src'; src.mkdir(); (src / 'old.py').write_text('old = 1\n', encoding='utf-8')
        start = self.call('workspace_snapshot', 'capture', expectation_id=expected['id'], scopes=['src'])
        self.assertFalse(start['git']['available'])
        (src / 'old.py').unlink(); (src / 'new.py').write_text('new = 2\n', encoding='utf-8')
        comp = self.call('workspace_snapshot', 'compare', baseline_id=start['id'])
        self.assertEqual({r['kind'] for r in comp['changes']}, {'added', 'deleted'})
        self.assertIn('-old = 1', next(r['diff'] for r in comp['changes'] if r['kind'] == 'deleted'))

    def test_git_baseline_includes_staged_unstaged_and_untracked_content(self):
        def git(*args): subprocess.run(['git', '-C', str(self.workspace), *args], check=True, capture_output=True)
        git('init'); git('config', 'user.name', 'Fixture'); git('config', 'user.email', 'fixture@example.invalid')
        f = self.workspace / 'app.py'; f.write_text('HEAD\n', encoding='utf-8'); git('add', 'app.py'); git('commit', '-m', 'fixture')
        f.write_text('staged\n', encoding='utf-8'); git('add', 'app.py'); f.write_text('actual dirty content\n', encoding='utf-8')
        (self.workspace / 'untracked.py').write_text('untracked content\n', encoding='utf-8')
        self.save(); expected = self.call('experience', 'freeze')
        start = self.call('workspace_snapshot', 'capture', expectation_id=expected['id'], scopes=['app.py', 'untracked.py'])
        self.assertEqual(start['files']['app.py']['sha256'], __import__('hashlib').sha256(f.read_bytes()).hexdigest())
        self.assertEqual(start['files']['untracked.py']['status'], 'captured')
        f.write_text('final\n', encoding='utf-8')
        comp = self.call('workspace_snapshot', 'compare', baseline_id=start['id'])
        self.assertIn('-actual dirty content', comp['changes'][0]['diff']); self.assertNotIn('-HEAD', comp['changes'][0]['diff'])

    def test_snapshot_private_binary_large_explicit_exclusions_and_storage_location(self):
        self.save(); expected = self.call('experience', 'freeze')
        for name, body in {'.env': b'password=secret', 'secret.key': b'secret', 'binary.png': b'\0abc', 'large.txt': b'a' * (ws.FILE_LIMIT + 1),
                'tokens.json': b'{"api_key":"12345678901234567890"}', 'omit.py': b'explicit', 'app.py': b'safe'}.items():
            (self.workspace / name).write_bytes(body)
        result = self.call('workspace_snapshot', 'capture', expectation_id=expected['id'], scopes=['.'], excluded_paths=['omit.py'])
        self.assertEqual(result['files']['app.py']['status'], 'captured')
        for name in ('.env', 'secret.key', 'binary.png', 'large.txt', 'tokens.json', 'omit.py'):
            self.assertNotIn('sha256', result['files'][name])
        root = ws.safe_root(self.store); self.assertFalse(root.is_relative_to(self.workspace))
        bodies = b''.join(p.read_bytes() for d in root.iterdir() for p in d.iterdir())
        self.assertNotIn(b'12345678901234567890', bodies)
        for path in ('../outside', 'C:/private', '/absolute', 'dir/../../file'):
            with self.assertRaises(ValueError): ws.normalize(path)

    def test_linked_scope_is_not_followed(self):
        self.save(); expected = self.call('experience', 'freeze')
        outside = self.root / 'outside'; outside.mkdir(); (outside / 'secret.txt').write_text('private', encoding='utf-8')
        link = self.workspace / 'linked'
        try: link.symlink_to(outside, target_is_directory=True)
        except OSError:
            if os.name != 'nt': self.skipTest('Symlinks unavailable')
            subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(outside)], check=True, capture_output=True)
        start = self.call('workspace_snapshot', 'capture', expectation_id=expected['id'], scopes=['linked'])
        self.assertFalse(any(e.get('sha256') for e in start['files'].values()))

    def test_prune_preserves_metadata_and_invalidates_review(self):
        row, baseline, comp, review = self.review()
        content = ws.safe_root(self.store) / baseline['storage_id'] / baseline['files']['app.py']['sha256']
        content.unlink()  # Simulate external content loss or a cleanup interrupted before DB commit.
        self.assertFalse(self.call('workspace_snapshot', 'status', snapshot_id=baseline['id'])['content_available'])
        self.call('workspace_snapshot', 'prune', snapshot_ids=[baseline['id']])
        state = self.call('workspace_snapshot', 'status', snapshot_id=baseline['id'])
        self.assertFalse(state['content_available']); self.assertIn('sha256', state['data']['files']['app.py'])
        self.assertEqual(self.call('behavior_review', 'status', review_id=review['id'])['validity'], 'needs_recheck')

    def test_extension_before_edit_and_missing_history_are_distinct(self):
        scenario, expected, baseline = self.prepare(); self.hook('还需要检查辅助模块')
        (self.workspace / 'helper.py').write_text('current\n', encoding='utf-8')
        extension = self.call('workspace_snapshot', 'extend', baseline_id=baseline['id'], scopes=['helper.py'], timing='already_modified')
        self.assertEqual(extension['files']['helper.py']['status'], 'no_pre_edit_baseline')
        comp = self.call('workspace_snapshot', 'compare', baseline_id=extension['id'])
        self.assertTrue(any(r['path'] == 'helper.py' for r in comp['uninspected']))
        with self.assertRaisesRegex(ValueError, 'disjoint'):
            self.call('workspace_snapshot', 'extend', baseline_id=baseline['id'], scopes=['app.py'], timing='before_first_edit')

    def test_review_uses_original_expectation_and_fills_unchecked_behavior(self):
        scenario, expected, baseline, comp = self.comparison()
        review = self.call('behavior_review', 'create', comparison_id=comp['id'], findings=[])
        self.assertEqual(review['expectation_id'], expected['id']); self.assertEqual(review['findings'][0]['judgment'], 'unknown')
        self.assertEqual(review['findings'][0]['behavior_ids'], ['save'])
        self.hook('重新检查')
        bad = self.finding(scenario); bad['scenario']['revision'] = 2
        with self.assertRaisesRegex(ValueError, 'frozen scenario'):
            self.call('behavior_review', 'create', comparison_id=comp['id'], findings=[bad])

    def test_judgment_is_independent_of_llm_code_and_test_report_strength(self):
        scenario, expected, baseline, comp = self.comparison()
        finding = self.finding(scenario, 'possibly_matches', evidence=[{'kind': 'llm', 'note': '模型判断可能正确'}])
        result = self.call('behavior_review', 'create', comparison_id=comp['id'], findings=[finding])
        self.assertIn('不能视为', result['findings'][0]['evidence_note'])
        self.hook('查看报告文件')
        (self.workspace / 'test.log').write_text('all passed', encoding='utf-8')
        finding['evidence'] = [{'kind': 'test', 'note': '报告声称通过', 'path': 'test.log', 'quote': 'all passed',
            'outcome': 'passed', 'tested_behaviors': ['save'], 'limits': '未核验执行过程'}]
        result = self.call('behavior_review', 'create', comparison_id=comp['id'], findings=[finding])
        self.assertEqual(result['findings'][0]['evidence'][0]['strength'], 'report_file_execution_unverified')

    def test_native_hook_execution_receipt_binds_output_and_keeps_coverage_limited(self):
        scenario, expected, baseline, comp = self.comparison()
        event = {'hook_event_name': 'PostToolUse', 'cwd': str(self.workspace), 'session_id': 'chat',
            'turn_id': str(self.turn), 'tool_use_id': 'call1', 'tool_name': 'Bash', 'tool_input': {'command': 'python -m unittest'},
            'tool_response': {'exit_code': 0, 'output': 'Ran 1 test\nOK'}}
        observed = observe(event, self.workspace, self.config); self.assertIsNotNone(observed)
        with self.store.connect() as db: record = ps.objects(db, self.task, 'tool_observation')[0]
        finding = self.finding(scenario, 'possibly_matches', evidence=[{'kind': 'test', 'note': '合成 Hook 返回中记录测试通过',
            'observation_id': record['id'], 'quote': 'OK', 'outcome': 'passed', 'tested_behaviors': ['save'], 'limits': '仅覆盖登记的一个行为；运行时输入状态未观察'}])
        result = self.call('behavior_review', 'create', comparison_id=comp['id'], findings=[finding])
        self.assertEqual(result['findings'][0]['evidence'][0]['strength'], 'test_execution_result')
        self.assertFalse(result['coverage_complete'])
        self.assertIsNone(observe(event, self.workspace, self.config))

    def test_extra_behavior_origin_requires_actual_changed_path(self):
        scenario, expected, baseline, comp = self.comparison()
        extra = {'finding_id': 'extra', 'judgment': 'extra', 'summary': '自动保留原始小票', 'importance': 'high',
            'evidence': [], 'limits': '尚未验证', 'change_origin': 'observed_change'}
        with self.assertRaisesRegex(ValueError, 'actual changed file'):
            self.call('behavior_review', 'create', comparison_id=comp['id'], findings=[extra])
        extra['change_origin'] = 'uncertain'
        result = self.call('behavior_review', 'create', comparison_id=comp['id'], findings=[extra])
        self.assertEqual(result['findings'][0]['change_origin'], 'uncertain')

    def test_feedback_fix_investigate_defer_keep_expectation_and_unresolved_history(self):
        row, baseline, comp, review = self.review()
        for revision, action in enumerate(('fix', 'investigate', 'defer')):
            self.hook('对这个问题' + action)
            self.call('behavior_review', 'feedback', review_id=review['id'], feedback=[{
                'finding_id': 'saving', 'action': action, 'note': '保留预期继续处理', 'expected_feedback_revision': revision}], **self.user())
        state = self.call('behavior_review', 'status', review_id=review['id'])
        self.assertEqual(state['findings'][0]['resolution_state'], 'deferred')
        self.assertEqual(state['findings'][0]['scenario']['revision'], 1)
        with self.store.connect() as db:
            self.assertEqual(len(ps.objects(db, self.task, 'product_feedback', latest=False)), 3)

    def test_accept_extra_preserves_unknown_evidence_and_grants_no_permissions(self):
        scenario, expected, baseline, comp = self.comparison()
        extra = {'finding_id': 'extra', 'judgment': 'extra', 'summary': '保留原始小票三十天', 'importance': 'high',
            'evidence': [], 'limits': '未验证', 'change_origin': 'uncertain'}
        review = self.call('behavior_review', 'create', comparison_id=comp['id'], findings=[extra])
        self.hook('保留这项额外行为，仅用于当前任务')
        result = self.call('behavior_review', 'feedback', review_id=review['id'], feedback=[{
            'finding_id': 'extra', 'action': 'accept_extra', 'note': '仅用于当前任务', 'expected_feedback_revision': 0}], **self.user())
        self.assertTrue(result['does_not_authorize_host_operations'])
        state = self.call('behavior_review', 'status', review_id=review['id'])
        self.assertEqual(state['findings'][0]['resolution_state'], 'accepted'); self.assertEqual(state['findings'][0]['evidence'], [])

    def test_code_and_evidence_changes_make_old_review_stale_without_overwrite(self):
        row, baseline, comp, review = self.review()
        (self.workspace / 'app.py').write_text('changed again\n', encoding='utf-8')
        state = self.call('behavior_review', 'status', review_id=review['id'])
        self.assertEqual(state['validity'], 'needs_recheck'); self.assertTrue(state['stale_reasons'])
        self.assertEqual(state['findings'][0]['summary'], review['findings'][0]['summary'])

    def test_documents_protect_handwritten_files_and_retry_without_new_versions(self):
        name = 'BUILDCHOICE_PRODUCT_' + self.task.split('-')[-1][:12] + '.md'
        (self.workspace / name).write_text('my notes', encoding='utf-8')
        with patch('os.replace', side_effect=OSError('locked')):
            result = self.call('experience', 'save', scenarios=[self.scenario()])
        self.assertEqual(result['document']['status'], 'pending')
        self.assertEqual((self.workspace / name).read_text(encoding='utf-8'), 'my notes')
        published = self.call('experience', 'document')
        self.assertEqual(published['document']['status'], 'synchronized')
        self.assertEqual(len(self.call('experience', 'status')['scenarios']), 1)

    def test_closed_and_off_modes_do_not_write_new_product_records(self):
        self.call('experience', 'close')
        with self.store.connect() as db: count = db.execute('SELECT count(*) FROM product_objects').fetchone()[0]
        with self.assertRaisesRegex(ValueError, 'closed'): self.save()
        self.config.write_text('{"config_version":2,"mode":"off","context_ttl_seconds":900}', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'DISABLED'): self.call('experience', 'status')
        with self.store.connect() as db: self.assertEqual(count, db.execute('SELECT count(*) FROM product_objects').fetchone()[0])

    def test_cross_chat_context_lists_recovery_entry_without_inheriting_approval(self):
        self.save(); self.hook('继续上次的产品任务', host='fresh')
        result = self.service.context_bundle(self.handle)
        self.assertEqual(result['product_tasks'][0]['task_id'], self.task)
        self.assertIn('status', result['product_tasks'][0]['resume'])

    def test_missing_hook_cannot_create_scenario_or_confirmation(self):
        for method, action, extra in [('experience', 'save', {'scenarios': [self.scenario()]}),
                                      ('experience', 'freeze', {})]:
            with self.assertRaisesRegex(ValueError, 'Hook'):
                self.call(method, action, session_handle='fake', **extra)

    def test_corrected_implementation_links_new_review_and_keeps_old_result(self):
        scenario, baseline, comparison, first = self.review()
        self.hook('修复后重新审阅')
        (self.workspace / 'app.py').write_text('save_after_review = True\n', encoding='utf-8')
        comp = self.call('workspace_snapshot', 'compare', baseline_id=baseline['id'])
        second = self.call('behavior_review', 'create', comparison_id=comp['id'], previous_review_id=first['id'],
            findings=[self.finding(scenario, 'possibly_matches', summary='当前代码要求核对后保存')])
        self.assertEqual(second['previous_review_id'], first['id']); self.assertEqual(second['validity'], 'current')
        self.assertEqual(comp['changes'], [])
        self.assertEqual(self.call('behavior_review', 'status', review_id=first['id'])['findings'][0]['judgment'], 'possibly_deviates')

    def test_changed_requirement_requires_trusted_decision_and_new_linked_scene(self):
        scenario, baseline, comparison, review = self.review(); self.hook('本任务改成自动保存小票')
        decision = self.service.record_instruction({'session_handle': self.handle, **self.user(),
            'expected_revision': 0, 'idempotency_key': 'requirement', 'decision': {
                'decision_key': 'receipt.auto', 'field': '小票保存方式', 'scope_key': self.task,
                'choice': {'label': '自动保存', 'value': 'auto'}}})
        ref = {'decision_id': decision['decision_id'], 'revision': decision['revision']}
        revised = self.scenario(scenario_id=scenario['id'], expected_revision=1,
            behaviors=[{'behavior_id': 'save', 'text': '本任务自动保存小票', 'source': {'kind': 'decision', **ref}}])
        new = self.save([revised])[0]
        result = self.call('behavior_review', 'feedback', review_id=review['id'], feedback=[{
            'finding_id': 'saving', 'action': 'change_requirement', 'note': '用户改变本任务要求', 'expected_feedback_revision': 0,
            'decision': ref, 'scenario': {'id': new['id'], 'revision': new['revision']}}], **self.user())
        self.assertTrue(result['recorded'])
        state = self.call('behavior_review', 'status', review_id=review['id'])
        self.assertEqual(state['findings'][0]['resolution_state'], 'requirement_changed')
        self.assertEqual(state['findings'][0]['scenario']['revision'], 1)

    def test_no_deviation_task_finishes_without_extra_findings(self):
        scenario, expected, baseline = self.prepare()
        comp = self.call('workspace_snapshot', 'compare', baseline_id=baseline['id'])
        review = self.call('behavior_review', 'create', comparison_id=comp['id'], findings=[
            self.finding(scenario, 'possibly_matches', summary='根据代码，核对后才保存')])
        self.assertEqual(len(review['findings']), 1); self.assertEqual(review['findings'][0]['judgment'], 'possibly_matches')
        self.call('experience', 'close'); self.assertFalse(self.call('experience', 'status')['enabled'])

    def test_storage_quota_and_retention_keep_unavailable_history_honest(self):
        scenario, expected, baseline = self.prepare()
        self.hook('继续采集')
        with patch.object(ws, 'PROJECT_LIMIT', 1):
            limited = self.call('workspace_snapshot', 'capture', expectation_id=expected['id'], scopes=['app.py'])
        self.assertEqual(limited['files']['app.py']['status'], 'storage_quota')
        with patch.object(ws, 'RETENTION_SECONDS', -1):
            self.call('workspace_snapshot', 'capture', expectation_id=expected['id'], scopes=['app.py'])
        self.assertFalse(self.call('workspace_snapshot', 'status', snapshot_id=baseline['id'])['content_available'])

    def test_partial_scene_revision_preserves_original_user_origin_without_reconfirming(self):
        original = self.save([self.scenario('user')])[0]; self.hook('只补充错误提示')
        revised = self.scenario(scenario_id=original['id'], expected_revision=1)
        revised['behaviors'][0]['source'] = {'kind': 'recorded', 'scenario': {'id': original['id'], 'revision': 1}, 'behavior_id': 'save'}
        revised['behaviors'].append({'behavior_id': 'error', 'text': '保存失败时展示错误提示', 'source': {'kind': 'ai', 'note': '补充异常处理'}})
        saved = self.save([revised])[0]
        self.assertEqual(saved['behaviors'][0]['source']['kind'], 'user')
        self.assertEqual(saved['behaviors'][0]['source']['message_digest'], original['behaviors'][0]['source']['message_digest'])
        self.assertEqual(self.call('experience', 'status')['scenarios'][0]['review_status'], 'revised')
        self.hook('再次修改')
        revised.update(expected_revision=2); revised['behaviors'][0]['text'] = '偷偷改成自动保存'
        with self.assertRaisesRegex(ValueError, 'identical stable behavior'): self.save([revised])

    def test_native_test_receipt_becomes_stale_if_code_changes_before_reuse(self):
        scenario, expected, baseline, comp = self.comparison()
        event = {'hook_event_name': 'PostToolUse', 'cwd': str(self.workspace), 'session_id': 'chat',
            'turn_id': str(self.turn), 'tool_use_id': 'old-test', 'tool_name': 'Bash', 'tool_input': {'command': 'python -m unittest'},
            'tool_response': {'exit_code': 0, 'output': 'OK'}}
        observe(event, self.workspace, self.config)
        with self.store.connect() as db: record = ps.objects(db, self.task, 'tool_observation')[0]
        (self.workspace / 'app.py').write_text('save_after_review = True\n', encoding='utf-8')
        new_comp = self.call('workspace_snapshot', 'compare', baseline_id=baseline['id'])
        finding = self.finding(scenario, 'possibly_matches', evidence=[{'kind': 'test', 'note': '旧测试返回',
            'observation_id': record['id'], 'quote': 'OK', 'outcome': 'passed', 'tested_behaviors': ['save'], 'limits': '原运行范围'}])
        review = self.call('behavior_review', 'create', comparison_id=new_comp['id'], findings=[finding])
        self.assertFalse(review['findings'][0]['evidence'][0]['current'])
        self.assertEqual(review['validity'], 'needs_recheck')

    def test_excluded_binary_and_large_files_do_not_fake_a_workspace_change(self):
        self.save(); expected = self.call('experience', 'freeze')
        (self.workspace / 'image.png').write_bytes(b'\0binary')
        (self.workspace / 'large.txt').write_bytes(b'a' * (ws.FILE_LIMIT + 1))
        baseline = self.call('workspace_snapshot', 'capture', expectation_id=expected['id'], scopes=['.'])
        comp = self.call('workspace_snapshot', 'compare', baseline_id=baseline['id'])
        review = self.call('behavior_review', 'create', comparison_id=comp['id'], findings=[])
        self.assertEqual(review['validity'], 'current'); self.assertGreaterEqual(len(review['scope']['uninspected']), 2)

    def test_one_user_reply_can_acknowledge_separately_presented_groups(self):
        scenes = self.save([self.scenario(), self.scenario(title='识别失败后的提示')])
        presentations = [self.call('experience', 'present', scenarios=[{'id': s['id'], 'revision': 1}]) for s in scenes]
        self.hook('认可刚才展示的这两组体验')
        for scene, shown in zip(scenes, presentations):
            self.call('experience', 'acknowledge', presentation_id=shown['id'],
                scenarios=[{'id': scene['id'], 'revision': 1, 'status': 'accepted'}], **self.user())
        self.assertEqual([s['review_status'] for s in self.call('experience', 'status')['scenarios']], ['accepted', 'accepted'])


class BatchDecisionTests(ProductWorkflowTests):
    # Reuse acceptance helpers without running the base acceptance tests twice.
    def batch(self, count=3, dependencies=False):
        candidates = []
        for i in range(count):
            c = {**candidate(), 'candidate_id': 'c' + str(i), 'field': 'Choice ' + str(i), 'decision_key': 'choice.' + str(i),
                'recommended_option_id': 'B', 'recommendation_reason': '更符合本任务体验'}
            if dependencies and i == 1: c['depends_on'] = ['choice.0']
            candidates.append(c)
        result = self.service.screen({'task_text': '做小票识别，核对后保存', 'task_id': self.task, 'next_step': '实现体验',
            'candidates': candidates, 'session_handle': self.handle, 'idempotency_key': uuid.uuid4().hex})
        refs = [{'decision_id': r['decision_id'], 'revision': r['revision']} for r in result['decisions']]
        return refs

    def test_partial_reply_records_independent_choices_and_leaves_discussion(self):
        refs = self.batch(); batch = self.call('batch_decisions', 'present', decisions=refs)
        self.hook('第一个选B，第二个按推荐，第三个再讨论')
        answers = [{**refs[0], 'status': 'selected', 'choice_id': 'B'},
                   {**refs[1], 'status': 'selected', 'choice_id': 'B', 'selection_basis': 'current_recommendation'},
                   {**refs[2], 'status': 'discuss'}]
        result = self.call('batch_decisions', 'submit', batch_id=batch['id'], answers=answers, **self.user())
        self.assertEqual([r['status'] for r in result['decisions']], ['confirmed', 'confirmed', 'discuss'])
        self.hook('第三个也选A')
        result = self.call('batch_decisions', 'submit', batch_id=batch['id'], answers=[{**refs[2], 'status': 'selected', 'choice_id': 'A'}], **self.user())
        self.assertEqual(result['pending'], [])

    def test_invalid_member_causes_full_transaction_rollback(self):
        refs = self.batch(); batch = self.call('batch_decisions', 'present', decisions=refs); self.hook('第一B第二A')
        with self.assertRaisesRegex(ValueError, 'another batch'):
            self.call('batch_decisions', 'submit', batch_id=batch['id'], answers=[{**refs[0], 'status': 'selected', 'choice_id': 'B'},
                {**refs[1], 'revision': 99, 'status': 'selected', 'choice_id': 'A'}], **self.user())
        with self.store.connect() as db: self.assertEqual(db.execute('SELECT count(*) FROM decision_v3_confirmations').fetchone()[0], 0)

    def test_unanswered_stale_member_rejects_whole_submission(self):
        refs = self.batch(); batch = self.call('batch_decisions', 'present', decisions=refs)
        self.service.prepare_revision(self.task, refs[2]['decision_id'], 1, {**candidate(), 'field': 'Choice 2', 'decision_key': 'choice.2'},
            '改变含义', self.handle)
        self.hook('第一个选B')
        with self.assertRaisesRegex(ValueError, 'stale'):
            self.call('batch_decisions', 'submit', batch_id=batch['id'], answers=[{**refs[0], 'status': 'selected', 'choice_id': 'B'}], **self.user())
        with self.store.connect() as db: self.assertEqual(db.execute('SELECT count(*) FROM decision_v3_confirmations').fetchone()[0], 0)

    def test_batch_rejects_dependencies_and_more_than_three_items(self):
        refs = self.batch(dependencies=True)
        with self.assertRaisesRegex(ValueError, 'dependencies'): self.call('batch_decisions', 'present', decisions=refs)
        with self.assertRaisesRegex(ValueError, 'CONTRACT'): self.call('batch_decisions', 'present', decisions=refs + [refs[0]])

    def test_batch_retry_is_idempotent_and_concurrent_submit_conflicts(self):
        refs = self.batch(1); batch = self.call('batch_decisions', 'present', decisions=refs); self.hook('选B')
        request = {'action': 'submit', 'task_id': self.task, 'session_handle': self.handle, 'idempotency_key': 'answer',
            'batch_id': batch['id'], 'answers': [{**refs[0], 'status': 'selected', 'choice_id': 'B'}], **self.user()}
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.service.batch_decisions(request), range(2)))
        self.assertTrue(any(r.get('replayed') for r in results))
        with self.store.connect() as db: self.assertEqual(db.execute('SELECT count(*) FROM decision_v3_confirmations').fetchone()[0], 1)
        with self.assertRaisesRegex(ValueError, 'Conflicting retry'):
            self.service.batch_decisions({**request, 'answers': [{**refs[0], 'status': 'selected', 'choice_id': 'A'}]})

    def test_batch_and_single_card_cannot_capture_same_reply(self):
        refs = self.batch(2); batch = self.call('batch_decisions', 'present', decisions=refs)
        with self.assertRaisesRegex(ValueError, 'batch is active'):
            self.service.activate(self.task, refs[0]['decision_id'], 1, 'single', self.handle)
        self.hook('B')
        with self.store.connect() as db: self.assertEqual(db.execute('SELECT count(*) FROM decision_v3_confirmations').fetchone()[0], 0)
        self.call('batch_decisions', 'suspend', batch_id=batch['id'])
        self.service.activate(self.task, refs[0]['decision_id'], 1, 'single2', self.handle)
        self.hook('B')
        with self.store.connect() as db: self.assertEqual(db.execute('SELECT count(*) FROM decision_v3_confirmations').fetchone()[0], 1)

    def test_expired_batch_and_wrong_chat_reply_cannot_confirm(self):
        refs = self.batch(1); batch = self.call('batch_decisions', 'present', decisions=refs)
        self.hook('选B', host='other')
        with self.assertRaisesRegex(ValueError, 'this chat'):
            self.call('batch_decisions', 'submit', batch_id=batch['id'], answers=[{**refs[0], 'status': 'selected', 'choice_id': 'B'}], **self.user())


# Only the batch-specific tests use this subclass; common helpers stay inherited.
for _name in list(ProductWorkflowTests.__dict__):
    if _name.startswith('test_') and _name not in BatchDecisionTests.__dict__:
        setattr(BatchDecisionTests, _name, None)

if __name__ == '__main__': unittest.main()
