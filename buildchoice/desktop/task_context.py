"""Bounded context assembly and literal changes; never decides business relevance."""
import hashlib
import json
import time
import uuid
from .audit import encode, now, MAX_BYTES
from . import decision_memory as memory


def authorize(service, store, handle, task_id=None):
    with store.connect() as db:
        ctx=store.context(db,handle,service.owner,claim=True)
    if ctx is None:raise ValueError('A current observed Hook handle is required')
    if task_id:store.task(task_id,service.owner,handle)
    return ctx


def host_tasks(store, ctx, task_id=None):
    with store.connect() as db:
        if task_id:
            rows=db.execute('SELECT * FROM decision_v3_tasks WHERE id=? AND workspace=? AND host_session_digest=?',
                (task_id,str(store.workspace),ctx['host_session_digest'])).fetchall()
        else:
            rows=db.execute('SELECT * FROM decision_v3_tasks WHERE workspace=? AND host_session_digest=? ORDER BY created DESC,id LIMIT 50',
                (str(store.workspace),ctx['host_session_digest'])).fetchall()
            active=db.execute('SELECT t.* FROM decision_v3_active a JOIN decision_v3_items i '
                'ON i.id=a.decision_id AND i.revision=a.revision JOIN decision_v3_tasks t ON t.id=i.task_id '
                'WHERE a.workspace=? AND a.host_session_digest=?',
                (str(store.workspace),ctx['host_session_digest'])).fetchone()
            if active and active['id'] not in {r['id'] for r in rows}:rows.append(active)
    return [dict(row) for row in rows]


def file_state(store, path):
    try:
        resolved=store.ledger.path(path)
        with resolved.open('rb') as stream:raw=stream.read(MAX_BYTES+1)
        if len(raw)>MAX_BYTES:return {'available':False,'reason':'oversized'}
        return {'available':True,'sha256':hashlib.sha256(raw).hexdigest()}
    except (OSError,ValueError):return {'available':False,'reason':'unavailable'}


def source_state(store, ident):
    with store.connect() as db:
        row=db.execute('SELECT s.* FROM sources s JOIN sessions t ON t.id=s.session WHERE s.id=? AND t.workspace=?',
            (ident,str(store.workspace))).fetchone()
    if not row:return {'source_id':ident,'current':False,'reason':'unknown_source'}
    state=file_state(store,row['locator'])
    return {'source_id':ident,'path':row['locator'],'recorded_sha256':row['digest'],
        'current_sha256':state.get('sha256'),'current':state.get('sha256')==row['digest'] and state['available']}


def build(service, store, handle, query='', paths=None, task_id=None, since=None, max_chars=12000):
    paths=paths or []
    if not isinstance(query,str) or len(query)>2000:raise ValueError('Query must be at most 2000 characters')
    if not isinstance(paths,list) or len(paths)>20 or any(not isinstance(p,str) or not 1<=len(p)<=512 for p in paths):
        raise ValueError('At most 20 bounded relative paths are allowed')
    if type(max_chars) is not int or not 2000<=max_chars<=50000:raise ValueError('max_chars must be 2000..50000')
    ctx=authorize(service,store,handle,task_id);host=ctx['host_session_digest']
    with store.connect() as db:
        db.execute('CREATE TABLE IF NOT EXISTS buildchoice_context_snapshots(id TEXT PRIMARY KEY,workspace TEXT,host TEXT,data_json TEXT,created TEXT)')
        previous=db.execute('SELECT * FROM buildchoice_context_snapshots WHERE id=? AND workspace=? AND host=?',
            (since,str(store.workspace),host)).fetchone() if since else None
    if since and previous is None:raise ValueError('Context snapshot is missing or belongs to another project/chat')
    session='audit-context-'+hashlib.sha256((str(store.workspace)+host).encode()).hexdigest()[:20]
    tasks=host_tasks(store,ctx,task_id)
    observed=store.ledger.observed_reads(host)
    with store.connect() as db:
        cached=[dict(r) for r in db.execute('SELECT * FROM sources WHERE session=? ORDER BY rowid DESC LIMIT 100',(session,))]
        # Explicit collector reads become reusable only through a decision in this chat.
        ids={ref['source_id'] for task in tasks for item in store.items(task['id'])
            for ref in json.loads(item['candidate_json']).get('evidence_refs',[])}
        for ident in sorted(ids):
            row=db.execute('SELECT s.* FROM sources s JOIN sessions t ON t.id=s.session '
                'WHERE s.id=? AND t.workspace=? AND s.origin=?',
                (ident,str(store.workspace),'collector_file_read')).fetchone()
            if row:cached.append(dict(row))
    by_path={}
    def add_receipt(value):
        prior=by_path.get(value['path'])
        if (prior is None or (value['current'] and not prior['current']) or
                (value['current'] and prior['current'] and value['full_file'] and not prior['full_file'])):
            by_path[value['path']]=value
    for value in observed:
        add_receipt(value)
    for value in cached:
        state=source_state(store,value['id'])
        add_receipt({'source_id':value['id'],'path':value['locator'],'file_sha256':value['digest'],
            'current':state['current'],'full_file':True})
    receipts=list(by_path.values())
    explicit=[]
    for relative in dict.fromkeys(paths):
        path=store.ledger.path(relative).relative_to(store.workspace).as_posix()
        found=next((r for r in receipts if r['path']==path and r['current'] and r['full_file']),None)
        if found:
            with store.connect() as db:row=dict(db.execute('SELECT * FROM sources WHERE id=?',(found['source_id'],)).fetchone())
            try:content=store.ledger.source_text(row);reused=True
            except (OSError,ValueError,UnicodeError):found=None
        if not found:
            with store.connect() as db:
                db.execute('INSERT OR IGNORE INTO sessions VALUES(?,?,?,?,?,?)',
                    (session,str(store.workspace),'Task context sources','',now(),'collector_file_read'))
            row=store.ledger.read(session,path);content=row['content'];reused=row['reused']
            found={'source_id':row['id'],'path':path,'file_sha256':row['digest'],'full_file':True,'current':True}
        explicit.append({**found,'content':content,'reused':reused,'provenance':row['origin']})
        receipts=[r for r in receipts if r['path']!=path]+[found]
    pending=[];decisions_snapshot={}
    with store.connect() as db:
        hidden={(r['decision_id'],r['revision']) for r in memory.records(store,db) if r['state'] not in ('active','needs_review')}
    with store.connect() as db:
        active=db.execute('SELECT * FROM decision_v3_active WHERE workspace=? AND host_session_digest=?',
            (str(store.workspace),host)).fetchone()
    for task in tasks:
        for row in store.items(task['id']):
            if task_id is None and (row['id'],row['revision']) in hidden:continue
            candidate=json.loads(row['candidate_json']);routing=json.loads(row['routing_json']);confirmation=store.confirmation(row)
            is_active=bool(active and active['decision_id']==row['id'] and active['revision']==row['revision'])
            entry={'task_id':task['id'],'decision_id':row['id'],'decision_key':memory.decision_key(candidate),
                'revision':row['revision'],'field':candidate['field'],'state':row['state'],
                'suggested_action':routing.get('suggested_action',routing['status']),
                'validation_status':routing.get('validation_status','valid'),'active':is_active,
                'confirmation':confirmation,'depends_on':candidate.get('depends_on',[])}
            if is_active:
                entry.update(card=routing['card'],card_expired=active['expires']<time.time(),
                    resume_action='reactivate_with_current_handle' if active['expires']<time.time() else 'continue_current_card')
            elif row['state']=='deferred':entry['resume_action']='reassess_when_model_declared_dependency_is_reached'
            elif confirmation:entry['resume_action']='reuse_recorded_choice_without_reasking'
            else:entry['resume_action']='review_existing_task'
            entry['references']=[source_state(store,r['source_id']) for r in candidate['evidence_refs']]
            if any(not r['current'] for r in entry['references']):entry['validation_status']='needs_evidence'
            pending.append(entry)
            decisions_snapshot[row['id']]={'revision':row['revision'],'state':row['state'],
                'confirmation_id':confirmation['id'] if confirmation else None,'candidate_sha256':hashlib.sha256(encode(candidate).encode()).hexdigest()}
    pending.sort(key=lambda r:not r['active'])
    with store.connect() as db:recalled=memory.recall(store,db,query,False,limit=30,include_review=True)
    snapshot_files={r['path']:file_state(store,r['path']) for r in receipts}
    prior_data=json.loads(previous['data_json']) if previous else None
    if prior_data:
        for path in prior_data['files']:snapshot_files.setdefault(path,file_state(store,path))
    state={'files':snapshot_files,'decisions':decisions_snapshot,
        'memory':{r['memory_id']:{'revision':r['revision'],'state':r['state'],'tier':r['tier']} for r in recalled['entries']}}
    changes=[]
    if prior_data:
        for section in ('files','decisions','memory'):
            for key in sorted(set(prior_data[section])|set(state[section])):
                before=prior_data[section].get(key);after=state[section].get(key)
                if before!=after:changes.append({'kind':section,'id':key,'before':before,'after':after,
                    'business_impact':'requires_llm_assessment'})
    ident='context-'+uuid.uuid4().hex
    with store.connect() as db:
        db.execute('INSERT INTO buildchoice_context_snapshots VALUES(?,?,?,?,?)',(ident,str(store.workspace),host,encode(state),now()))
        db.execute('DELETE FROM buildchoice_context_snapshots WHERE workspace=? AND host=? AND id NOT IN '
            '(SELECT id FROM buildchoice_context_snapshots WHERE workspace=? AND host=? ORDER BY created DESC LIMIT 100)',
            (str(store.workspace),host,str(store.workspace),host))
    result={'schema_version':'context.v1','snapshot_id':ident,'workspace':str(store.workspace),
        'decisions':[],'sources':[],'memory':[],'changes':[],'omitted':{},
        'management_request':json.loads(ctx['outcome_json']).get('_memory_request'),
        'semantic_judgment_by':'llm','does_not_authorize_host_operations':True}
    from .document_projection import status as projection_status
    result['document']=projection_status(service,store,handle)
    # Opt-in tasks are shared within this workspace, while confirmation handles remain chat-local.
    # No product records/tables are created for normal development context queries.
    result['product_tasks']=[]
    with store.connect() as db:
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='product_tasks'").fetchone():
            for product in db.execute('SELECT p.*,t.workspace FROM product_tasks p JOIN decision_v3_tasks t ON t.id=p.task WHERE t.workspace=?', (str(store.workspace),)):
                from . import product_store as ps
                entry={'task_id':product['task'],'enabled':bool(product['enabled']), 'generation':product['generation'],
                    'scenario_count':len(ps.objects(db,product['task'],'scenario')),
                    'review_ids':[r['id'] for r in ps.objects(db,product['task'],'behavior_review')],
                    'resume':'buildchoice_experience status with task_id; present current content before new approvals'}
                if len(encode(result))+len(encode(entry))<max_chars-500:result['product_tasks'].append(entry)
                else:result['omitted']['product_tasks']=result['omitted'].get('product_tasks',0)+1
    reply=json.loads(ctx['outcome_json']).get('_reply')
    if reply and json.loads(ctx['outcome_json']).get('confirmation_status')=='awaiting_user':
        result['pending_reply']={k:reply[k] for k in ('decision_id','revision','message_digest')}
    if active and active['decision_id']:
        result['active_card_ref']={'decision_id':active['decision_id'],'revision':active['revision'],
            'expired':active['expires']<time.time()}
    def append(section,value):
        result[section].append(value)
        if len(encode(result))>max_chars-350:
            result[section].pop();result['omitted'][section]=result['omitted'].get(section,0)+1
            return False
        return True
    for entry in pending:append('decisions',entry)
    for entry in explicit:
        full=entry['content'];entry={**entry,'content':full[:min(4000,max_chars//3)]}
        entry.update(content_truncated=len(entry['content'])<len(full),total_content_chars=len(full))
        while not append('sources',entry) and len(entry['content'])>200:
            result['omitted']['sources']-=1
            entry['content']=entry['content'][:len(entry['content'])//2];entry['content_truncated']=True
    explicit_ids={r['source_id'] for r in explicit}
    for receipt in receipts:
        if receipt['source_id'] not in explicit_ids:append('sources',receipt)
    for entry in recalled['entries']:
        append('memory',{k:entry[k] for k in ('memory_id','decision_id','decision_key','revision','field','choice','tier','state','provenance','scope_key','conditions')})
    for change in changes:append('changes',change)
    result['omitted']={k:v for k,v in result['omitted'].items() if v}
    if len(encode(result))>max_chars:
        # Large management metadata is never allowed to bypass the response budget.
        result['management_request']=None;result['omitted']['management_request']=1
    return result
