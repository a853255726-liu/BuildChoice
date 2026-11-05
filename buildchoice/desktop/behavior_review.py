"""Behavior judgments and independently recorded evidence strength, never certification."""
import hashlib
from . import product_store as ps
from .product_contracts import validate
from . import workspace_snapshot as snapshots


def evidence(store, db, task_id, given):
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
        if 'quote' not in given or given['quote'] not in '\n'.join(lines[start - 1:end]): raise ValueError('Exact evidence quote is required in the cited lines')
        result.update(sha256=hashlib.sha256(raw).hexdigest(), start_line=start, end_line=end)
    elif not given.get('observation_id'): raise ValueError('File/test/runtime evidence requires a real file or observed tool result')
    if kind in ('test', 'runtime') and (not given.get('limits') or not given.get('tested_behaviors')):
        raise ValueError('Executed/reported checks require explicit behavior coverage and limits')
    return result


def status(store, db, row):
    from .experience import current_reasons
    data = row['data']; comparison = ps.get(db, data['comparison_id'], 'code_comparison', task_id=row['task'])
    expected = ps.get(db, comparison['data']['expectation_id'], 'expectation', task_id=row['task'])
    reasons = current_reasons(store, db, expected['data'])
    end = ps.get(db, comparison['data']['end_id'], 'code_snapshot', task_id=row['task'])
    reasons += snapshots.freshness(store, db, end)
    for segment in snapshots.baseline_chain(db, ps.get(db, comparison['data']['baseline_id'])):
        if snapshots.tombstoned(db, segment['id']): reasons.append('baseline_content_unavailable:' + segment['id'])
        else:
            for entry in segment['data']['files'].values():
                if entry['status'] != 'captured': continue
                try: snapshots.blob(store, segment, entry)
                except (OSError, ValueError): reasons.append('baseline_content_unavailable:' + segment['id']); break
    findings = []
    for finding in data['findings']:
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
                         'requires_followup': finding['judgment'] != 'possibly_matches' or not supported,
                         'resolution_state': state, 'feedback_revision': last['revision'] if last else 0})
    return {'id': row['id'], 'revision': row['revision'], 'task_id': row['task'], **data,
            'findings': findings, 'validity': 'needs_recheck' if reasons else 'current',
            'stale_reasons': sorted(set(reasons)), 'coverage_complete': False,
            'scope': {k: comparison['data'][k] for k in ('scopes', 'excluded_paths', 'uninspected', 'outside_scope', 'attribution')}}


def execute(service, request):
    request = validate('review', request); action = request['action']; task_id = request['task_id']
    def handler(store, db, ctx):
        if action == 'status': return status(store, db, ps.get(db, request['review_id'], 'behavior_review', task_id=task_id))
        if action == 'create':
            comparison = ps.get(db, request['comparison_id'], 'code_comparison', task_id=task_id)
            expectation = ps.get(db, comparison['data']['expectation_id'], 'expectation', task_id=task_id)
            end = ps.get(db, comparison['data']['end_id'], 'code_snapshot', task_id=task_id)
            if snapshots.freshness(store, db, end): raise ValueError('Workspace changed since comparison; capture a new comparison')
            if request.get('previous_review_id'): ps.get(db, request['previous_review_id'], 'behavior_review', task_id=task_id)
            ids = [f['finding_id'] for f in request['findings']]
            if len(ids) != len(set(ids)) or any(i.startswith('unverified-') for i in ids): raise ValueError('Duplicate or reserved finding identity')
            findings = []; covered = set()
            for finding in request['findings']:
                item = dict(finding)
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
                item['evidence'] = [evidence(store, db, task_id, e) for e in finding['evidence']]
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
                    findings.append({'finding_id': 'unverified-' + ref['id'], 'scenario': ref, 'behavior_ids': missing,
                        'judgment': 'unknown', 'summary': scenario['data']['title'] + '：部分预期尚无检查记录。',
                        'importance': 'high', 'evidence': [{'kind': 'missing', 'note': '未提交相应检查依据', 'strength': 'missing', 'current': False}],
                        'limits': '未检查的行为：' + '、'.join(missing)})
            result = ps.put(store, db, task_id, 'behavior_review', {'comparison_id': comparison['id'],
                'expectation_id': expectation['id'], 'previous_review_id': request.get('previous_review_id'), 'findings': findings})
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
        return {'recorded': True, 'feedback': saved, 'source': source}
    result = ps.run(service, request, handler)
    if action == 'create' and result.get('replayed'):
        store = service.store()
        with store.connect() as db:
            result = {**result, **status(store, db, ps.get(db, result['id'], 'behavior_review', task_id=task_id))}
    if action != 'status':
        from .experience import publish
        result['document'] = publish(service, task_id)
    return result


JUDGMENT = {'possibly_matches': '可能符合预期', 'possibly_deviates': '可能偏离预期', 'extra': '额外产品行为', 'unknown': '无法判断'}
STRENGTH = {'llm_analysis_only': '仅有 LLM 分析', 'actual_code_or_file': '有实际代码或文件依据',
    'test_execution_result': '有实际工具执行返回，测试含义与覆盖由 Agent 解释',
    'runtime_tool_observation': '有实际工具观察，限所记录的操作范围',
    'report_file_execution_unverified': '有报告文件，执行过程未核验', 'missing': '缺少证据'}
ORIGIN = {'observed_change': '本次范围内确实观察到变化，不能归因于单一修改者',
          'preexisting': '原有行为，是否早已存在由 Agent 结合起点内容判断', 'uncertain': '无法确定是否由本次任务引入'}


def render(review):
    lines = ['## 产品行为审阅', '', '状态：' + ('需要重新检查' if review['validity'] != 'current' else '当前检查记录'),
             '结论限于记录的检查范围，不能证明所有路径均正确。', '']
    if review['stale_reasons']: lines += ['需复核原因：' + '；'.join(review['stale_reasons']), '']
    order = {'possibly_deviates': 0, 'extra': 1, 'unknown': 2, 'possibly_matches': 3}
    for finding in sorted(review['findings'], key=lambda f: (order[f['judgment']], f['importance'] != 'high')):
        lines += ['- ' + JUDGMENT[finding['judgment']] + '：' + finding['summary']]
        if finding.get('change_origin'): lines += ['  来源判断：' + ORIGIN[finding['change_origin']]]
        if not finding['evidence']: lines += ['  缺少检查证据。']
        for e in finding['evidence']:
            lines += ['  证据：' + STRENGTH[e['strength']] + ('（已过期或不可用）' if not e.get('current', True) else '') + '；' + e['note']]
            if e.get('path'): lines += ['  依据：' + e['path'] + ':' + str(e.get('start_line', 1))]
            if e.get('observation_id'): lines += ['  工具执行记录：' + e['observation_id']]
        labels = {'unresolved': '待处理', 'deferred': '已暂缓，仍待处理', 'accepted': '已接受具体额外行为',
                  'requirement_changed': '已修改要求，保留原审阅'}
        lines += ['  检查限制：' + finding['limits'], '  处理状态：' + labels[finding['resolution_state']]]
    scope = review['scope']
    lines += ['', '实际检查范围：' + '、'.join(scope['scopes']), '范围外内容未检查；排除/无法检查项：' + str(len(scope['uninspected']))]
    return '\n'.join(lines)
