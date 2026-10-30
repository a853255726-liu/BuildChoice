"""Public-only evidence routing with an explicit evidence-sufficiency hypothesis.

Routing is deliberately limited to self-contained newline paragraphs that each
mention exactly one candidate. Coordinated prose and unanchored follow-ups keep
the entire evidence block. No label or semantic keyword decides the answer.
"""
import re
from buildchoice.predictor.fingerprints import fingerprint
from buildchoice.predictor.independent_fields_v7 import public_pairs as original_pairs


def route_evidence(body, fields, target):
    lines=[s.strip() for s in body.splitlines() if s.strip()]
    mentions=[{f for f in fields if re.search(r'(?<!\w)'+re.escape(f)+r'(?!\w)',s,re.I)
               or (re.search(r'[\u3400-\u9fff]',f) and f in s)} for s in lines]
    if len(lines)<2 or any(len(m)!=1 for m in mentions) or set().union(*mentions)!=set(fields):
        return body,False
    return '\n'.join(s for s,m in zip(lines,mentions) if target in m),True


def public_pairs(given, arm='routed_sufficiency'):
    pairs,unread=original_pairs(given)
    if arm=='full_context':return pairs,unread
    if arm!='routed_sufficiency':raise ValueError('Unknown v8 arm')
    fields=[p['field'] for p in pairs if p['kind']=='resolved']
    zh=bool(re.search(r'[\u3400-\u9fff]',given['task']))
    result=[]
    for q in pairs:
        q=dict(q)
        if q['kind']=='resolved':
            q['premise'],q['routed']=route_evidence(q['premise'],fields,q['field'])
            q['hypothesis']=(f'现有证据足以唯一确定{q["field"]}当前有效且已获授权的取值。' if zh else
                f'The available evidence establishes a single currently valid, authorized value for {q["field"]}.')
            q['pair_id']=fingerprint([q['kind'],q['premise'],q['hypothesis']])
        result.append(q)
    return result,unread
