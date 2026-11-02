"""Deterministic routing based on declared candidates and verified evidence."""
from copy import deepcopy
import json
import re
import unicodedata
from .candidate_identity import options_equal,merge_risk_presentation,scope,important_engineering

RISK_ORDER = {'irreversible_delete': 0, 'payment': 0, 'external_transfer': 0, 'publish': 0,
              'privacy': 1, 'personal_data': 1, 'security': 1, 'access_control': 1, 'cost': 2}
IMMEDIATE_ACTIONS = {
    'external_transfer': r'发送.{0,16}(外部|第三方)|上传.{0,16}(外部|第三方)|send.{0,30}(external|third.party)',
    'payment': r'调用.{0,12}付费|购买|支付|charge|purchase|paid.api',
    'irreversible_delete': r'永久删除|不可逆删除|purge|permanently.delete',
    'publish': r'正式发布|部署.{0,10}公开|publish.{0,20}(public|internet)|deploy.{0,15}public'}


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
    risks = set(candidate['risk_flags'])
    sensitive = bool(risks)
    dependency = candidate['current_dependency']
    reasons = []
    if any(re.search(pattern, next_step, re.I) for risk, pattern in IMMEDIATE_ACTIONS.items() if risk in risks):
        dependency = 'yes'
        reasons.append('IMMEDIATE_EFFECT_OVERRIDES_DEFER')
    if evidence.get('conflict') or evidence.get('invalid') or evidence.get('insufficient'):
        return {'status': 'INSPECT',
                'reason_codes': reasons + ['EVIDENCE_CONFLICT_OR_UNVERIFIED'], 'effective_dependency': dependency}
    if evidence.get('unread'):
        return {'status': 'INSPECT', 'reason_codes': reasons + ['RELEVANT_ACCESSIBLE_RESOURCE_UNREAD'], 'effective_dependency': dependency}
    if confirmation and confirmation.get('applicable') is True:
        return {'status': 'PROCEED', 'reason_codes': reasons + ['OBSERVED_USER_CHOICE'], 'effective_dependency': dependency}
    if not sensitive and candidate.get('relevance', 'yes') == 'no':
        return {'status': 'PROCEED', 'reason_codes': reasons + ['OUTSIDE_CURRENT_TASK'], 'effective_dependency': dependency}
    if any(r['product_choice']=='uncertain' and r['severity'] in ('medium','high') and r.get('relevance','yes')!='no'
           for r in candidate.get('engineering_risks',[])):
        return {'status':'INSPECT','reason_codes':reasons+['ENGINEERING_IMPACT_NEEDS_INSPECTION'],'effective_dependency':dependency}
    engineering=important_engineering(candidate)
    if not sensitive and not engineering and (candidate.get('engineering_detail') or candidate['needs_user_choice'] == 'no'):
        return {'status': 'PROCEED', 'reason_codes': reasons + ['REVERSIBLE_ENGINEERING_DETAIL'], 'effective_dependency': dependency}
    if not sensitive and evidence.get('applicable_constraint') is True:
        return {'status': 'PROCEED', 'reason_codes': reasons + ['LITERAL_PROJECT_CONSTRAINT'], 'effective_dependency': dependency}
    status = 'DEFER' if dependency == 'no' else 'ASK_NOW'
    reasons += ['USER_CHOICE', 'UNRESOLVED', 'LATER_DEPENDENCY' if status == 'DEFER' else 'CURRENT_OR_UNCERTAIN_DEPENDENCY']
    if sensitive: reasons.append('EXPLICIT_USER_CHOICE_REQUIRED')
    if engineering:reasons.append('PRODUCT_IMPACT_ENGINEERING_TRADEOFF')
    return {'status': status, 'reason_codes': reasons, 'effective_dependency': dependency}


def sort_key(candidate):
    return (min((RISK_ORDER[r] for r in candidate['risk_flags']), default=3),
            {'yes': 0, 'uncertain': 1, 'no': 2}[candidate['current_dependency']], field_key(candidate['field']))


# These are observations of literal plan/code text, never proof of executed effects.
SIGNALS = (
    ('destructive_data',r'\b(?:DROP\s+TABLE|TRUNCATE\s+TABLE|ALTER\s+TABLE\s+\w+\s+DROP\s+COLUMN)\b|永久删除现有数据','data_integrity','irreversible_delete'),
    ('overwrite_data',r'open\(\s*[\'\"][^\'\"]+\.(?:json|csv|db|sqlite)[\'\"]\s*,\s*[\'\"]w|覆盖现有数据|overwrite existing (?:data|records)','data_integrity','irreversible_delete'),
    ('browser_storage',r'\blocalStorage\.(?:setItem|clear|removeItem)\s*\(','backup_recovery',None),
    ('external_call',r'\brequests\.post\s*\(|\bfetch\(\s*[\'\"]https?://','availability','external_transfer'),
    ('deployment',r'\b(?:terraform\s+destroy|kubectl\s+apply)\b|正式部署到公网','deployment_rollback','publish'),
    ('compatibility',r'\bdrop_column\s*\(|不可逆迁移|不兼容旧版本','compatibility_migration',None),
)


def risk_diagnostics(next_step, excerpts, candidates):
    result=[];seen=set()
    for context in [{'text':next_step,'origin':'agent_declared_next_step'},*excerpts]:
        for signal,pattern,direction,flag in SIGNALS:
            found=re.search(pattern,context['text'],re.I)
            if not found or re.search(r'不要|禁止|避免|\bprevent\b|\bavoid\b',context['text'][max(0,found.start()-24):found.start()],re.I):continue
            key=(signal,context.get('source_id'),found[0])
            if key in seen:continue
            seen.add(key)
            covered=any(c.get('relevance','yes')!='no' and
                ((flag and flag in c['risk_flags']) or any(r['direction']==direction for r in c.get('engineering_risks',[]))) for c in candidates)
            result.append({'code':'RISK_SIGNAL_REVIEWED' if covered else 'POSSIBLE_MISSING_PRODUCT_RISK',
                'signal':signal,'direction':direction,'matched_text':found[0][:200],
                'origin':context['origin'],'source_id':context.get('source_id'),
                'requires_inspection':not covered,'coverage_provenance':'agent_declared' if covered else 'not_reported',
                'does_not_prove_risk_or_execution':True,
                'next_action':'Check conditions, actual consequences and recoverability; add a relevant candidate or an explicit ordinary-engineering assessment, then re-screen.'})
    return result[:60]
