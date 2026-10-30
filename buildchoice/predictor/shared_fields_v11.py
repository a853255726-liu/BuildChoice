"""Retain whole evidence when a sentence anchors multiple candidate fields.

Shared assertions can create a discourse group wider than the next named field.
No semantic decision labels are assigned here; ambiguous grouping retains input.
"""
from buildchoice.predictor.fingerprints import fingerprint
from buildchoice.predictor.sentence_fields_v10 import public_pairs as v10_pairs,sentences,mentions,route_evidence as old_route


def route_evidence(body,fields,target):
    spans,_=sentences(body)
    for start,end in spans:
        mentioned=mentions(body[start:end],fields)
        if len(mentioned)>1:
            return body,False,[{'start':0,'end':len(body),'text':body}],'shared_statement_preserve_full'
    return old_route(body,fields,target)


def public_pairs(given):
    pairs,unread=v10_pairs(given);fields=[q['field'] for q in pairs if q['kind']=='resolved'];body=next(e['content'] for e in given['evidence'] if e['source_id']=='e1');out=[]
    for q in pairs:
        q=dict(q)
        if q['kind']=='resolved':
            q['premise'],q['routed'],q['evidence_spans'],q['routing_reason']=route_evidence(body,fields,q['field'])
            q['pair_id']=fingerprint([q['kind'],q['premise'],q['hypothesis']])
        out.append(q)
    return out,unread
