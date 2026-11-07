"""Check declared presentation content; never infer risk, authorization or semantics."""
import json
import re
import unicodedata

VERSION = 'decision-content.v1'
LIMITS = {'question': 90, 'impact': 160, 'recommendation_reason': 100,
          'label': 32, 'tradeoff': 140, 'risk_warning': 180,
          'risk_condition':140,'risk_reason':200}
RISK_FIELDS = {'risk_level', 'risk_warning', 'risk_basis', 'risk_reason',
               'risk_condition', 'risk_evidence_refs'}


def require_current(candidates):
    """New MCP extraction uses the current contract; old stored cards remain activatable."""
    missing=[{'field':'candidates.'+str(index)+'.content_version','rule':'current_content_contract_required'}
             for index,candidate in enumerate(candidates)
             if isinstance(candidate,dict) and candidate.get('content_version')!=VERSION]
    if missing:
        raise ValueError(json.dumps({'code':'CONTENT_REPAIR_REQUIRED','issues':missing,
            'next_action':'Use content_version='+VERSION+' and explicit risk_assessment for every option. '
                          'Keep product meaning unchanged and retry with a new idempotency key.',
            'semantic_verified_by_program':False},ensure_ascii=False))


def normalized(text):
    return re.sub(r'[\W_]+', '', unicodedata.normalize('NFKC', text).casefold())


def validate_content(candidate):
    """The versioned contract is strict. Legacy records retain their original contents."""
    if candidate.get('content_version') != VERSION:
        return
    issues = []

    def issue(field, rule):
        issues.append({'field': field, 'rule': rule})

    def text(value, field, limit, optional=False):
        if not value.strip() and not optional:
            issue(field, 'nonblank_text_required')
        if len(value) > limit:
            issue(field, 'max_length_' + str(limit))
        if '\n' in value or '\r' in value or re.search(r'```|^\s*#|\*\*|[\x00-\x1f\x7f]', value):
            issue(field, 'plain_single_line_required')
        if re.search(r'buildchoice-v3-ctx-|decv3-[a-f0-9]{8}|ASK_NOW|validation_status', value):
            issue(field, 'internal_metadata_in_display')

    for name in ('question', 'impact', 'recommendation_reason'):
        text(candidate.get(name, ''), name, LIMITS[name], optional=name == 'recommendation_reason')
    recommended = candidate.get('recommended_option_id')
    reason = candidate.get('recommendation_reason', '')
    if bool(recommended) != bool(reason.strip()):
        issue('recommendation_reason', 'recommendation_and_reason_must_be_paired')
    labels = []; outcomes = []
    for index, option in enumerate(candidate['options']):
        prefix = 'options.' + str(index) + '.'
        for name in ('label', 'tradeoff'):
            text(option[name], prefix + name, LIMITS[name])
        if re.match(r'^\s*(?:[ABCＡＢＣ][.．、:：)]|[1-3１２３][.．、:：)])\s*', option['label']):
            issue(prefix + 'label', 'label_must_not_include_numbering')
        if re.search(r'[（(]\s*推荐\s*[）)]', option['label']):
            issue(prefix + 'label', 'recommendation_is_a_separate_field')
        labels.append(normalized(option['label']));outcomes.append(normalized(option['tradeoff']))
        if option['id'] == recommended and normalized(reason) in (normalized(option['label']), normalized(option['tradeoff'])):
            issue('recommendation_reason', 'reason_repeats_option_verbatim')
        assessment = option.get('risk_assessment')
        if assessment is None:
            issue(prefix + 'risk_assessment', 'explicit_assessment_required')
            continue
        text(assessment['reason'], prefix + 'risk_assessment.reason', 200)
        status = assessment['status']
        if status != 'risks_identified' and any(key in option for key in RISK_FIELDS):
            issue(prefix + 'risk_assessment', 'assessment_conflicts_with_risk_fields')
        if status == 'risks_identified':
            if any(not option.get(key) for key in ('risk_level', 'risk_warning', 'risk_basis')):
                issue(prefix + 'risk_assessment', 'identified_risk_needs_level_warning_and_basis')
            else:
                text(option['risk_warning'], prefix + 'risk_warning', LIMITS['risk_warning'])
                for name in ('risk_condition','risk_reason'):
                    if name in option:text(option[name], prefix + name, LIMITS[name])
                if option['risk_basis'] == 'potential' and not all(option.get(k, '').strip() for k in ('risk_condition', 'risk_reason')):
                    issue(prefix + 'risk_assessment', 'potential_risk_needs_condition_and_reason')
                if option['risk_basis'] == 'observed' and not option.get('risk_evidence_refs'):
                    issue(prefix + 'risk_assessment', 'observed_risk_needs_current_source_references')
    if len(set(labels)) != len(labels):issue('options', 'duplicate_display_labels')
    if len(set(outcomes)) != len(outcomes):issue('options', 'duplicate_outcomes_require_model_review')
    if issues:
        raise ValueError(json.dumps({'code': 'CONTENT_REPAIR_REQUIRED', 'issues': issues,
            'next_action': 'Regenerate only the reported content, preserving product meaning and risk consequences; '
                           'retry with a new idempotency key. Do not truncate text or show a handwritten card.',
            'semantic_verified_by_program': False}, ensure_ascii=False))


def risk_assessments(card):
    return [{'choice_id': option['id'],
             **option.get('risk_assessment', {'status': 'not_assessed', 'reason': 'Legacy option has no explicit risk assessment.'}),
             'provenance': 'agent_declared', 'semantic_verified_by_program': False}
            for option in card['options']]
