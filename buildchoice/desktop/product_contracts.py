"""One strict wire contract shared by MCP discovery and execution."""
from copy import deepcopy
from jsonschema import Draft202012Validator, ValidationError


def obj(properties, required=None):
    return {'type': 'object', 'properties': properties,
            'required': list(properties) if required is None else required, 'additionalProperties': False}


def arr(item, minimum=0, maximum=100):
    return {'type': 'array', 'items': item, 'minItems': minimum, 'maxItems': maximum}


def enum(*values):
    return {'enum': list(values)}


S = {'type': 'string', 'minLength': 1, 'maxLength': 4000}
ID = {'type': 'string', 'minLength': 1, 'maxLength': 160}
N = {'type': 'integer', 'minimum': 1}
REF = obj({'id': ID, 'revision': N})
DECISION = obj({'decision_id': ID, 'revision': N})
USER = {'user_message': {'type': 'string', 'minLength': 1, 'maxLength': 50000},
        'quote': {'type': 'string', 'minLength': 1, 'maxLength': 2000}, 'reason': S}
SOURCE = {'oneOf': [
    obj({'kind': enum('user'), **USER}),
    obj({'kind': enum('decision'), **DECISION['properties']}),
    obj({'kind': enum('project'), 'source_id': ID, 'quote': S}),
    obj({'kind': enum('recorded'), 'scenario': REF, 'behavior_id': ID}),
    obj({'kind': enum('ai', 'unresolved'), 'note': S})]}
BEHAVIOR = obj({'behavior_id': ID, 'text': S, 'source': SOURCE, 'technical_refs': arr(S, maximum=20)},
               ['behavior_id', 'text', 'source'])
SCENARIO = obj({'scenario_id': ID, 'expected_revision': {'type': 'integer', 'minimum': 0},
                'title': S, 'trigger': S, 'action': S, 'scope': S, 'conditions': arr(S),
                'behaviors': arr(BEHAVIOR, 1), 'related_decisions': arr(DECISION)},
               ['expected_revision', 'title', 'trigger', 'action', 'scope', 'behaviors'])


def action(name, properties=None, required=None, task=True, mutate=True):
    base = {'action': enum(name), 'session_handle': ID}
    if task: base['task_id'] = ID
    if mutate: base['idempotency_key'] = ID
    extra = properties or {}
    return obj({**base, **extra}, list(base) + (list(extra) if required is None else required))


EXPERIENCE = {'oneOf': [
    action('enable', {'task_text': S, 'task_id': ID,'purpose':enum('plan','feedback'),
                      'review_policy':enum('standard','independent')}, ['task_text'], task=False),
    action('close'),
    action('save', {'scenarios': arr(SCENARIO, 1, 50)}),
    action('present', {'scenarios': arr(REF, 1, 50)}, []),
    action('acknowledge', {'presentation_id': ID,
        'scenarios': arr(obj({**REF['properties'], 'status': enum('accepted', 'pending', 'deferred', 'discuss')}), 1, 50), **USER}),
    action('freeze', {'scenarios': arr(REF, 1, 50)}, []),
    action('status', {'task_id': ID}, [], task=False, mutate=False),
    action('document', mutate=False)]}

SNAPSHOT = {'oneOf': [
    action('inspect', {'scopes': arr(ID, 1, 50), 'excluded_paths': arr(ID)}, ['scopes']),
    action('capture', {'expectation_id': ID, 'scopes': arr(ID, 1, 50), 'excluded_paths': arr(ID)},
           ['expectation_id', 'scopes']),
    action('extend', {'baseline_id': ID, 'scopes': arr(ID, 1, 50),
        'timing': enum('before_first_edit', 'already_modified') }),
    action('compare', {'baseline_id': ID}),
    action('prune', {'snapshot_ids': arr(ID, 1, 100)}),
    action('status', {'snapshot_id': ID}, mutate=False)]}

EVIDENCE = obj({'kind': enum('llm', 'file', 'test', 'runtime', 'missing'), 'note': S,
                'path': ID, 'quote': S, 'start_line': N, 'end_line': N,
                'outcome': enum('passed', 'failed', 'unknown'), 'command': S,
                'tested_behaviors': arr(ID), 'limits': S, 'observation_id': ID}, ['kind', 'note'])
SHORT = {'type':'string','minLength':1,'maxLength':160}
GAP = obj({'situation':{'type':'string','minLength':1,'maxLength':80},
           'effect':{'type':'string','minLength':1,'maxLength':80},
           'next_step':{'type':'string','minLength':1,'maxLength':100},'owner':enum('agent','user')})
DISPLAY = obj({'title':{'type':'string','minLength':1,'maxLength':48},
               'check':enum('observed','tested','read','not_checked'),
               'impact':SHORT,'gap':GAP}, ['title','check'])
REPORT = obj({'version':enum('behavior-feedback.v1'),'overview':arr(ID,1,5)})
REFERENCE = obj({'text':S,'source':SOURCE})
FINDING = obj({'finding_id': ID, 'scenario': REF, 'behavior_ids': arr(ID),
               'judgment': enum('possibly_matches', 'possibly_deviates', 'extra', 'unknown'),
               'summary': S, 'importance': enum('high', 'normal', 'low'),
               'change_origin': enum('observed_change', 'preexisting', 'uncertain'),
               'evidence': arr(EVIDENCE), 'limits': S,'display':DISPLAY,'reference':REFERENCE},
              ['finding_id', 'judgment', 'summary', 'importance', 'evidence', 'limits'])
FEEDBACK = obj({'finding_id': ID, 'action': enum('fix', 'change_requirement', 'accept_extra', 'investigate', 'defer'),
                'note': S, 'expected_feedback_revision': {'type': 'integer', 'minimum': 0},
                'decision': DECISION, 'scenario': REF},
               ['finding_id', 'action', 'note', 'expected_feedback_revision'])
FACT_SOURCE = {'oneOf': [*SOURCE['oneOf'][:3], SOURCE['oneOf'][-1],
    obj({'kind':enum('task'),'task_id':ID,'task_text':S,'quote':S})]}
REVIEW_FACT = obj({'fact_id':ID,'scope':enum('goal','data','runtime','product','delivery'),
                  'role':enum('requirement','constraint','context','explanation'),
                  'source':FACT_SOURCE,'interpretation':S}, ['fact_id','scope','role','source'])
ARTIFACT = obj({'path':ID,'start_line':N,'end_line':N}, ['path'])
ISSUE = obj({'issue_id':ID,'title':SHORT,'observation':S,'effect':S,
             'basis_fact_ids':arr(ID), 'artifacts':arr(obj({'path':ID,'start_line':N,'end_line':N,'quote':S}))})
QUESTION = obj({'question_id':ID,'question':S,'issue_ids':arr(ID)})
REVIEWER = obj({'agent_id':ID,'fork_turns':enum('none'),'model_policy':enum('inherit'),
                'permissions':enum('inherit_host')})
ADOPTION = obj({'id':ID,'revision':N,'dispositions':arr(obj({'issue_id':ID,
    'action':enum('include','exclude'),'finding_id':ID,'reason':S}, ['issue_id','action']),maximum=40)})
REVIEW = {'oneOf': [
    action('create', {'comparison_id': ID, 'findings': arr(FINDING), 'previous_review_id': ID,
                     'report':REPORT,'independent_review':ADOPTION}, ['comparison_id', 'findings']),
    action('supplement', {'current_snapshot_id':ID,'findings':arr(FINDING,1),
                         'previous_review_id':ID,'report':REPORT,'independent_review':ADOPTION}, ['current_snapshot_id','findings','report']),
    action('prepare_independent', {'current_snapshot_id':ID,'facts':arr(REVIEW_FACT,1,30),
        'artifacts':arr(ARTIFACT,1,20),
        'review_topics':{**arr(enum('interface','documentation','debugging'),maximum=3),'uniqueItems':True},
        'max_chars':{'type':'integer','minimum':2000,'maximum':80000}},
        ['current_snapshot_id','facts','artifacts']),
    action('submit_independent', {'packet_id':ID,'reviewer':REVIEWER,
        'issues':arr(ISSUE,maximum=40),'questions':arr(QUESTION,maximum=20)}),
    action('provide_background', {'independent_review_id':ID,'expected_revision':N,
        'answers':arr(obj({'question_id':ID,'facts':arr(REVIEW_FACT,1,10)}),1,20)}),
    action('reconsider_independent', {'independent_review_id':ID,'expected_revision':N,
        'background_id':ID,'issues':arr(ISSUE,maximum=40),'questions':arr(QUESTION,maximum=20),
        'changes':arr(obj({'issue_id':ID,'action':enum('keep','revise','withdraw','add'),'reason':S}),maximum=80)}),
    action('independent_status', {'independent_review_id':ID}, mutate=False),
    action('feedback', {'review_id': ID, 'feedback': arr(FEEDBACK, 1), **USER}),
    action('status', {'review_id': ID}, mutate=False)]}

BATCH = {'oneOf': [
    action('present', {'decisions': arr(DECISION, 1, 3)}),
    action('suspend', {'batch_id': ID}),
    action('submit', {'batch_id': ID, 'answers': arr(obj({**DECISION['properties'],
        'status': enum('selected', 'deferred', 'discuss'), 'choice_id': ID,
        'selection_basis': enum('explicit', 'current_recommendation')},
        ['decision_id', 'revision', 'status']), 1, 3), **USER}),
    action('status', {'batch_id': ID}, mutate=False)]}

CONTRACTS = {'experience': EXPERIENCE, 'snapshot': SNAPSHOT, 'review': REVIEW, 'batch': BATCH}


def input_schema(kind):
    result=deepcopy(CONTRACTS[kind])
    if kind=='review':
        for branch in result['oneOf']:
            if branch['properties']['action']['enum'][0] in ('create','supplement'):
                if 'report' not in branch['required']:branch['required'].append('report')
                required=branch['properties']['findings']['items']['required']
                if 'display' not in required:required.append('display')
    return result


def validate(kind, value):
    try:
        Draft202012Validator(CONTRACTS[kind]).validate(value)
    except ValidationError as error:
        details = [e.message for e in error.context if not any(p == 'action' for p in e.path)]
        raise ValueError('INVALID_PRODUCT_CONTRACT: ' + '; '.join(details or [error.message])[:900]) from None
    return deepcopy(value)
