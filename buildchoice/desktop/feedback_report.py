"""Concise product feedback: deterministic structure checks, model-owned product judgment."""
import json
import re

VERSION='behavior-feedback.v1'
RANK={'not_checked':0,'read':1,'tested':2,'observed':3}
CHECK_LABEL={'not_checked':'待检查','read':'已查看相关资料','tested':'已做相关测试','observed':'已做操作检查'}


def fail(issues):
    raise ValueError(json.dumps({'code':'FEEDBACK_CONTENT_REPAIR_REQUIRED','issues':issues,
        'next_action':'Revise the named fields with concrete user behavior and supported check states. '
                      'Keep detailed evidence in evidence/limits; retry with a new idempotency key.',
        'semantic_verified_by_program':False},ensure_ascii=False))


def require_current(request):
    if request.get('action') in ('create','supplement') and request.get('report',{}).get('version')!=VERSION:
        fail([{'field':'report.version','rule':'current_structured_feedback_required'}])


def supported_check(finding):
    chosen=set(finding.get('behavior_ids') or [finding['finding_id']])
    current=[e for e in finding['evidence'] if e.get('current',True)]
    for strength,kind in [('runtime_tool_observation','observed'),('test_execution_result','tested')]:
        covered={b for e in current if e.get('strength')==strength for b in e.get('tested_behaviors',[])}
        if chosen<=covered:return kind
    if any(e.get('strength') in ('actual_code_or_file','test_execution_result','runtime_tool_observation','report_file_execution_unverified') for e in current):return 'read'
    return 'not_checked'


def validate_content(request, findings):
    if 'report' not in request:return  # Historical API records retain compatibility.
    issues=[]
    def issue(field,rule):issues.append({'field':field,'rule':rule})
    def plain(value,field,maximum):
        if not value.strip():issue(field,'nonblank_text_required')
        if len(value)>maximum:issue(field,'max_length_'+str(maximum))
        if re.search(r'[\x00-\x1f\x7f]|```|\*\*|buildchoice-v3-ctx-|decv3-[a-f0-9]{8}',value):
            issue(field,'plain_user_facing_text_required')
    offered={f['finding_id'] for f in findings}
    overview=request['report']['overview']
    if len(overview)!=len(set(overview)) or not set(overview)<=offered:
        issue('report.overview','unique_existing_finding_ids_required')
    for index,finding in enumerate(findings):
        prefix='findings.'+str(index)+'.';display=finding.get('display')
        if display is None:issue(prefix+'display','structured_display_required');continue
        plain(finding['summary'],prefix+'summary',180)
        plain(display['title'],prefix+'display.title',48)
        if RANK[display['check']]>RANK[supported_check(finding)]:
            issue(prefix+'display.check','check_claim_exceeds_current_evidence_or_behavior_coverage')
        material=finding['importance']!='low'
        if material and finding['judgment'] in ('possibly_deviates','extra','unknown') and not display.get('impact'):
            issue(prefix+'display.impact','explain_the_user_consequence')
        if display.get('impact'):plain(display['impact'],prefix+'display.impact',160)
        gap=display.get('gap')
        if finding['importance']=='high' and finding['judgment']=='unknown' and display['check']=='not_checked' and not gap:
            issue(prefix+'display.gap','important_unchecked_behavior_needs_concrete_gap_and_next_step')
        if gap:
            for key in ('situation','effect','next_step'):plain(gap[key],prefix+'display.gap.'+key,100 if key=='next_step' else 80)
            if gap['situation'].strip()==gap['effect'].strip():issue(prefix+'display.gap.effect','do_not_repeat_the_same_gap')
            if gap['situation'].strip('。 .') in ('尚未验证','缺少证据','证据不足','无法判断','未完成检查','其他情况未验证'):
                issue(prefix+'display.gap.situation','name_the_specific_operation_or_screen')
            if gap['next_step'].strip('。 .') in ('继续检查','进一步验证','补充测试'):
                issue(prefix+'display.gap.next_step','name_the_specific_followup')
    if issues:fail(issues)


def view(finding):
    """Old rows are displayed without backfilling invented judgments or a new approval."""
    display=dict(finding.get('display') or {'title':finding.get('scenario_title') or finding['summary'],
                                          'check':supported_check(finding)})
    if RANK[display['check']]>RANK[supported_check(finding)]:display['check']=supported_check(finding)
    return display


def feedback_acknowledgment(saved,findings):
    steps={'fix':'接下来处理该行为并复查。','change_requirement':'接下来按新要求调整并复查。',
           'accept_extra':'保留这项行为。','investigate':'接下来补查这项具体行为。','defer':'保留待办，暂不处理。'}
    return '\n'.join('已记录对「'+view(findings[item['finding_id']])['title']+'」的意见。'+steps[item['action']] for item in saved)


def render(review):
    findings=review['findings'];by_id={f['finding_id']:f for f in findings}
    supplement=review.get('review_mode')=='current'
    lines=['## 修改后的使用反馈','']
    if supplement:lines+=['这是当前行为的补充检查，不包含正式的前后行为对照。','']
    lines+=['### 当前使用时会怎样' if supplement else '### 这次主要改变了什么','']
    overview=review.get('report',{}).get('overview') or [f['finding_id'] for f in findings[:3]]
    for ident in overview:
        finding=by_id[ident];display=view(finding)
        lines+=['- '+finding['summary']+'（'+CHECK_LABEL[display['check']]+'）']
    if not overview:lines+=['本次尚未提供可说明的具体行为。']
    attention=[f for f in findings if f['importance']!='low' and
               f['judgment'] in ('possibly_deviates','extra','unknown') and
               f.get('resolution_state') not in ('accepted','requirement_changed')]
    lines+=['','### 优先值得你看的地方','']
    if not attention:lines+=['本次检查未报告需要优先处理的差异。' if review.get('validity')=='current' else '需要先更新检查，再判断有无重要差异。']
    for finding in attention:
        display=view(finding)
        relation={'possibly_deviates':'可能偏离预期','extra':'补充发现','unknown':'尚不能对照原要求判断'}[finding['judgment']]
        lines+=['- **'+display['title']+'**：'+relation+'。']
        last=finding.get('feedback')
        if last:
            action=last['data']['action']
            label={'fix':'待修正','investigate':'待补查','defer':'已暂缓'}.get(action)
            if label:lines+=['  处理状态：'+label+'。']
        if finding['finding_id'] not in overview:lines+=['  当前表现：'+finding['summary']+'（'+CHECK_LABEL[display['check']]+'）']
        if finding.get('expected_behavior'):
            label='参照内容' if supplement else '原约定'
            lines+=['  '+label+'：'+'；'.join(finding['expected_behavior'])]
        if display.get('impact'):lines+=['  对你的影响：'+display['impact']]
        if finding.get('change_origin')=='preexisting':lines+=['  这是原有行为。']
        elif finding.get('change_origin')=='uncertain' and not supplement:lines+=['  尚不能确定是否由本次改动引入。']
    gaps=[];seen=set()
    for finding in sorted(findings,key=lambda f:f['importance']!='high'):
        display=view(finding);gap=display.get('gap')
        if not gap and not finding.get('display') and finding['judgment']=='unknown' and finding['importance']=='high':
            # Legacy omitted checks remain visible, phrased using the actual product behavior.
            operation='；'.join(finding.get('expected_behavior') or [finding['summary']])
            gap={'situation':operation,'effect':'这项操作还没有对应的检查结果。',
                 'next_step':'补查这项操作的实际表现。','owner':'agent'}
        if not gap or finding['importance']=='low':continue
        key=(gap['situation'],gap['effect'],gap['next_step'],gap['owner'])
        if key not in seen:gaps.append(gap);seen.add(key)
    if review.get('validity')!='current':
        reasons=review.get('stale_reasons',[])
        if any(r.startswith(('workspace_changed:','scope_inventory_changed:')) for r in reasons):
            situation,effect,step='当前产品已有后续变化','原来的检查结果需要更新。','按当前版本复查相关操作。'
        elif any(r.startswith(('snapshot_content_unavailable','baseline_content_unavailable')) for r in reasons):
            situation,effect,step='原检查记录已不可用','无法继续复查原来的检查过程。','补查当前操作，保留无法还原的部分。'
        elif any(r.startswith(('scenario_changed:','decision_changed:')) for r in reasons):
            situation,effect,step='原来的要求已更新','需要重新判断当前操作是否符合新要求。','按新要求复查相关操作。'
        else:
            situation,effect,step='相关检查资料已有变化','原判断需要重新核对。','重新读取相关资料并检查对应操作。'
        gaps.insert(0,{'situation':situation,'effect':effect,'next_step':step,'owner':'agent'})
    if gaps:
        lines+=['','### 还有什么具体情况需要确认','']
        for gap in gaps:
            owner='我来处理' if gap['owner']=='agent' else '需要你参与'
            lines+=['- '+gap['situation']+'：'+gap['effect']+' 下一步（'+owner+'）：'+gap['next_step']]
    lines+=['','### 如何表达修改意见','']
    if attention:
        title=view(attention[0])['title']
        lines+=['可以直接说“把「'+title+'」改成……”。我会先对应到具体行为，再说明处理方式。']
    else:lines+=['想调整时，直接描述哪个操作应该怎样变化即可。']
    return '\n'.join(lines)
