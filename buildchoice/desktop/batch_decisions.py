"""Frozen batches, LLM reply interpretation and atomic trusted selections."""
import json
import time
import uuid
from . import product_store as ps
from .product_contracts import validate
from .decision_store import fingerprint
from .decision_cards import render
from .audit import encode, now


def tables(db):
    db.execute('''CREATE TABLE IF NOT EXISTS product_active_batches(
        host TEXT PRIMARY KEY, batch_id TEXT, expires REAL)''')


def item(store, db, task_id, ref):
    row = db.execute('SELECT * FROM decision_v3_items WHERE id=? AND task_id=? ORDER BY revision DESC LIMIT 1',
                     (ref['decision_id'], task_id)).fetchone()
    if row is None or row['revision'] != ref['revision']:
        raise ValueError('Batch contains a stale or incorrectly owned decision')
    route = json.loads(row['routing_json'])
    if route.get('validation_status', 'valid') != 'valid': raise ValueError('Decision sources require inspection')
    return dict(row), route


def state(store, db, row):
    answers = ps.objects(db, row['task'], 'batch_answer')
    answers = [r for r in answers if r['data']['batch_id'] == row['id']]
    by_id = {r['data']['decision_id']: r['data'] for r in answers}
    decisions = []
    for ref in row['data']['decisions']:
        try:
            current, _ = item(store, db, row['task'], ref)
            status = 'confirmed' if store.confirmation(current) else by_id.get(ref['decision_id'], {}).get('status', 'unanswered')
        except ValueError: status = 'stale'
        decisions.append({**ref, 'status': status})
    return {'id': row['id'], 'task_id': row['task'], 'decisions': decisions,
            'pending': [r for r in decisions if r['status'] not in ('confirmed',)],
            'expires': row['data']['expires'], 'message': row['data']['message']}


def execute(service, request):
    request = validate('batch', request); action = request['action']; task_id = request['task_id']
    def handler(store, db, ctx):
        tables(db); host = ctx['host_session_digest']
        if action == 'status': return state(store, db, ps.get(db, request['batch_id'], 'batch', task_id=task_id))
        if action == 'suspend':
            row = ps.get(db, request['batch_id'], 'batch', task_id=task_id)
            db.execute('DELETE FROM product_active_batches WHERE host=? AND batch_id=?', (host, row['id']))
            return {**state(store, db, row), 'suspended': True, 'unanswered_items_retained': True}
        if action == 'present':
            single = db.execute('SELECT * FROM decision_v3_active WHERE workspace=? AND host_session_digest=?',
                (str(store.workspace), host)).fetchone()
            if single and single['decision_id'] and single['expires'] >= time.time():
                raise ValueError('Finish or defer the active single card before presenting a batch')
            active = db.execute('SELECT * FROM product_active_batches WHERE host=?', (host,)).fetchone()
            if active and active['expires'] >= time.time():
                prior = state(store, db, ps.get(db, active['batch_id'], 'batch'))
                if prior['pending']:
                    if [(r['decision_id'], r['revision']) for r in prior['decisions']] == [(r['decision_id'], r['revision']) for r in request['decisions']]:
                        return {**prior, 'already_active': True}
                    raise ValueError('Another frozen batch is active; continue its unresolved items')
            ids = [r['decision_id'] for r in request['decisions']]
            if len(ids) != len(set(ids)): raise ValueError('Duplicate decision in batch')
            frozen = []; messages = []
            confirmed = {r['id'] for r in store.items(task_id) if store.confirmation(r)}
            key_map = {json.loads(r['candidate_json']).get('decision_key'): r['id'] for r in store.items(task_id)}
            for index, ref in enumerate(request['decisions'], 1):
                row, route = item(store, db, task_id, ref)
                candidate = json.loads(row['candidate_json'])
                if store.confirmation(row) or route['status'] != 'ASK_NOW' or not route.get('card'):
                    raise ValueError('Batch may contain only unresolved ASK_NOW decisions')
                for dependency in candidate.get('depends_on', []):
                    # IDs/keys are deterministic; other business dependency meaning remains LLM-owned.
                    target = key_map.get(dependency, dependency)
                    if target in ids or (target not in confirmed and any(r['id'] == target for r in store.items(task_id))):
                        raise ValueError('Resolve decision dependencies in a prior batch')
                evidence = service.evidence(store, candidate, [])
                if evidence['invalid'] or evidence['conflict']: raise ValueError('Batch decision sources have changed')
                frozen.append({**ref, 'candidate_digest': fingerprint(candidate), 'card': route['card'],
                               'card_digest': fingerprint(route['card'])})
                messages.append(render(route['card'], index, len(ids)))
            message = '\n\n'.join(messages) + '\n\n可逐项选择、暂缓或讨论；“都按推荐”只适用于此批明确列出推荐的项目。'
            result = ps.put(store, db, task_id, 'batch', {'host': host, 'turn': ctx['host_turn_digest'],
                'expires': time.time() + store.ttl, 'decisions': frozen, 'message': message, 'delivery_status': 'agent_must_display'})
            db.execute('INSERT INTO product_active_batches VALUES(?,?,?) ON CONFLICT(host) DO UPDATE SET '
                'batch_id=excluded.batch_id,expires=excluded.expires', (host, result['id'], result['expires']))
            return result
        row = ps.get(db, request['batch_id'], 'batch', task_id=task_id)
        data = ps.presentation(store, db, ctx, row['id'], 'batch', task_id)
        active = db.execute('SELECT * FROM product_active_batches WHERE host=?', (host,)).fetchone()
        if not active or active['batch_id'] != row['id']: raise ValueError('This batch is no longer active in the current chat')
        source = ps.user_source(ctx, request)
        answers = request['answers']; ids = [a['decision_id'] for a in answers]
        if len(ids) != len(set(ids)): raise ValueError('Duplicate answer in submission')
        frozen = {r['decision_id']: r for r in data['decisions']}
        # Check the entire frozen set before mutating any item, including unanswered versions.
        current = {}
        for ref in data['decisions']:
            item_row, route = item(store, db, task_id, ref)
            candidate = json.loads(item_row['candidate_json'])
            if fingerprint(candidate) != ref['candidate_digest'] or fingerprint(route['card']) != ref['card_digest']:
                raise ValueError('Frozen question/options/recommendation changed')
            evidence = service.evidence(store, candidate, [])
            if evidence['invalid'] or evidence['conflict']: raise ValueError('Frozen decision references are stale')
            current[ref['decision_id']] = item_row
        for answer in answers:
            ref = frozen.get(answer['decision_id'])
            if ref is None or ref['revision'] != answer['revision']: raise ValueError('Answer belongs to another batch/version')
            item_row = current[answer['decision_id']]
            if store.confirmation(item_row): raise ValueError('Already answered items must be omitted; revise through a new instruction')
            choices = {o['id'] for o in ref['card']['options']}
            if answer['status'] == 'selected':
                if answer.get('choice_id') not in choices: raise ValueError('Selected option is not in the frozen card')
                if answer.get('selection_basis') == 'current_recommendation':
                    recommendation = ref['card'].get('recommendation')
                    if not recommendation or recommendation['option_id'] != answer['choice_id']:
                        raise ValueError('Only an explicitly frozen recommendation may be used')
                db.execute('INSERT INTO decision_v3_confirmations VALUES(?,?,?,?,?,?,?,?)',
                    ('conf-' + uuid.uuid4().hex, answer['decision_id'], answer['revision'], answer['choice_id'],
                     'llm_interpreted_user_reply', ctx['host_turn_digest'], ctx['prompt_digest'], now()))
                db.execute("UPDATE decision_v3_items SET state='confirmed' WHERE id=? AND revision=?", (answer['decision_id'], answer['revision']))
                store.event(db, task_id, 'USER_CHOICE_OBSERVED', {**answer, **source, 'batch_id': row['id']})
            elif answer.get('choice_id'): raise ValueError('Discussion/defer cannot contain a selection')
            else:
                if answer['status'] == 'deferred' and not ref['card']['allow_defer']: raise ValueError('This decision does not permit defer')
                db.execute('UPDATE decision_v3_items SET state=? WHERE id=? AND revision=?',
                    ('deferred' if answer['status'] == 'deferred' else 'needs_explanation', answer['decision_id'], answer['revision']))
            ident = 'batchanswer-' + row['id'] + '-' + answer['decision_id']
            previous = db.execute('SELECT max(revision) FROM product_objects WHERE id=?', (ident,)).fetchone()[0] or 0
            ps.put(store, db, task_id, 'batch_answer', {'batch_id': row['id'], **answer, 'source': source}, ident, previous)
        result = state(store, db, row)
        if not result['pending']: db.execute('DELETE FROM product_active_batches WHERE host=?', (host,))
        # Existing decision projection is queued in the same atomic transaction.
        from .document_projection import queue
        queue(service, store, request['session_handle'])
        return {**result, 'recorded': True, 'source': source}
    result = ps.run(service, request, handler)
    if action == 'submit' and result.get('replayed'):
        store = service.store()
        with store.connect() as db:
            result = {**result, **state(store, db, ps.get(db, request['batch_id'], 'batch', task_id=task_id))}
    if action == 'submit':
        from .document_projection import publish
        result['document'] = publish(service, service.store(), request['session_handle'])
    return result
