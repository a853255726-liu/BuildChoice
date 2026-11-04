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
        for attr in ('needs_user_choice', 'current_dependency', 'relevance'):
            values = [prior.get(attr, 'yes'), original.get(attr, 'yes')]
            prior[attr] = 'yes' if 'yes' in values else 'uncertain' if 'uncertain' in values else 'no'
        prior['engineering_detail'] = prior.get('engineering_detail', False) and original.get('engineering_detail', False)
        seen = {json.dumps(r, sort_keys=True) for r in prior['evidence_refs']}
        for reference in original['evidence_refs']:
            if json.dumps(reference, sort_keys=True) not in seen:
                prior['evidence_refs'].append(deepcopy(reference))
    return [result[key] for key in order]


def route(candidate, evidence, confirmation=None, next_step=''):
    """Keep the model's recommendation separate from objective evidence validation."""
    action=candidate.get('suggested_action')
    if action is None:
        # These are explicit caller declarations, not risk/keyword inference.
        action=('PROCEED' if candidate.get('relevance')=='no' or candidate.get('engineering_detail') or
                candidate['needs_user_choice']=='no' else 'DEFER' if candidate['current_dependency']=='no' else 'ASK_NOW')
    validation='needs_evidence' if evidence.get('invalid') or evidence.get('unread') else 'valid'
    status='INSPECT' if validation!='valid' else 'PROCEED' if confirmation else action
    reasons=(['REFERENCE_RECHECK_REQUIRED'] if validation!='valid' else
             ['EXISTING_RECORDED_CHOICE'] if confirmation else ['LLM_RECOMMENDATION'])
    return {'status':status,'reason_codes':reasons,'effective_dependency':candidate['current_dependency'],
            'suggested_action':action,'validation_status':validation,'semantic_judgment_by':'llm'}


def sort_key(candidate):
    return candidate.get('priority',0)
