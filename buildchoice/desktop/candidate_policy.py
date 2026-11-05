"""Validate and combine caller declarations without inferring business importance."""
from copy import deepcopy
import json
import re
import unicodedata
from .candidate_identity import options_equal,merge_risk_presentation,scope

def field_key(field):
    return re.sub(r'[\W_]+', '', unicodedata.normalize('NFKC', field).casefold())


def candidate_key(candidate):
    return 'key:'+candidate['decision_key'] if candidate.get('decision_key') else field_key(candidate['field'])


def deduplicate(candidates):
    result = {}; order = []
    for original in candidates:
        key = candidate_key(original)
        if not key: raise ValueError('Field needs a meaningful name')
        if key not in result:
            result[key] = deepcopy(original)
            result[key]['_candidate_ids'] = [original['candidate_id']]
            order.append(key)
            continue
        prior = result[key]
        if prior['category']!=original['category']:raise ValueError('Same decision key has conflicting categories')
        for attr in ('suggested_action','allow_defer'):
            if attr in prior and attr in original and prior[attr]!=original[attr]:
                raise ValueError('Same decision has conflicting '+attr+' declarations')
            if attr in original:prior[attr]=original[attr]
        if prior.get('memory_intent','uncertain')!=original.get('memory_intent','uncertain'):
            prior['memory_intent']='uncertain'
        if not options_equal(prior['options'],original['options']) or scope(prior)!=scope(original):
            raise ValueError('Same decision has conflicting option definitions; reconcile before screening')
        merge_risk_presentation(prior['options'],original['options'])
        prior['engineering_risks']=list({json.dumps(r,sort_keys=True):r
            for r in prior.get('engineering_risks',[])+original.get('engineering_risks',[])}.values())
        prior['material_change']=prior.get('material_change',False) or original.get('material_change',False)
        prior['history_matches']=list({json.dumps(r,sort_keys=True):r
            for r in prior.get('history_matches',[])+original.get('history_matches',[])}.values())
        prior['_candidate_ids'].append(original['candidate_id'])
        prior['risk_flags'] = sorted(set(prior['risk_flags'] + original['risk_flags']))
        seen = {json.dumps(r, sort_keys=True) for r in prior['evidence_refs']}
        for reference in original['evidence_refs']:
            if json.dumps(reference, sort_keys=True) not in seen:
                prior['evidence_refs'].append(deepcopy(reference))
    return [result[key] for key in order]


def route(candidate, evidence, confirmation=None):
    """Keep the model's recommendation separate from objective evidence validation."""
    action=candidate.get('suggested_action')
    if action not in ('ASK_NOW','INSPECT','DEFER','PROCEED'):
        raise ValueError('Explicit suggested_action required')
    validation='needs_evidence' if evidence.get('invalid') or evidence.get('unread') else 'valid'
    status='INSPECT' if validation!='valid' else 'PROCEED' if confirmation else action
    reasons=(['REFERENCE_RECHECK_REQUIRED'] if validation!='valid' else
             ['EXISTING_RECORDED_CHOICE'] if confirmation else ['LLM_RECOMMENDATION'])
    return {'status':status,'reason_codes':reasons,
            'suggested_action':action,'validation_status':validation,'semantic_judgment_by':'llm'}


def sort_key(candidate):
    return candidate.get('priority',0)
