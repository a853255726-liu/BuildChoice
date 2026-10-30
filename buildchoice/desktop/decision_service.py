"""Coordinate V3 contracts, verified evidence, rule routing and persisted cards."""
import hashlib
import json
from .audit import encode, pointer_value, MAX_BYTES
from .candidate_policy import deduplicate, route, sort_key, field_key
from .decision_cards import make_card
from .decision_contracts import validate
from .decision_settings import read as read_settings
from .decision_store import DecisionStore
from .nli_candidate_adapter import assess_candidates, RuntimeProvider


class DecisionService:
    def __init__(self, workspace, owner, settings_path=None, database=None, provider=None):
        self.workspace=workspace;self.owner=owner;self.settings_path=settings_path;self.database=database
        self.provider=provider

    def settings(self):
        return read_settings(self.settings_path) if self.settings_path is not None else read_settings()

    def store(self):
        config=self.settings()
        if config['mode']!='pilot':raise ValueError('V3_DISABLED')
        return DecisionStore(self.workspace,self.database,config['context_ttl_seconds'])

    def evidence(self, store, candidate, resources):
        result={'status':'missing','invalid':False,'conflict':False,'unread':False,'applicable_constraint':False,
                'source_ids':[],'contents':[],'observed_values':[]}
        literals=[];constraint=False
        for reference in candidate['evidence_refs']:
            with store.connect() as db:
                row=db.execute('SELECT s.* FROM sources s JOIN sessions t ON t.id=s.session WHERE s.id=? AND t.workspace=?',
                               (reference['source_id'],str(store.workspace))).fetchone()
            if row is None or row['origin']!='collector_file_read':
                result['invalid']=True;continue
            source=dict(row)
            try:
                path=store.ledger.path(source['locator'])
                with path.open('rb') as stream:raw=stream.read(MAX_BYTES+1)
                if len(raw)>MAX_BYTES or hashlib.sha256(raw).hexdigest()!=source['digest']:
                    result['invalid']=True
                if 'pointer' in reference:
                    actual=pointer_value(source['content'],reference['pointer']);literals.append(encode(actual))
                    result['observed_values'].append(actual)
                    try:container=json.loads(source['content'])
                    except ValueError:container={}
                    if (reference.get('relation')=='constraint' and isinstance(container,dict) and
                            field_key(str(container.get('field','')))==field_key(candidate['field']) and
                            reference['pointer']=='/chosen' and
                            any(encode(actual)==encode(o.get('value',o['label'])) for o in candidate['options'])):
                        constraint=True
                elif reference['quote'] not in source['content']:result['invalid']=True
            except (OSError,ValueError,KeyError,IndexError,TypeError):result['invalid']=True
            result['source_ids'].append(source['id'])
            result['contents'].append({'source_id':source['id'],'path':source['locator'],'sha256':source['digest'],'content':source['content']})
        result['conflict']=len(set(literals))>1
        for resource in resources:
            if field_key(candidate['field']) in {field_key(f) for f in resource['covers']}:
                try:store.ledger.path(resource['path']);result['unread']=True
                except (OSError,ValueError):result['invalid']=True
        result['applicable_constraint']=constraint and not result['invalid'] and not result['conflict']
        result['status']=('conflict' if result['conflict'] else 'unverified_or_changed' if result['invalid'] else
                          'unread' if result['unread'] else 'literal_constraint' if result['applicable_constraint'] else
                          'bound_for_review' if result['source_ids'] else 'missing')
        return result

    def screen(self, request):
        validate('ScreenRequest',request)
        store=self.store()
        candidates=deduplicate(request['candidates']);candidates.sort(key=sort_key)
        task=store.open_task(request['task_text'],request['phase'],self.owner,request.get('session_handle'),request.get('task_id'))
        if task['binding_status']=='hook_observed' and not request.get('session_handle'):
            raise ValueError('Observed tasks require a fresh Hook context for screening')
        cached=store.begin_operation(task['id'],'screen',request['idempotency_key'],request)
        if cached is not None:return cached
        resources=request.get('resources',[])
        evidence={c['field']:self.evidence(store,c,resources) for c in candidates}
        content={s['source_id']:s for e in evidence.values() for s in e['contents']}
        full_evidence='\n\n'.join(encode(content[k]) for k in sorted(content))
        settings=self.settings()
        if self.provider is None:self.provider=RuntimeProvider(settings['model_runtime'])
        models,diagnostics=assess_candidates(request['task_text'],candidates,full_evidence,resources,
                                            settings['model_check']=='on',self.provider)
        existing={r['field_key']:r for r in store.items(task['id'])}
        decisions=[]
        for candidate in candidates:
            key=field_key(candidate['field']);prior=existing.get(key);confirmation=store.confirmation(prior) if prior else None
            ev=evidence[candidate['field']]
            if confirmation:
                old=json.loads(prior['candidate_json'])
                old_evidence=self.evidence(store,old,[])
                if (old['options']!=candidate['options'] or old['category']!=candidate['category'] or
                        not set(candidate['risk_flags']).issubset(old['risk_flags']) or old_evidence['invalid']):
                    confirmation=None
            model=models[candidate['field']]
            policy=route(candidate,ev,confirmation,model,request['next_step'])
            result={'decision_id':'pending','candidate_ids':candidate['_candidate_ids'],'field':candidate['field'],'revision':1,
                    'status':policy['status'],'reason_codes':policy['reason_codes'],'evidence_status':ev['status'],
                    'model_status':model['status'],'model_fields':model['fields'],'card':None,
                    'confirmation_status':'user_message_observed' if confirmation else 'awaiting_user' if task['binding_status']=='hook_observed' else 'agent_reported_unverified'}
            ident,revision=store.save_item(task['id'],key,candidate,result,prior)
            if prior and prior['state']=='confirmed' and confirmation is None and revision==prior['revision']:
                revision+=1;result['revision']=revision
            if result['status']=='ASK_NOW':
                card_candidate=dict(candidate)
                card_candidate['depends_on']=candidate.get('depends_on') or [request['next_step']]
                result['card']=make_card(ident,revision,card_candidate,policy)
            store.write_item(task['id'],key,candidate,result,prior)
            decisions.append(validate('Decision',result))
        response={'schema_version':'decision.v3','task_id':task['id'],'binding_status':task['binding_status'],
                  'decisions':decisions,'model_diagnostics':diagnostics,'does_not_authorize_host_operations':True}
        validate('ScreenResponse',response)
        with store.connect() as db:store.event(db,task['id'],'MODEL_CHECK_RECORDED',diagnostics)
        store.finish_operation(task['id'],'screen',request['idempotency_key'],response)
        return response

    def activate(self, task_id, decision_id, revision, idempotency_key, session_handle=None):
        if type(revision) is not int or revision<1 or not isinstance(idempotency_key,str) or not 1<=len(idempotency_key)<=150:
            raise ValueError('Valid card revision and bounded idempotency key required')
        store=self.store();task=store.task(task_id,self.owner,session_handle)
        if task['binding_status']=='hook_observed' and not session_handle:
            raise ValueError('Card activation requires an unexpired Hook context')
        pending=[r for r in store.items(task_id) if json.loads(r['routing_json'])['status']=='ASK_NOW' and r['state'] not in ('confirmed','superseded')]
        position=next((i+1 for i,r in enumerate(pending) if r['id']==decision_id),1)
        return store.activate(task,decision_id,revision,idempotency_key,position,len(pending))

    def status(self, task_id=None, session_handle=None):
        settings=self.settings()
        if settings['mode']=='off':
            return {'schema_version':'decision.v3','enabled':False,'mode':'off','model_check':settings['model_check'],'decisions':[]}
        store=self.store()
        if task_id:
            task=store.task(task_id,self.owner,session_handle)
            return {'enabled':True,**store.status(task,self.owner)}
        with store.connect() as db:
            ctx=store.context(db,session_handle,self.owner,claim=True)
            if ctx:
                tasks=[dict(r) for r in db.execute('SELECT * FROM decision_v3_tasks WHERE workspace=? AND host_session_digest=? ORDER BY created',
                       (str(store.workspace),ctx['host_session_digest']))]
            else:tasks=[dict(r) for r in db.execute("SELECT * FROM decision_v3_tasks WHERE owner=? AND binding_status='unverified' ORDER BY created",(self.owner,))]
        return {'schema_version':'decision.v3','enabled':True,'mode':'pilot','model_check':settings['model_check'],
                'binding_status':'hook_observed' if ctx else 'unverified',
                'tasks':[store.status(task,self.owner) for task in tasks],'does_not_authorize_host_operations':True}

    def prepare_revision(self, task_id, decision_id, revision, candidate, reason, session_handle=None):
        validate('Candidate',candidate)
        if type(revision) is not int or revision<1:raise ValueError('Valid source revision required')
        if not isinstance(reason,str) or not reason.strip() or len(reason)>1000:raise ValueError('Concrete revision reason required')
        store=self.store();task=store.task(task_id,self.owner,session_handle)
        if task['binding_status']=='hook_observed' and not session_handle:raise ValueError('Revision requires current Hook context')
        return store.prepare_revision(task,decision_id,revision,candidate,reason)
