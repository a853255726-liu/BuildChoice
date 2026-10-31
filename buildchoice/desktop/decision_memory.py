"""Project-local recall derived from observed choices, with explicit lifecycle commands.

Memory never creates confirmations or grants permission to execute host operations.
Lifecycle changes are accepted only by the trusted Hook from an exact user command.
"""
import hashlib
import json
import re
import time
from datetime import datetime
from .audit import encode
from .audit import MAX_BYTES
from .candidate_policy import field_key

REFERENCE_SECONDS = 30 * 24 * 60 * 60
COMMANDS = {'长期记住': 'promote', '取消长期': 'unpin', '遗忘': 'forget', '恢复': 'restore'}


def memory_id(confirmation_id):
    return 'M' + hashlib.sha256(confirmation_id.encode()).hexdigest()[:12].upper()


def timestamp(value):
    return datetime.fromisoformat(value).timestamp()


def sources_current(store, db, references, checked):
    for reference in references:
        ident=reference['source_id']
        if ident not in checked:
            source=db.execute('''SELECT s.* FROM sources s JOIN sessions t ON t.id=s.session
                WHERE s.id=? AND t.workspace=?''',(ident,str(store.workspace))).fetchone()
            valid=False
            if source and source['origin']=='collector_file_read':
                try:
                    with store.ledger.path(source['locator']).open('rb') as stream:raw=stream.read(MAX_BYTES+1)
                    valid=len(raw)<=MAX_BYTES and hashlib.sha256(raw).hexdigest()==source['digest']
                except (OSError,ValueError):pass
            checked[ident]=valid
        if not checked[ident]:return False
    return True


def records(store, db, clock=None):
    """Derive references lazily, including pre-upgrade confirmations; never rewrite history."""
    clock = time.time() if clock is None else clock
    rows = db.execute('''SELECT i.*, c.id AS confirmation_id, c.choice_id,
        c.created AS confirmed_at, c.provenance
        FROM decision_v3_confirmations c JOIN decision_v3_items i
        ON i.id=c.decision_id AND i.revision=c.revision
        JOIN decision_v3_tasks t ON t.id=i.task_id
        WHERE t.workspace=? AND t.binding_status='hook_observed'
        AND c.provenance='user_message_observed'
        ORDER BY c.created, c.id''', (str(store.workspace),)).fetchall()
    latest = {r['id']: r['revision'] for r in db.execute('''SELECT i.id, max(i.revision) AS revision
        FROM decision_v3_items i JOIN decision_v3_tasks t ON t.id=i.task_id
        WHERE t.workspace=? GROUP BY i.id''', (str(store.workspace),))}
    actions = {}
    for row in db.execute('''SELECT e.data_json FROM decision_v3_events e
        JOIN decision_v3_tasks t ON t.id=e.task_id
        WHERE t.workspace=? AND e.event_type='MEMORY_ACTION_OBSERVED' ORDER BY e.id''', (str(store.workspace),)):
        value = json.loads(row[0])
        actions.setdefault(value['memory_id'], []).append(value)
    result = []; checked={}
    for row in rows:
        candidate = json.loads(row['candidate_json'])
        chosen = next((o for o in candidate['options'] if o['id'] == row['choice_id']), None)
        if chosen is None:
            continue
        ident = memory_id(row['confirmation_id'])
        tier, forgotten, anchor = 'reference', False, timestamp(row['confirmed_at'])
        for action in actions.get(ident, []):
            if action['action'] == 'promote': tier = 'rule'
            elif action['action'] == 'unpin': tier, anchor = 'reference', action['at']
            elif action['action'] == 'forget': forgotten = True
            elif action['action'] == 'restore': forgotten, anchor = False, action['at']
        expires = None if tier == 'rule' else anchor + REFERENCE_SECONDS
        state = ('superseded' if latest.get(row['id']) != row['revision'] or row['state'] != 'confirmed'
                 else 'forgotten' if forgotten else 'archived' if expires is not None and clock >= expires
                 else 'needs_review' if not sources_current(store,db,candidate['evidence_refs'],checked) else 'active')
        result.append({'memory_id': ident, 'task_id': row['task_id'], 'decision_id': row['id'],
            'revision': row['revision'], 'confirmation_id': row['confirmation_id'],
            'provenance': 'user_message_observed', 'field': candidate['field'],
            'category': candidate['category'], 'question': candidate['question'],
            'choice': chosen, 'options': candidate['options'], 'risk_flags': candidate['risk_flags'],
            'tier': tier, 'state': state, 'confirmed_at': row['confirmed_at'],
            'expires_at': expires, 'scope': 'project', 'does_not_authorize_host_operations': True})
    return result


def choice_value(option):
    return encode(option.get('value', option['label']))


def rule_meaning(entry):
    chosen=entry['choice']
    return (entry['category'],choice_value(chosen),
        '' if 'value' in chosen else chosen['tradeoff'],tuple(sorted(entry['risk_flags'])))


def conflicts(entries):
    groups = {}
    for entry in entries:
        if entry['state'] == 'active' and entry['tier'] == 'rule':
            groups.setdefault(field_key(entry['field']), []).append(entry)
    return [{'field': group[0]['field'], 'memory_ids': [e['memory_id'] for e in group]}
            for group in groups.values() if len({rule_meaning(e) for e in group}) > 1]


def recall(store, db, query='', include_archived=False, limit=30):
    if not isinstance(query, str) or len(query) > 2000:
        raise ValueError('Memory query must be at most 2000 characters')
    if type(include_archived) is not bool:
        raise ValueError('include_archived must be boolean')
    entries = records(store, db)
    visible = [e for e in entries if include_archived or e['state'] == 'active']
    # Transparent lexical recall only. Partial matches are suggestions, not proof of scope.
    terms = re.findall(r'[a-z0-9_]+|[\u4e00-\u9fff]', query.casefold())
    def score(entry):
        text = (entry['field'] + ' ' + entry['question'] + ' ' + entry['choice']['label']).casefold()
        return sum(term in text for term in set(terms))
    if terms:
        visible = [e for e in visible if score(e) > 0 or e['memory_id'].casefold() in query.casefold()]
    visible.sort(key=lambda e: (score(e), e['tier'] == 'rule', e['confirmed_at'], e['memory_id']), reverse=True)
    return {'schema_version': 'memory.v1', 'entries': visible[:limit], 'total_matches': len(visible),
        'truncated': len(visible) > limit, 'conflicts': conflicts(entries),
        'reference_retention_days': 30, 'matching': 'lexical_suggestions_not_semantic_scope_proof',
        'commands': {key: key + ' <memory_id>' for key in COMMANDS},
        'does_not_authorize_host_operations': True}


def observe_command(store, db, prompt, host_turn_digest, clock=None):
    """No Agent-write endpoint: exact whole-message commands only, outside a pending card."""
    match = re.fullmatch(r'(长期记住|取消长期|遗忘|恢复)\s+(M[0-9A-Fa-f]{12})', prompt.strip())
    if not match:
        return None
    at = time.time() if clock is None else clock
    ident, action = match[2].upper(), COMMANDS[match[1]]
    entry = next((e for e in records(store, db, at) if e['memory_id'] == ident), None)
    if entry is None or entry['state'] == 'superseded':
        return {'memory_status': 'rejected', 'memory_id': ident, 'reason': 'UNKNOWN_OR_SUPERSEDED_MEMORY'}
    if action == 'promote' and entry['state'] != 'active':
        return {'memory_status': 'rejected', 'memory_id': ident, 'reason': 'RESTORE_BEFORE_PROMOTING'}
    value = {'memory_id': ident, 'action': action, 'at': at,
        'host_turn_digest': host_turn_digest, 'provenance': 'user_message_observed'}
    store.event(db, entry['task_id'], 'MEMORY_ACTION_OBSERVED', value)
    return {'memory_status': 'applied', 'memory_id': ident, 'memory_action': action}


def signature(store, db):
    return [{k: e[k] for k in ('memory_id', 'state', 'tier', 'expires_at', 'field', 'category', 'choice', 'risk_flags')}
            for e in records(store, db)]


def match_candidate(store, db, candidate, task_id):
    """Only explicit live project rules with identical field/category/option meaning apply.

    The Agent must preserve stable field names; lexical retrieval never auto-confirms scope.
    Sensitive actions still go through the normal decision and host authorization paths.
    """
    rules = [e for e in records(store, db) if e['state'] == 'active' and e['tier'] == 'rule'
             and e['task_id'] != task_id and field_key(e['field']) == field_key(candidate['field'])]
    if not rules:
        return None
    values = {rule_meaning(e) for e in rules}
    ids = [e['memory_id'] for e in rules]
    if len(values) != 1:
        return {'status': 'conflict', 'memory_ids': ids, 'reason': 'PROJECT_RULES_CONFLICT'}
    if candidate.get('memory_intent','uncertain')!='reuse':
        return {'status':'conflict','memory_ids':ids,'reason':
            'PROJECT_RULE_CHANGE_REQUESTED' if candidate.get('memory_intent')=='change' else 'PROJECT_RULE_SCOPE_UNCERTAIN'}
    rule = rules[-1]
    options = [o for o in candidate['options'] if choice_value(o) == choice_value(rule['choice'])]
    # Without explicit structured values, labels AND tradeoffs must agree: a reused label
    # such as "Automatic" can otherwise hide an entirely different behavior.
    compatible = (len(options) == 1 and candidate['category'] == rule['category'] and
        (('value' in options[0] and 'value' in rule['choice']) or
         options[0]['tradeoff'] == rule['choice']['tradeoff']))
    if not compatible:
        return {'status': 'conflict', 'memory_ids': ids, 'reason': 'PROJECT_RULE_SCOPE_OR_OPTIONS_CHANGED'}
    if candidate['risk_flags'] or rule['risk_flags']:
        return {'status': 'reference_only', 'memory_ids': ids, 'reason': 'SENSITIVE_RULE_REQUIRES_CURRENT_CHOICE'}
    return {'status': 'applicable', 'memory_ids': ids, 'choice_id': options[0]['id'],
        'source_confirmation_id': rule['confirmation_id'], 'reason': 'PROJECT_MEMORY_RULE'}
