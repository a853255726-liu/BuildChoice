"""Append-only product history on the existing ledger and trusted Hook boundary."""
import json
import uuid
from .audit import encode, now
from .decision_store import fingerprint, canonical_prompt, prompt_matches


def tables(db):
    db.execute('''CREATE TABLE IF NOT EXISTS product_tasks(
        task TEXT PRIMARY KEY, enabled INTEGER NOT NULL, generation INTEGER NOT NULL DEFAULT 0)''')
    db.execute('''CREATE TABLE IF NOT EXISTS product_objects(
        id TEXT NOT NULL, revision INTEGER NOT NULL, task TEXT NOT NULL,
        kind TEXT NOT NULL, data TEXT NOT NULL, created TEXT NOT NULL,
        PRIMARY KEY(id,revision))''')
    db.execute('CREATE INDEX IF NOT EXISTS product_objects_task ON product_objects(task,kind,created)')
    db.execute('''CREATE TABLE IF NOT EXISTS product_operations(
        host TEXT, key TEXT, turn TEXT, target TEXT, digest TEXT, response TEXT,
        PRIMARY KEY(host,key), UNIQUE(host,turn,target))''')
    db.execute('''CREATE TABLE IF NOT EXISTS product_documents(
        task TEXT PRIMARY KEY, path TEXT, digest TEXT, state TEXT, error TEXT)''')
    db.execute('''CREATE TABLE IF NOT EXISTS product_task_hosts(
        host TEXT PRIMARY KEY, task TEXT NOT NULL)''')


def context(service, store, db, handle):
    ctx = store.context(db, handle, service.owner, claim=True)
    if ctx is None:
        raise ValueError('A current real Hook context is required')
    return ctx


def user_source(ctx, request):
    text = canonical_prompt(request['user_message'])
    quote = request['quote']
    if not quote.strip() or quote not in text or not prompt_matches(ctx['prompt_digest'], text):
        raise ValueError('Full user_message and exact quote must match the actual current Hook message')
    return {'quote': quote, 'message_digest': ctx['prompt_digest'],
            'host': ctx['host_session_digest'], 'turn': ctx['host_turn_digest'],
            'provenance': 'llm_interpreted_user_instruction', 'semantic_verified_by_program': False}


def task(store, db, ident, enabled=True):
    row = db.execute('SELECT t.*,p.enabled,p.generation FROM decision_v3_tasks t '
                     'JOIN product_tasks p ON p.task=t.id WHERE t.id=? AND t.workspace=?',
                     (ident, str(store.workspace))).fetchone()
    if row is None:
        raise ValueError('Unknown product task in this workspace')
    if enabled and not row['enabled']:
        raise ValueError('Product workflow is closed for this task')
    return dict(row)


def get(db, ident, kind=None, revision=None, task_id=None):
    row = db.execute('SELECT * FROM product_objects WHERE id=? ' +
                     ('AND revision=? ' if revision is not None else '') +
                     'ORDER BY revision DESC LIMIT 1',
                     (ident, revision) if revision is not None else (ident,)).fetchone()
    if row is None or (kind and row['kind'] != kind) or (task_id and row['task'] != task_id):
        raise ValueError('Unknown or incorrectly owned product record')
    return {**dict(row), 'data': json.loads(row['data'])}


def objects(db, task_id, kind, latest=True):
    return [{**dict(r), 'data': json.loads(r['data'])} for r in db.execute(
        'SELECT o.* FROM product_objects o WHERE task=? AND kind=? ' +
        ('AND revision=(SELECT max(revision) FROM product_objects WHERE id=o.id) ' if latest else '') +
        'ORDER BY created,id', (task_id, kind))]


def put(store, db, task_id, kind, data, ident=None, expected=0):
    ident = ident or kind + '-' + uuid.uuid4().hex
    latest = db.execute('SELECT max(revision) FROM product_objects WHERE id=?', (ident,)).fetchone()[0] or 0
    if latest != expected:
        raise ValueError('PRODUCT_VERSION_CONFLICT: reload current version')
    revision = expected + 1
    db.execute('INSERT INTO product_objects VALUES(?,?,?,?,?,?)',
               (ident, revision, task_id, kind, encode(data), now()))
    db.execute('UPDATE product_tasks SET generation=generation+1 WHERE task=?', (task_id,))
    store.event(db, task_id, 'PRODUCT_' + kind.upper(), {'id': ident, 'revision': revision})
    db.execute("INSERT INTO product_documents VALUES(?,NULL,NULL,'pending',NULL) "
               "ON CONFLICT(task) DO UPDATE SET state='pending'", (task_id,))
    return {'id': ident, 'revision': revision, 'task_id': task_id, **data}


def run(service, request, handler, require_task=True):
    store = service.store()  # Check mode before creating any product tables or files.
    with store.transaction() as db:
        tables(db)
        ctx = context(service, store, db, request['session_handle'])
        task_id = request.get('task_id')
        if require_task:
            task(store, db, task_id, enabled=request['action'] not in ('status', 'document', 'independent_status'))
            db.execute('INSERT INTO product_task_hosts VALUES(?,?) ON CONFLICT(host) DO UPDATE SET task=excluded.task',
                       (ctx['host_session_digest'], task_id))
        target = request['action'] + ':' + str(task_id) + ':' + str(request.get('presentation_id',
            request.get('scenario_id', request.get('review_id', request.get('batch_id', '')))))
        digest = fingerprint({k: v for k, v in request.items() if k not in ('session_handle', 'idempotency_key')})
        key = request.get('idempotency_key')
        if request['action'] not in ('acknowledge', 'feedback', 'submit'):
            target += ':' + (digest if request['action'] == 'save' else str(key))
        old = None
        if key:
            old = db.execute('SELECT * FROM product_operations WHERE host=? AND (key=? OR (turn=? AND target=?))',
                             (ctx['host_session_digest'], key, ctx['host_turn_digest'], target)).fetchall()
        if old:
            if any(r['digest'] != digest for r in old):
                raise ValueError('Conflicting retry or second interpretation in the same turn')
            return {**json.loads(old[0]['response']), 'replayed': True,
                    'receipt_only': True, 'does_not_reapply_historical_state': True}
        result = handler(store, db, ctx)
        result = {'schema_version': 'product.v1', 'task_id': task_id, 'does_not_authorize_host_operations': True,
                  'semantic_judgment_by': 'llm', **result}
        if key:
            db.execute('INSERT INTO product_operations VALUES(?,?,?,?,?,?)',
                       (ctx['host_session_digest'], key, ctx['host_turn_digest'], target, digest, encode(result)))
        return result


def decision_ref(store, db, reference):
    row = db.execute('SELECT i.* FROM decision_v3_items i JOIN decision_v3_tasks t ON t.id=i.task_id '
                     'WHERE i.id=? AND t.workspace=? ORDER BY revision DESC LIMIT 1',
                     (reference['decision_id'], str(store.workspace))).fetchone()
    if row is None or row['revision'] != reference['revision']:
        raise ValueError('Decision source is stale or outside this workspace')
    conf = store.confirmation(row)
    if conf is None or not conf['applicable'] or conf['provenance'] not in (
            'user_message_observed', 'llm_interpreted_user_reply', 'llm_interpreted_user_instruction'):
        raise ValueError('Decision source requires current trusted confirmation')
    return {**reference, 'confirmation_id': conf['id']}


def presentation(store, db, ctx, ident, kind, task_id):
    row = get(db, ident, kind, task_id=task_id)
    data = row['data']
    if data['host'] != ctx['host_session_digest'] or data['turn'] == ctx['host_turn_digest']:
        raise ValueError('Re-present frozen content in this chat before using a new real user reply')
    import time
    if data['expires'] < time.time():
        raise ValueError('Presentation expired; show current content again')
    return data
