"""Project-local recall derived from observed choices, with explicit lifecycle commands.

Memory never creates confirmations or grants permission to execute host operations.
Lifecycle changes require a real Hook command or a Hook-bound management request.
"""
import hashlib
import json
import re
import time
from datetime import datetime
from .audit import encode
from .audit import MAX_BYTES
from .candidate_policy import field_key
from .candidate_identity import scope,option_semantics
import math
import unicodedata

REFERENCE_SECONDS = 30 * 24 * 60 * 60
COMMANDS = {'长期记住': 'promote', '取消长期': 'unpin', '遗忘': 'forget', '恢复': 'restore'}


def management_intent(prompt):
    """Conservative authorization grammar, not a semantic decision classifier.

    Unrecognized language can be clarified by the Skill; it never grants write access.
    Whole-message matching excludes quotations, questions and compound instructions.
    """
    text=prompt.strip().rstrip('。！!')
    if (len(text)>500 or re.search(r'[\n\r\"“”‘’\'`?？,，;；:：]',text)
            or re.search(r'不要|不想|是否|能否|可以吗|例如|比如|建议|用户说|假如|如果',text)):
        return None
    text=re.sub(r'^(?:请帮我|请|帮我)', '',text).strip()
    patterns=[
        ('promote',r'(?:把|将)(.+?)(?:长期记住|长期保存|设为项目默认规则|设为项目规则)'),
        ('promote',r'(?:长期记住|长期保存)(.+)'),
        ('promote',r'记住(.+?(?:决定|决策|选择))'),
        ('promote',r'以后(?:这个|本)?项目都按(.+?)(?:来|执行|处理)'),
        ('unpin',r'取消(.+?)的长期(?:记忆|规则|保存)'),
        ('forget',r'(?:遗忘|忘记)(.+)'),
        ('restore',r'恢复(.+?)的(?:记忆|规则)'),
    ]
    for action,pattern in patterns:
        match=re.fullmatch(pattern,text)
        if match:
            target=match[1].strip()
            if not target or re.fullmatch(r'M[0-9a-fA-F]{12}',target):return None
            return {'action':action,'target':target}
    return None


def observe_request(store, db, prompt, host_session_digest):
    """Freeze possible targets when the Hook sees the user, before any Agent writes.

    Deictic targets belong to this real chat. Named targets may refer to this project's
    history across chats, but must match literally and uniquely; fuzzy recall alone is
    insufficient to authorize a modification.
    """
    intent=management_intent(prompt)
    if intent is None:return None
    entries=records(store,db)
    target=intent['target']
    recent=target in ('刚才的选择','刚才的决定','刚才的方案','刚才确认的选择',
        '这个选择','这个方案','这个决定','该方案','上一个决定')
    if recent:
        tasks=db.execute('SELECT id,created FROM decision_v3_tasks WHERE workspace=? AND host_session_digest=?',
            (str(store.workspace),host_session_digest)).fetchall()
        task_ids={r['id'] for r in tasks}
        matches=[e for e in entries if e['task_id'] in task_ids]
        if matches:
            latest=max(e['confirmed_at'] for e in matches)
            matches=[e for e in matches if e['confirmed_at']==latest]
            if any(timestamp(t['created'])>timestamp(latest) for t in tasks):matches=[]
    else:
        query=re.sub(r'^(?:之前|以前)?(?:关于)?','',target)
        query=re.sub(r'的(?:决定|决策|选择|方案|记忆|规则)$','',query).strip()
        # Questions may mention *both* alternatives. Substring hits such as "save"
        # in "do not save" cannot authorize a choice. Only explicit topic wording
        # permits partial field matching; fuzzy recall remains available to the Skill.
        topic=bool(re.match(r'^(?:之前|以前)?关于',target))
        matches=[e for e in entries if e['state']!='superseded' and len(query)>=2 and
            (query.casefold() in (e['field'].casefold(),e['choice']['label'].casefold(),e['decision_key'].casefold())
             or (topic and query.casefold() in e['field'].casefold()))]
    return {**intent,'targets':[{k:e[k] for k in ('memory_id','revision','confirmation_id','scope_key','conditions')}
        for e in matches], 'reason': 'TARGET_UNIQUE' if len(matches)==1 else
        'TARGET_AMBIGUOUS' if matches else 'TARGET_NOT_FOUND', 'binding':'hook_observed'}


def manage(store, db, ctx, ident, revision, action):
    """The caller selects a result; only the Hook's frozen unique target authorizes it."""
    request=json.loads(ctx['outcome_json']).get('_memory_request')
    def clarify(reason):
        return {'memory_status':'clarification_required','reason':reason,'does_not_authorize_host_operations':True}
    if not request or request.get('binding')!='hook_observed':return clarify('EXPLICIT_USER_MEMORY_REQUEST_REQUIRED')
    if action!=request['action']:return clarify('USER_REQUEST_ACTION_MISMATCH')
    if len(request['targets'])!=1:return clarify(request['reason'])
    expected=request['targets'][0]
    if ident!=expected['memory_id'] or type(revision) is not int or revision!=expected['revision']:
        return clarify('USER_REQUEST_TARGET_MISMATCH')
    entry=next((e for e in records(store,db) if e['memory_id']==ident),None)
    if entry is None or any(entry[k]!=expected[k] for k in expected):return clarify('MEMORY_VERSION_OR_SCOPE_CHANGED')
    if entry['state']=='superseded':return clarify('UNKNOWN_OR_SUPERSEDED_MEMORY')
    if action=='promote' and entry['state']!='active':return clarify('RESTORE_OR_REVIEW_BEFORE_PROMOTING')
    if action not in ('promote','unpin','forget','restore'):return clarify('UNSUPPORTED_MEMORY_ACTION')
    # Preserve the original conflict mechanism: never silently replace another rule.
    if action=='promote':
        prospective=[dict(e,tier='rule') if e['memory_id']==ident else e for e in records(store,db)]
        if any(ident in c['memory_ids'] for c in conflicts(prospective)):return clarify('PROJECT_RULES_CONFLICT')
    prior=[json.loads(r[0]) for r in db.execute("SELECT data_json FROM decision_v3_events WHERE task_id=? AND event_type='MEMORY_ACTION_OBSERVED'",
        (entry['task_id'],))]
    repeated=any(v['host_turn_digest']==ctx['host_turn_digest'] and v.get('host_session_digest')==ctx['host_session_digest']
                 and v['memory_id']==ident and v['action']==action for v in prior)
    if not repeated:
        store.event(db,entry['task_id'],'MEMORY_ACTION_OBSERVED',{'memory_id':ident,'action':action,
            'at':time.time(),'host_turn_digest':ctx['host_turn_digest'],'provenance':'user_message_observed',
            'authorization':'hook_bound_memory_request','user_prompt_digest':ctx['prompt_digest'],
            'host_session_digest':ctx['host_session_digest'],
            'revision':revision,'scope_key':entry['scope_key'],'conditions':entry['conditions']})
    return {'memory_status':'applied','memory_id':ident,'memory_action':action,'revision':revision,
        'scope_key':entry['scope_key'],'conditions':entry['conditions'],'replayed':repeated,
        'does_not_authorize_host_operations':True}


def decision_key(candidate):
    return candidate.get('decision_key') or 'legacy.'+hashlib.sha256(
        (candidate['category']+':'+field_key(candidate['field'])).encode()).hexdigest()[:20]


def terms(value):
    """Word tokens plus Chinese phrases/bigrams; no isolated-character recall."""
    value=unicodedata.normalize('NFKC',value).casefold()
    result=set(re.findall(r'[a-z0-9_]+',value))
    for phrase in re.findall(r'[\u4e00-\u9fff]{2,}',value):
        result.add(phrase)
        result.update(phrase[i:i+2] for i in range(len(phrase)-1))
    return result


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
            if source and source['origin'] in ('collector_file_read','hook_file_read'):
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
        AND c.provenance IN ('user_message_observed','llm_interpreted_user_reply','llm_interpreted_user_instruction')
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
        result.append({'memory_id': ident,'decision_key':decision_key(candidate), 'task_id': row['task_id'], 'decision_id': row['id'],
            'revision': row['revision'], 'confirmation_id': row['confirmation_id'],
            'provenance': row['provenance'], 'semantic_verified_by_program':False, 'field': candidate['field'],
            'category': candidate['category'], 'question': candidate['question'],
            'choice': chosen, 'options': candidate['options'], 'risk_flags': candidate['risk_flags'],
            'scope_key':candidate.get('scope_key','project'),'conditions':candidate.get('conditions',[]),
            'tier': tier, 'state': state, 'confirmed_at': row['confirmed_at'],
            'expires_at': expires, 'scope': 'project', 'does_not_authorize_host_operations': True})
    return result


def choice_value(option):
    return encode(option.get('value', option['label']))


def choice_identity(option):
    if not option.get('option_key'):
        if not option.get('conditions') and 'behavior' not in option:return choice_value(option)
        return encode({'value':option.get('value',option['label']),'conditions':option.get('conditions',[]),
                       'behavior':option.get('behavior')})
    return encode({'option_key':option['option_key'],**({'value':option['value']} if 'value' in option else {}),
        **({'behavior':option['behavior']} if 'behavior' in option else {}),'conditions':option.get('conditions',[])})


def rule_meaning(entry):
    chosen=entry['choice']
    return (entry['category'],choice_identity(chosen),
        '' if 'value' in chosen or chosen.get('option_key') else chosen['tradeoff'])


def conflicts(entries):
    groups = {}
    for entry in entries:
        if entry['state'] == 'active' and entry['tier'] == 'rule':
            groups.setdefault((entry['decision_key'],encode(scope(entry))), []).append(entry)
    return [{'field': group[0]['field'], 'memory_ids': [e['memory_id'] for e in group]}
            for group in groups.values() if len({rule_meaning(e) for e in group}) > 1]


def recall(store, db, query='', include_archived=False, limit=30, include_review=False):
    if not isinstance(query, str) or len(query) > 2000:
        raise ValueError('Memory query must be at most 2000 characters')
    if type(include_archived) is not bool:
        raise ValueError('include_archived must be boolean')
    entries = records(store, db)
    visible = [e for e in entries if include_archived or e['state'] == 'active' or
               (include_review and e['state']=='needs_review')]
    query_terms=terms(query)
    documents={e['memory_id']:terms(e['field']+' '+e['question']+' '+e['scope_key']+' '+
        ' '.join(e['conditions'])+' '+' '.join(o['label']+' '+o.get('tradeoff','') for o in e['options'])) for e in visible}
    frequencies={term:sum(term in document for document in documents.values()) for term in query_terms}
    def exact(entry):
        value=query.strip().casefold()
        return bool(value) and value in (entry['memory_id'].casefold(),entry['decision_id'].casefold(),entry['decision_key'].casefold())
    def score(entry):
        if exact(entry):return 1000
        document=documents[entry['memory_id']]
        value=sum((1+math.log(1+(len(documents)+1)/(frequencies[t]+1)))*min(len(t),6)
                  for t in query_terms if t in document)
        if len(query.strip())>=2 and query.casefold() in (entry['field']+' '+entry['question']+' '+entry['choice']['label']).casefold():value+=20
        return value
    if query.strip():
        visible = [e for e in visible if exact(e) or score(e)>0]
    visible.sort(key=lambda e: (score(e), e['tier'] == 'rule', e['confirmed_at'], e['memory_id']), reverse=True)
    return {'schema_version': 'memory.v1', 'entries': visible[:limit], 'total_matches': len(visible),
        'truncated': len(visible) > limit, 'conflicts': conflicts(entries),
        'reference_retention_days': 30, 'matching': 'weighted_words_cjk_bigrams_and_stable_ids',
        'semantic_relations':'Agent judges same/related/conflict/different_scope in the existing extraction; retrieval does not grant reuse',
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


def signature(store, db, exclude_task=None):
    return [{**{k: e[k] for k in ('memory_id','decision_key', 'state', 'tier', 'expires_at', 'field', 'category','risk_flags','scope_key','conditions')},
             'choice':option_semantics(e['choice'])}
            for e in records(store, db) if e['task_id']!=exclude_task]


def review_history(store, db, candidates):
    entries={e['memory_id']:e for e in records(store,db)}
    result=[]
    for candidate in candidates:
        for claim in candidate.get('history_matches',[]):
            entry=entries.get(claim['memory_id'])
            valid=bool(entry and entry['revision']==claim['revision'] and entry['state']=='active')
            same_scope=bool(entry and scope(candidate)==scope(entry))
            same_key=bool(entry and decision_key(candidate)==entry['decision_key'])
            result.append({'candidate_id':candidate['candidate_id'],**claim,'provenance':'agent_declared_semantic_relation',
                'source_current':valid,'stable_identity_matches':same_key,'scope_matches':same_scope,
                'can_authorize_reuse':False,'semantic_equivalence_independently_verified':False})
    return result[:100]


def match_candidate(store, db, candidate, task_id):
    """Only explicit live rules with matching decision/category/option identities apply.

    The Agent preserves stable decision keys; lexical retrieval never auto-confirms scope.
    Reuse never grants permission for host operations.
    """
    rules = [e for e in records(store, db) if e['state'] == 'active' and e['tier'] == 'rule'
             and e['task_id'] != task_id and e['decision_key']==decision_key(candidate) and scope(e)==scope(candidate)]
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
    claims=[c for c in candidate.get('history_matches',[]) if c['memory_id'] in ids]
    if (scope(candidate)!=scope(rule) or candidate.get('material_change') or
            any(c['revision']!=next(e['revision'] for e in rules if e['memory_id']==c['memory_id'])
                or c['relation']!='same' for c in claims)):
        return {'status':'conflict','memory_ids':ids,'reason':'PROJECT_RULE_SCOPE_OR_MEANING_CHANGED'}
    options = [o for o in candidate['options'] if choice_identity(o) == choice_identity(rule['choice'])]
    # Without structured values or stable option keys, labels AND tradeoffs must agree: a reused label
    # such as "Automatic" can otherwise hide an entirely different behavior.
    compatible = (len(options) == 1 and candidate['category'] == rule['category'] and
        ((options[0].get('option_key') and options[0].get('option_key')==rule['choice'].get('option_key')) or
         ('value' in options[0] and 'value' in rule['choice']) or
         options[0]['tradeoff'] == rule['choice']['tradeoff']))
    if not compatible:
        return {'status': 'conflict', 'memory_ids': ids, 'reason': 'PROJECT_RULE_SCOPE_OR_OPTIONS_CHANGED'}
    return {'status': 'applicable', 'memory_ids': ids, 'choice_id': options[0]['id'],
        'source_confirmation_id': rule['confirmation_id'], 'reason': 'PROJECT_MEMORY_RULE'}
