"""Readable projections of recorded choices, with literal revision/source changes."""
import json
import os
import uuid
from pathlib import Path
from .audit import encode, linked_path, PRIVATE_PARTS
from .task_context import authorize, host_tasks, source_state
from . import decision_memory as memory

MARKER='<!-- BuildChoice generated decision document -->'


def readable(value):
    if value is None:return '未设置'
    if isinstance(value,list):return '；'.join(readable(v) for v in value) or '无'
    return str(value) if isinstance(value,(str,int,float,bool)) else encode(value)


def change_lines(change):
    labels={'scope_key':'适用范围','conditions':'适用条件','label':'名称','tradeoff':'方案说明',
        'value':'取值','behavior':'行为','option_key':'方案标识'}
    if change['field']=='material_change':return ['- 方案含义变化：由 LLM 声明，需核对本版本的选择。']
    if change['field']!='options':
        return ['- '+labels.get(change['field'],change['field'])+'：'+readable(change['before'])+' → '+readable(change['after'])]
    before={o['id']:o for o in change['before']};after={o['id']:o for o in change['after']};lines=[]
    for ident in dict.fromkeys([*before,*after]):
        if ident not in before:lines.append('- 新增方案：'+after[ident]['label']);continue
        if ident not in after:lines.append('- 移除方案：'+before[ident]['label']);continue
        for key,label in labels.items():
            if before[ident].get(key)!=after[ident].get(key):
                lines.append('- 方案 '+ident+' 的'+label+'：'+readable(before[ident].get(key))+' → '+readable(after[ident].get(key)))
    return lines or ['- 方案展示信息已更新。']


def destination(store, relative, marker=MARKER):
    if not isinstance(relative,str) or not relative or len(relative)>512 or ':' in relative:
        raise ValueError('Use a relative Markdown document path')
    parts=Path(relative.replace('\\','/')).parts
    if Path(relative).is_absolute() or '..' in parts or any(p.lower() in PRIVATE_PARTS or p.lower().startswith('.env') for p in parts):
        raise ValueError('Document path must stay inside the project')
    current=store.workspace
    for part in parts:
        current=current/part
        if linked_path(current):raise ValueError('Linked document paths are excluded')
    target=current.resolve()
    if not target.is_relative_to(store.workspace) or target.suffix.lower()!='.md' or not target.parent.is_dir():
        raise ValueError('Choose an existing project directory and a Markdown filename')
    if target.exists():
        with target.open('r',encoding='utf-8') as stream:header=stream.read(len(marker))
        if header!=marker:raise ValueError('Existing user-authored document will not be overwritten')
    return target


def document(service, store, handle, task_id=None, include_archived=False, write=False, path='BUILDCHOICE_DECISIONS.md', confirmed_only=False):
    if type(include_archived) is not bool or type(write) is not bool:raise ValueError('Boolean flags required')
    ctx=authorize(service,store,handle,task_id)
    if write and not confirmed_only:
        with store.connect() as db:
            exists=db.execute("SELECT 1 FROM sqlite_master WHERE name='decision_v3_document_jobs'").fetchone()
            job=db.execute('SELECT path FROM decision_v3_document_jobs WHERE workspace=?',(str(store.workspace),)).fetchone() if exists else None
        if job and path in (job['path'],'BUILDCHOICE_DECISIONS.md'):
            if task_id or include_archived:raise ValueError('Use a separate path for task-specific or archived exports')
            from .document_projection import publish
            sync=publish(service,store,handle)
            result=document(service,store,handle,confirmed_only=True)
            result.update(written=sync['status']=='synchronized',document=sync,path=sync.get('path'))
            return result
    with store.connect() as db:entries=memory.records(store,db)
    hidden={(e['decision_id'],e['revision']) for e in entries if e['state'] not in ('active','needs_review')}
    entries=[e for e in entries if include_archived or e['state'] in ('active','needs_review')]
    if task_id:entries=[e for e in entries if e['task_id']==task_id]
    total=len(entries);entries=entries[-100:]
    rows=[];seen=set();checks={}
    def references(candidate):
        result=[]
        for ref in candidate['evidence_refs']:
            if ref['source_id'] not in checks:checks[ref['source_id']]=source_state(store,ref['source_id'])
            result.append({**checks[ref['source_id']],**{k:ref[k] for k in ('quote','pointer') if k in ref}})
        return result
    def project(row, confirmation=None, state=None):
        candidate=json.loads(row['candidate_json']);route=json.loads(row['routing_json'])
        choice=next((o for o in candidate['options'] if confirmation and o['id']==confirmation['choice_id']),None)
        with store.connect() as db:
            previous=db.execute('SELECT * FROM decision_v3_items WHERE id=? AND revision<? ORDER BY revision DESC LIMIT 1',
                (row['id'],row['revision'])).fetchone()
            prior_choice=db.execute('SELECT * FROM decision_v3_confirmations WHERE decision_id=? AND revision<? ORDER BY revision DESC LIMIT 1',
                (row['id'],row['revision'])).fetchone()
        changes=[]
        if previous:
            old=json.loads(previous['candidate_json'])
            for key in ('scope_key','conditions','options'):
                if old.get(key)!=candidate.get(key):changes.append({'field':key,'before':old.get(key),'after':candidate.get(key)})
            if candidate.get('material_change'):changes.append({'field':'material_change','declared_by':'llm'})
        return {'decision_id':row['id'],'decision_key':memory.decision_key(candidate),'revision':row['revision'],
            'field':candidate['field'],'question':candidate['question'],'state':state or row['state'],
            'scope':candidate.get('scope_key','project'),'conditions':candidate.get('conditions',[]),
            'choice':choice,'confirmation':dict(confirmation) if confirmation else None,
            'suggested_action':route.get('suggested_action',route['status']),'references':references(candidate),
            'previous_confirmation':dict(prior_choice) if prior_choice else None,'changes':changes}
    with store.connect() as db:
        for entry in entries:
            row=db.execute('SELECT i.* FROM decision_v3_items i JOIN decision_v3_tasks t ON t.id=i.task_id '
                'WHERE i.id=? AND i.revision=? AND t.workspace=?',(entry['decision_id'],entry['revision'],str(store.workspace))).fetchone()
            conf=db.execute('SELECT * FROM decision_v3_confirmations WHERE id=?',(entry['confirmation_id'],)).fetchone()
            if row:
                rows.append(project(row,conf,entry['state']));seen.add((row['id'],row['revision']))
    for task in ([] if confirmed_only else host_tasks(store,ctx,task_id)):
        for row in store.items(task['id']):
            if not include_archived and (row['id'],row['revision']) in hidden:continue
            if (row['id'],row['revision']) not in seen:
                rows.append(project(row,store.confirmation(row)));seen.add((row['id'],row['revision']))
    truncated=total>100 or len(rows)>150
    rows=rows[:150]
    lines=[MARKER,'# 项目决策记录','',
        '汇总已保存的选择、适用范围、待办事项和修订差异，供后续开发参考。',
        '文件变化时保留原选择，并标注需要复核的引用。','']
    labels={'confirmed':'已记录选择','active':'已记录选择','needs_review':'选择保留，来源待复核','deferred':'暂缓',
        'card_active':'等待回答','needs_explanation':'等待解释或回复判读','screened':'已登记','inspecting':'资料待核对',
        'superseded':'已有后续修订','archived':'已归档','forgotten':'已遗忘'}
    if total>100:lines+=['已确认记忆仅展示最近100条；可按任务导出或查询更多记录。','']
    if not rows:lines+=['当前范围没有可展示的决策记录。','']
    for item in rows:
        lines+=['## '+item['field'],'',item['question'],'',
            '- 标识：'+item['decision_key']+' · v'+str(item['revision']),
            '- 状态：'+labels.get(item['state'],item['state']),'- 范围：'+item['scope']]
        if item['conditions']:lines+=['- 适用条件：'+'；'.join(item['conditions'])]
        if item['choice']:
            lines+=['- 已选方案：'+item['choice']['label'],'- 方案说明：'+item['choice']['tradeoff']]
            if 'value' in item['choice']:lines+=['- 实际取值：'+readable(item['choice']['value'])]
            if 'behavior' in item['choice']:lines+=['- 行为：'+readable(item['choice']['behavior'])]
            provenance=item['confirmation']['provenance']
            sources={'llm_interpreted_user_reply':'实际用户消息，选项对应由 LLM 解释',
                'llm_interpreted_user_instruction':'实际用户修改指令，含义与范围由 LLM 解释'}
            lines+=['- 选择来源：'+sources.get(provenance,'实际用户消息中的明确选项回复')]
        else:lines+=['- 尚无当前版本的用户选择；LLM 建议：'+item['suggested_action']]
        if item['previous_confirmation']:
            lines+=['- 原确认：v'+str(item['previous_confirmation']['revision'])+'，选项 '+item['previous_confirmation']['choice_id']]
        for ref in item['references']:
            lines+=['- 引用：'+ref.get('path',ref['source_id'])+' · '+('版本有效' if ref['current'] else '文件已变化或不可读取，需复核')]
        for change in item['changes']:
            lines+=change_lines(change)
        lines+=['']
    markdown='\n'.join(lines)+'\n'
    result={'schema_version':'decision-document.v1','markdown':markdown,'decisions':rows,
        'truncated':truncated,'written':False,'does_not_authorize_host_operations':True}
    if write:
        target=destination(store,path);temporary=target.with_name(target.name+'.'+uuid.uuid4().hex+'.tmp')
        try:
            temporary.write_text(markdown,encoding='utf-8')
            destination(store,path)  # Recheck ownership immediately before atomic replacement.
            os.replace(temporary,target)
        finally:temporary.unlink(missing_ok=True)
        result.update(written=True,path=target.relative_to(store.workspace).as_posix())
    return result
