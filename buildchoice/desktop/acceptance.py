"""Immutable Agent-derived acceptance sets anchored to observed user choices."""
import json
import uuid
from pathlib import Path
from jsonschema import Draft202012Validator
from .audit import encode, now
from .common import ROOT
from .decision_store import fingerprint


def validate(schema, kind, value):
    document=json.loads((ROOT/'docs/contracts'/schema).read_text(encoding='utf-8'))
    Draft202012Validator({**document,'$ref':'#/$defs/'+kind}).validate(value)
    return value


def events(store, kind, task_id=None):
    with store.connect() as db:
        sql='SELECT data_json FROM decision_v3_events WHERE event_type=?'
        args=[kind]
        if task_id is not None:sql+=' AND task_id=?';args.append(task_id)
        rows=db.execute(sql+' ORDER BY id',args).fetchall()
    return [json.loads(row[0]) for row in rows]


def confirmed(store, task_id, decision_id, revision, db=None):
    if db is None:
        with store.connect() as connection:return confirmed(store,task_id,decision_id,revision,connection)
    task=db.execute('SELECT * FROM decision_v3_tasks WHERE id=? AND workspace=?',
                    (task_id,str(store.workspace))).fetchone()
    row=db.execute('SELECT * FROM decision_v3_items WHERE task_id=? AND id=? AND revision=?',
                   (task_id,decision_id,revision)).fetchone()
    latest=db.execute('SELECT max(revision) FROM decision_v3_items WHERE id=?',(decision_id,)).fetchone()[0]
    if task is None or task['binding_status']!='hook_observed' or row is None or row['state']!='confirmed' or latest!=revision:
        raise ValueError('CURRENT_OBSERVED_CONFIRMATION_REQUIRED')
    confirmation=db.execute("SELECT * FROM decision_v3_confirmations WHERE decision_id=? AND revision=? AND provenance='user_message_observed'",
                            (decision_id,revision)).fetchone()
    if confirmation is None:raise ValueError('CURRENT_OBSERVED_CONFIRMATION_REQUIRED')
    candidate=json.loads(row['candidate_json'])
    choice=next((option for option in candidate['options'] if option['id']==confirmation['choice_id']),None)
    if choice is None:raise ValueError('CONFIRMATION_OPTION_MISMATCH')
    return dict(confirmation),choice


def get(store, acceptance_id):
    for value in reversed(events(store,'ACCEPTANCE_PREPARED')):
        if value['acceptance_id']==acceptance_id:
            validate('acceptance-v1.schema.json','AcceptanceSet',value)
            body={key:value[key] for key in ('task_id','decision_id','decision_revision','confirmation_id','choice','criteria')}
            if fingerprint(body)!=value['acceptance_digest']:raise ValueError('ACCEPTANCE_DIGEST_MISMATCH')
            return value
    raise ValueError('UNKNOWN_ACCEPTANCE_SET')


def current(store, acceptance):
    confirmation,_=confirmed(store,acceptance['task_id'],acceptance['decision_id'],acceptance['decision_revision'])
    if confirmation['id']!=acceptance['confirmation_id']:raise ValueError('CONFIRMATION_CHANGED')
    latest=next((a for a in reversed(events(store,'ACCEPTANCE_PREPARED',acceptance['task_id']))
                 if a['decision_id']==acceptance['decision_id']),None)
    if latest is None or latest['acceptance_id']!=acceptance['acceptance_id']:raise ValueError('ACCEPTANCE_SUPERSEDED')


def prepare(store, task, decision_id, revision, criteria, key):
    validate('acceptance-v1.schema.json','PrepareInput',{'decision_id':decision_id,'revision':revision,'criteria':criteria,'idempotency_key':key})
    ids=[c['criterion_id'] for c in criteria]
    if len(ids)!=len(set(ids)):raise ValueError('DUPLICATE_CRITERION_ID')
    if any(not c[name].strip() for c in criteria for name in ('criterion_id','description','basis')):
        raise ValueError('CONCRETE_CRITERION_REQUIRED')
    if not any(c['required'] for c in criteria):raise ValueError('REQUIRED_CRITERION_NEEDED')
    given={'decision_id':decision_id,'revision':revision,'criteria':criteria}
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        confirmation,choice=confirmed(store,task['id'],decision_id,revision,db)
        cached=db.execute("SELECT * FROM decision_v3_operations WHERE task_id=? AND operation='acceptance' AND key=?",(task['id'],key)).fetchone()
        if cached:
            if cached['input_digest']!=fingerprint(given):raise ValueError('IDEMPOTENCY_INPUT_CHANGED')
            return json.loads(cached['response_json'])
        rows=db.execute("SELECT data_json FROM decision_v3_events WHERE task_id=? AND event_type='ACCEPTANCE_PREPARED'",(task['id'],)).fetchall()
        prior=[json.loads(row[0]) for row in rows if json.loads(row[0])['decision_id']==decision_id]
        body={'task_id':task['id'],'decision_id':decision_id,'decision_revision':revision,
              'confirmation_id':confirmation['id'],'choice':choice,'criteria':criteria}
        value={**body,'schema_version':'acceptance.v1','acceptance_id':'acc-'+uuid.uuid4().hex,
               'acceptance_version':max((a['acceptance_version'] for a in prior),default=0)+1,
               'acceptance_digest':fingerprint(body),'created':now(),'basis':'user_confirmed_decision',
               'criterion_author':'agent','human_approval':'not_separately_confirmed','coverage_complete':False}
        validate('acceptance-v1.schema.json','AcceptanceSet',value)
        store.event(db,task['id'],'ACCEPTANCE_PREPARED',value)
        db.execute('INSERT INTO decision_v3_operations VALUES(?,?,?,?,?)',(task['id'],'acceptance',key,fingerprint(given),encode(value)))
    return value
