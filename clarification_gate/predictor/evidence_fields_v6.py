"""Public field inventory adapter; no private status or action is available here."""
from clarification_gate.predictor.decomposed_fields import public_pairs as legacy_pairs, hypothesis, choose_fields
from clarification_gate.predictor.fingerprints import fingerprint


def public_pairs(given):
    if set(given) != {'task','conversation','evidence','available_resources','inspection_log'}:
        raise ValueError('Unsupported snapshot keys')
    evidence={r['source_id']:r['content'] for r in given['evidence']}
    if 'e3' not in evidence:
        return legacy_pairs(given)
    inventory=evidence['e3']
    prefix='Field inventory: '
    if not inventory.startswith(prefix):raise ValueError('Unsupported public inventory')
    fields=inventory[len(prefix):].split(' || ')
    if len(fields)!=2 or len(set(fields))!=2 or any(not f.strip() for f in fields):
        raise ValueError('Two distinct public fields required')
    fields=sorted(fields,key=lambda s:fingerprint('candidate-order:'+s))
    scope=given['task']
    if scope in ('Continue this submission for the current exercise.','继续完成当前演练的这次提交。'):
        scope=next(r['content'] for r in reversed(given['conversation']) if r['role']=='user')
    zh=any('\u3400'<=c<='\u9fff' for c in scope)
    views={'required':scope,'resolved':evidence['e1'],'indexed':evidence['e2']}
    pairs=[]
    for kind,premise in views.items():
        for field in fields:
            h=hypothesis(kind,field,zh)
            pairs.append({'pair_id':fingerprint([kind,premise,h]),'kind':kind,'field':field,'premise':premise,'hypothesis':h})
    unread=any(r['resource_id']=='r1' and r['read_state']=='unread' for r in given['available_resources'])
    return pairs,unread
