"""Transactional V3 state, isolated from audit.v1 decisions and reviews.

Trust is scoped to locally trusted host Hook callbacks, not protection against
arbitrary local code that can mutate this user's database or invoke callbacks.
"""
import hashlib
import json
import re
import secrets
import sqlite3
import time
import uuid
from contextlib import closing
from pathlib import Path
from .audit import Ledger, encode, now


def fingerprint(value):
    return hashlib.sha256(encode(value).encode('utf-8')).hexdigest()


def message_digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


class DecisionStore:
    def __init__(self, workspace, database=None, ttl=900):
        self.ledger = Ledger(workspace, database)
        self.workspace = self.ledger.workspace
        self.database = self.ledger.database
        self.ttl = ttl
        self.migrate()

    def connect(self):
        db = self.ledger.connect()
        db.execute('PRAGMA foreign_keys=ON')
        return db

    def migrate(self):
        with self.connect() as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='decision_v3_migrations'").fetchone():
                version=db.execute('SELECT max(version) FROM decision_v3_migrations').fetchone()[0]
                if version != 1: raise ValueError('Unsupported V3 database version')
                return
            backup = self.database.with_name(self.database.name + '.before-v3.bak')
            if not backup.exists():
                with closing(sqlite3.connect(backup)) as destination: db.backup(destination)
            db.executescript('''
            BEGIN IMMEDIATE;
            CREATE TABLE IF NOT EXISTS decision_v3_migrations(version INTEGER PRIMARY KEY, applied TEXT, backup TEXT);
            CREATE TABLE IF NOT EXISTS decision_v3_tasks(
              id TEXT PRIMARY KEY, workspace TEXT NOT NULL, host_session_digest TEXT NOT NULL,
              task_digest TEXT NOT NULL, owner TEXT NOT NULL, phase TEXT NOT NULL,
              binding_status TEXT NOT NULL, created TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS decision_v3_items(
              id TEXT NOT NULL, revision INTEGER NOT NULL, task_id TEXT NOT NULL REFERENCES decision_v3_tasks(id),
              field_key TEXT NOT NULL, candidate_json TEXT NOT NULL, routing_json TEXT NOT NULL,
              state TEXT NOT NULL, needs_recheck INTEGER NOT NULL DEFAULT 0, created TEXT NOT NULL,
              PRIMARY KEY(id,revision));
            CREATE INDEX IF NOT EXISTS decision_v3_task_items ON decision_v3_items(task_id,field_key,revision);
            CREATE TABLE IF NOT EXISTS decision_v3_confirmations(
              id TEXT PRIMARY KEY, decision_id TEXT NOT NULL, revision INTEGER NOT NULL,
              choice_id TEXT, provenance TEXT NOT NULL, host_turn_digest TEXT,
              user_prompt_digest TEXT, created TEXT NOT NULL,
              UNIQUE(decision_id,revision),
              FOREIGN KEY(decision_id,revision) REFERENCES decision_v3_items(id,revision));
            CREATE TABLE IF NOT EXISTS decision_v3_contexts(
              handle TEXT PRIMARY KEY, workspace TEXT NOT NULL, host_session_digest TEXT NOT NULL,
              host_turn_digest TEXT NOT NULL, prompt_digest TEXT NOT NULL, expires REAL NOT NULL,
              owner TEXT, task_id TEXT, outcome_json TEXT NOT NULL,
              UNIQUE(workspace,host_session_digest,host_turn_digest));
            CREATE TABLE IF NOT EXISTS decision_v3_active(
              workspace TEXT NOT NULL, host_session_digest TEXT NOT NULL, decision_id TEXT, revision INTEGER,
              expires REAL, delivery_status TEXT NOT NULL,
              PRIMARY KEY(workspace,host_session_digest));
            CREATE TABLE IF NOT EXISTS decision_v3_operations(
              task_id TEXT NOT NULL, operation TEXT NOT NULL, key TEXT NOT NULL,
              input_digest TEXT NOT NULL, response_json TEXT,
              PRIMARY KEY(task_id,operation,key));
            CREATE TABLE IF NOT EXISTS decision_v3_events(
              id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT, event_type TEXT NOT NULL,
              data_json TEXT NOT NULL, created TEXT NOT NULL);
            INSERT OR IGNORE INTO decision_v3_migrations VALUES(1,datetime('now'),'before-v3.bak');
            COMMIT;
            ''')
            db.execute('UPDATE decision_v3_migrations SET backup=? WHERE version=1',(str(backup),))

    def event(self, db, task_id, kind, data):
        db.execute('INSERT INTO decision_v3_events(task_id,event_type,data_json,created) VALUES(?,?,?,?)',
                   (task_id,kind,encode(data),now()))

    def release_active(self, db, active, reason):
        """Release only the pending slot; never infer a choice or discard history."""
        row=db.execute('SELECT * FROM decision_v3_items WHERE id=? AND revision=?',
                       (active['decision_id'],active['revision'])).fetchone()
        db.execute('UPDATE decision_v3_active SET decision_id=NULL,revision=NULL WHERE workspace=? AND host_session_digest=?',
                   (active['workspace'],active['host_session_digest']))
        if row:
            db.execute("UPDATE decision_v3_items SET state='screened' WHERE id=? AND revision=? AND state IN ('card_active','needs_explanation')",
                       (row['id'],row['revision']))
            self.event(db,row['task_id'],'CARD_RELEASED',{'decision_id':row['id'],
                'revision':row['revision'],'reason':reason,'confirmation_status':'not_confirmed'})

    def observe_hook(self, event):
        if event.get('hook_event_name') != 'UserPromptSubmit': return None
        cwd=event.get('cwd'); session=event.get('session_id'); turn=event.get('turn_id'); prompt=event.get('prompt')
        if not isinstance(cwd,str) or not Path(cwd).resolve().is_relative_to(self.workspace): return None
        if not all(isinstance(v,str) and v for v in (session,turn,prompt)) or len(prompt)>50000:
            return {'status':'unverified','reason':'MISSING_OR_OVERSIZED_HOST_IDENTITY'}
        session_hash=message_digest(session); turn_hash=message_digest(turn); prompt_hash=message_digest(prompt)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            previous=db.execute('SELECT * FROM decision_v3_contexts WHERE workspace=? AND host_session_digest=? AND host_turn_digest=?',
                                (str(self.workspace),session_hash,turn_hash)).fetchone()
            if previous:
                if previous['prompt_digest']!=prompt_hash: raise ValueError('Host turn reused with different input')
                if previous['expires']<time.time(): return {'status':'unverified','reason':'EXPIRED_HOST_CONTEXT'}
                return {'status':'observed','session_handle':previous['handle'],**json.loads(previous['outcome_json'])}
            db.execute('UPDATE decision_v3_contexts SET expires=? WHERE workspace=? AND host_session_digest=? AND host_turn_digest<>?',
                       (time.time()-1,str(self.workspace),session_hash,turn_hash))
            outcome={'confirmation_status':'none'}; linked_task=None
            active=db.execute('SELECT * FROM decision_v3_active WHERE workspace=? AND host_session_digest=? AND decision_id IS NOT NULL',
                              (str(self.workspace),session_hash)).fetchone()
            if active:
                row=db.execute('SELECT * FROM decision_v3_items WHERE id=? AND revision=?',(active['decision_id'],active['revision'])).fetchone()
                latest=db.execute('SELECT max(revision) FROM decision_v3_items WHERE id=?',(active['decision_id'],)).fetchone()[0]
                if active['expires']<time.time() or row is None or latest!=active['revision']:
                    self.release_active(db,active,'EXPIRED_OR_SUPERSEDED_CARD')
                    outcome={'confirmation_status':'not_confirmed','reason':'EXPIRED_OR_SUPERSEDED_CARD'}
                else:
                    card=json.loads(row['routing_json'])['card']; text=prompt.strip()
                    selected=re.fullmatch(r'(?:(D[0-9A-F]{8})\s+)?(?:选\s*)?([ABC])',text)
                    valid_ids={o['id'] for o in card['options']}
                    if selected and selected[2] in valid_ids and (selected[1] is None or selected[1]==card['display_id']):
                        db.execute('INSERT INTO decision_v3_confirmations VALUES(?,?,?,?,?,?,?,?)',
                            ('conf-'+uuid.uuid4().hex,row['id'],row['revision'],selected[2],'user_message_observed',turn_hash,prompt_hash,now()))
                        db.execute("UPDATE decision_v3_items SET state='confirmed' WHERE id=? AND revision=?",(row['id'],row['revision']))
                        db.execute('UPDATE decision_v3_active SET decision_id=NULL,revision=NULL WHERE workspace=? AND host_session_digest=?',
                                   (str(self.workspace),session_hash))
                        linked_task=row['task_id']
                        outcome={'confirmation_status':'user_message_observed','decision_id':row['id'],'revision':row['revision'],'choice_id':selected[2]}
                        self.event(db,row['task_id'],'USER_CHOICE_OBSERVED',outcome)
                    elif text in ('暂缓','稍后决定','defer') and card['allow_defer']:
                        db.execute("UPDATE decision_v3_items SET state='deferred' WHERE id=? AND revision=?",(row['id'],row['revision']))
                        db.execute('UPDATE decision_v3_active SET decision_id=NULL,revision=NULL WHERE workspace=? AND host_session_digest=?',
                                   (str(self.workspace),session_hash))
                        linked_task=row['task_id'];outcome={'confirmation_status':'deferred','decision_id':row['id']}
                        self.event(db,row['task_id'],'USER_DEFERRED',{'decision_id':row['id'],'prompt_digest':prompt_hash})
                    else:
                        db.execute("UPDATE decision_v3_items SET state='needs_explanation' WHERE id=? AND revision=?",(row['id'],row['revision']))
                        linked_task=row['task_id'];outcome={'confirmation_status':'awaiting_user','decision_id':row['id'],
                            'reason':'EXPLICIT_CHOICE_REQUIRED','delivery_status':'not_observed'}
                        self.event(db,row['task_id'],'USER_REPLY_NOT_AUTOCONFIRMED',{'decision_id':row['id'],'prompt_digest':prompt_hash})
            handle='buildchoice-v3-ctx-'+secrets.token_urlsafe(24)
            db.execute('INSERT INTO decision_v3_contexts VALUES(?,?,?,?,?,?,?,?,?)',
                       (handle,str(self.workspace),session_hash,turn_hash,prompt_hash,time.time()+self.ttl,None,linked_task,encode(outcome)))
            return {'status':'observed','session_handle':handle,**outcome}

    def context(self, db, handle, owner, claim=False):
        if handle is None: return None
        row=db.execute('SELECT * FROM decision_v3_contexts WHERE handle=?',(handle,)).fetchone()
        if row is None or row['workspace']!=str(self.workspace) or row['expires']<time.time():
            raise ValueError('Missing, mismatched or expired Hook context')
        if row['owner'] is not None and row['owner']!=owner: raise ValueError('Hook context already claimed by another MCP session')
        if claim: db.execute('UPDATE decision_v3_contexts SET owner=? WHERE handle=?',(owner,handle))
        return dict(row)

    def task(self, task_id, owner, handle=None):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM decision_v3_tasks WHERE id=?',(task_id,)).fetchone()
            if row is None or row['workspace']!=str(self.workspace): raise ValueError('Unknown task in this workspace')
            ctx=self.context(db,handle,owner,claim=True)
            if row['binding_status']=='hook_observed' and ctx is None:
                raise ValueError('Observed tasks require a current Hook handle')
            if row['owner']!=owner:
                if ctx is None or ctx['host_session_digest']!=row['host_session_digest'] or not row['host_session_digest']:
                    raise ValueError('Task does not belong to this observed host session')
            if ctx is not None and row['host_session_digest'] and ctx['host_session_digest']!=row['host_session_digest']:
                raise ValueError('Cross-session Hook binding rejected')
            return dict(row)

    def open_task(self, task_text, phase, owner, handle=None, task_id=None):
        if task_id:
            row=self.task(task_id,owner,handle)
            if row['task_digest']!=message_digest(task_text): raise ValueError('Original task changed; start a new task scope')
            return row
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            ctx=self.context(db,handle,owner,claim=True)
            if ctx:
                if ctx['task_id']:
                    row=db.execute('SELECT * FROM decision_v3_tasks WHERE id=?',(ctx['task_id'],)).fetchone()
                    if row and row['task_digest']==message_digest(task_text): return dict(row)
                    # A non-option reply may be a new request. The Agent signals that
                    # by opening a new scope with this exact observed message. Strict
                    # choices/defer replies remain bound to their original task.
                    outcome=json.loads(ctx['outcome_json'])
                    if (outcome.get('confirmation_status')!='awaiting_user' or
                            ctx['prompt_digest']!=message_digest(task_text)):
                        raise ValueError('Hook context cannot be rebound to another task')
                    active=db.execute('SELECT a.* FROM decision_v3_active a JOIN decision_v3_items i ON i.id=a.decision_id AND i.revision=a.revision '
                        'WHERE a.workspace=? AND a.host_session_digest=? AND i.task_id=?',
                        (str(self.workspace),ctx['host_session_digest'],ctx['task_id'])).fetchone()
                    if active:self.release_active(db,active,'NEW_TASK_SCOPE')
                if ctx['prompt_digest']!=message_digest(task_text): raise ValueError('Task does not match actual observed user input')
            else:
                existing=db.execute('SELECT * FROM decision_v3_tasks WHERE owner=? AND task_digest=? AND host_session_digest=? ORDER BY created DESC LIMIT 1',
                                    (owner,message_digest(task_text),'')).fetchone()
                if existing:return dict(existing)
            ident='task-'+uuid.uuid4().hex
            row={'id':ident,'workspace':str(self.workspace),'host_session_digest':ctx['host_session_digest'] if ctx else '',
                 'task_digest':message_digest(task_text),'owner':owner,'phase':phase,
                 'binding_status':'hook_observed' if ctx else 'unverified','created':now()}
            db.execute('INSERT INTO decision_v3_tasks VALUES(:id,:workspace,:host_session_digest,:task_digest,:owner,:phase,:binding_status,:created)',row)
            if ctx: db.execute('UPDATE decision_v3_contexts SET task_id=? WHERE handle=?',(ident,handle))
            self.event(db,ident,'TASK_REGISTERED',{'binding_status':row['binding_status'],'task_digest':row['task_digest']})
            return row

    def begin_operation(self, task_id, operation, key, given):
        value=fingerprint(given)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM decision_v3_operations WHERE task_id=? AND operation=? AND key=?',(task_id,operation,key)).fetchone()
            if row:
                if row['input_digest']!=value: raise ValueError('Idempotency key reused with changed input')
                if row['response_json'] is None: raise ValueError('Operation already in progress; inspect status before retrying')
                return json.loads(row['response_json'])
            db.execute('INSERT INTO decision_v3_operations VALUES(?,?,?,?,NULL)',(task_id,operation,key,value))
        return None

    def finish_operation(self, task_id, operation, key, response):
        with self.connect() as db:
            db.execute('UPDATE decision_v3_operations SET response_json=? WHERE task_id=? AND operation=? AND key=?',
                       (encode(response),task_id,operation,key))

    def items(self, task_id):
        with self.connect() as db:
            rows=db.execute('SELECT i.* FROM decision_v3_items i WHERE task_id=? AND revision=(SELECT max(j.revision) FROM decision_v3_items j WHERE j.id=i.id) ORDER BY created,id',(task_id,)).fetchall()
            return [dict(row) for row in rows]

    def confirmation(self, item):
        if item['state']!='confirmed': return None
        with self.connect() as db:
            row=db.execute('SELECT * FROM decision_v3_confirmations WHERE decision_id=? AND revision=?',(item['id'],item['revision'])).fetchone()
        return {**dict(row),'applicable':True} if row else None

    def save_item(self, task_id, field_key, candidate, routing, existing=None):
        if existing:
            ident=existing['id'];revision=existing['revision']
            old=json.loads(existing['candidate_json'])
            if (old['options']!=candidate['options'] or old['category']!=candidate['category'] or
                    not set(candidate['risk_flags']).issubset(old['risk_flags'])):
                revision+=1
        else:ident='decv3-'+uuid.uuid4().hex;revision=1
        routing.update(decision_id=ident,revision=revision)
        return ident,revision

    def write_item(self, task_id, field_key, candidate, result, existing=None):
        ident=result['decision_id'];revision=result['revision']
        state={'ASK_NOW':'screened','INSPECT':'inspecting','DEFER':'deferred','PROCEED':'screened'}[result['status']]
        if existing and result['confirmation_status']=='user_message_observed' and result['status']=='PROCEED' and revision==existing['revision']:state='confirmed'
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if existing and revision!=existing['revision']:
                db.execute("UPDATE decision_v3_items SET state='superseded' WHERE id=? AND revision=?",(ident,existing['revision']))
                db.execute('UPDATE decision_v3_active SET decision_id=NULL,revision=NULL WHERE decision_id=?',(ident,))
            db.execute('INSERT INTO decision_v3_items VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(id,revision) DO UPDATE SET candidate_json=excluded.candidate_json,routing_json=excluded.routing_json,state=excluded.state',
                (ident,revision,task_id,field_key,encode(candidate),encode(result),state,0,now()))
            self.event(db,task_id,'CANDIDATE_SCREENED',{'decision_id':ident,'revision':revision,'status':result['status'],'reason_codes':result['reason_codes']})

    def activate(self, task, decision_id, revision, key, position, total):
        from .decision_cards import render
        given={'decision_id':decision_id,'revision':revision}
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            prior=db.execute('SELECT * FROM decision_v3_operations WHERE task_id=? AND operation=? AND key=?',(task['id'],'activate',key)).fetchone()
            if prior:
                if prior['input_digest']!=fingerprint(given):raise ValueError('Idempotency key reused with changed input')
            row=db.execute('SELECT * FROM decision_v3_items WHERE id=? AND task_id=? AND revision=?',(decision_id,task['id'],revision)).fetchone()
            latest=db.execute('SELECT max(revision) FROM decision_v3_items WHERE id=?',(decision_id,)).fetchone()[0]
            if row is None or latest!=revision:raise ValueError('Card revision is stale or not part of task')
            result=json.loads(row['routing_json'])
            if result['status']!='ASK_NOW' or row['state'] in ('confirmed','superseded'):raise ValueError('Only unresolved ASK_NOW cards can activate')
            scope=task['host_session_digest'] or 'unverified:'+task['owner']
            active=db.execute('SELECT * FROM decision_v3_active WHERE workspace=? AND host_session_digest=?',(str(self.workspace),scope)).fetchone()
            if prior:
                cached=json.loads(prior['response_json'])
                # A retry may repeat only the card that is still actually pending.
                # Never replay historical text while another card receives A/B replies.
                if (active is None or (active['decision_id'],active['revision'])!=(decision_id,revision) or
                        active['expires']<time.time() or row['state'] not in ('card_active','needs_explanation') or
                        cached['card']!=result['card']):
                    raise ValueError('Cached card activation is no longer current; inspect status and use a new activation key')
                return cached
            if active and active['decision_id'] and active['expires']<time.time():
                self.release_active(db,active,'EXPIRED_CARD')
                active=None
            if active and active['decision_id'] and (active['decision_id'],active['revision'])!=(decision_id,revision):
                raise ValueError('Another card is already active in this host session')
            db.execute('INSERT INTO decision_v3_active VALUES(?,?,?,?,?,?) ON CONFLICT(workspace,host_session_digest) DO UPDATE SET decision_id=excluded.decision_id,revision=excluded.revision,expires=excluded.expires,delivery_status=excluded.delivery_status',
                       (str(self.workspace),scope,decision_id,revision,time.time()+self.ttl,'not_observed'))
            db.execute("UPDATE decision_v3_items SET state='card_active' WHERE id=? AND revision=?",(decision_id,revision))
            response={'schema_version':'decision.v3','task_id':task['id'],'decision_id':decision_id,'revision':revision,
                      'state':'card_active','delivery_status':'not_observed','confirmation_status':'awaiting_user' if task['binding_status']=='hook_observed' else 'agent_reported_unverified',
                      'card':result['card'],'message':render(result['card'],position,total,task['binding_status']=='hook_observed'),
                      'does_not_authorize_host_operations':True}
            self.event(db,task['id'],'CARD_ACTIVATED',{'decision_id':decision_id,'revision':revision,'delivery_status':'not_observed'})
            db.execute('INSERT INTO decision_v3_operations VALUES(?,?,?,?,?)',(task['id'],'activate',key,fingerprint(given),encode(response)))
        return response

    def prepare_revision(self, task, decision_id, revision, candidate, reason):
        from .decision_cards import make_card
        from .candidate_policy import field_key
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM decision_v3_items WHERE id=? AND task_id=? AND revision=?',(decision_id,task['id'],revision)).fetchone()
            latest=db.execute('SELECT max(revision) FROM decision_v3_items WHERE id=?',(decision_id,)).fetchone()[0]
            if row is None or revision!=latest:raise ValueError('Revision source is stale')
            if field_key(candidate['field'])!=row['field_key']:raise ValueError('A revision must preserve decision identity')
            next_revision=revision+1
            result=json.loads(row['routing_json']);result.update(revision=next_revision,status='ASK_NOW',reason_codes=['REVISION_REQUIRES_NEW_USER_CHOICE'],confirmation_status='awaiting_user')
            for name in ('model_status','model_fields'):result.pop(name,None)
            result['card']=make_card(decision_id,next_revision,candidate,{'effective_dependency':candidate['current_dependency']})
            db.execute("UPDATE decision_v3_items SET state='superseded' WHERE id=? AND revision=?",(decision_id,revision))
            db.execute('UPDATE decision_v3_active SET decision_id=NULL,revision=NULL WHERE decision_id=?',(decision_id,))
            db.execute('INSERT INTO decision_v3_items VALUES(?,?,?,?,?,?,?,?,?)',(decision_id,next_revision,task['id'],row['field_key'],encode(candidate),encode(result),'screened',1,now()))
            self.event(db,task['id'],'REVISION_PREPARED',{'decision_id':decision_id,'revision':next_revision,'reason':reason,'prior_revision':revision})
        return result

    def status(self, task, owner):
        from .implementation import status as implementation_status
        from .verification import status as verification_status
        items=self.items(task['id']);decisions=[]
        with self.connect() as db:
            for row in items:
                current=json.loads(row['routing_json']);current.update(state=row['state'],needs_recheck=bool(row['needs_recheck']),confirmation=self.confirmation(row))
                for name in ('model_status','model_fields'):current.pop(name,None)
                if current['confirmation']:
                    current.update(status='PROCEED',card=None,confirmation_status='user_message_observed')
                decisions.append(current)
            confirmations=[dict(r) for r in db.execute('SELECT c.* FROM decision_v3_confirmations c JOIN decision_v3_items i ON c.decision_id=i.id AND c.revision=i.revision WHERE i.task_id=? ORDER BY c.created',(task['id'],))]
            coverage_row=db.execute("SELECT data_json FROM decision_v3_events WHERE task_id=? AND event_type='COVERAGE_RECORDED' ORDER BY id DESC LIMIT 1",(task['id'],)).fetchone()
            coverage=json.loads(coverage_row[0]) if coverage_row else {'reported':False,'provenance':'agent_declared','entries':[],'does_not_establish_completeness':True}
        return {'schema_version':'decision.v3','task_id':task['id'],'binding_status':task['binding_status'],
                'decisions':decisions,'coverage':coverage,'implementations':implementation_status(self,task['id']),
                'confirmation_history':confirmations,'verification':verification_status(self,task['id']),
                'does_not_authorize_host_operations':True}
