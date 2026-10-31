"""Fixed conversation-card rendering; activation does not attest UI delivery."""
from .decision_contracts import validate


def make_card(decision_id, revision, candidate, route):
    recommendation = None
    if candidate['recommended_option_id'] is not None and candidate['recommendation_reason'].strip():
        recommendation = {'option_id': candidate['recommended_option_id'], 'reason': candidate['recommendation_reason']}
    card = {'revision': revision, 'display_id': 'D' + decision_id.split('-')[-1][:8].upper(),
            'question': candidate['question'], 'why_it_matters': candidate['impact'], 'options': candidate['options'],
            'recommendation': recommendation, 'allow_discuss': True,
            'allow_defer': route['effective_dependency'] == 'no' or not candidate['risk_flags'],
            'blocked_steps': candidate.get('depends_on', []) or ([candidate['field']] if route['effective_dependency'] != 'no' else [])}
    return validate('Card', card)


def render(card, position=1, total=1, verified=True):
    lines = [f'【BuildChoice · 决策 {position}/{total} · {card["display_id"]} · v{card["revision"]}】',
             card['question'], '原因：' + card['why_it_matters']]
    for option in card['options']:
        recommended = card['recommendation'] and card['recommendation']['option_id'] == option['id']
        lines.append(option['id'] + '. ' + option['label'] + ('（推荐）' if recommended else '') + '：' + option['tradeoff'])
    if card['recommendation']:
        lines.append('建议 ' + card['recommendation']['option_id'] + '，因为' + card['recommendation']['reason'])
    lines.append('可回复“我选第二个”、完整方案名称，或 ' + ' / '.join(o['id'] for o in card['options']) + '；需要讨论可回复“解释一下”。')
    if card['allow_defer']:
        lines.append('可回复“暂缓”，在依赖此选择的步骤前重新确认。')
    elif card['blocked_steps']:
        lines.append('等待期间暂停受影响步骤：' + '、'.join(card['blocked_steps']) + '；其他独立工作可以继续。')
    if not verified:
        lines.append('本次未绑定可信 Hook：可在聊天中讨论，但确认记录保持未核验。')
    return '\n'.join(lines)
