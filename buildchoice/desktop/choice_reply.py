"""Resolve clear whole-message choices against the single active card."""
import re
import unicodedata


def normalized(value):
    return re.sub(r'\s+','',unicodedata.normalize('NFKC',value).casefold()).strip('。.!！')


def parse_choice(prompt,card):
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
