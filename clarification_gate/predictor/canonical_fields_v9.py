"""Use public field names to mark the target consistently, preserving values.

This reduces unfamiliar-name variation without parsing approval/negation or
using private targets. Quoted values are left unchanged. Distinct other fields
retain distinct aliases; full evidence is retained unless v8 routing applies.
"""
import re
from clarification_gate.predictor.fingerprints import fingerprint
from clarification_gate.predictor.evidence_fields_v8 import public_pairs as v8_pairs

QUOTES=r'("[^"\n]*"|“[^”\n]*”)'


def canonicalize(text,fields,target,zh):
    pattern='|'.join(re.escape(f) if re.search(r'[\u3400-\u9fff]',f) else r'(?<![A-Za-z0-9_])'+re.escape(f)+r'(?![A-Za-z0-9_])'
                     for f in sorted(fields,key=len,reverse=True))
    regex=re.compile(pattern,re.I);lookup={f.casefold():f for f in fields}
    parts=re.split(QUOTES,text);order=[]
    for part in parts[::2]:
        for m in regex.finditer(part):
            name=lookup[m.group(0).casefold()]
            if name!=target and name not in order:order.append(name)
    mapping={target:'目标字段' if zh else 'the target setting'}
    mapping.update({f:(f'其他字段{i+1}' if zh else f'other setting {i+1}') for i,f in enumerate(order)})
    for i in range(0,len(parts),2):
        parts[i]=regex.sub(lambda m:mapping[lookup[m.group(0).casefold()]],parts[i])
    return ''.join(parts)


def public_pairs(given,arm='canonical_focus'):
    if arm=='full_context':return v8_pairs(given,'full_context')
    if arm=='routed_sufficiency':return v8_pairs(given,arm)
    if arm!='canonical_focus':raise ValueError('Unknown v9 arm')
    pairs,unread=v8_pairs(given,'routed_sufficiency')
    fields=[q['field'] for q in pairs if q['kind']=='required']
    if len({f.casefold() for f in fields})!=len(fields):
        raise ValueError('Candidate names must be distinct ignoring case')
    zh=bool(re.search(r'[\u3400-\u9fff]',given['task']));out=[]
    for original in pairs:
        q=dict(original)
        for key in ('premise','hypothesis'):q[key]=canonicalize(q[key],fields,q['field'],zh)
        q['pair_id']=fingerprint([q['kind'],q['premise'],q['hypothesis']]);out.append(q)
    return out,unread
