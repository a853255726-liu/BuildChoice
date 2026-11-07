"""Synchronize only maintained, explicitly marked Skill blocks; no runtime dependency."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from buildchoice.desktop.guidance import VERSION, TOPICS, compose

SKILL = Path('plugins/buildchoice/skills/decision-discovery')
BLOCKS = {
    SKILL/'SKILL.md': ('entry',),
    SKILL/'references/independent-review.md': ('review',),
    SKILL/'references/feedback-content.md': ('completion',),
    **{SKILL/f'references/{file}.md': ('topic:'+topic,) for topic,file in (
        ('interface','interface-content'),('documentation','documentation-consistency'),('debugging','evidence-debugging'))},
}


def render(name):
    text = TOPICS[name.split(':',1)[1]]['zh'] if name.startswith('topic:') else compose(name,'zh')
    return f'维护版本：`{VERSION}`。\n\n'+text


def update(text, name):
    start=f'<!-- buildchoice-guidance:{name}:start -->'
    end=f'<!-- buildchoice-guidance:{name}:end -->'
    if text.count(start)!=1 or text.count(end)!=1 or text.index(start)>=text.index(end):
        raise ValueError('Missing, duplicate or reversed guidance markers: '+name)
    a=text.index(start)+len(start);b=text.index(end)
    newline='\r\n' if '\r\n' in text else '\n'
    return text[:a]+newline+render(name).replace('\n',newline)+newline+text[b:]


def synchronize(root=ROOT, check=False):
    pending=[]
    for relative,names in BLOCKS.items():
        path=root/relative
        original=path.read_bytes().decode('utf-8')
        result=original
        for name in names:result=update(result,name)
        if result!=original:pending.append((path,result))
    # Validate every marker before any write; --check never modifies files.
    if check and pending:
        raise ValueError('Generated guidance drift: '+', '.join(str(p.relative_to(root)) for p,_ in pending))
    for path,result in pending:
        path.write_bytes(result.encode('utf-8'))
    return [str(p.relative_to(root)) for p,_ in pending]


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check',action='store_true')
    args=parser.parse_args()
    try:
        changed=synchronize(check=args.check)
    except ValueError as error:
        parser.exit(1,str(error)+'\n')
    print('Guidance blocks current.' if not changed else 'Updated '+', '.join(changed))
