"""Task-scoped scenarios, per-behavior origins and frozen pre-development expectations."""
import time
from . import product_store as ps
from .product_contracts import validate
from .decision_store import fingerprint


def latest_scenarios(db, task_id):
    return ps.objects(db, task_id, 'scenario')


def scenario_state(db, row):
    state = 'revised' if row['revision'] > 1 else 'generated'
    for event in ps.objects(db, row['task'], 'scenario_review', latest=False):
        if {'id': row['id'], 'revision': row['revision']} == event['data']['scenario']:
            state = event['data']['status']
    return state


def refs(db, task_id, supplied=None):
    rows = latest_scenarios(db, task_id)
    if not rows: raise ValueError('Generate scenarios before presenting or freezing expectations')
    if supplied is not None:
        if len({r['id'] for r in supplied}) != len(supplied): raise ValueError('Duplicate scenario')
        chosen = {r['id']: r['revision'] for r in supplied}
        rows = [r for r in rows if r['id'] in chosen]
        if len(rows) != len(chosen) or any(r['revision'] != chosen[r['id']] for r in rows):
            raise ValueError('Scenario version is stale or not part of task')
    return [{'id': r['id'], 'revision': r['revision']} for r in rows]


def validate_source(service, store, db, ctx, source, behavior, task_id):
    source = dict(source)
    if source['kind'] == 'recorded':
        prior = ps.get(db, source['scenario']['id'], 'scenario', source['scenario']['revision'], task_id)
        original = next((b for b in prior['data']['behaviors'] if b['behavior_id'] == source['behavior_id']), None)
        if original is None or original['text'] != behavior['text'] or original['behavior_id'] != behavior['behavior_id']:
            raise ValueError('Recorded origins can only be reused for the identical stable behavior')
        return {**original['source'], 'reused_from': source['scenario']}
    if source['kind'] == 'user':
        return {'kind': 'user', **ps.user_source(ctx, source)}
    if source['kind'] == 'decision':
        return {'kind': 'decision', **ps.decision_ref(store, db, source)}
    if source['kind'] == 'project':
        result = service.evidence(store, {'evidence_refs': [{'source_id': source['source_id'], 'quote': source['quote']}]}, [])
        if result['invalid'] or not result['source_ids']:
            raise ValueError('Project origin must cite actually read, unchanged source text')
    return source


def current_reasons(store, db, expectation):
    reasons = []
    for reference in expectation['scenarios']:
        row = ps.get(db, reference['id'], 'scenario', task_id=expectation['task_id'])
        if row['revision'] != reference['revision']:
            reasons.append('scenario_changed:' + reference['id'])
        frozen = ps.get(db, reference['id'], 'scenario', reference['revision'])
        for decision in frozen['data'].get('related_decisions', []) + [b['source'] for b in frozen['data']['behaviors'] if b['source']['kind'] == 'decision']:
            try: ps.decision_ref(store, db, decision)
            except ValueError: reasons.append('decision_changed:' + decision['decision_id'])
        from .task_context import source_state
        for behavior in frozen['data']['behaviors']:
            source = behavior['source']
            if source['kind'] == 'project' and not source_state(store, source['source_id'])['current']:
                reasons.append('source_changed:' + source['source_id'])
    return list(dict.fromkeys(reasons))


def summary(store, db, task_id):
    task = ps.task(store, db, task_id, enabled=False)
    scenarios = [{'id': r['id'], 'revision': r['revision'], **r['data'],
                  'review_status': scenario_state(db, r)} for r in latest_scenarios(db, task_id)]
    expectations = [{'id': r['id'], **r['data']} for r in ps.objects(db, task_id, 'expectation')]
    from .behavior_review import status as review_status
    reviews = [review_status(store, db, r) for r in ps.objects(db, task_id, 'behavior_review')]
    unresolved = []
    for review in reviews:
        followups = [r for r in reviews if r.get('previous_review_id') == review['id']]
        for finding in review['findings']:
            superseded = any(new['finding_id'] == finding['finding_id'] or (
                finding.get('scenario') and new.get('scenario') == finding['scenario'] and
                set(finding.get('behavior_ids', [])) <= set(new.get('behavior_ids', [])))
                for followup in followups for new in followup['findings'])
            if not superseded and finding['resolution_state'] in ('unresolved', 'deferred') and (
                    finding['requires_followup'] or review['validity'] != 'current'):
                unresolved.append({'review_id': review['id'], **finding})
    return {'task_id': task_id, 'enabled': bool(task['enabled']), 'generation': task['generation'],
            'scenarios': scenarios, 'expectations': expectations, 'reviews': reviews,
            'latest_review': reviews[-1] if reviews else None,
            'unresolved_differences': unresolved,
            'pending_batches': [r for r in ps.objects(db, task_id, 'batch')],
            'document': document_status(store, db, task_id)}


def execute(service, request):
    request = validate('experience', request)
    action = request['action']; task_id = request.get('task_id')

    def handler(store, db, ctx):
        nonlocal task_id
        if action == 'enable':
            if task_id:
                # Cross-chat recovery is workspace-scoped, never an inherited confirmation handle.
                row = db.execute('SELECT * FROM decision_v3_tasks WHERE id=? AND workspace=?',
                                 (task_id, str(store.workspace))).fetchone()
                if row is None: raise ValueError('Unknown task')
            else:
                row = store.open_task(request['task_text'], 'before_implementation', service.owner, request['session_handle'])
                task_id = row['id']
            db.execute('INSERT INTO product_tasks VALUES(?,1,0) ON CONFLICT(task) DO UPDATE SET enabled=1', (task_id,))
            db.execute('INSERT INTO product_task_hosts VALUES(?,?) ON CONFLICT(host) DO UPDATE SET task=excluded.task',
                       (ctx['host_session_digest'], task_id))
            return {'task_id': task_id, 'enabled': True}
        if action == 'status':
            if task_id: return summary(store, db, task_id)
            return {'tasks': [summary(store, db, r['task']) for r in db.execute(
                'SELECT p.task FROM product_tasks p JOIN decision_v3_tasks t ON t.id=p.task WHERE t.workspace=?',
                (str(store.workspace),))]}
        ps.task(store, db, task_id, enabled=action != 'document')
        if action == 'close':
            db.execute('UPDATE product_tasks SET enabled=0 WHERE task=?', (task_id,))
            return {'task_id': task_id, 'enabled': False}
        if action == 'document':
            return {'task_id': task_id, 'markdown': render(store, db, task_id)}
        if action == 'save':
            saved = []; seen = set()
            for given in request['scenarios']:
                ident = given.get('scenario_id')
                if ident in seen and ident is not None: raise ValueError('Duplicate scenario identity')
                seen.add(ident)
                if ident: ps.get(db, ident, 'scenario', task_id=task_id)
                elif given['expected_revision'] != 0: raise ValueError('New scenarios require expected_revision=0')
                ids = [b['behavior_id'] for b in given['behaviors']]
                if len(ids) != len(set(ids)): raise ValueError('Duplicate behavior identity')
                data = {k: v for k, v in given.items() if k not in ('scenario_id', 'expected_revision')}
                data['behaviors'] = [{**b, 'source': validate_source(service, store, db, ctx, b['source'], b, task_id)} for b in given['behaviors']]
                data['related_decisions'] = [ps.decision_ref(store, db, d) for d in data.get('related_decisions', [])]
                saved.append(ps.put(store, db, task_id, 'scenario', data, ident, given['expected_revision']))
            return {'scenarios': saved, 'user_approved': False}
        if action == 'present':
            references = refs(db, task_id, request.get('scenarios'))
            contents = [ps.get(db, r['id'], 'scenario', r['revision']) for r in references]
            message = render_scenarios(db, contents)
            result = ps.put(store, db, task_id, 'experience_presentation', {
                'host': ctx['host_session_digest'], 'turn': ctx['host_turn_digest'],
                'expires': time.time() + store.ttl, 'scenarios': references,
                'message': message, 'content_digest': fingerprint(message), 'delivery_status': 'agent_must_display'})
            for ref in references:
                # A later display never downgrades an already accepted version.
                if scenario_state(db, ps.get(db, ref['id'], revision=ref['revision'])) not in ('accepted', 'pending', 'deferred', 'discuss'):
                    ps.put(store, db, task_id, 'scenario_review', {'scenario': ref, 'status': 'displayed', 'presentation_id': result['id']})
            return result
        if action == 'acknowledge':
            shown = ps.presentation(store, db, ctx, request['presentation_id'], 'experience_presentation', task_id)
            source = ps.user_source(ctx, request)
            if len({r['id'] for r in request['scenarios']}) != len(request['scenarios']): raise ValueError('Duplicate acknowledgement')
            for ref in request['scenarios']:
                clean = {'id': ref['id'], 'revision': ref['revision']}
                if clean not in shown['scenarios']: raise ValueError('Unshown or changed scenario cannot be acknowledged')
                refs(db, task_id, [clean])
                ps.put(store, db, task_id, 'scenario_review', {'scenario': clean, 'status': ref['status'],
                    'source': source, 'presentation_id': request['presentation_id']})
            return {'recorded': True, 'scenarios': request['scenarios'], 'source': source}
        if action == 'freeze':
            references = refs(db, task_id, request.get('scenarios'))
            rows = [ps.get(db, r['id'], revision=r['revision']) for r in references]
            data = {'task_id': task_id, 'scenarios': references,
                    'review_states': {r['id']: scenario_state(db, r) for r in rows},
                    'content_digest': fingerprint([r['data'] for r in rows])}
            reasons = current_reasons(store, db, data)
            if reasons: raise ValueError('Expectation sources require review: ' + ','.join(reasons))
            return ps.put(store, db, task_id, 'expectation', data)
        raise ValueError('Unsupported experience action')

    result = ps.run(service, request, handler, require_task=False)
    if action == 'document': result['document'] = publish(service, task_id)
    if action not in ('status', 'document') and result.get('task_id'):
        result['document'] = publish(service, result['task_id'])
    return result


SOURCE_LABELS = {'user': '用户明确要求', 'decision': '已确认决定', 'project': '项目资料', 'ai': 'AI 建议或推导', 'unresolved': '尚未明确'}
STATE_LABELS = {'generated': '已生成，尚未审阅', 'displayed': '已展示，尚未认可', 'accepted': '已认可',
                'pending': '待决定', 'deferred': '暂缓', 'discuss': '讨论中', 'revised': '已修订，尚未认可'}
MARKER = '<!-- BuildChoice generated product document -->'


def render_scenarios(db, rows):
    lines = ['产品体验预期', '']
    for index, row in enumerate(rows, 1):
        data = row['data']
        lines += [str(index) + '. ' + data['title'] + '（v' + str(row['revision']) + '）',
                  data['trigger'] + ' → ' + data['action'], '适用范围：' + data['scope']]
        if data.get('conditions'): lines += ['适用条件：' + '；'.join(data['conditions'])]
        for behavior in data['behaviors']:
            lines.append('- ' + behavior['text'] + '〔' + SOURCE_LABELS[behavior['source']['kind']] + '〕')
        lines += ['审阅状态：' + STATE_LABELS[scenario_state(db, row)], '']
    lines += ['可认可当前展示的具体方案、修改、讨论或暂缓；展示和保存本身不代表认可。']
    return '\n'.join(lines)


def render(store, db, task_id):
    from .behavior_review import render as render_review, status as review_status
    lines = [MARKER, '# 产品预期与行为审阅', '', render_scenarios(db, latest_scenarios(db, task_id)), '']
    expectations = ps.objects(db, task_id, 'expectation')
    lines += ['已保存开发预期基线：' + str(len(expectations)) + ' 份；每次审阅使用其关联的冻结版本。', '']
    for row in ps.objects(db, task_id, 'behavior_review'):
        lines += [render_review(review_status(store, db, row)), '']
    return '\n'.join(lines) + '\n'


def document_status(store, db, task_id):
    row = db.execute('SELECT * FROM product_documents WHERE task=?', (task_id,)).fetchone()
    if row is None: return {'status': 'not_requested'}
    state = row['state']
    if row['path']:
        try:
            from .decision_document import destination
            import hashlib
            actual = hashlib.sha256(destination(store, row['path'], MARKER).read_bytes()).hexdigest()
            current = hashlib.sha256(render(store, db, task_id).encode('utf-8')).hexdigest()
            if actual != row['digest'] or current != row['digest']: state = 'pending'
        except (OSError, ValueError): state = 'pending'
    return {'status': state, 'path': row['path'], 'reason': row['error']}


def publish(service, task_id):
    import hashlib
    import os
    import uuid
    from .decision_document import destination
    store = service.store()
    with store.transaction() as db:
        ps.tables(db); ps.task(store, db, task_id, enabled=False)
        name = 'BUILDCHOICE_PRODUCT_' + task_id.split('-')[-1][:12] + '.md'
        old = db.execute('SELECT * FROM product_documents WHERE task=?', (task_id,)).fetchone()
        temporary = None
        try:
            path = None
            for candidate in dict.fromkeys([old['path'] if old else None, name, name.replace('.md', '.generated.md')]):
                if not candidate: continue
                try: target = destination(store, candidate, MARKER); path = candidate; break
                except ValueError: continue
            if path is None: raise ValueError('Generated product document paths are occupied')
            content = render(store, db, task_id).encode('utf-8'); digest = hashlib.sha256(content).hexdigest()
            temporary = target.with_name(target.name + '.' + uuid.uuid4().hex + '.tmp')
            temporary.write_bytes(content)
            destination(store, path, MARKER)
            os.replace(temporary, target)
            db.execute("INSERT INTO product_documents VALUES(?,?,?,'synchronized',NULL) ON CONFLICT(task) "
                       "DO UPDATE SET path=excluded.path,digest=excluded.digest,state='synchronized',error=NULL", (task_id, path, digest))
            return {'status': 'synchronized', 'path': path, 'sha256': digest}
        except (OSError, ValueError, UnicodeError) as error:
            db.execute("INSERT INTO product_documents VALUES(?,NULL,NULL,'pending',?) ON CONFLICT(task) "
                       "DO UPDATE SET state='pending',error=excluded.error", (task_id, type(error).__name__))
            return {'status': 'pending', 'reason': type(error).__name__, 'retry': 'experience document'}
        finally:
            if temporary:
                try: temporary.unlink(missing_ok=True)
                except OSError: pass
