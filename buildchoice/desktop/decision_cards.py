"""Fixed conversation-card rendering; activation does not attest UI delivery."""
from .decision_contracts import validate


def make_card(decision_id, revision, candidate):
    recommendation = None
    if candidate['recommended_option_id'] is not None and candidate['recommendation_reason'].strip():
        recommendation = {'option_id': candidate['recommended_option_id'], 'reason': candidate['recommendation_reason']}
    card = {'revision': revision, 'display_id': 'D' + decision_id.split('-')[-1][:8].upper(),
            'question': candidate['question'], 'why_it_matters': candidate['impact'], 'options': candidate['options'],
            'recommendation': recommendation, 'allow_discuss': True,
            'allow_defer': candidate.get('allow_defer',True),
            'blocked_steps': candidate.get('depends_on', []) or [candidate['field']]}
    if candidate.get('content_version'):card['content_version']=candidate['content_version']
    return validate('Card', card)


def render(card, position=1, total=1, verified=True):
    from .conversation_ui import option_text
    lines = [f'### BuildChoice · 选择 {position}/{total}', '',
             '**' + card['question'] + '**', '', '**产品影响**', card['why_it_matters'], '', '**可选方案**', '']
    for option in card['options']:
        lines += [option_text(card, option), '']
    if card['recommendation']:
        lines += ['**推荐理由**', card['recommendation']['reason'], '']
    lines.append('可选择 ' + ' / '.join(o['id'] for o in card['options']) + '，也可以直接说明想法或继续讨论。')
    if card['allow_defer']:
        lines.append('需要稍后决定时，可回复“暂缓”。')
    elif card['blocked_steps']:
        lines.append('等待期间暂停受影响步骤：' + '、'.join(card['blocked_steps']) + '；其他独立工作可以继续。')
    if not verified:
        lines.append('本次未绑定可信 Hook：可在聊天中讨论，但确认记录保持未核验。')
    return '\n'.join(lines)
