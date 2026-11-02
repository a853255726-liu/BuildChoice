"""Narrow PostToolUse adapters. Unknown/failed/truncated reads never create receipts."""
import json
import re
import shlex
from pathlib import Path
from .audit import Ledger, MAX_BYTES
from .decision_settings import read as read_settings

MCP_READERS={'mcp__filesystem__read_file','mcp__filesystem__read_text_file'}


def shell_read(command):
    if not isinstance(command,str) or re.search(r'[\r\n$`;<> &]',command.replace(' ','')):
        return None
    # Exact, literal PowerShell read and one known range selector; never scripts.
    match=re.fullmatch(r"Get-Content\s+(?:(?:-LiteralPath|-Path)\s+)?(?P<path>'[^']+'|\"[^\"]+\"|[a-zA-Z0-9_./:\\-]+)"
        r"(?:\s*\|\s*Select-Object\s+-Skip\s+(?P<skip>\d+)\s+-First\s+(?P<count>\d+))?",command,re.I)
    if match:
        return match['path'].strip('\'"'),int(match['skip'] or 0)+1,int(match['count']) if match['count'] else None
    if '|' in command:return None
    try:parts=shlex.split(command)
    except ValueError:return None
    if len(parts)==3 and parts[:2]==['cat','--']:return parts[2],1,None
    if len(parts)==2 and parts[0]=='cat' and not parts[1].startswith('-'):return parts[1],1,None
    if len(parts)==4 and parts[:2]==['sed','-n']:
        match=re.fullmatch(r'([1-9][0-9]*),([1-9][0-9]*)p',parts[2])
        if match and int(match[2])>=int(match[1]):return parts[3],int(match[1]),int(match[2])-int(match[1])+1
    return None


def returned_text(response, shell=False):
    if isinstance(response,str):
        try:response=json.loads(response)
        except ValueError:
            if not shell:return None
            # Native unified-exec model-facing output. Unknown wrappers/polls are
            # skipped; a matching body must still equal the entire selected range.
            match=re.fullmatch(r'(?:Chunk ID: [^\n]+\n)?Wall time: [0-9.]+ seconds\n'
                r'(?:Process exited with code 0|Exit code: 0)\n(?:Output|Final output):\n(.*)',response,re.S)
            return match[1] if match else None
    if not isinstance(response,dict) or response.get('isError') or response.get('session_id') is not None:return None
    if shell:
        if type(response.get('exit_code')) is not int or response['exit_code']!=0:return None
        if response.get('stderr') or response.get('truncated'):return None
        value=response.get('output',response.get('stdout'))
        return value if isinstance(value,str) else None
    content=response.get('content')
    if isinstance(content,list) and len(content)==1 and isinstance(content[0],dict) and content[0].get('type')=='text':
        return content[0].get('text')
    return None


def observe(event, workspace, settings_path=None):
    """Receive only actual host callbacks; there is deliberately no MCP write API."""
    try:return _observe(event,workspace,settings_path)
    except (OSError,ValueError,TypeError,UnicodeError):return None


def _observe(event, workspace, settings_path):
    if event.get('hook_event_name')!='PostToolUse':return None
    config=read_settings(settings_path) if settings_path is not None else read_settings()
    if config['mode']!='pilot':return None
    if not all(isinstance(event.get(k),str) and event[k] for k in ('cwd','session_id','turn_id','tool_use_id','tool_name')):return None
    workspace=Path(workspace).resolve();cwd=Path(event['cwd']).resolve()
    if not cwd.is_relative_to(workspace):return None
    args=event.get('tool_input');name=event['tool_name']
    if not isinstance(args,dict):return None
    if name=='Bash':
        spec=shell_read(args.get('command',args.get('cmd')))
        output=returned_text(event.get('tool_response'),shell=True)
        directory=Path(args.get('workdir') or cwd)
        cwd=(cwd/directory).resolve() if not directory.is_absolute() else directory.resolve()
    elif name in MCP_READERS:
        if set(args)-{'path','head','tail'} or ('head' in args and 'tail' in args):return None
        head,tail=args.get('head'),args.get('tail')
        if tail is not None:return None  # No inferred tail offsets in this adapter.
        if head is not None and (type(head) is not int or head<1):return None
        spec=(args.get('path'),1,head);output=returned_text(event.get('tool_response'))
    else:return None
    if not spec or not isinstance(spec[0],str) or not isinstance(output,str) or not output:return None
    # Resolve relative to the actual invocation directory, then reuse private/path guards.
    path=Path(spec[0]);path=path if path.is_absolute() else cwd/path
    try:relative=path.absolute().relative_to(workspace).as_posix()
    except ValueError:return None
    ledger=Ledger(workspace);file=ledger.path(relative)
    with file.open('rb') as stream:raw=stream.read(MAX_BYTES+1)
    if len(raw)>MAX_BYTES:return None
    lines=raw.decode('utf-8-sig').splitlines();start,count=spec[1:]
    end=len(lines) if count is None else min(len(lines),start+count-1)
    if start<1 or end<start:return None
    fragment='\n'.join(lines[start-1:end]);actual=output.replace('\r\n','\n')
    if actual not in (fragment,fragment+'\n'):return None
    receipt=ledger.observe_read(event,relative,raw,start,end,fragment)
    return {'hookSpecificOutput':{'hookEventName':'PostToolUse','additionalContext':
        'BuildChoice 真实工具读取记录：'+json.dumps(receipt,ensure_ascii=False)+
        '。可用于 evidence_refs；仅证明工具返回了这些行，不证明理解或用户同意。'}}
