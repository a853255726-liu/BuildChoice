"""Durable, retryable Markdown projection; SQLite remains authoritative."""
import hashlib
import os
import uuid
from .audit import now
from .decision_document import document, destination

DEFAULT='BUILDCHOICE_DECISIONS.md'


def tables(db):
    db.execute('''CREATE TABLE IF NOT EXISTS decision_v3_document_jobs(
        workspace TEXT PRIMARY KEY,path TEXT,markdown TEXT,digest TEXT,state TEXT,error TEXT,updated TEXT)''')


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def queue(service,store,handle):
    markdown=document(service,store,handle,confirmed_only=True)['markdown']
    with store.connect() as db:
        tables(db)
        db.execute("INSERT INTO decision_v3_document_jobs VALUES(?,NULL,?,?,'pending',NULL,?) "
            "ON CONFLICT(workspace) DO UPDATE SET markdown=excluded.markdown,digest=excluded.digest,state='pending',error=NULL,updated=excluded.updated",
            (str(store.workspace),markdown,digest(markdown),now()))


def safe_path(store,preferred):
    # Reuse only files owned by this generator; never replace handwritten notes.
    for path in dict.fromkeys([preferred or DEFAULT,DEFAULT,'BUILDCHOICE_DECISIONS.generated.md',
            *('BUILDCHOICE_DECISIONS.generated.'+str(i)+'.md' for i in range(2,102))]):
        try:return path,destination(store,path)
        except (ValueError,UnicodeError):continue
    raise ValueError('No available generated decision document path')


def publish(service,store,handle):
    if store._transaction.get() is not None:raise ValueError('Publish requires a committed ledger transaction')
    # Serializes record writers and publishers. Always project the latest ledger,
    # including when retrying an old receipt after a newer revision was committed.
    with store.transaction() as db:
        tables(db)
        job=db.execute('SELECT * FROM decision_v3_document_jobs WHERE workspace=?',(str(store.workspace),)).fetchone()
        if not job:return {'status':'not_requested'}
        queue(service,store,handle)
        job=db.execute('SELECT * FROM decision_v3_document_jobs WHERE workspace=?',(str(store.workspace),)).fetchone()
        temporary=None;path=job['path']
        try:
            path,target=safe_path(store,path)
            if not target.exists() or hashlib.sha256(target.read_bytes()).hexdigest()!=job['digest']:
                temporary=target.with_name(target.name+'.'+uuid.uuid4().hex+'.tmp')
                temporary.write_bytes(job['markdown'].encode('utf-8'))
                destination(store,path)
                os.replace(temporary,target)
            db.execute("UPDATE decision_v3_document_jobs SET path=?,state='published',error=NULL WHERE workspace=?",(path,str(store.workspace)))
            return {'status':'synchronized','path':path,'sha256':job['digest']}
        except (OSError,ValueError,UnicodeError) as error:
            db.execute("UPDATE decision_v3_document_jobs SET path=?,state='pending',error=? WHERE workspace=?",
                (path,type(error).__name__,str(store.workspace)))
            return {'status':'pending','path':path,'reason':type(error).__name__,
                'retry':'Repeat buildchoice_record_instruction or write buildchoice_decision_document'}
        finally:
            if temporary is not None:
                try:temporary.unlink(missing_ok=True)
                except OSError:pass


def status(service,store,handle):
    with store.connect() as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='decision_v3_document_jobs'").fetchone():return {'status':'not_requested'}
        row=db.execute('SELECT * FROM decision_v3_document_jobs WHERE workspace=?',(str(store.workspace),)).fetchone()
    if row is None:return {'status':'not_requested'}
    current=digest(document(service,store,handle,confirmed_only=True)['markdown'])
    try:
        target=destination(store,row['path'])
        actual=hashlib.sha256(target.read_bytes()).hexdigest()
    except (OSError,ValueError,TypeError,UnicodeError):actual=None
    return {'status':'synchronized' if row['state']=='published' and actual==row['digest']==current else 'pending',
        'path':row['path'],'reason':row['error'],'sha256':row['digest']}
