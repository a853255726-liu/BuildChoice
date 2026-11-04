"""Keep risk presentation separate from option behavior and applicability."""
from copy import deepcopy

RISK_PRESENTATION = {'risk_level','risk_warning','risk_basis','risk_reason','risk_condition','risk_evidence_refs'}


def option_semantics(option):
    return {k:v for k,v in option.items() if k not in RISK_PRESENTATION}


def options_equal(left, right):
    return [option_semantics(o) for o in left] == [option_semantics(o) for o in right]


def scope(candidate):
    return (candidate.get('scope_key','project'),candidate.get('conditions',[]))


def candidate_content(candidate):
    return {k:v for k,v in candidate.items() if k not in ('candidate_id','_candidate_ids')}


def material_change(old, new):
    def identity(candidate):
        return [{k:o[k] for k in ('id','option_key','value','behavior','conditions') if k in o} for o in candidate['options']]
    return (identity(old)!=identity(new) or old['category']!=new['category'] or
            scope(old)!=scope(new) or new.get('material_change',False))


def merge_risk_presentation(prior, incoming):
    """Within one extraction, retain supported high warnings despite harmless copy differences."""
    rank={'low':0,'medium':1,'high':2}
    for old,new in zip(prior,incoming):
        if rank.get(new.get('risk_level'),-1)>rank.get(old.get('risk_level'),-1):
            for name in RISK_PRESENTATION:
                old.pop(name,None)
                if name in new:old[name]=deepcopy(new[name])
