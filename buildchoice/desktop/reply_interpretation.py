"""Bind an LLM's interpretation to an actual pending user message and card version."""
import json
import time
import uuid
from .audit import now
from .decision_store import fingerprint
from .reply_binding import ReplyBindingError


PROVENANCE='llm_interpreted_user_reply'


def interpret(store, task, owner, handle, decision_id, revision, choice_id, quote, reason):
    if type(revision) is not int or revision<1:raise ValueError('Valid revision required')
    if not isinstance(quote,str) or not 2<=len(quote)<=2000:raise ValueError('Exact user-message quote required')
    if not isinstance(reason,str) or not reason.strip() or len(reason)>1000:raise ValueError('Interpretation reason required')
    with store.connect() as db:
        store.begin(db)
        ctx=store.context(db,handle,owner,claim=True)
        if ctx is None or task['binding_status']!='hook_observed' or ctx['host_session_digest']!=task['host_session_digest']:
            raise ValueError('Current observed user-message context required')
        outcome=json.loads(ctx['outcome_json']);reply=outcome.get('_reply')
        if not reply or (reply['decision_id'],reply['revision'])!=(decision_id,revision):
            raise ReplyBindingError('NO_OBSERVED_REPLY', 'No matching pending user reply in this context')
        if quote not in reply['text']:raise ValueError('Quote is not present in the actual user reply')
        latest=db.execute('SELECT max(revision) FROM decision_v3_items WHERE id=?',(decision_id,)).fetchone()[0]
        if latest!=revision:raise ValueError('Reply interpretation belongs to an old decision revision')
        prior=db.execute('SELECT * FROM decision_v3_confirmations WHERE decision_id=? AND revision=?',(decision_id,revision)).fetchone()
        if prior:
            if (prior['provenance'],prior['host_turn_digest'],prior['choice_id'])!=(PROVENANCE,ctx['host_turn_digest'],choice_id):
                raise ValueError('Reply interpretation conflicts with an existing recorded choice')
            return {'confirmation':dict(prior),'replayed':True,'semantic_verified_by_program':False,
                'does_not_authorize_host_operations':True}
        row=db.execute('SELECT * FROM decision_v3_items WHERE task_id=? AND id=? AND revision=?',(task['id'],decision_id,revision)).fetchone()
        active=db.execute('SELECT * FROM decision_v3_active WHERE workspace=? AND host_session_digest=?',
            (str(store.workspace),ctx['host_session_digest'])).fetchone()
        if (row is None or latest!=revision or active is None or
                (active['decision_id'],active['revision'])!=(decision_id,revision) or active['expires']<time.time()):
            raise ValueError('Pending card is expired, changed or belongs to another task')
        card=json.loads(row['routing_json'])['card']
        if fingerprint(card)!=reply['card_digest'] or choice_id not in {o['id'] for o in card['options']}:
            raise ValueError('Card or selected option changed since the user message')
        ident='conf-'+uuid.uuid4().hex
        db.execute('INSERT INTO decision_v3_confirmations VALUES(?,?,?,?,?,?,?,?)',
            (ident,decision_id,revision,choice_id,PROVENANCE,ctx['host_turn_digest'],reply['message_digest'],now()))
        db.execute("UPDATE decision_v3_items SET state='confirmed' WHERE id=? AND revision=?",(decision_id,revision))
        db.execute('UPDATE decision_v3_active SET decision_id=NULL,revision=NULL WHERE workspace=? AND host_session_digest=?',
            (str(store.workspace),ctx['host_session_digest']))
        evidence={'decision_id':decision_id,'revision':revision,'choice_id':choice_id,'quote':quote,'reason':reason,
            'message_digest':reply['message_digest'],'provenance':PROVENANCE,'semantic_verified_by_program':False}
        store.event(db,task['id'],'USER_REPLY_INTERPRETED',evidence)
        outcome.update(confirmation_status=PROVENANCE,decision_id=decision_id,revision=revision,choice_id=choice_id)
        db.execute('UPDATE decision_v3_contexts SET outcome_json=? WHERE handle=?',(json.dumps(outcome,ensure_ascii=False),handle))
        # A repeat uses the same frozen source; no second confirmation or user action is created.
        confirmation=dict(db.execute('SELECT * FROM decision_v3_confirmations WHERE id=?',(ident,)).fetchone())
        return {'confirmation':confirmation,'interpretation':evidence,'replayed':False,'semantic_verified_by_program':False,
            'does_not_authorize_host_operations':True}
