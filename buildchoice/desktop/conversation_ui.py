"""Host-native question payloads derived from frozen cards, without granting confirmation."""
import re
from .decision_store import fingerprint
from .decision_content import validate_content, risk_assessments


def clean_label(label):
    # Display-only cleanup; the immutable candidate/card and option identity are unchanged.
    return re.sub(r'(?:\s*[（(]推荐[）)])+\s*$', '', label).strip()


def option_text(card, option, numbered=True):
    recommended = card.get('recommendation') or {}
    suffix = '（推荐）' if recommended.get('option_id') == option['id'] else ''
    label=clean_label(option['label'])
    # Older frozen labels can carry their own prefix. Remove decoration only;
    # retain the immutable choice ID in bindings and the Markdown fallback.
    label=re.sub(r'^\s*'+re.escape(option['id'])+r'[.．、:：)]\s*', '', label)
    text = (option['id'] + '. ' if numbered else '') + label + suffix + '：' + option['tradeoff']
    if option.get('risk_warning') and option.get('risk_basis') in ('observed','potential'):
        basis = '项目资料中的风险' if option.get('risk_basis') == 'observed' else '可能发生'
        text += '\n风险提示（' + basis + '）：' + option['risk_warning']
        if option.get('risk_basis')=='potential' and option.get('risk_condition'):
            text += '\n发生条件：' + option['risk_condition']
    return text


def decision_presentation(entries):
    """entries contains decision_id/revision/card from the actual activation or frozen batch."""
    if not 1 <= len(entries) <= 3:
        raise ValueError('Native decision forms contain one to three frozen questions')
    questions = []; bindings = []; details = []
    for index, entry in enumerate(entries):
        card = entry['card']
        recommendation=card.get('recommendation') or {}
        validate_content({**card, 'impact':card['why_it_matters'],
                          'recommended_option_id':recommendation.get('option_id'),
                          'recommendation_reason':recommendation.get('reason','')})
        title = card['question'].strip()
        answers = [{'text': option_text(card, option, numbered=False), 'choice_id': option['id']} for option in card['options']]
        questions.append({'title': title, 'options': [answer['text'] for answer in answers]})
        bindings.append({'question_index': index, 'decision_id': entry['decision_id'],
            'revision': entry['revision'], 'card_sha256': fingerprint(card), 'answers': answers})
        details.append({'question_index':index,'impact':card['why_it_matters'],
                        'recommendation':card.get('recommendation'),
                        'allow_discuss':card['allow_discuss'],'allow_defer':card['allow_defer'],
                        'risk_assessments':risk_assessments(card)})
    return {'schema_version': 'conversation-presentation.v2', 'preferred_surface': 'host_native_questions',
        'native_request': {'questions': questions}, 'bindings': bindings,
        'details':details,
        'content_validation':{'status':'passed','scope':'structure_and_presentation_only',
                              'semantic_verified_by_program':False},
        'agent_action': 'Call the available host request_user_input_async with native_request; do not paste a text card first. '
                        'Do not append details or boilerplate by default. Details are available when the user requests explanation. '
                        'If only request_user_input exists, use its documented shape in its supported mode. '
                        'If neither is available, show the fixed Markdown message and disclose text-only fallback.',
        'delivery_status': 'requires_host_render', 'user_confirmed': False,
        'reply_action': 'Wait for an actual Hook-observed user reply with a fresh handle. Inspect context.reply_binding first. '
                        'If an async answer has no fresh Hook context, keep it unrecorded; do not reuse the old handle, '
                        'switch recording tools, or redisplay the card. Explain once; request an ordinary chat message '
                        'only if saving is required. Map the exact answer to the frozen question/option; '
                        'use existing reply_interpret or batch submit. A preselected option or UI receipt is not consent.'}


def single(response):
    return {**response, 'presentation': decision_presentation([{
        'decision_id': response['decision_id'], 'revision': response['revision'], 'card': response['card']}])}
