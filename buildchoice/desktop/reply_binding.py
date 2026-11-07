"""Actionable binding failures without accepting an unobserved user message."""
import json
import time


class ReplyBindingError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)

    def result(self):
        return {
            'schema_version': 'reply-binding.v1', 'status': 'unbound',
            'recorded': False, 'code': self.code, 'message': str(self),
            'recovery': {
                'action': 'wait_for_current_hook_context',
                'retry_with_same_handle': False,
                'switch_recording_interface': False,
                'guidance': 'The supplied handle does not prove the new reply. Read the fresh Hook context. '
                            'If a native async answer has no fresh handle, keep its ledger status unrecorded. '
                            'Explain once; request one ordinary chat message only if saving the decision is required. '
                            'Do not redisplay the card, synthesize a Hook event, or relax source checks.'},
            'does_not_authorize_host_operations': True}


def binding_state(context, active=None):
    """Only describe stored source readiness; never infer the user's intention."""
    outcome = json.loads(context['outcome_json'])
    reply = outcome.get('_reply')
    status = outcome.get('confirmation_status', 'none')
    confirmed = status in ('user_message_observed', 'llm_interpreted_user_reply',
                           'llm_interpreted_user_instruction')
    live = bool(active and active['decision_id'] and active['expires'] >= time.time())
    matching = bool(live and reply and
                    (reply['decision_id'], reply['revision']) ==
                    (active['decision_id'], active['revision']))
    ready = matching and status == 'awaiting_user'
    state = ('already_recorded' if confirmed else 'ready_to_interpret' if ready else
             'awaiting_new_hook_message' if live and not reply else 'no_current_pending_reply')
    return {'status': state, 'can_interpret_reply': bool(ready),
            'retry_interpret_with_this_handle': bool(ready),
            'next_action': ('reuse_recorded_choice' if confirmed else 'interpret_actual_reply' if ready else
                            'wait_for_fresh_hook_context' if live else 'inspect_current_card'),
            'native_async_reply_requires_fresh_hook': True}


def recording_result(action):
    """MCP boundary: expected source gaps are structured recovery results, never success."""
    try:
        return action()
    except ReplyBindingError as error:
        return error.result()
