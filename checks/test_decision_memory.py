"""Synthetic host events: memory retention, explicit commands and cross-chat policy reuse."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from buildchoice.desktop.audit import Ledger
from buildchoice.desktop.decision_service import DecisionService
from buildchoice.desktop.decision_store import DecisionStore
from buildchoice.desktop.decision_settings import update
from buildchoice.desktop import decision_memory as memory
from test_guidance import candidate


def rule_candidate():
    value=candidate()
    value.update(field='Receipt saving',category='business_rule',risk_flags=[],memory_intent='reuse',
        question='When should a receipt be saved?',impact='Controls when the ledger changes.')
    value['options']=[{'id':'A','label':'Review first','tradeoff':'Only save after review.'},
                      {'id':'B','label':'Automatic','tradeoff':'Save as soon as recognition ends.'}]
    return value


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.workspace=Path(tempfile.mkdtemp(prefix='buildchoice-memory-')).resolve()
        self.settings=self.workspace/'settings.json'
        update('pilot',self.settings)
        self.store=DecisionStore(self.workspace)
        self.service=DecisionService(self.workspace,'owner-1',self.settings)
        self.turn=0

    def hook(self,prompt,session='chat-1'):
        self.turn+=1
        return self.store.observe_hook({'hook_event_name':'UserPromptSubmit','cwd':str(self.workspace),
            'session_id':session,'turn_id':str(self.turn),'prompt':prompt})

    def request(self,prompt,handle,cand=None):
        return {'task_text':prompt,'phase':'before_implementation','next_step':'Implement receipt saving',
            'session_handle':handle,'idempotency_key':uuid.uuid4().hex,
            'candidates':[rule_candidate() if cand is None else cand]}

    def confirm(self,choice='A',cand=None,session='chat-1',service=None):
        service=service or self.service
        prompt='Implement saving '+uuid.uuid4().hex
        handle=self.hook(prompt,session)['session_handle']
        result=service.screen(self.request(prompt,handle,cand));item=result['decisions'][0]
        service.activate(result['task_id'],item['decision_id'],1,uuid.uuid4().hex,handle)
        reply=self.hook(choice,session)
        entries=service.memory('',True,reply['session_handle'])['entries']
        entry=next(e for e in entries if e['decision_id']==item['decision_id'])
        return result,item,reply['session_handle'],entry

    def command(self,word,entry,session='chat-1'):
        return self.hook(word+' '+entry['memory_id'],session)

    def new_screen(self,cand=None,service=None,session='chat-2'):
        service=service or DecisionService(self.workspace,'owner-2',self.settings)
        prompt='Continue receipt saving '+uuid.uuid4().hex
        handle=self.hook(prompt,session)['session_handle']
        request=self.request(prompt,handle,cand)
        return service,request,service.screen(request)

    def test_observed_choices_automatically_recalled_across_chat_without_task_access(self):
        first,item,handle,entry=self.confirm()
        self.assertEqual((entry['tier'],entry['state']),('reference','active'))
        other=DecisionService(self.workspace,'owner-2',self.settings)
        fresh=self.hook('Continue the receipt feature','chat-2')['session_handle']
        recalled=other.memory('Receipt',False,fresh)
        self.assertEqual(recalled['entries'][0]['confirmation_id'],entry['confirmation_id'])
        with self.assertRaisesRegex(ValueError,'host session'):
            other.status(first['task_id'],fresh)
        with self.assertRaises(ValueError):other.memory()
        self.assertEqual(self.new_screen()[2]['decisions'][0]['status'],'ASK_NOW')

    def test_no_unconfirmed_or_agent_reported_memory(self):
        request=self.request('Unverified',None)
        self.service.screen(request)
        handle=self.hook('Current task')['session_handle']
        self.assertEqual(self.service.memory('',True,handle)['entries'],[])

    def test_reference_archives_at_exact_30_days_and_reads_do_not_renew(self):
        _,_,_,entry=self.confirm()
        expires=entry['expires_at']
        with self.store.connect() as db:
            self.assertEqual(memory.records(self.store,db,expires-0.001)[0]['state'],'active')
            self.assertEqual(memory.records(self.store,db,expires)[0]['state'],'archived')
        with patch.object(memory.time,'time',return_value=expires):
            with self.store.connect() as db:
                self.assertEqual(memory.recall(self.store,db)['entries'],[])
                self.assertEqual(memory.recall(self.store,db,include_archived=True)['entries'][0]['state'],'archived')
                self.assertEqual(memory.recall(self.store,db,include_archived=True)['entries'][0]['expires_at'],expires)

    def test_explicit_promote_persists_rule_and_reuses_without_fabricating_confirmation(self):
        _,_,_,entry=self.confirm()
        outcome=self.command('长期记住',entry)
        self.assertEqual(outcome['memory_action'],'promote')
        with self.store.connect() as db:
            current=memory.records(self.store,db,entry['expires_at']+100)[0]
            self.assertEqual((current['tier'],current['state'],current['expires_at']),('rule','active',None))
        service,request,response=self.new_screen()
        decision=response['decisions'][0]
        self.assertEqual((decision['status'],decision['confirmation_status']),('PROCEED','project_rule_reused'))
        status=service.status(response['task_id'],request['session_handle'])
        self.assertIsNone(status['decisions'][0]['confirmation'])
        self.assertEqual(status['confirmation_history'],[])
        self.assertEqual(decision['memory']['source_confirmation_id'],entry['confirmation_id'])

    def test_forget_restore_unpin_and_duplicate_hook_keep_history(self):
        _,_,_,entry=self.confirm()
        self.command('长期记住',entry)
        self.command('遗忘',entry)
        with self.store.connect() as db:
            self.assertEqual(memory.records(self.store,db)[0]['state'],'forgotten')
            self.assertEqual(db.execute('SELECT count(*) FROM decision_v3_confirmations').fetchone()[0],1)
        self.command('恢复',entry)
        outcome=self.command('取消长期',entry)
        with self.store.connect() as db:
            current=memory.records(self.store,db)[0]
            self.assertEqual((current['tier'],current['state']),('reference','active'))
            self.assertGreaterEqual(current['expires_at'],entry['expires_at'])
            count=db.execute("SELECT count(*) FROM decision_v3_events WHERE event_type='MEMORY_ACTION_OBSERVED'").fetchone()[0]
        event={'hook_event_name':'UserPromptSubmit','cwd':str(self.workspace),'session_id':'chat-1',
            'turn_id':str(self.turn),'prompt':'取消长期 '+entry['memory_id']}
        self.assertEqual(self.store.observe_hook(event),outcome)
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM decision_v3_events WHERE event_type='MEMORY_ACTION_OBSERVED'").fetchone()[0],count)

    def test_archived_reference_can_be_restored_with_a_fresh_window(self):
        _,_,_,entry=self.confirm()
        at=entry['expires_at']+10
        with self.store.connect() as db:
            rejected=memory.observe_command(self.store,db,'长期记住 '+entry['memory_id'],'fixture',at)
            self.assertEqual(rejected['memory_status'],'rejected')
            memory.observe_command(self.store,db,'恢复 '+entry['memory_id'],'fixture',at)
            restored=memory.records(self.store,db,at)[0]
            self.assertEqual(restored['expires_at'],at+memory.REFERENCE_SECONDS)
            self.assertEqual(restored['state'],'active')

    def test_commands_cannot_be_quoted_embedded_or_applied_during_a_card(self):
        _,_,_,entry=self.confirm()
        for prompt in ['请解释长期记住 '+entry['memory_id'], '"遗忘 '+entry['memory_id']+'"',
                       '长期记住 '+entry['memory_id']+' 并部署', '长期记住 M000000000000']:
            self.hook(prompt)
        with self.store.connect() as db:self.assertEqual(memory.records(self.store,db)[0]['tier'],'reference')
        prompt='Another decision';handle=self.hook(prompt)['session_handle']
        res=self.service.screen(self.request(prompt,handle))
        self.service.activate(res['task_id'],res['decisions'][0]['decision_id'],1,'active',handle)
        self.assertNotIn('memory_action',self.command('长期记住',entry))
        with self.store.connect() as db:self.assertEqual(memory.records(self.store,db)[0]['tier'],'reference')

    def test_foreign_project_and_expired_context_do_not_expose_memory(self):
        _,_,handle,_=self.confirm()
        other=Path(tempfile.mkdtemp(prefix='buildchoice-other-memory-'))
        service=DecisionService(other,'other',self.settings)
        with self.assertRaises(ValueError):service.memory('',True,handle)
        with self.store.connect() as db:db.execute('UPDATE decision_v3_contexts SET expires=0')
        with self.assertRaises(ValueError):self.service.memory('',True,handle)

    def test_conflicting_project_rules_never_silently_choose_a_winner(self):
        _,_,_,a=self.confirm('A');self.command('长期记住',a)
        # Sensitive flag forces a fresh task choice, then create the conflicting rule.
        changed=rule_candidate();changed['risk_flags']=['privacy']
        _,_,_,b=self.confirm('B',changed);self.command('长期记住',b)
        service,req,res=self.new_screen()
        self.assertEqual(res['decisions'][0]['status'],'ASK_NOW')
        self.assertEqual(res['decisions'][0]['memory']['status'],'conflict')
        self.assertEqual(len(service.memory('',False,req['session_handle'])['conflicts']),1)

    def test_changed_option_meaning_scope_and_sensitive_actions_require_current_choice(self):
        _,_,_,entry=self.confirm();self.command('长期记住',entry)
        for mutate in [lambda c:c['options'][0].update(tradeoff='Save immediately too.'),
                       lambda c:c.update(category='access_control'),
                       lambda c:c.update(risk_flags=['payment']),
                       lambda c:c['options'][0].update(label='Something else')]:
            changed=rule_candidate();mutate(changed)
            self.assertEqual(self.new_screen(changed)[2]['decisions'][0]['status'],'ASK_NOW')
        unrelated=rule_candidate();unrelated['field']='Other saving policy'
        self.assertNotIn('memory',self.new_screen(unrelated)[2]['decisions'][0])

    def test_same_meaning_reordered_options_reuse_the_new_choice_id(self):
        cand=rule_candidate();cand['options'][0]['value']='review';cand['options'][1]['value']='auto'
        _,_,_,entry=self.confirm(cand=cand);self.command('长期记住',entry)
        cand=deepcopy(cand);cand['options'][0]['id']='B';cand['options'][1]['id']='A'
        decision=self.new_screen(cand)[2]['decisions'][0]
        self.assertEqual(decision['status'],'PROCEED')
        self.assertEqual(decision['memory']['choice_id'],'B')

    def test_explicit_change_or_unclear_scope_never_silently_reuses_the_old_rule(self):
        _,_,_,entry=self.confirm();self.command('长期记住',entry)
        for intent in ('change','uncertain',None):
            cand=rule_candidate()
            if intent is None:cand.pop('memory_intent')
            else:cand['memory_intent']=intent
            decision=self.new_screen(cand)[2]['decisions'][0]
            self.assertEqual(decision['status'],'ASK_NOW')
            self.assertIn(decision['memory']['reason'],('PROJECT_RULE_CHANGE_REQUESTED','PROJECT_RULE_SCOPE_UNCERTAIN'))

    def test_forgetting_invalidates_cached_and_live_reused_status(self):
        _,_,_,entry=self.confirm();self.command('长期记住',entry)
        service,req,res=self.new_screen()
        self.assertEqual(service.screen(req),res)
        self.command('遗忘',entry,session='chat-3')
        with self.assertRaisesRegex(ValueError,'CACHED_SCREEN_STALE'):service.screen(req)
        state=service.status(res['task_id'],req['session_handle'])['decisions'][0]
        self.assertEqual(state['confirmation_status'],'project_rule_stale')
        self.assertEqual(state['status'],'ASK_NOW')

    def test_superseded_rule_cannot_be_restored_or_reused(self):
        task,item,_,entry=self.confirm();pin=self.command('长期记住',entry)
        self.service.prepare_revision(task['task_id'],item['decision_id'],1,rule_candidate(),'Change saving policy',pin['session_handle'])
        outcome=self.command('恢复',entry)
        self.assertEqual(outcome['memory_status'],'rejected')
        with self.store.connect() as db:self.assertEqual(memory.records(self.store,db)[0]['state'],'superseded')
        self.assertEqual(self.new_screen()[2]['decisions'][0]['status'],'ASK_NOW')

    def test_changed_evidence_stops_old_rule_and_does_not_renew_on_restore(self):
        path=self.workspace/'policy.txt';path.write_text('Receipt review policy',encoding='utf-8')
        ledger=Ledger(self.workspace);audit=ledger.start('Fixture','Synthetic source')
        source=ledger.read(audit['id'],'policy.txt')
        cand=rule_candidate();cand['evidence_refs']=[{'source_id':source['id'],'quote':'Receipt review policy'}]
        _,_,_,entry=self.confirm(cand=cand);self.command('长期记住',entry)
        path.write_text('Changed policy',encoding='utf-8')
        self.command('恢复',entry)
        with self.store.connect() as db:self.assertEqual(memory.records(self.store,db)[0]['state'],'needs_review')
        self.assertEqual(self.new_screen()[2]['decisions'][0]['status'],'ASK_NOW')

    def test_conflicting_file_constraint_requires_resolution(self):
        _,_,_,entry=self.confirm();self.command('长期记住',entry)
        path=self.workspace/'choice.json';path.write_text(json.dumps({'field':'Receipt saving','chosen':'Automatic'}),encoding='utf-8')
        ledger=Ledger(self.workspace);audit=ledger.start('Fixture','Synthetic conflicting source')
        source=ledger.read(audit['id'],'choice.json')
        cand=rule_candidate();cand['evidence_refs']=[{'source_id':source['id'],'pointer':'/chosen','relation':'constraint'}]
        decision=self.new_screen(cand)[2]['decisions'][0]
        self.assertEqual(decision['status'],'ASK_NOW')
        self.assertEqual(decision['memory']['reason'],'PROJECT_RULE_CONFLICTS_WITH_SOURCE')

    def test_reused_task_source_change_invalidates_live_status(self):
        _,_,_,entry=self.confirm();self.command('长期记住',entry)
        path=self.workspace/'current.json';path.write_text(json.dumps({'field':'Receipt saving','chosen':'Review first'}),encoding='utf-8')
        ledger=Ledger(self.workspace);audit=ledger.start('Fixture','Current matching source')
        source=ledger.read(audit['id'],'current.json')
        cand=rule_candidate();cand['evidence_refs']=[{'source_id':source['id'],'pointer':'/chosen','relation':'constraint'}]
        service,req,res=self.new_screen(cand)
        self.assertEqual(res['decisions'][0]['confirmation_status'],'project_rule_reused')
        path.write_text('Changed',encoding='utf-8')
        self.assertEqual(service.status(res['task_id'],req['session_handle'])['decisions'][0]['confirmation_status'],'project_rule_stale')

    def test_deduplication_does_not_discard_conflicting_memory_intent(self):
        from buildchoice.desktop.candidate_policy import deduplicate
        a=rule_candidate();b=deepcopy(a);b.update(candidate_id='other',memory_intent='change')
        self.assertEqual(deduplicate([a,b])[0]['memory_intent'],'uncertain')

    def test_off_mode_and_query_bounds(self):
        _,_,handle,_=self.confirm()
        with self.assertRaises(ValueError):self.service.memory('x'*2001,False,handle)
        update('off',self.settings)
        with self.assertRaisesRegex(ValueError,'V3_DISABLED'):self.service.memory('',True,handle)


if __name__=='__main__':unittest.main()
