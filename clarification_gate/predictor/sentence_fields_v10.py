"""Public sentence routing; keep histories and fall back on ambiguous scope.

This is candidate evidence retrieval, not a learned coreference resolver. It
never turns approval/negation keywords into field labels. Sentence offsets are
returned for auditing; ambiguous unanchored/global follow-ups keep full text.
"""
import re
from clarification_gate.predictor.fingerprints import fingerprint
from clarification_gate.predictor.evidence_fields_v8 import public_pairs as v8_pairs,route_evidence as paragraph_route

ARMS=('sentence_route','sentence_augmented','sentence_relations')
GLOBAL=re.compile(r'\b(?:both|all|neither|none|these|those|above|former|latter|each|either|everything|every|any|no|other|earlier|previous|prior|it|its|they|them|that|this)\b|revok|withdr|cancel|void|suspend|expir|所有|全部|上述|以上|前者|后者|两项|两者|这些|那些|该项|该决定|这个决定|它们|该批准|一律|均|都|撤销|撤回|作废|失效|无效|取消|暂停',re.I)
BROAD=re.compile(r'\b(?:all|both|every)\b.{0,30}\b(?:decisions|choices|approvals|settings|authorizations)\b|所有|全部|上述|以上|一律',re.I)


def mentions(text,fields):
    return {f for f in fields if (f in text if re.search(r'[\u3400-\u9fff]',f) else
            bool(re.search(r'(?<![A-Za-z0-9_])'+re.escape(f)+r'(?![A-Za-z0-9_])',text,re.I)))}


def sentences(body):
    """Split outside double/curly quotes, never inside decimal numbers/paths."""
    spans=[];start=0;closing=[]
    for i,c in enumerate(body):
        if closing and c==closing[-1]:closing.pop();continue
        if c in ('"','“','‘'):
            closing.append({'"':'"','“':'”','‘':'’'}[c]);continue
        if closing:continue
        boundary=c in '。！？!?\n' or (c=='.' and (i+1==len(body) or body[i+1].isspace()))
        if boundary:
            if body[start:i+1].strip():spans.append((start,i+1))
            start=i+1
    if body[start:].strip():spans.append((start,len(body)))
    return spans,bool(closing)


def route_evidence(body,fields,target):
    full=[{'start':0,'end':len(body),'text':body}]
    # ASCII single-quoted sentences are not parsed as apostrophe-safe quotes.
    if re.search(r"(?:^|\s)'[^'\n]*[.!?][^'\n]*'",body):return body,False,full,'single_quote_ambiguity'
    spans,unclosed=sentences(body)
    if unclosed:return body,False,full,'unclosed_quote'
    for a,b in spans:
        if BROAD.search(body[a:b]) and mentions(body[a:b],fields)!=set(fields):
            return body,False,full,'global_scope_with_partial_anchor'
    paragraph,used=paragraph_route(body,fields,target)
    if used:
        chosen=[];offset=0
        for line in body.splitlines(keepends=True):
            if target in mentions(line,fields):chosen.append({'start':offset,'end':offset+len(line),'text':line})
            offset+=len(line)
        return paragraph,True,chosen,'self_contained_field_paragraphs'
    groups=[]
    for a,b in spans:
        text=body[a:b];names=mentions(text,fields)
        if BROAD.search(text) and names!=set(fields):return body,False,full,'global_scope_with_partial_anchor'
        if names:
            groups.append({'fields':names,'start':a,'end':b})
        else:
            if not groups or GLOBAL.search(text):return body,False,full,'unanchored_or_global_followup'
            groups[-1]['end']=b
    if not groups or set().union(*(g['fields'] for g in groups))!=set(fields):
        return body,False,full,'missing_candidate_anchor'
    chosen=[{'start':g['start'],'end':g['end'],'text':body[g['start']:g['end']]} for g in groups if target in g['fields']]
    if len(chosen)==len(groups):return body,False,full,'shared_full_context'
    return '\n'.join(s['text'].strip() for s in chosen),True,chosen,'sentence_groups'


def public_pairs(given,arm='sentence_route'):
    if arm=='routed_sufficiency':return v8_pairs(given,arm)
    if arm=='rerouted_v8':arm='sentence_route'
    if arm not in ARMS:raise ValueError('Unknown v10 arm')
    pairs,unread=v8_pairs(given,'routed_sufficiency')
    fields=[q['field'] for q in pairs if q['kind']=='resolved'];body=next(e['content'] for e in given['evidence'] if e['source_id']=='e1')
    if len({f.casefold() for f in fields})!=len(fields):raise ValueError('Candidate names must be distinct ignoring case')
    out=[]
    for original in pairs:
        q=dict(original)
        if q['kind']=='resolved':
            q['premise'],q['routed'],q['evidence_spans'],q['routing_reason']=route_evidence(body,fields,q['field'])
            q['pair_id']=fingerprint([q['kind'],q['premise'],q['hypothesis']])
        out.append(q)
    return out,unread
