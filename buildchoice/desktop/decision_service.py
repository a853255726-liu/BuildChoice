"""Validate LLM declarations and bind real sources to persisted decision state."""
import hashlib
import json
from .audit import encode, pointer_value, MAX_BYTES
from .candidate_policy import deduplicate, route, sort_key, field_key, candidate_key
from .candidate_identity import material_change,candidate_content,RISK_PRESENTATION
from .decision_cards import make_card
from .decision_contracts import validate
from .decision_settings import read as read_settings
from .decision_store import DecisionStore,canonical_prompt,fingerprint
from . import decision_memory as memory


class DecisionService:
    def __init__(self, workspace, owner, settings_path=None, database=None):
        self.workspace=workspace;self.owner=owner;self.settings_path=settings_path;self.database=database

    def settings(self):
        return read_settings(self.settings_path) if self.settings_path is not None else read_settings()

    def store(self):
        config=self.settings()
        if config['mode']!='pilot':raise ValueError('V3_DISABLED')
        return DecisionStore(self.workspace,self.database,config['context_ttl_seconds'])

    def source_paths(self, store, verified_ids):
        with store.connect() as db:
            return {row['locator'] for ident in verified_ids for row in db.execute(
                'SELECT s.locator FROM sources s JOIN sessions t ON t.id=s.session WHERE s.id=? AND t.workspace=?',
                (ident,str(store.workspace)))}

    def evidence(self, store, candidate, resources, host_session_digest=None):
        result={'status':'missing','invalid':False,'conflict':False,'unread':False,'insufficient':False,
                'applicable_constraint':False,'source_ids':[],'observed_values':[],
                'interpretations':[],'excerpts':[],'does_not_establish_user_confirmation':True}
        literals=[];constraint=False
        for reference in candidate['evidence_refs']:
            with store.connect() as db:
                row=db.execute('SELECT s.* FROM sources s JOIN sessions t ON t.id=s.session WHERE s.id=? AND t.workspace=?',
                               (reference['source_id'],str(store.workspace))).fetchone()
            if row is None or row['origin'] not in ('collector_file_read','hook_file_read'):
                result['invalid']=True;continue
            source=dict(row)
            try:
                with store.ledger.path(source['locator']).open('rb') as stream:raw=stream.read(MAX_BYTES+1)
                if len(raw)>MAX_BYTES or hashlib.sha256(raw).hexdigest()!=source['digest']:
                    result['invalid']=True;continue
                content=store.ledger.source_text(source,raw)
                if (source['origin']=='hook_file_read' and 'pointer' in reference and
                        not json.loads(source['metadata'])['full_file']):
                    result['invalid']=True;continue
                if 'quote' in reference and reference['quote'] not in content:
                    result['invalid']=True;continue
                actual=pointer_value(content,reference['pointer']) if 'pointer' in reference else None
                if reference.get('relation')=='constraint':
                    try:container=json.loads(content)
                    except ValueError:container={}
                    identity=(isinstance(container,dict) and
                        ((candidate.get('decision_key') and container.get('decision_key')==candidate['decision_key']) or
                         (not container.get('decision_key') and field_key(str(container.get('field','')))==field_key(candidate['field']))))
                    same_scope=isinstance(container,dict) and container.get('scope_key','project')==candidate.get('scope_key','project') and container.get('conditions',[])==candidate.get('conditions',[])
                    literal=identity and same_scope and reference.get('pointer')=='/chosen'
                    if literal:
                        literals.append(encode(actual));result['observed_values'].append(actual)
                    supported=literal and any(encode(actual)==encode(o.get('value',o['label'])) for o in candidate['options'])
                    constraint=constraint or supported
                    # Applicability of prose and business meaning belongs to the LLM.
                if reference.get('interpretation'):
                    result['interpretations'].append({'source_id':source['id'],'text':reference['interpretation'],
                        'provenance':'agent_declared','semantic_validity_independently_verified':False})
                result['excerpts'].append({'source_id':source['id'],'text':reference.get('quote',encode(actual)),
                    'origin':'collector_verified_quote_or_pointer'})
                result['source_ids'].append(source['id'])
            except (OSError,ValueError,KeyError,IndexError,TypeError):result['invalid']=True
        result['conflict']=len(set(literals))>1
        verified_paths=self.source_paths(store,result['source_ids'])
        observed=store.ledger.observed_reads(host_session_digest,[r['path'] for r in resources]) if resources else []
        for resource in resources:
            if field_key(candidate['field']) in {field_key(f) for f in resource['covers']}:
                try:
                    path=store.ledger.path(resource['path']).relative_to(store.workspace).as_posix()
                    read=path in verified_paths or any(r['path']==path and r['current'] and
                        (r['full_file'] or r['source_id'] in result['source_ids']) for r in observed)
                    result['unread']=result['unread'] or not read
                except (OSError,ValueError):result['invalid']=True
        result['applicable_constraint']=constraint and not any(result[k] for k in ('invalid','conflict','insufficient','unread'))
        result['status']=('conflict' if result['conflict'] else 'unverified_or_changed' if result['invalid'] else
                          'unread' if result['unread'] else 'interpretation_pending' if result['insufficient'] else
                          'literal_constraint' if result['applicable_constraint'] else 'bound_for_review' if result['source_ids'] else 'missing')
        return result

    def coverage(self, store, request):
        """Record the Agent's explanation; source binding does not prove coverage."""
        entries=[]
        for entry in request.get('coverage',[]):
            probe={'field':entry['dimension'],'evidence_refs':entry.get('evidence_refs',[]),'options':[]}
            evidence=self.evidence(store,probe,[])
            entries.append({**entry,'source_status':evidence['status'],'source_ids':evidence['source_ids']})
        return {'reported':'coverage' in request,'provenance':'agent_declared',
                'entries':entries,'does_not_establish_completeness':True}

    def screen(self, request):
        request=validate('ScreenRequest',request)
        store=self.store()
        candidates=deduplicate(request['candidates']);candidates.sort(key=sort_key)
        with store.transaction():
            return self._screen(store,request,candidates)

    def screen_inputs(self, store, request, task_id=None):
        """Snapshot the current bounded files, including coverage and unread resources."""
        files={};sources={}
        def file_state(locator):
            if locator not in files:
                try:
                    path=store.ledger.path(locator)
                    with path.open('rb') as stream:raw=stream.read(MAX_BYTES+1)
                    files[locator]={'sha256':hashlib.sha256(raw).hexdigest(),
                        'oversized':len(raw)>MAX_BYTES,'bytes':path.stat().st_size}
                except (OSError,ValueError):files[locator]={'unavailable':True}
            return files[locator]
        references=[ref for entry in [*request['candidates'],*request.get('coverage',[])] for ref in entry.get('evidence_refs',[])]
        references.extend(ref for c in request['candidates'] for o in c['options'] for ref in o.get('risk_evidence_refs',[]))
        if task_id:
            references.extend(ref for item in store.items(task_id)
                for ref in json.loads(item['candidate_json']).get('evidence_refs',[]))
        ids={ref['source_id'] for ref in references}
        with store.connect() as db:
            for source_id in sorted(ids):
                row=db.execute('SELECT s.* FROM sources s JOIN sessions t ON t.id=s.session WHERE s.id=? AND t.workspace=?',
                    (source_id,str(store.workspace))).fetchone()
                sources[source_id]=None if row is None else {'locator':row['locator'],'digest':row['digest'],
                    'origin':row['origin'],'file':file_state(row['locator'])}
        for resource in request.get('resources',[]):file_state(resource['path'])
        with store.connect() as db:
            memories=memory.signature(store,db,exclude_task=task_id) if request.get('session_handle') else []
            task=db.execute('SELECT host_session_digest FROM decision_v3_tasks WHERE id=?',(task_id,)).fetchone() if task_id else None
        reads=store.ledger.observed_reads(task[0],[r['path'] for r in request.get('resources',[])]) if task else []
        return {'sources':sources,'files':files,'memory':memories,'observed_reads':reads}

    def screen_snapshot(self, store, task_id, inputs):
        items=[{key:row[key] for key in ('id','revision','candidate_json','routing_json')} |
               {'confirmation':store.confirmation(row)} for row in store.items(task_id)]
        with store.connect() as db:
            latest=db.execute("SELECT data_json FROM decision_v3_events WHERE task_id=? AND event_type='COVERAGE_RECORDED' ORDER BY id DESC LIMIT 1",
                (task_id,)).fetchone()
        return fingerprint({'inputs':inputs,'items':items,'coverage':json.loads(latest[0]) if latest else None})

    def _screen(self, store, request, candidates):
        task=store.open_task(request['task_text'],request['phase'],self.owner,request.get('session_handle'),request.get('task_id'))
        if task['binding_status']=='hook_observed' and not request.get('session_handle'):
            raise ValueError('Observed tasks require a fresh Hook context for screening')
        given={k:v for k,v in request.items() if k not in ('task_id','session_handle')}
        given['task_text']=canonical_prompt(request['task_text'])
        cached=store.begin_operation(task['id'],'screen',request['idempotency_key'],given,legacy_given=request)
        inputs=self.screen_inputs(store,request,task['id'])
        if cached is not None:
            if (cached.get('screen_cache_version')!=2 or
                    cached.get('snapshot')!=self.screen_snapshot(store,task['id'],inputs)):
                raise ValueError('CACHED_SCREEN_STALE: read current sources/status and screen with a new idempotency key')
            cached=cached['response']
            # Historical responses remain on disk, but retired fields leave the live API.
            cached.pop('model_diagnostics',None)
            cached.setdefault('coverage',{'reported':False,'provenance':'agent_declared','entries':[],
                                         'does_not_establish_completeness':True})
            for decision in cached['decisions']:
                for name in ('model_status','model_fields'):decision.pop(name,None)
            return validate('ScreenResponse',cached)
        resources=request.get('resources',[])
        evidence={candidate_key(c):self.evidence(store,c,resources,task['host_session_digest']) for c in candidates}
        coverage=self.coverage(store,request)
        coverage_evidence=[self.evidence(store,{'field':entry['dimension'],'options':[],
            'evidence_refs':entry.get('evidence_refs',[])},[]) for entry in request.get('coverage',[])]
        diagnostics=[]
        reads=store.ledger.observed_reads(task['host_session_digest'],[r['path'] for r in resources]) if resources else []
        verified_ids={ident for ev in evidence.values() for ident in ev['source_ids']}
        verified_paths=self.source_paths(store,verified_ids)
        def resource_read(resource):
            try:path=store.ledger.path(resource['path']).relative_to(store.workspace).as_posix()
            except (OSError,ValueError):return False
            return path in verified_paths or any(r['path']==path and r['current'] and (r['full_file'] or r['source_id'] in verified_ids) for r in reads)
        if any(not resource_read(resource) for resource in resources):
            diagnostics.append({'code':'DECLARED_RESOURCES_REQUIRE_INSPECTION','requires_inspection':True})
        if any(ev['invalid'] or ev['unread'] for ev in coverage_evidence):
            diagnostics.append({'code':'COVERAGE_EVIDENCE_RECHECK_REQUIRED','requires_inspection':True})
        with store.connect() as db:history_review=memory.review_history(store,db,candidates)
        for review in history_review:
            if review['relation']=='same' and not all(review[k] for k in ('source_current','stable_identity_matches','scope_matches')):
                diagnostics.append({'code':'HISTORY_REFERENCE_RECHECK_REQUIRED','candidate_id':review['candidate_id'],
                    'memory_id':review['memory_id'],'requires_inspection':True})
        existing={r['field_key']:r for r in store.items(task['id'])}
        decisions=[]
        for candidate in candidates:
            key=candidate_key(candidate);prior=existing.get(key);confirmation=store.confirmation(prior) if prior else None
            ev=evidence[key]
            card_options=self.risk_options(store,candidate,diagnostics)
            if confirmation:
                old=json.loads(prior['candidate_json'])
                if candidate_content(old)!=candidate_content(candidate) and material_change(old,candidate):
                    confirmation=None
            policy=route(candidate,ev,confirmation)
            with store.connect() as db:
                recalled=memory.match_candidate(store,db,candidate,task['id']) if request.get('session_handle') else None
            if recalled and recalled['status']=='applicable' and ev['applicable_constraint']:
                chosen=next(o for o in candidate['options'] if o['id']==recalled['choice_id'])
                if any(encode(v)!=memory.choice_value(chosen) for v in ev['observed_values']):
                    recalled={'status':'conflict','memory_ids':recalled['memory_ids'],'reason':'PROJECT_RULE_CONFLICTS_WITH_SOURCE'}
                    policy.update(status='INSPECT',validation_status='needs_review',reason_codes=['STRUCTURED_VALUES_DIFFER'])
            reused=False
            if recalled and not confirmation and policy['validation_status']=='valid':
                if (recalled['status']=='applicable' and candidate.get('memory_intent')=='reuse'
                        and candidate['suggested_action']=='PROCEED'):
                    policy.update(status='PROCEED',reason_codes=['LLM_REQUESTED_PROJECT_RULE_REUSE'])
                    reused=True
                elif (candidate.get('memory_intent')=='reuse' and candidate.get('suggested_action')=='PROCEED'
                      and recalled['status']!='applicable'):
                    policy.update(status='INSPECT',validation_status='needs_review',reason_codes=['RULE_IDENTITY_OR_STATE_RECHECK_REQUIRED'])
            result={'decision_id':'pending','decision_key':memory.decision_key(candidate),
                    'candidate_ids':candidate['_candidate_ids'],'field':candidate['field'],'revision':1,
                    'status':policy['status'],'suggested_action':policy['suggested_action'],
                    'validation_status':policy['validation_status'],'semantic_judgment_by':'llm',
                    'reason_codes':policy['reason_codes'],'evidence_status':ev['status'],
                    'card':None,
                    'confirmation_status':confirmation['provenance'] if confirmation else 'awaiting_user' if task['binding_status']=='hook_observed' else 'agent_reported_unverified'}
            if recalled:result['memory']=recalled
            if reused:result['confirmation_status']='project_rule_reused'
            ident,revision=store.save_item(task['id'],key,candidate,result,prior)
            result['processing']={'duplicate':bool(prior and revision==prior['revision'] and
                candidate_content(json.loads(prior['candidate_json']))==candidate_content(candidate)),
                'already_answered':bool(confirmation),'previous_state':prior['state'] if prior else None}
            if result['status']=='ASK_NOW':
                card_candidate=dict(candidate)
                card_candidate['options']=card_options
                card_candidate['depends_on']=candidate.get('depends_on') or [request['next_step']]
                result['card']=make_card(ident,revision,card_candidate)
            store.write_item(task['id'],key,candidate,result,prior)
            decisions.append(validate('Decision',result))
        response={'schema_version':'decision.v3','task_id':task['id'],'binding_status':task['binding_status'],
                  'decisions':decisions,'coverage':coverage,'does_not_authorize_host_operations':True,
                  'diagnostics':diagnostics,'history_review':history_review,'semantic_judgment_by':'llm',
                  'risk_review':{'scope':'declared_next_step_and_cited_excerpts_only','coverage_complete':False,
                      'no_signal_does_not_establish_no_risk':True,'engineering_risks_provenance':'agent_declared'}}
        statuses={d['status'] for d in decisions}
        response['suggested_action']=request.get('suggested_action') or next((s for s in ('INSPECT','ASK_NOW','DEFER') if any(d['suggested_action']==s for d in decisions)),'PROCEED')
        response['screen_status']=('INSPECT' if any(d.get('requires_inspection') for d in diagnostics) else
            next((status for status in ('INSPECT','ASK_NOW','DEFER') if status in statuses),response['suggested_action']))
        response['validation_status']=('needs_evidence' if any(d.get('requires_inspection') for d in diagnostics)
            else next((d['validation_status'] for d in decisions if d['validation_status']!='valid'),'valid'))
        validate('ScreenResponse',response)
        with store.connect() as db:store.event(db,task['id'],'COVERAGE_RECORDED',coverage)
        after=self.screen_inputs(store,request,task['id'])
        if inputs!=after:raise ValueError('SCREEN_INPUT_CHANGED_DURING_EVALUATION: re-read sources and retry')
        store.finish_operation(task['id'],'screen',request['idempotency_key'],{
            'screen_cache_version':2,'snapshot':self.screen_snapshot(store,task['id'],after),'response':response})
        return response

    def risk_options(self, store, candidate, diagnostics):
        options=[]
        for option in candidate['options']:
            value=dict(option)
            if option.get('risk_level')=='high' and option.get('risk_warning'):
                refs=option.get('risk_evidence_refs',[])
                proof=self.evidence(store,{'field':candidate['field'],'options':[],'evidence_refs':refs},[])
                grounded=bool(refs and not proof['invalid'] and len(proof['source_ids'])==len(refs))
                conditional=bool(option.get('risk_basis')=='potential' and option.get('risk_reason','').strip() and option.get('risk_condition','').strip() and not proof['invalid'])
                if not (grounded or conditional) or option.get('risk_basis') not in ('observed','potential'):
                    for key in RISK_PRESENTATION:value.pop(key,None)
                    diagnostics.append({'code':'OPTION_WARNING_NEEDS_BASIS','option_id':option['id'],
                        'candidate_id':candidate['candidate_id'],'requires_inspection':True})
            options.append(value)
        return options

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
            return {'schema_version':'decision.v3','enabled':False,'mode':'off','decisions':[]}
        store=self.store()
        if task_id:
            task=store.task(task_id,self.owner,session_handle)
            return {'enabled':True,**self.task_status(store,task)}
        with store.connect() as db:
            ctx=store.context(db,session_handle,self.owner,claim=True)
            if ctx:
                tasks=[dict(r) for r in db.execute('SELECT * FROM decision_v3_tasks WHERE workspace=? AND host_session_digest=? ORDER BY created',
                       (str(store.workspace),ctx['host_session_digest']))]
            else:tasks=[dict(r) for r in db.execute("SELECT * FROM decision_v3_tasks WHERE owner=? AND binding_status='unverified' ORDER BY created",(self.owner,))]
        return {'schema_version':'decision.v3','enabled':True,'mode':'pilot',
                'binding_status':'hook_observed' if ctx else 'unverified',
                'tasks':[self.task_status(store,task) for task in tasks],
                'observed_reads':store.ledger.observed_reads(ctx['host_session_digest']) if ctx else [],
                'project_memory':self.memory('',False,session_handle) if ctx else None,
                'does_not_authorize_host_operations':True}

    def memory(self, query='', include_archived=False, session_handle=None):
        store=self.store()
        with store.connect() as db:
            ctx=store.context(db,session_handle,self.owner,claim=True)
            if ctx is None:
                raise ValueError('Project memory requires a current observed Hook context')
            result=memory.recall(store,db,query,include_archived)
            request=json.loads(ctx['outcome_json']).get('_memory_request')
            result['management_request']=request
            return result

    def manage_memory(self, memory_id, revision, action='promote', session_handle=None):
        store=self.store()
        with store.connect() as db:
            store.begin(db)
            ctx=store.context(db,session_handle,self.owner,claim=True)
            if ctx is None:raise ValueError('Memory management requires a current observed Hook context')
            return memory.manage(store,db,ctx,memory_id,revision,action)

    def task_status(self, store, task):
        result=store.status(task,self.owner)
        result['observed_reads']=store.ledger.observed_reads(task['host_session_digest'])
        items={r['id']:r for r in store.items(task['id'])}
        with store.connect() as db:
            for item in result['decisions']:
                from .task_context import source_state
                candidate=json.loads(items[item['decision_id']]['candidate_json'])
                item['reference_checks']=[source_state(store,r['source_id']) for r in candidate['evidence_refs']]
                if any(not r['current'] for r in item['reference_checks']):
                    item.update(validation_status='needs_evidence',needs_recheck=True)
                if item['confirmation_status']!='project_rule_reused':continue
                candidate=json.loads(items[item['decision_id']]['candidate_json'])
                current=memory.match_candidate(store,db,candidate,task['id'])
                evidence=self.evidence(store,candidate,[])
                if current!=item.get('memory') or evidence['invalid'] or evidence['unread']:
                    item.update(status='INSPECT',validation_status='needs_review',
                        confirmation_status='project_rule_stale',card=None,
                        reason_codes=['REUSED_RULE_NO_LONGER_CURRENT_RESCREEN_REQUIRED'])
                    item['needs_recheck']=True
        return result

    def prepare_revision(self, task_id, decision_id, revision, candidate, reason, session_handle=None):
        candidate=validate('Candidate',candidate)
        if type(revision) is not int or revision<1:raise ValueError('Valid source revision required')
        if not isinstance(reason,str) or not reason.strip() or len(reason)>1000:raise ValueError('Concrete revision reason required')
        store=self.store();task=store.task(task_id,self.owner,session_handle)
        if task['binding_status']=='hook_observed' and not session_handle:raise ValueError('Revision requires current Hook context')
        return store.prepare_revision(task,decision_id,revision,candidate,reason)

    def link_implementation(self, task_id, decision_id, revision, path, note,
                            start_line=None, end_line=None, session_handle=None):
        from .implementation import link
        store=self.store();task=store.task(task_id,self.owner,session_handle)
        return link(store,task,decision_id,revision,path,note,start_line,end_line)

    def interpret_reply(self, task_id, decision_id, revision, choice_id, quote, reason, session_handle):
        from .reply_interpretation import interpret
        store=self.store();task=store.task(task_id,self.owner,session_handle)
        return interpret(store,task,self.owner,session_handle,decision_id,revision,choice_id,quote,reason)

    def record_instruction(self, request):
        from .instruction_record import record
        return record(self,self.store(),request)

    def context_bundle(self, session_handle, query='', paths=None, task_id=None, since=None, max_chars=12000):
        from .task_context import build
        return build(self,self.store(),session_handle,query,paths or [],task_id,since,max_chars)

    def decision_document(self, session_handle, task_id=None, include_archived=False, write=False, path='BUILDCHOICE_DECISIONS.md'):
        from .decision_document import document
        return document(self,self.store(),session_handle,task_id,include_archived,write,path)

    def acceptance_prepare(self, task_id, decision_id, revision, criteria, session_handle, idempotency_key):
        from .acceptance import prepare
        store=self.store();task=store.task(task_id,self.owner,session_handle)
        return prepare(store,task,decision_id,revision,criteria,idempotency_key)

    def verify_decision(self, task_id, decision_id, revision, acceptance_id, code_evidence_refs,
                        execution_id, session_handle, idempotency_key):
        from .verification import verify
        store=self.store();task=store.task(task_id,self.owner,session_handle)
        return verify(store,task,decision_id,revision,acceptance_id,code_evidence_refs,execution_id,idempotency_key)
