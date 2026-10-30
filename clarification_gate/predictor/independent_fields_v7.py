"""Independent binary field states; accepts zero, one, or many positives."""
import re
from clarification_gate.predictor.fingerprints import fingerprint
from clarification_gate.predictor.decomposed_fields import hypothesis

KINDS=('required','resolved','indexed')


def public_pairs(given):
    if not isinstance(given,dict) or set(given)!={'task','conversation','evidence','available_resources','inspection_log'}:
        raise ValueError('Unsupported snapshot container')
    if not isinstance(given['task'],str) or not given['task'].strip():raise ValueError('Missing current task')
    for key in ('conversation','evidence','available_resources','inspection_log'):
        if not isinstance(given[key],list):raise ValueError('Expected list containers')
    if given['conversation'] or given['inspection_log']:
        raise ValueError('Conversation and inspection reconciliation are not implemented; supply a reviewed current snapshot')
    if any(not isinstance(r,dict) or not isinstance(r.get('source_id'),str) or not isinstance(r.get('content'),str) for r in given['evidence']):
        raise ValueError('Invalid evidence')
    evidence={r['source_id']:r['content'] for r in given['evidence']}
    if len(evidence)!=len(given['evidence']) or set(evidence)!={'e1','e2','e3'}:raise ValueError('Expected three distinct evidence sources')
    prefix='Field inventory: '
    if not evidence['e3'].startswith(prefix):raise ValueError('Missing public candidate inventory')
    fields=evidence['e3'][len(prefix):].split(' || ')
    if len(fields) not in (2,3) or len(set(fields))!=len(fields) or any(not x.strip() or x!=x.strip() for x in fields):
        raise ValueError('Exactly two or three distinct public candidates required')
    if len(given['available_resources'])>1:raise ValueError('Multiple resources unsupported')
    unread=False
    for r in given['available_resources']:
        if not isinstance(r,dict) or r.get('resource_id')!='r1' or r.get('read_state')!='unread' or not isinstance(r.get('locator'),str) or not r['locator']:
            raise ValueError('Unsupported resource identity or state')
        token=r'(?<![A-Za-z0-9_./\\-])'+re.escape(r['locator'])+r'(?![A-Za-z0-9_/\\-]|\.[A-Za-z0-9_])'
        if not re.search(token,evidence['e2']):raise ValueError('Resource locator does not match public index')
        unread=True
    fields=sorted(fields,key=lambda s:fingerprint('v7-candidate:'+s))
    zh=bool(re.search(r'[\u3400-\u9fff]',given['task']));pairs=[]
    for kind,premise in [('required',given['task']),('resolved',evidence['e1']),('indexed',evidence['e2'])]:
        for field in fields:
            h=hypothesis(kind,field,zh)
            pairs.append({'pair_id':fingerprint([kind,premise,h]),'kind':kind,'field':field,'premise':premise,'hypothesis':h})
    return pairs,unread


def compose(required,resolved,indexed,unread):
    unresolved=set(required)-set(resolved)
    if not unresolved:return 'PASS'
    if unread and unresolved&set(indexed):return 'INSPECT'
    return 'ASK'


def choose(pairs,probabilities,unread,thresholds):
    fields={kind:sorted(p['field'] for p in pairs if p['kind']==kind and probabilities[p['pair_id']]>=thresholds[kind]) for kind in KINDS}
    return {'action':compose(fields['required'],fields['resolved'],fields['indexed'],unread),
            'fields':fields,'task_executed':False,'scores_are_calibrated_probabilities':False}
