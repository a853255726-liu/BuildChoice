"""Public-input adapter and fieldwise NLI for controlled two-setting snapshots.

This adapter supports the authored v4/v5 grammar, not arbitrary user tasks.
It never receives private required/resolved/indexed field labels at inference.
"""
import re
from buildchoice.predictor.fingerprints import fingerprint

KINDS=('required','resolved','indexed')
GENERIC={'Continue this submission for the current exercise.','继续完成当前演练的这次提交。'}


def public_views(given):
    required_keys={'task','conversation','evidence','available_resources','inspection_log'}
    if set(given)!=required_keys:raise ValueError('Unsupported snapshot keys')
    evidence={e['source_id']:e['content'] for e in given['evidence']}
    scope=given['task']
    if scope in GENERIC:
        scope=next(m['content'] for m in reversed(given['conversation']) if m['role']=='user')
    state=evidence.get('e1')
    if state is None:
        state=next((m['content'] for m in given['conversation'] if m['role']=='user'
                    and ('the early draft used' in m['content'] or '原稿为' in m['content'])),None)
    index=evidence.get('e2')
    if not state or not index:raise ValueError('Unsupported controlled evidence layout')
    fields=[]
    for line in state.splitlines():
        match=re.match(r'^([^:\n：]+)(?:: |：)(?:the early draft used|two equally authoritative|the candidates are|原稿为|两份同级|候选为)',line)
        if match:fields.append(match.group(1).strip())
    if len(fields)!=2 or len(set(fields))!=2:raise ValueError('Expected exactly two public field names')
    # Order is label-independent; neither "field 0" nor first-mentioned field
    # is used as a private answer or a shortcut decision.
    fields=sorted(fields,key=lambda s:fingerprint('candidate-order:'+s))
    zh=bool(re.search(r'[\u3400-\u9fff]',scope))
    unread=any(r['resource_id']=='r1' and r['read_state']=='unread' for r in given['available_resources'])
    return {'required':scope,'resolved':state,'indexed':index,'fields':fields,'language':'zh' if zh else 'en','unread':unread}


def hypothesis(kind,field,zh):
    if zh:
        return {'required':f'本次交付必须确定{field}。',
                'resolved':f'负责人已经对{field}作出有效的最终决定。',
                'indexed':f'未读资料中包含{field}的最终决定。'}[kind]
    return {'required':f'The current delivery requires a decision on {field}.',
            'resolved':f'The owner has made a usable final decision on {field}.',
            'indexed':f'The unread resource contains the final decision on {field}.'}[kind]


def public_pairs(given):
    view=public_views(given);rows=[]
    for kind in KINDS:
        for field in view['fields']:
            premise=view[kind];hyp=hypothesis(kind,field,view['language']=='zh')
            rows.append({'pair_id':fingerprint([kind,premise,hyp]),'kind':kind,'field':field,
                         'premise':premise,'hypothesis':hyp})
    return rows,view['unread']


def compose(required,resolved,indexed,unread):
    if required==resolved:return 'PASS'
    if required==indexed and unread:return 'INSPECT'
    return 'ASK'


def choose_fields(pairs,scores,unread):
    selected={}
    for kind in KINDS:
        candidates=[r for r in pairs if r['kind']==kind]
        selected[kind]=max(candidates,key=lambda r:scores[r['pair_id']])['field']
    return {'action':compose(selected['required'],selected['resolved'],selected['indexed'],unread),
            'fields':selected,'decision_scores_calibrated':False,'task_executed':False}
