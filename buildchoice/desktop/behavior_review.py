"""Behavior judgments and independently recorded evidence strength, never certification."""
import hashlib
from . import product_store as ps
from .product_contracts import validate
from . import workspace_snapshot as snapshots


def evidence(store, db, task_id, given, field="evidence.quote"):
    result = dict(given)
    kind = given['kind']
    result.update(current=True, semantic_verified_by_program=False)
    if kind in ('llm', 'missing'):
        if 'path' in given or 'observation_id' in given: raise ValueError('Analysis/missing evidence cannot claim observed artifacts')
        result['strength'] = 'llm_analysis_only' if kind == 'llm' else 'missing'
        return result
    if kind in ('test', 'runtime') and given.get('observation_id'):
        observed = ps.get(db, given['observation_id'], 'tool_observation', task_id=task_id)
        quote = given.get('quote')
        if not quote or quote not in observed['data']['output']: raise ValueError('Execution evidence must quote the actual observed output')
        if given.get('command') and given['command'] != observed['data']['command']: raise ValueError('Execution command mismatch')
        if given.get('outcome') == 'passed' and observed['data']['exit_code'] != 0: raise ValueError('Nonzero execution cannot support a passing result')
        result.update(strength='test_execution_result' if kind == 'test' else 'runtime_tool_observation',
            observation=observed['data'], input_state_during_execution='not_observed',
            behavior_mapping='llm_declared')
        if observed['data'].get('scope_snapshot_id'):
            snapshot = ps.get(db, observed['data']['scope_snapshot_id'], 'code_snapshot', task_id=task_id)
            if snapshots.current_files(store, snapshot) != observed['data']['code_state_after']:
                result.update(current=False, stale_reason='code_changed_since_tool_observation')
        else:
            result.update(current=False, stale_reason='execution_code_scope_not_observed')
    elif kind in ('test', 'runtime'):
        # A real log file is evidence of the report, not proof a command/interaction occurred.
        result['strength'] = 'report_file_execution_unverified'
    else: result['strength'] = 'actual_code_or_file'
    if given.get('path'):
        path = store.ledger.path(given['path'])
        with path.open('rb') as stream: raw = stream.read(snapshots.FILE_LIMIT + 1)
        if len(raw) > snapshots.FILE_LIMIT or b'\0' in raw: raise ValueError('Evidence file is too large or binary')
        text = raw.decode('utf-8-sig')
        if snapshots.excluded(given['path']) or snapshots.SECRET_CONTENT.search(text): raise ValueError('Sensitive evidence is excluded')
        lines = text.splitlines(); start = given.get('start_line', 1); end = given.get('end_line', len(lines))
        if not 1 <= start <= end <= len(lines): raise ValueError('Evidence line range does not exist')
        if 'quote' not in given or not given['quote'].strip() or given['quote'] not in '\n'.join(lines[start - 1:end]):
            from .guidance import evidence_repair
            evidence_repair(field, given['path'], start, end, 'exact_quote_required_in_cited_lines')
        result.update(sha256=hashlib.sha256(raw).hexdigest(), start_line=start, end_line=end)
    elif not given.get('observation_id'): raise ValueError('File/test/runtime evidence requires a real file or observed tool result')
    if kind in ('test', 'runtime') and (not given.get('limits') or not given.get('tested_behaviors')):
        raise ValueError('Executed/reported checks require explicit behavior coverage and limits')
    return result


def status(store, db, row):
    from .experience import current_reasons
    data = row['data'];supplement=data.get('review_mode')=='current'
    if supplement:
        end=ps.get(db,data['current_snapshot_id'],'code_snapshot',task_id=row['task'])
        reasons=snapshots.freshness(store,db,end)
        scope={'scopes':end['data']['scopes'],'excluded_paths':end['data']['excluded_paths'],
               'uninspected':[e for e in end['data']['files'].values() if e['status']!='captured'],
               'outside_scope':[],'attribution':'no_pre_development_comparison'}
    else:
        comparison = ps.get(db, data['comparison_id'], 'code_comparison', task_id=row['task'])
        expected = ps.get(db, comparison['data']['expectation_id'], 'expectation', task_id=row['task'])
        reasons = current_reasons(store, db, expected['data'])
        end = ps.get(db, comparison['data']['end_id'], 'code_snapshot', task_id=row['task'])
        reasons += snapshots.freshness(store, db, end)
        scope={k:comparison['data'][k] for k in ('scopes','excluded_paths','uninspected','outside_scope','attribution')}
        for segment in snapshots.baseline_chain(db, ps.get(db, comparison['data']['baseline_id'])):
            if snapshots.tombstoned(db, segment['id']): reasons.append('baseline_content_unavailable:' + segment['id'])
            else:
                for entry in segment['data']['files'].values():
                    if entry['status'] != 'captured': continue
                    try: snapshots.blob(store, segment, entry)
                    except (OSError, ValueError): reasons.append('baseline_content_unavailable:' + segment['id']); break
    findings = []
    if data.get('independent_review'):
        from .independent_review import session_state
        linked=data['independent_review']; independent=session_state(store,db,linked['id'],row['task'])
        if independent['revision']!=linked['revision'] or independent['validity']!='current':
            reasons.append('independent_review_changed_or_stale')
    for finding in data['findings']:
        expectation_text=[]
        scenario_title=None
        if finding.get('scenario'):
            ref=finding['scenario']
            scenario=ps.get(db,ref['id'],'scenario',ref['revision'],row['task'])
            scenario_title=scenario['data']['title']
            expectation_text=[b['text'] for b in scenario['data']['behaviors'] if b['behavior_id'] in finding.get('behavior_ids',[])]
        if finding.get('reference'):
            reference=finding['reference'];expectation_text=[reference['text']]
            source=reference['source']
            try:
                if source['kind']=='project':
                    from .task_context import source_state
                    if not source_state(store,source['source_id'])['current']:reasons.append('reference_changed:'+finding['finding_id'])
                elif source['kind']=='decision':ps.decision_ref(store,db,source)
            except (KeyError,OSError,ValueError):reasons.append('reference_changed:'+finding['finding_id'])
        checks = []
        for item in finding['evidence']:
            current = item.get('kind') != 'missing' and item.get('current', True)
            observation = item.get('observation')
            if observation and observation.get('scope_snapshot_id'):
                snapshot = ps.get(db, observation['scope_snapshot_id'], 'code_snapshot', task_id=row['task'])
                if snapshots.current_files(store, snapshot) != observation['code_state_after']: current = False
            if item.get('path'):
                try:
                    path = store.ledger.path(item['path'])
                    with path.open('rb') as stream: raw = stream.read(snapshots.FILE_LIMIT + 1)
                    current = current and hashlib.sha256(raw).hexdigest() == item['sha256']
                except (OSError, ValueError): current = False
            if not current and item['kind'] != 'missing': reasons.append('evidence_changed_or_unavailable:' + finding['finding_id'])
            checks.append({**item, 'current': current})
        feedback = [r for r in ps.objects(db, row['task'], 'product_feedback')
                    if r['data']['review_id'] == row['id'] and r['data']['finding_id'] == finding['finding_id']]
        last = feedback[-1] if feedback else None
        action = last['data']['action'] if last else None
        state = 'accepted' if action == 'accept_extra' else 'requirement_changed' if action == 'change_requirement' else 'deferred' if action == 'defer' else 'unresolved'
        supported = any(e.get('current') and e['strength'] in ('actual_code_or_file', 'test_execution_result', 'runtime_tool_observation') for e in checks)
        findings.append({**finding, 'evidence': checks, 'feedback': last,
                         'scenario_title':scenario_title,'expected_behavior':expectation_text,
                         'requires_followup': finding['judgment'] != 'possibly_matches' or not supported,
                         'resolution_state': state, 'feedback_revision': last['revision'] if last else 0})
    result={'id': row['id'], 'revision': row['revision'], 'task_id': row['task'], **data,
            'findings': findings, 'validity': 'needs_recheck' if reasons else 'current',
            'stale_reasons': sorted(set(reasons)), 'coverage_complete': False,
            'scope':scope}
    result['message']=render(result)
    result['presentation']={'preferred_surface':'conversation_markdown',
        'agent_action':'Show message as the primary nontechnical behavior feedback. Do not replace it with commands or a test count. '
                      'Use findings.evidence for technical detail only when requested.',
        'has_frozen_baseline':not supplement,'does_not_establish_full_correctness':True,
        'technical_details':'findings.evidence, findings.limits, scope and stale_reasons are on demand; do not append boilerplate.',
        'semantic_verified_by_program':False}
    return result


def execute(service, request):
    request = validate('review', request); action = request['action']; task_id = request['task_id']
    from . import independent_review as independent
    if action in independent.ACTIONS:
        return independent.execute(service, request)
    def handler(store, db, ctx):
        if action == 'status': return status(store, db, ps.get(db, request['review_id'], 'behavior_review', task_id=task_id))
        if action == 'supplement':
            end=ps.get(db,request['current_snapshot_id'],'code_snapshot',task_id=task_id)
            if end['data']['phase']!='current_review':raise ValueError('Supplement requires a current inspection, not a pre-development baseline')
            if snapshots.freshness(store,db,end):raise ValueError('Workspace changed since current inspection; inspect again')
            if not any(e['status']=='captured' for e in end['data']['files'].values()):raise ValueError('Current inspection has no captured files')
            if request.get('previous_review_id'):ps.get(db,request['previous_review_id'],'behavior_review',task_id=task_id)
            independent_link = independent.adoption(store,db,task_id,request,end['id'])
            findings=[];ids=[f['finding_id'] for f in request['findings']]
            if len(ids)!=len(set(ids)):raise ValueError('Duplicate finding identity')
            for finding_index, finding in enumerate(request['findings']):
                item=dict(finding)
                if finding.get('scenario') or finding.get('behavior_ids'):raise ValueError('Supplement does not adopt or freeze new expectation scenarios')
                if finding.get('change_origin') not in (None,'uncertain'):raise ValueError('Without an old comparison, change origin must remain uncertain')
                reference=finding.get('reference')
                if finding['judgment'] in ('possibly_matches','possibly_deviates') and not reference:
                    raise ValueError('Comparison judgment requires an actual reference; missing requirements are not a deviation')
                if reference:
                    from .experience import validate_source
                    source=validate_source(service,store,db,ctx,reference['source'],{'text':reference['text']},task_id)
                    if finding['judgment'] in ('possibly_matches','possibly_deviates') and source['kind'] not in ('user','decision','project'):
                        raise ValueError('Comparison requires an actual user, decision or project reference')
                    item['reference']={**reference,'source':source}
                item['evidence']=[evidence(store,db,task_id,e,f'findings[{finding_index}].evidence[{i}].quote') for i,e in enumerate(finding['evidence'])]
                for e in item['evidence']:
                    if not set(e.get('tested_behaviors',[]))<={finding['finding_id']}:raise ValueError('Supplement evidence coverage must name the actual finding')
                    if e.get('path') and end['data']['files'].get(e['path'],{}).get('status')!='captured':raise ValueError('Evidence is outside the inspected current files')
                findings.append(item)
            from .feedback_report import validate_content
            validate_content(request,findings)
            result=ps.put(store,db,task_id,'behavior_review',{'review_mode':'current',
                'current_snapshot_id':end['id'],'previous_review_id':request.get('previous_review_id'),
                'report':request['report'],'findings':findings,'independent_review':independent_link})
            return status(store,db,ps.get(db,result['id']))
        if action == 'create':
            comparison = ps.get(db, request['comparison_id'], 'code_comparison', task_id=task_id)
            expectation = ps.get(db, comparison['data']['expectation_id'], 'expectation', task_id=task_id)
            end = ps.get(db, comparison['data']['end_id'], 'code_snapshot', task_id=task_id)
            if snapshots.freshness(store, db, end): raise ValueError('Workspace changed since comparison; capture a new comparison')
            if request.get('previous_review_id'): ps.get(db, request['previous_review_id'], 'behavior_review', task_id=task_id)
            independent_link = independent.adoption(store,db,task_id,request,end['id'])
            ids = [f['finding_id'] for f in request['findings']]
            if len(ids) != len(set(ids)) or any(i.startswith('unverified-') for i in ids): raise ValueError('Duplicate or reserved finding identity')
            findings = []; covered = set()
            for finding_index, finding in enumerate(request['findings']):
                item = dict(finding)
                if finding.get('reference'):raise ValueError('Formal review uses the original frozen scenario, not a replacement reference')
                if finding['judgment'] != 'extra':
                    if 'scenario' not in finding or finding['scenario'] not in expectation['data']['scenarios']:
                        raise ValueError('Findings must reference the pre-development frozen scenario version')
                elif not finding.get('change_origin'): raise ValueError('Extra behaviors require an explicit change origin')
                if 'scenario' in finding:
                    if finding['scenario'] not in expectation['data']['scenarios']: raise ValueError('Scenario is outside frozen expectation')
                    scenario = ps.get(db, finding['scenario']['id'], 'scenario', finding['scenario']['revision'])
                    valid = {b['behavior_id'] for b in scenario['data']['behaviors']}
                    chosen = set(finding.get('behavior_ids', []))
                    if not chosen or not chosen <= valid: raise ValueError('Specify actual frozen behavior IDs covered by the finding')
                    covered |= {(scenario['id'], bid) for bid in chosen}
                else: chosen = set()
                item['evidence'] = [evidence(store,db,task_id,e,f'findings[{finding_index}].evidence[{i}].quote') for i,e in enumerate(finding['evidence'])]
                if any(not set(e.get('tested_behaviors', [])) <= chosen for e in item['evidence'] if finding['judgment'] != 'extra'):
                    raise ValueError('Evidence coverage references an unrelated behavior')
                if finding['judgment'] == 'possibly_matches' and not any(e['strength'] not in ('missing', 'llm_analysis_only') for e in item['evidence']):
                    item['evidence_note'] = '仅有分析或缺少证据，不能视为行为已验证。'
                if finding.get('change_origin') == 'observed_change':
                    paths = {e.get('path') for e in item['evidence']}
                    if not paths & {c['path'] for c in comparison['data']['changes']}:
                        raise ValueError('Observed change requires evidence in the actual changed file set')
                findings.append(item)
            # Never hide a frozen behavior merely because the Agent omitted it.
            for ref in expectation['data']['scenarios']:
                scenario = ps.get(db, ref['id'], 'scenario', ref['revision'])
                missing = [b['behavior_id'] for b in scenario['data']['behaviors'] if (ref['id'], b['behavior_id']) not in covered]
                if missing:
                    if 'report' in request:
                        from .feedback_report import fail
                        fail([{'field':'findings','rule':'cover_each_frozen_behavior','scenario':ref,'behavior_ids':missing}])
                    findings.append({'finding_id': 'unverified-' + ref['id'], 'scenario': ref, 'behavior_ids': missing,
                        'judgment': 'unknown', 'summary': scenario['data']['title'] + '：部分预期尚无检查记录。',
                        'importance': 'high', 'evidence': [{'kind': 'missing', 'note': '未提交相应检查依据', 'strength': 'missing', 'current': False}],
                        'limits': '未检查的行为：' + '、'.join(missing)})
            from .feedback_report import validate_content
            validate_content(request,findings)
            result = ps.put(store, db, task_id, 'behavior_review', {'comparison_id': comparison['id'],
                'expectation_id': expectation['id'], 'previous_review_id': request.get('previous_review_id'), 'findings': findings,
                'independent_review':independent_link,
                **({'report':request['report']} if 'report' in request else {})})
            return status(store, db, ps.get(db, result['id']))
        row = ps.get(db, request['review_id'], 'behavior_review', task_id=task_id)
        current = status(store, db, row)
        source = ps.user_source(ctx, request)
        by_id = {f['finding_id']: f for f in current['findings']}
        if len({f['finding_id'] for f in request['feedback']}) != len(request['feedback']): raise ValueError('Duplicate feedback target')
        saved = []
        for feedback in request['feedback']:
            finding = by_id.get(feedback['finding_id'])
            if finding is None: raise ValueError('Unknown finding')
            if finding['feedback_revision'] != feedback['expected_feedback_revision']: raise ValueError('Feedback version conflict')
            if feedback['action'] == 'accept_extra' and finding['judgment'] != 'extra': raise ValueError('Only concrete extra behavior can be accepted')
            if feedback['action'] == 'accept_extra' and current['validity'] != 'current':
                raise ValueError('Review is stale; inspect current behavior before accepting/changing requirements')
            if feedback['action'] == 'change_requirement':
                if 'decision' not in feedback or 'scenario' not in feedback: raise ValueError('Changed requirement needs a trusted decision and new scenario version')
                decision = ps.decision_ref(store, db, feedback['decision'])
                scenario = ps.get(db, feedback['scenario']['id'], 'scenario', feedback['scenario']['revision'], task_id)
                linked = scenario['data'].get('related_decisions', []) + [b['source'] for b in scenario['data']['behaviors'] if b['source']['kind'] == 'decision']
                if not any(d['decision_id'] == decision['decision_id'] and d['revision'] == decision['revision'] for d in linked):
                    raise ValueError('Revised scenario must link the actual changed decision')
                if feedback['scenario'] == finding.get('scenario'): raise ValueError('Requirement changes require a new scenario version')
            ident = 'feedback-' + row['id'] + '-' + feedback['finding_id']
            saved.append(ps.put(store, db, task_id, 'product_feedback', {'review_id': row['id'],
                **feedback, 'source': source, 'accepted_behavior': finding['summary'] if feedback['action'] == 'accept_extra' else None,
                'original_expectation_retained': True}, ident, feedback['expected_feedback_revision']))
        from .feedback_report import feedback_acknowledgment
        return {'recorded': True, 'feedback': saved, 'source': source,
                'message':feedback_acknowledgment(saved,by_id)}
    result = ps.run(service, request, handler)
    if action in ('create','supplement') and result.get('replayed'):
        store = service.store()
        with store.connect() as db:
            result = {**result, **status(store, db, ps.get(db, result['id'], 'behavior_review', task_id=task_id))}
    if action != 'status':
        from .experience import publish
        result['document'] = publish(service, task_id)
    from .product_workflow import progress
    return {**result,'workflow':progress(service.store(),task_id)}


JUDGMENT = {'possibly_matches': '可能符合预期', 'possibly_deviates': '可能偏离预期', 'extra': '额外产品行为', 'unknown': '无法判断'}
STRENGTH = {'llm_analysis_only': '仅有 LLM 分析', 'actual_code_or_file': '有实际代码或文件依据',
    'test_execution_result': '有实际工具执行返回，测试含义与覆盖由 Agent 解释',
    'runtime_tool_observation': '有实际工具观察，限所记录的操作范围',
    'report_file_execution_unverified': '有报告文件，执行过程未核验', 'missing': '缺少证据'}
ORIGIN = {'observed_change': '本次范围内确实观察到变化，不能归因于单一修改者',
          'preexisting': '原有行为，是否早已存在由 Agent 结合起点内容判断', 'uncertain': '无法确定是否由本次任务引入'}


def render(review):
    from .feedback_report import render as render_feedback
    return render_feedback(review)
