"""Contracts, observed execution, freshness and compatibility; synthetic confirmations only."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from verification_helpers import setup_fixture,small_manifest,criteria,ROOT
from buildchoice.desktop import acceptance,verification
from buildchoice.desktop.decision_service import DecisionService
from buildchoice.desktop.verification_runner import collect
from buildchoice.desktop.migration import rollback_decision_database
from buildchoice.desktop.audit import Ledger


class VerificationTests(unittest.TestCase):
    def setUp(self):
        self.f=setup_fixture();small_manifest(self.f)

    def run_tests(self,body=None,timeout=None):
        if body is not None:(self.f['workspace']/'test_app.py').write_text(body,encoding='utf-8')
        if timeout is not None:
            path=self.f['workspace']/'manifest.json';value=json.loads(path.read_text());value['timeout_seconds']=timeout;path.write_text(json.dumps(value))
        return collect(self.f['workspace'],self.f['conditions']['acceptance_id'],'manifest.json',self.f['global_settings'],self.f['settings'])

    def verify(self,receipt=None,key='verify',refs=None):
        f=self.f
        return f['service'].verify_decision(f['task']['id'],f['item']['decision_id'],1,f['conditions']['acceptance_id'],
            refs or [],receipt['execution_id'] if receipt else None,f['handle'],key)

    def prepare(self,conditions,key='prepare-more',owner=None,revision=1):
        f=self.f
        return (owner or f['service']).acceptance_prepare(f['task']['id'],f['item']['decision_id'],revision,conditions,f['handle'],key)

    def test_prepare_binds_real_choice_and_marks_agent_derivation(self):
        result=self.prepare(criteria())
        self.assertEqual(result['choice']['id'],'A')
        self.assertEqual(result['criterion_author'],'agent')
        self.assertEqual(result['human_approval'],'not_separately_confirmed')
        self.assertEqual(result['basis'],'user_confirmed_decision')
        self.assertEqual(self.prepare(criteria()),result)
        changed=criteria();changed[0]['description']='Changed condition'
        with self.assertRaises(ValueError):self.prepare(changed)

    def test_prepare_rejects_unconfirmed_and_other_session(self):
        other=DecisionService(self.f['workspace'],'another-session',settings_path=self.f['settings'])
        with self.assertRaises(ValueError):self.prepare(criteria(),owner=other)
        with self.f['store'].connect() as db:db.execute("UPDATE decision_v3_items SET state='screened'")
        with self.assertRaises(ValueError):self.prepare(criteria())

    def test_prepare_rejects_expired_handle_old_revision_and_claimed_approval(self):
        invalid=criteria();invalid[0]['human_approval']='confirmed'
        with self.assertRaises(Exception):self.prepare(invalid)
        with self.assertRaises(ValueError):self.prepare(criteria(),revision=9)
        with self.f['store'].connect() as db:db.execute('UPDATE decision_v3_contexts SET expires=0')
        with self.assertRaises(ValueError):self.prepare(criteria())

    def test_missing_execution_is_inconclusive_without_executing_any_command(self):
        with patch('subprocess.Popen',side_effect=AssertionError('MCP verifier must not execute commands')):
            result=self.verify()
        self.assertEqual(result['verdict'],'inconclusive')
        self.assertFalse(result['current_pass'])

    def test_actual_tests_can_pass_and_failed_assertions_fail(self):
        result=self.verify(self.run_tests())
        self.assertEqual(result['verdict'],'passed');self.assertTrue(result['current_pass'])
        self.assertEqual(result['criteria'][0]['behavior_provenance'],'collector_observed_execution')
        receipt=self.run_tests('import unittest\nclass Checks(unittest.TestCase):\n def test_ok(self): self.assertEqual(1,2)\n')
        self.assertEqual(self.verify(receipt,'failed')['verdict'],'failed')

    def test_zero_tests_skips_and_unmapped_tests_do_not_pass(self):
        for i,body in enumerate(['# no tests\n',
            'import unittest\nclass Checks(unittest.TestCase):\n @unittest.skip("not run")\n def test_ok(self): pass\n',
            'import unittest\nclass Checks(unittest.TestCase):\n def test_other(self): self.assertTrue(True)\n']):
            self.assertEqual(self.verify(self.run_tests(body),'missing-'+str(i))['verdict'],'inconclusive')

    def test_import_error_and_timeout_are_errors(self):
        receipt=self.run_tests('raise RuntimeError("startup failed")\n')
        self.assertEqual(self.verify(receipt,'error')['verdict'],'error')
        receipt=self.run_tests('import time\ntime.sleep(20)\n',timeout=1)
        self.assertEqual(receipt['execution_status'],'timeout')
        self.assertEqual(self.verify(receipt,'timeout')['verdict'],'error')

    def test_forged_stdout_and_report_file_cannot_manufacture_execution(self):
        body='import unittest\nprint("{\\"passed\\": true}")\nclass Checks(unittest.TestCase):\n def test_ok(self): self.fail("actual assertion failed")\n'
        self.assertEqual(self.verify(self.run_tests(body))['verdict'],'failed')
        (self.f['workspace']/'fake-report.json').write_text('{"passed":true}')
        with self.assertRaises(ValueError):
            verification.verify(self.f['store'],self.f['task'],self.f['item']['decision_id'],1,
                self.f['conditions']['acceptance_id'],[],'exec-'+'0'*32,'unknown')

    def test_report_tamper_and_missing_artifact_invalidate_historical_pass(self):
        receipt=self.run_tests();result=self.verify(receipt)
        report=self.f['workspace']/'.buildchoice_audit/verification_runs'/receipt['execution_id']/'report.json'
        report.write_text('{"passed":true}')
        current=verification.present(self.f['store'],result)
        self.assertEqual(current['verdict'],'passed');self.assertEqual(current['applicability'],'stale');self.assertFalse(current['current_pass'])
        report.rename(report.with_suffix('.moved'))
        self.assertIn('EXECUTION_ARTIFACT_UNAVAILABLE',verification.present(self.f['store'],result)['stale_reasons'])

    def test_input_changes_and_idempotent_rechecks_do_not_reuse_current_pass(self):
        receipt=self.run_tests();result=self.verify(receipt)
        path=self.f['workspace']/'app.py';path.write_text('value = 2\n')
        again=self.verify(receipt)
        self.assertEqual(again['verification_id'],result['verification_id'])
        self.assertFalse(again['current_pass']);self.assertIn('INPUT_SNAPSHOT_CHANGED',again['stale_reasons'])

    def test_test_manifest_and_config_changes_are_stale(self):
        config=self.f['workspace']/'config.json';config.write_text('{}')
        manifest_file=self.f['workspace']/'manifest.json';value=json.loads(manifest_file.read_text());value['files']['config']=['config.json'];manifest_file.write_text(json.dumps(value))
        result=self.verify(self.run_tests())
        for path in [config,self.f['workspace']/'test_app.py',manifest_file]:
            before=path.read_bytes();path.write_bytes(before+b'\n')
            self.assertFalse(verification.present(self.f['store'],result)['current_pass'])
            path.write_bytes(before)

    def test_environment_change_and_runtime_change_are_stale(self):
        receipt=self.run_tests();result=self.verify(receipt)
        with patch('buildchoice.desktop.verification.environment_current',return_value=False):
            self.assertIn('EXECUTION_ENVIRONMENT_CHANGED',verification.present(self.f['store'],result)['stale_reasons'])
        with patch('buildchoice.desktop.verification.runtime_digest',return_value='changed'):
            self.assertFalse(verification.present(self.f['store'],result)['current_pass'])

    def test_selected_environment_and_bytecode_cache_cannot_reuse_earlier_pass(self):
        import os
        import py_compile
        path=self.f['workspace']/'test_app.py'
        passed='import unittest\nclass Checks(unittest.TestCase):\n def test_ok(self): self.assertEqual(1,1)\n'
        failed=passed.replace('(1,1)','(1,2)')
        path.write_text(passed);stamp=path.stat()
        py_compile.compile(str(path),doraise=True)
        path.write_text(failed);os.utime(path,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
        self.assertEqual(self.verify(self.run_tests())['verdict'],'failed')
        from buildchoice.desktop.verification_inputs import environment_snapshot,environment_current
        with patch.dict(os.environ,{'BUILDCHOICE_TEST_BROWSER':str(self.f['workspace']/'app.py')}):
            environment=environment_snapshot([])
        with patch.dict(os.environ,{'BUILDCHOICE_TEST_BROWSER':str(path)}):
            self.assertFalse(environment_current(environment))

    def test_acceptance_and_decision_revision_invalidate_previous_results(self):
        result=self.verify(self.run_tests())
        self.prepare(criteria(),'replacement')
        self.assertFalse(verification.present(self.f['store'],result)['current_pass'])
        f=self.f
        f['service'].prepare_revision(f['task']['id'],f['item']['decision_id'],1,f['candidate'],'Changed choice',f['handle'])
        status=f['service'].status(f['task']['id'],f['handle'])['verification']
        self.assertFalse(status['verifications'][0]['current_pass'])
        self.assertEqual(status['verifications'][0]['verdict'],'passed')
        with self.assertRaises(ValueError):self.prepare(criteria(),'old')

    def test_cross_task_or_acceptance_receipt_is_rejected(self):
        receipt=self.run_tests()
        new=self.prepare(criteria(),'new-set')
        with self.assertRaises(ValueError):
            verification.verify(self.f['store'],self.f['task'],self.f['item']['decision_id'],1,new['acceptance_id'],[],receipt['execution_id'],'foreign')

    def test_mutation_during_execution_cannot_pass_current_snapshot(self):
        body='import unittest\nfrom pathlib import Path\nclass Checks(unittest.TestCase):\n def test_ok(self):\n  Path("app.py").write_text("changed")\n  self.assertTrue(True)\n'
        result=self.verify(self.run_tests(body))
        self.assertFalse(result['current_pass']);self.assertIn('INPUT_CHANGED_DURING_EXECUTION',result['stale_reasons'])

    def test_missing_code_and_private_manifest_paths_are_rejected(self):
        (self.f['workspace']/'app.py').rename(self.f['workspace']/'moved.py')
        with self.assertRaises((ValueError,OSError)):self.run_tests()
        self.assertEqual(self.verify()['verdict'],'inconclusive')
        value=json.loads((self.f['workspace']/'manifest.json').read_text())
        value['files']['implementation']=['.buildchoice_audit/ledger.sqlite3']
        (self.f['workspace']/'manifest.json').write_text(json.dumps(value))
        with self.assertRaises(ValueError):self.run_tests()

    def test_source_evidence_is_read_and_changes_invalidate_results(self):
        f=self.f;ledger=Ledger(f['workspace']);session=ledger.start('Code','Reference')
        source=ledger.read(session['id'],'app.py')
        refs=[{'criterion_id':'one','source_id':source['id'],'quote':'value = 1'}]
        result=self.verify(self.run_tests(),refs=refs)
        self.assertTrue(result['code_evidence'][0]['bound'])
        (f['workspace']/'app.py').write_text('value = 3\n')
        self.assertFalse(verification.present(f['store'],result)['current_pass'])

    def test_disabled_collector_service_and_old_ledger_rollback(self):
        self.f['global_settings'].write_text('{"config_version":1,"mode":"off"}')
        with self.assertRaises(ValueError):self.run_tests()
        self.f['settings'].write_text('{"config_version":2,"mode":"off","context_ttl_seconds":900}')
        with self.assertRaises(ValueError):self.prepare(criteria())
        ledger=Ledger(self.f['workspace']);session=ledger.start('Keep audit','Old data')
        result=rollback_decision_database(self.f['workspace'])
        self.assertTrue(result['audit_v1_preserved'])
        self.assertEqual(ledger.session(session['id'])['title'],'Keep audit')


if __name__=='__main__':unittest.main()
