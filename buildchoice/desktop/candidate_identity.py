"""Keep risk presentation separate from option behavior and applicability."""
from copy import deepcopy

RISK_PRESENTATION = {'risk_level','risk_warning','risk_basis','risk_reason','risk_condition','risk_evidence_refs'}


def option_semantics(option):
    return {k:v for k,v in option.items() if k not in RISK_PRESENTATION}


def options_equal(left, right):
    return [option_semantics(o) for o in left] == [option_semantics(o) for o in right]


def scope(candidate):
    return (candidate.get('scope_key','project'),candidate.get('conditions',[]))


def important_engineering(candidate):
    return [r for r in candidate.get('engineering_risks',[]) if r['product_choice']=='yes'
            and r['severity'] in ('medium','high') and r.get('relevance','yes')!='no']


def material_change(old, new):
    if (not options_equal(old['options'],new['options']) or old['category']!=new['category']
            or scope(old)!=scope(new) or new.get('material_change',False)
            or not set(new['risk_flags']).issubset(old['risk_flags'])):
        return True
    def impacts(candidate):
        return {(r['direction'],r['severity'],r['condition'],r['recoverability'])
                for r in important_engineering(candidate)}
    return not impacts(new).issubset(impacts(old))


def merge_risk_presentation(prior, incoming):
    """Within one extraction, retain supported high warnings despite harmless copy differences."""
    rank={'low':0,'medium':1,'high':2}
    for old,new in zip(prior,incoming):
        if rank.get(new.get('risk_level'),-1)>rank.get(old.get('risk_level'),-1):
            for name in RISK_PRESENTATION:
                old.pop(name,None)
                if name in new:old[name]=deepcopy(new[name])
