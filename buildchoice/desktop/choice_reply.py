"""Resolve clear whole-message choices against the single active card."""
import re
import json
import unicodedata


def normalized(value):
    return re.sub(r'\s+','',unicodedata.normalize('NFKC',value).casefold()).strip('。.!！')


def parse_choice(prompt,card):
    if prompt.strip().startswith('<send_user_message_question_reply>'):
        return parse_native_choice(prompt,card)
    if len(prompt)>500:return None
    text=normalized(prompt)
    display=card['display_id'].casefold()
    named=re.match(r'^(d[0-9a-f]{8})[:：,，]?',text)
    if named:
        if named[1]!=display:return None
        text=text[named.end():]
    # Only complete affirmative templates. Quotes, questions, conditional replies,
    # multiple options and additional instructions do not match these templates.
    forms=[text]
    if text.endswith('吧'):forms.append(text[:-1])
    positive=re.fullmatch(r'(?:我(?:就)?(?:选(?:择)?|要)|(?:就)?(?:选(?:择)?|采用|使用|用)|决定用|ichoose|choose|select|use)(.+?)(?:吧|好了|就好)?',text)
    if positive:forms.append(positive[1])
    options=card['options'];matches=set()
    for form in forms:
        for i,option in enumerate(options,1):
            labels={normalized(option['label']),option['id'].casefold()}
            number='一二三'[i-1]
            labels.update({f'第{i}个',f'第{i}个方案',f'第{number}个',f'第{number}个方案',
                           f'第{number}项',f'第{i}项',f'方案{i}',f'方案{number}',
                           f'方案{option["id"].casefold()}',f'{option["id"].casefold()}方案'})
            if form in labels:matches.add(option['id'])
        if form in ('推荐方案','你推荐的方案','按推荐方案','按你推荐的来','就按你推荐的来'):
            recommendation=card.get('recommendation')
            if recommendation:matches.add(recommendation['option_id'])
    if len(matches)==1:return {'choice_id':matches.pop(),'method':'explicit_option_expression'}
    return None


def parse_native_choice(prompt, card):
    """Called only for a prompt already observed by the trusted UserPromptSubmit Hook.

    This parser cannot create a context from an assistant-supplied UI receipt. It accepts
    only an exact single-card question/answer expression, never custom text or batches.
    """
    if len(prompt) > 8000 or 'question' not in card:
        return None
    text = prompt.strip()
    start, end = '<send_user_message_question_reply>', '</send_user_message_question_reply>'
    if not text.endswith(end):
        return None

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate field')
            result[key] = value
        return result

    try:
        items = json.loads(text[len(start):-len(end)].strip(), object_pairs_hook=unique_object)
        if not isinstance(items, list) or len(items) != 1:
            return None
        item = items[0]
        if (not isinstance(item, dict) or set(item) != {'questionItemId', 'question', 'answer'}
                or any(not isinstance(value, str) for value in item.values())
                or item['question'] != card['question'].strip()):
            return None
        identity = json.loads(item['questionItemId'])
        if (not isinstance(identity, list) or len(identity) != 3
                or identity[0] != 'request_user_input_async'
                or not isinstance(identity[1], str)
                or not re.fullmatch(r'call_[A-Za-z0-9_-]{1,120}', identity[1])
                or type(identity[2]) is not int or identity[2] != 0):
            return None
        from .conversation_ui import option_text
        matches = [option['id'] for option in card['options']
                   if item['answer'] == option_text(card, option, numbered=False)]
        if len(matches) == 1:
            return {'choice_id': matches[0], 'method': 'explicit_native_option_expression'}
    except (ValueError, TypeError, KeyError):
        pass
    return None
