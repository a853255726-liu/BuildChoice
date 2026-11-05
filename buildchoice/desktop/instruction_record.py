"""Record the LLM's interpretation of an actual instruction without inventing a card."""
import json
import uuid
from .audit import encode, now
from .decision_contracts import validate
from .decision_store import canonical_prompt, fingerprint, prompt_matches
from . import decision_memory as memory

PROVENANCE = 'llm_interpreted_user_instruction'


def tables(db):
    db.execute('''CREATE TABLE IF NOT EXISTS decision_v3_instructions(
        workspace TEXT, host TEXT, key TEXT, turn TEXT, target TEXT, digest TEXT,
        response TEXT, PRIMARY KEY(workspace,host,key), UNIQUE(workspace,host,turn,target))''')


def meaning(candidate, choice):
    # Literal equality only; semantic equivalence remains the LLM's responsibility.
    return {k:candidate.get(k,default) for k,default in
        (('decision_key',''),('scope_key','project'),('category','business_rule'),('conditions',[]))} | {
        'choice':{k:choice.get(k,default) for k,default in
            (('value',choice['label']),('behavior',None),('conditions',[]))}}


def record(service, store, request):
    request=validate('InstructionRequest',request)
    handle=request['session_handle']
    supplied=request.get('decision')
    ident=request.get('decision_id')
    expected=request['expected_revision']
    if bool(ident)!=(expected>0):raise ValueError('decision_id and current expected_revision are required together')
    if not ident and not supplied:raise ValueError('A new decision requires decision and expected_revision=0')
    if supplied and request.get('choice_id'):raise ValueError('Supply decision or choice_id, not both')
    text=canonical_prompt(request['user_message'])
    quote=request.get('quote',text)
    if not quote.strip() or len(quote)>2000 or quote not in text:raise ValueError('An exact bounded instruction quote is required')
    digest=fingerprint({k:v for k,v in request.items() if k not in
        ('session_handle','idempotency_key','quote','reason','user_message')} | {'message':text})
    with store.transaction() as db:
        tables(db)
        ctx=store.context(db,handle,service.owner,claim=True)
        if ctx is None or not prompt_matches(ctx['prompt_digest'],text):
            raise ValueError('Full user_message must match the current actual Hook message')
        workspace=str(store.workspace);host=ctx['host_session_digest'];key=request['idempotency_key']
        target=ident or supplied['decision_key']+'@'+supplied.get('scope_key','project')
        previous=db.execute('SELECT * FROM decision_v3_instructions WHERE workspace=? AND host=? AND '
            '(key=? OR (turn=? AND target=?))',(workspace,host,key,ctx['host_turn_digest'],target)).fetchall()
        if previous:
            if any(r['digest']!=digest for r in previous):raise ValueError('Instruction retry conflicts with the recorded input')
            result=json.loads(previous[0]['response']);result['replayed']=True
            # A replay is a receipt, never an instruction to reinstate an old version.
        else:
            old=None;confirmation=None
            if ident:
                old=db.execute('SELECT * FROM decision_v3_items WHERE id=? ORDER BY revision DESC LIMIT 1',(ident,)).fetchone()
                if old is None:raise ValueError('Unknown decision')
                task=store.task(old['task_id'],service.owner,handle)
                if old['revision']!=expected:raise ValueError('DECISION_REVISION_CHANGED: read the current version before updating')
                prior=json.loads(old['candidate_json']);confirmation=store.confirmation(old)
                for event in db.execute("SELECT data_json FROM decision_v3_events WHERE task_id=? AND event_type='USER_INSTRUCTION_RECORDED'",(task['id'],)):
                    value=json.loads(event[0])
                    if value['decision_id']==ident and value['host_turn_digest']==ctx['host_turn_digest']:
                        raise ValueError('This instruction already has a recorded interpretation; reuse the original request')
            else:
                # Refuse duplicate canonical records within this chat, even across task scopes.
                for row in db.execute('SELECT i.* FROM decision_v3_items i JOIN decision_v3_tasks t ON t.id=i.task_id '
                        'WHERE t.workspace=? AND t.host_session_digest=? AND i.revision='
                        '(SELECT max(revision) FROM decision_v3_items WHERE id=i.id)',(workspace,host)):
                    candidate=json.loads(row['candidate_json'])
                    if memory.decision_key(candidate)==supplied['decision_key'] and candidate.get('scope_key','project')==supplied.get('scope_key','project'):
                        raise ValueError('Existing decision requires decision_id='+row['id']+' and expected_revision='+str(row['revision']))
                task=store.open_task(text,'unspecified',service.owner,handle)
            if supplied:
                candidate={**(prior if old else {}),**{k:v for k,v in supplied.items() if k!='choice'}}
                if old and memory.decision_key(prior)!=supplied['decision_key']:raise ValueError('A revision must retain its decision_key')
                choice={'id':'A','tradeoff':'','conditions':[],**supplied['choice']}
                candidate.update(candidate_id='instruction',question=supplied['field'],impact=request['reason'],
                    category=candidate.get('category','business_rule'),scope_key=candidate.get('scope_key','project'),
                    conditions=candidate.get('conditions',[]),risk_flags=[],evidence_refs=supplied.get('evidence_refs',[]),
                    options=[choice],recommended_option_id=None,record_kind='user_instruction',suggested_action='PROCEED')
            elif request.get('choice_id'):
                candidate=prior
                choice=next((o for o in prior['options'] if o['id']==request['choice_id']),None)
                if choice is None:raise ValueError('choice_id is not an offered option')
            elif confirmation and confirmation['applicable']:
                candidate=prior;choice=next(o for o in prior['options'] if o['id']==confirmation['choice_id'])
            else:raise ValueError('A pending decision requires decision or choice_id')
            evidence=service.evidence(store,candidate,[],host)
            if evidence['invalid'] or evidence['conflict']:raise ValueError('Instruction references are invalid, changed or conflicting')
            chosen_before=next((o for o in prior['options'] if confirmation and o['id']==confirmation['choice_id']),None) if old else None
            unchanged=bool(chosen_before and confirmation['applicable'] and meaning(prior,chosen_before)==meaning(candidate,choice))
            if unchanged:
                revision=expected;choice=chosen_before
            else:
                matches=[o for o in prior['options'] if meaning(prior,o)==meaning(candidate,choice)] if old else []
                # A clear instruction may answer a prepared proposal that was never activated.
                answer_pending=bool(old and not confirmation and len(matches)==1)
                if answer_pending:candidate=prior;choice=matches[0]
                revision=expected if answer_pending else expected+1
                ident=ident or 'decision-'+uuid.uuid4().hex
                if old and not answer_pending:
                    db.execute("UPDATE decision_v3_items SET state='superseded' WHERE id=?",(ident,))
                routing={'decision_id':ident,'revision':revision,'candidate_id':candidate['candidate_id'],'field':candidate['field'],
                    'status':'PROCEED','suggested_action':'PROCEED','validation_status':'valid','card':None,
                    'confirmation_status':PROVENANCE,'reason_codes':['OBSERVED_USER_INSTRUCTION'],'semantic_judgment_by':'llm'}
                if answer_pending:
                    db.execute("UPDATE decision_v3_items SET state='confirmed',routing_json=? WHERE id=? AND revision=?",
                        (encode(routing),ident,revision))
                else:
                    db.execute('INSERT INTO decision_v3_items VALUES(?,?,?,?,?,?,?,?,?)',
                        (ident,revision,task['id'],old['field_key'] if old else 'key:'+supplied['decision_key'],
                         encode(candidate),encode(routing),'confirmed',0,now()))
                db.execute('INSERT INTO decision_v3_confirmations VALUES(?,?,?,?,?,?,?,?)',
                    ('conf-'+uuid.uuid4().hex,ident,revision,choice['id'],PROVENANCE,ctx['host_turn_digest'],ctx['prompt_digest'],now()))
            db.execute('UPDATE decision_v3_active SET decision_id=NULL,revision=NULL WHERE workspace=? AND host_session_digest=? AND decision_id=?',
                (workspace,host,ident))
            source={'quote':quote,'reason':request['reason'],'user_prompt_digest':ctx['prompt_digest'],
                'host_turn_digest':ctx['host_turn_digest'],'provenance':PROVENANCE,'semantic_verified_by_program':False}
            store.event(db,task['id'],'USER_INSTRUCTION_RECORDED',{'decision_id':ident,'revision':revision,**source})
            result={'schema_version':'instruction.v1','recorded':True,'task_id':task['id'],'decision_id':ident,
                'revision':revision,'choice':choice,'unchanged':unchanged,'replayed':False,'source':source,
                'semantic_verified_by_program':False,'does_not_authorize_host_operations':True}
            db.execute('INSERT INTO decision_v3_instructions VALUES(?,?,?,?,?,?,?)',
                (workspace,host,key,ctx['host_turn_digest'],target,digest,encode(result)))
            from .document_projection import queue
            queue(service,store,handle)
        latest=db.execute('SELECT max(revision) FROM decision_v3_items WHERE id=?',(result['decision_id'],)).fetchone()[0]
        result.update(latest_revision=latest,current=latest==result['revision'])
    from .document_projection import publish
    result['document']=publish(service,store,handle)
    return result
