"""Binding, candidate validation, evidence freshness and atomic-screen regressions."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'checks'))
from test_guidance import candidate
from buildchoice.desktop.audit import Ledger,encode
from buildchoice.desktop.decision_contracts import validate
from buildchoice.desktop.decision_service import DecisionService
from buildchoice.desktop.decision_store import DecisionStore,fingerprint,message_digest


class ScreenRecoveryTests(unittest.TestCase):
    def setUp(self):
        base=Path(os.environ.get('BUILDCHOICE_CHECK_ROOT',tempfile.gettempdir())).resolve()
        self.workspace=base/('buildchoice-screen-'+uuid.uuid4().hex);self.workspace.mkdir()
        self.settings=self.workspace/'v3.json'
        self.settings.write_text('{"config_version":2,"mode":"pilot","context_ttl_seconds":900}',encoding='utf-8')
        self.service=DecisionService(self.workspace,'screen-owner',settings_path=self.settings)
        self.store=DecisionStore(self.workspace)

    def request(self,**extras):
        return {'task_text':'Implement profile visibility','phase':'before_implementation',
            'next_step':'Implement visibility','candidates':[candidate()],
            'idempotency_key':'screen-key',**extras}

    def hook(self,prompt,turn='1',session='screen-host'):
        return self.store.observe_hook({'hook_event_name':'UserPromptSubmit','cwd':str(self.workspace),
            'session_id':session,'turn_id':turn,'prompt':prompt})['session_handle']

    def counts(self):
        with self.store.connect() as db:
            return {name:db.execute('SELECT count(*) FROM decision_v3_'+name).fetchone()[0]
                    for name in ('tasks','items','operations','events')}

    def evidence_request(self):
        path=self.workspace/'choice.json'
        path.write_text(json.dumps({'field':'Profile visibility','chosen':'Private'}),encoding='utf-8')
        ledger=Ledger(self.workspace);session=ledger.start('Synthetic requirement','Local fixture only')
        source=ledger.read(session['id'],'choice.json')
        choice={**candidate(),'risk_flags':[],'category':'business_rule',
            'evidence_refs':[{'source_id':source['id'],'pointer':'/chosen','relation':'constraint'}]}
        return path,self.request(candidates=[choice])

    def test_host_line_endings_and_boundary_empty_lines_match_without_changing_identity(self):
        body='修复页面布局\n保留正文  空格'
        for i,prompt in enumerate([body,body+'\n',body.replace('\n','\r\n')+'\r\n','\n'+body+'\n\n',body.replace('\n','\r')+'\r']):
            with self.subTest(prompt=repr(prompt)):
                handle=self.hook(prompt,session='host-'+str(i))
                result=self.service.screen(self.request(task_text=body,session_handle=handle))
                self.assertEqual(result['binding_status'],'hook_observed')
                self.assertEqual(self.service.screen(self.request(task_text=body+'\n',session_handle=handle)),result)
        a=self.hook(body,session='distinct');b=self.hook(body,session='distinct\n')
        self.assertNotEqual(a,b)

    def test_binding_still_rejects_body_space_indent_and_content_changes(self):
        body='Keep  both spaces\n  keep indentation'
        handle=self.hook(body+'\r\n')
        for changed in [body.replace('  both',' both'),body.replace('\n  keep','\n keep'),body+' and delete data']:
            with self.subTest(changed=changed),self.assertRaises(ValueError):
                self.service.screen(self.request(task_text=changed,session_handle=handle))
        self.assertEqual(self.counts()['tasks'],0)

    def test_legacy_terminal_newline_digests_remain_usable_without_rewriting_history(self):
        body='Implement profile visibility';handle=self.hook(body+'\n')
        with self.store.connect() as db:
            db.execute('UPDATE decision_v3_contexts SET prompt_digest=? WHERE handle=?',(message_digest(body+'\n'),handle))
        result=self.service.screen(self.request(task_text=body,session_handle=handle))
        with self.store.connect() as db:
            db.execute('UPDATE decision_v3_tasks SET task_digest=? WHERE id=?',(message_digest(body+'\n'),result['task_id']))
        status=self.service.screen(self.request(task_id=result['task_id'],task_text=body,session_handle=handle))
        self.assertEqual(status,result)
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT task_digest FROM decision_v3_tasks').fetchone()[0],message_digest(body+'\n'))

    def test_revision_and_initial_screen_share_option_and_recommendation_checks(self):
        result=self.service.screen(self.request());item=result['decisions'][0]
        bad_ids=candidate();bad_ids['options'][1]['id']='A'
        bad_recommendation=candidate();bad_recommendation['recommended_option_id']='C'
        before=self.counts()
        for bad in (bad_ids,bad_recommendation):
            with self.subTest(candidate=bad):
                with self.assertRaises(ValueError):validate('ScreenRequest',self.request(candidates=[bad]))
                with self.assertRaises(ValueError):
                    self.service.prepare_revision(result['task_id'],item['decision_id'],1,bad,'Invalid revision')
        self.assertEqual(self.counts(),before)
        valid=candidate();valid['options'][1]['id']='C';valid['recommended_option_id']='C'
        valid['recommendation_reason']='Keeps the chosen scope explicit.'
        revision=self.service.prepare_revision(result['task_id'],item['decision_id'],1,valid,'Valid revision')
        self.assertEqual(revision['revision'],2)
        self.assertEqual(revision['card']['recommendation']['option_id'],'C')

    def test_cached_proceed_is_rejected_after_source_change_or_removal(self):
        path,request=self.evidence_request()
        first=self.service.screen(request)
        self.assertEqual(first['decisions'][0]['status'],'PROCEED')
        self.assertEqual(self.service.screen(request),first)
        path.write_text(json.dumps({'field':'Profile visibility','chosen':'Shared'}),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'CACHED_SCREEN_STALE'):self.service.screen(request)
        fresh=self.service.screen({**request,'idempotency_key':'fresh'})
        self.assertEqual(fresh['decisions'][0]['status'],'ASK_NOW')
        path.unlink()
        with self.assertRaisesRegex(ValueError,'CACHED_SCREEN_STALE'):
            self.service.screen({**request,'idempotency_key':'fresh'})

    def test_cache_checks_coverage_resources_and_confirmed_decision_state(self):
        path,request=self.evidence_request()
        refs=request['candidates'][0]['evidence_refs']
        coverage=self.request(candidates=[],coverage=[{'dimension':'access_visibility','status':'resolved',
            'reason':'Read local fixture.','evidence_refs':refs}])
        self.service.screen(coverage);path.write_text('Changed',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'CACHED_SCREEN_STALE'):self.service.screen(coverage)
        resource=self.workspace/'unread.txt';resource.write_text('First',encoding='utf-8')
        resources=self.request(task_text='Inspect unread file',resources=[{'path':'unread.txt','covers':['Profile visibility']}])
        self.service.screen(resources);resource.write_text('Second',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'CACHED_SCREEN_STALE'):self.service.screen(resources)
        handle=self.hook('Implement profile visibility')
        observed=self.request(session_handle=handle,idempotency_key='observed')
        result=self.service.screen(observed);item=result['decisions'][0]
        self.service.activate(result['task_id'],item['decision_id'],1,'activate',handle)
        fresh_handle=self.hook('A',turn='2')
        with self.assertRaisesRegex(ValueError,'CACHED_SCREEN_STALE'):
            self.service.screen({**observed,'task_id':result['task_id'],'session_handle':fresh_handle})

    def test_source_change_during_screen_rolls_back_instead_of_caching_a_mixed_snapshot(self):
        path,request=self.evidence_request();before=self.counts()
        original=self.service.evidence
        def change_after_read(*args):
            result=original(*args)
            path.write_text(json.dumps({'field':'Profile visibility','chosen':'Shared'}),encoding='utf-8')
            return result
        with patch.object(self.service,'evidence',side_effect=change_after_read):
            with self.assertRaisesRegex(ValueError,'SCREEN_INPUT_CHANGED_DURING_EVALUATION'):
                self.service.screen(request)
        self.assertEqual(self.counts(),before)
        self.assertEqual(self.service.screen(request)['decisions'][0]['status'],'ASK_NOW')

    def test_interrupted_result_write_rolls_back_task_items_context_and_operation(self):
        handle=self.hook('Implement profile visibility');request=self.request(session_handle=handle)
        before=self.counts()
        with patch.object(DecisionStore,'finish_operation',side_effect=OSError('simulated interrupted persistence')):
            with self.assertRaises(OSError):self.service.screen(request)
        self.assertEqual(self.counts(),before)
        with self.store.connect() as db:
            row=db.execute('SELECT owner,task_id FROM decision_v3_contexts WHERE handle=?',(handle,)).fetchone()
            self.assertEqual(tuple(row),(None,None))
        result=self.service.screen(request)
        self.assertEqual(len(result['decisions']),1)
        self.assertEqual(self.counts()['operations'],1)

    def test_mid_batch_failure_rolls_back_earlier_candidate_and_keeps_existing_history(self):
        saved=self.service.screen(self.request(task_text='Existing task',idempotency_key='existing'))
        before=self.counts();original=DecisionStore.write_item
        def fail_second(store,task_id,key,cand,result,existing=None):
            original(store,task_id,key,cand,result,existing)
            if cand['candidate_id']=='second':raise OSError('simulated second-candidate failure')
        other={**candidate(),'candidate_id':'second','field':'Second choice'}
        request=self.request(task_text='New batch',candidates=[candidate(),other])
        with patch.object(DecisionStore,'write_item',fail_second):
            with self.assertRaises(OSError):self.service.screen(request)
        self.assertEqual(self.counts(),before)
        self.assertEqual(self.service.status(saved['task_id'])['decisions'][0]['revision'],1)
        self.assertEqual(len(self.service.screen(request)['decisions']),2)

    def test_legacy_incomplete_marker_is_recovered_but_completed_legacy_cache_is_not_reused(self):
        request=self.request();first=self.service.screen(request)
        with self.store.connect() as db:
            db.execute("UPDATE decision_v3_operations SET input_digest=?,response_json=NULL WHERE operation='screen'",(fingerprint(request),))
        recovered=self.service.screen(request)
        self.assertEqual(recovered['decisions'][0]['decision_id'],first['decisions'][0]['decision_id'])
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM decision_v3_operations WHERE response_json IS NULL').fetchone()[0],0)
            db.execute("UPDATE decision_v3_operations SET response_json=? WHERE operation='screen'",(encode(first),))
        with self.assertRaisesRegex(ValueError,'CACHED_SCREEN_STALE'):self.service.screen(request)

    def test_concurrent_identical_requests_commit_once_and_replay_same_response(self):
        request=self.request();entered=threading.Event();release=threading.Event()
        original=DecisionStore.finish_operation;calls=[]
        def pause_finish(store,*args):
            calls.append(1);entered.set()
            if not release.wait(5):raise RuntimeError('Test synchronization timed out')
            return original(store,*args)
        with patch.object(DecisionStore,'finish_operation',pause_finish),ThreadPoolExecutor(max_workers=2) as pool:
            first=pool.submit(self.service.screen,request)
            self.assertTrue(entered.wait(5))
            second=pool.submit(self.service.screen,request)
            time.sleep(0.1);release.set()
            a=first.result(timeout=10);b=second.result(timeout=10)
        self.assertEqual(a,b);self.assertEqual(len(calls),1)
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM decision_v3_events WHERE event_type='COVERAGE_RECORDED'").fetchone()[0],1)


if __name__=='__main__':unittest.main()
