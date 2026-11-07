"""Structural progress hints only: no keyword-based intent classification or approval inference."""

from .guidance import WORKFLOW_COMPLETION


def progress(store, task_id):
    base = {'mode': 'standard', 'stage': 'not_enabled', 'frozen_expectation': False,
            'code_baseline': False, 'before_after_review_available': False,
            'completion_rule': WORKFLOW_COMPLETION}
    with store.connect() as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='product_tasks'").fetchone(): return base
        task = db.execute('SELECT enabled FROM product_tasks WHERE task=?', (task_id,)).fetchone()
        if task is None: return base
        from .product_store import objects
        scenes = objects(db, task_id, 'scenario')
        expected = objects(db, task_id, 'expectation')
        snapshots = objects(db, task_id, 'code_snapshot')
        comparisons = objects(db, task_id, 'code_comparison')
        reviews = objects(db, task_id, 'behavior_review')
        expectation = expected[-1] if expected else None
        versions={s['id']:s['revision'] for s in scenes}
        expectation_current=bool(expectation) and all(versions.get(r['id'])==r['revision'] for r in expectation['data']['scenarios'])
        start = [s for s in snapshots if s['data']['phase'] in ('start', 'extension') and
                 expectation and s['data']['expectation_id'] == expectation['id']]
        current_comparisons = [c for c in comparisons if expectation and c['data']['expectation_id'] == expectation['id']]
        current_reviews = [r for r in reviews if expectation and r['data'].get('expectation_id') == expectation['id']]
        intents=objects(db,task_id,'workflow_intent')
        feedback_task=bool(intents and intents[-1]['data']['purpose']=='feedback')
        inspections=[s for s in snapshots if s['data']['phase']=='current_review']
        supplements=[r for r in reviews if r['data'].get('review_mode')=='current']
        stage, action = 'needs_scenarios', 'experience save, then present'
        if scenes: stage, action = 'needs_expectation_review', 'present full scenarios; record the real reply; freeze the adopted version'
        if expected: stage, action = 'needs_code_baseline', 'snapshot capture BEFORE the first source edit'
        if start: stage, action = 'ready_for_implementation', 'implement, run relevant checks, then snapshot compare'
        if current_comparisons: stage, action = 'needs_behavior_review', 'behavior_review create, then show its nontechnical message'
        if current_reviews: stage, action = 'review_recorded', 'check freshness, show the nontechnical review and unresolved feedback'
        if expectation and not expectation_current:
            stage,action='needs_expectation_review','present the revised scenarios and freeze a new adopted version; retain the old baseline'
        if feedback_task and not start and not comparisons:
            stage,action='needs_current_inspection','inspect current files, check relevant operations, then behavior_review supplement; do not create new expectations'
        elif feedback_task and start and not current_comparisons:
            stage,action='needs_behavior_review','compare the original saved baseline, then create behavior feedback'
        if inspections:
            stage,action='needs_current_behavior_review','check current operations and create behavior_review supplement using this inspection'
            if any(r['data']['current_snapshot_id']==inspections[-1]['id'] for r in supplements):
                stage,action='current_review_recorded','show concise current-behavior feedback; accept natural-language feedback without new expectation approval'
        review_policy=intents[-1]['data'].get('review_policy','standard') if intents else 'standard'
        if review_policy=='independent' and stage in ('needs_behavior_review','needs_current_behavior_review'):
            from .independent_review import session_state
            target=inspections[-1]['id'] if inspections else current_comparisons[-1]['data']['end_id'] if current_comparisons else None
            packets=[p for p in objects(db,task_id,'review_packet') if p['data']['snapshot_id']==target]
            sessions=[r for r in objects(db,task_id,'independent_review') if any(p['id']==r['data']['packet_id'] for p in packets)]
            stage,action='needs_independent_packet','prepare_independent with original sourced goals, scoped constraints and current deliverable sections'
            if packets: stage,action='needs_independent_reviewer','host spawn_agent fork_turns=none, inherited model; send only payload and submit actual reviewer output'
            if sessions:
                state=session_state(store,db,sessions[-1]['id'],task_id)
                if state['validity']=='current':
                    stage,action='needs_review_adoption','include or explain exclusion of each issue in behavior_review create/supplement'
                    if state['questions']:stage,action='needs_targeted_background','answer concrete pending questions with sourced facts; do not supply full chat history'
                    if any(b['review_revision']==state['revision'] for b in state['backgrounds']):
                        stage,action='needs_reviewer_reconsideration','follow up with the same reviewer; record explicit issue dispositions and reasons'
                else:stage,action='needs_independent_packet','materials changed; inspect again and prepare a new packet'
        if not task['enabled']: stage, action = 'closed', 'reuse history; enable explicitly to continue this product workflow'
        return {**base, 'mode': 'product_review', 'stage': stage, 'next_action': action,
                'review_policy':review_policy,
                'frozen_expectation': bool(expected), 'code_baseline': bool(start),
                'adopted_expectation_current':expectation_current,
                'before_after_review_available': bool(current_reviews),
                'review_ids': [r['id'] for r in current_reviews+supplements],
                'current_inspection':bool(inspections),'current_review_available':bool(supplements)}


from .guidance import CONTEXT_GUIDANCE as CONVERSATION_GUIDANCE
