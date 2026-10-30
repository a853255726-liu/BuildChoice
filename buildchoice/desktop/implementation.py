"""Agent-reported code locations with real file hashes, never correctness attestations."""
import hashlib
import json
from .audit import MAX_BYTES, encode


def snapshot(store, path, start_line=None, end_line=None):
    for value in (start_line, end_line):
        if value is not None and (type(value) is not int or value < 1):
            raise ValueError('Line numbers must be positive integers')
    if end_line is not None and start_line is None:
        raise ValueError('end_line requires start_line')
    if start_line is not None and end_line is not None and end_line < start_line:
        raise ValueError('Line range is reversed')
    file=store.ledger.path(path)
    with file.open('rb') as stream:raw=stream.read(MAX_BYTES+1)
    if len(raw)>MAX_BYTES:raise ValueError('Implementation file exceeds 256 KiB')
    text=raw.decode('utf-8-sig')
    if start_line is not None and max(start_line,end_line or start_line)>len(text.splitlines()):
        raise ValueError('Implementation line is outside the actual file')
    return {'path':file.relative_to(store.workspace).as_posix(),
            'start_line':start_line,'end_line':end_line,'file_sha256':hashlib.sha256(raw).hexdigest()}


def link(store, task, decision_id, revision, path, note, start_line=None, end_line=None):
    if type(revision) is not int or revision < 1:raise ValueError('Valid decision revision required')
    if not isinstance(note,str) or not note.strip() or len(note)>500:
        raise ValueError('Explain the implementation relation in at most 500 characters')
    observed=snapshot(store,path,start_line,end_line)
    identity={key:observed[key] for key in ('path','start_line','end_line')}
    identity.update(decision_id=decision_id,revision=revision)
    link_id='impl-'+hashlib.sha256(encode(identity).encode()).hexdigest()[:20]
    record={**identity,'link_id':link_id,'file_sha256':observed['file_sha256'],'note':note,
            'provenance':'agent_reported_implementation',
            'does_not_prove_correctness':True}
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT * FROM decision_v3_items WHERE task_id=? AND id=? AND revision=?',
                       (task['id'],decision_id,revision)).fetchone()
        latest=db.execute('SELECT max(revision) FROM decision_v3_items WHERE id=?',(decision_id,)).fetchone()[0]
        if row is None or latest!=revision or row['state']=='superseded':
            raise ValueError('Implementation must reference the current decision revision')
        rows=db.execute("SELECT data_json FROM decision_v3_events WHERE task_id=? AND event_type='IMPLEMENTATION_LINKED' ORDER BY id",(task['id'],)).fetchall()
        previous={entry['link_id']:entry for entry in (json.loads(r[0]) for r in rows)}
        if previous.get(link_id)==record:return record
        if link_id not in previous and len(previous)>=100:
            raise ValueError('Task already has 100 implementation links; use a new task scope')
        store.event(db,task['id'],'IMPLEMENTATION_LINKED',record)
    return record


def status(store, task_id):
    with store.connect() as db:
        rows=db.execute("SELECT data_json FROM decision_v3_events WHERE task_id=? AND event_type='IMPLEMENTATION_LINKED' ORDER BY id",(task_id,)).fetchall()
    links={entry['link_id']:entry for entry in (json.loads(r[0]) for r in rows)}
    revisions={entry['id']:entry['revision'] for entry in store.items(task_id)}
    result=[]
    for entry in links.values():
        reasons=[]
        if revisions.get(entry['decision_id'])!=entry['revision']:reasons.append('DECISION_REVISION_CHANGED')
        try:
            current=snapshot(store,entry['path'])
            file_status='unchanged' if current['file_sha256']==entry['file_sha256'] else 'changed'
        except (OSError,ValueError,UnicodeError):file_status='missing_or_unreadable'
        if file_status!='unchanged':reasons.append('IMPLEMENTATION_FILE_CHANGED_OR_UNAVAILABLE')
        result.append({**entry,'file_status':file_status,'needs_recheck':bool(reasons),'reason_codes':reasons})
    return result
