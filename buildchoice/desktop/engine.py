"""Revision-aware advisory policy. Model results never authorize tool execution."""
import threading
from collections import OrderedDict
from copy import deepcopy
from jsonschema import ValidationError
from buildchoice.desktop.common import digest
from buildchoice.desktop.contracts import validate_request, ASSESSMENT, RESPONSE
from buildchoice.backends.base import UnsupportedInput


class BuildChoiceEngine:
    def __init__(self, backend, policy_version='field-policy-v1'):
        self.backend = backend
        self.reference = backend.reference
        self.policy_version = policy_version
        self.lock = threading.Lock()
        self.revisions = OrderedDict()
        self.cache = OrderedDict()

    def failure(self, request, status, reason):
        return self.response(request, status, None, {
            'status': status if status != 'STALE' else 'UNSUPPORTED', 'backend': self.reference,
            'kind': 'none', 'field_states': None, 'action_advice': None,
            'score_semantics': 'none', 'reason_codes': [reason]}, [reason])

    def response(self, request, status, action, assessment, reasons):
        s = request.get('snapshot', {})
        ctx = request.get('context', {})
        states = assessment.get('field_states')
        missing = sorted(set(states['required']) - set(states['resolved'])) if states else []
        resources = [r['resource_id'] for r in s.get('resources', [])
                     if r['read_state'] == 'unread'] if action == 'INSPECT' else []
        names = {c['field_id']: c['name'] for c in s.get('candidates', [])}
        hint = ('请确认当前有效取值：' + '、'.join(names[f] for f in missing))[:1000] if action == 'ASK' else None
        result = {'schema_version': 'buildchoice.v1', 'request_id': request['request_id'],
                  'snapshot_id': s['snapshot_id'], 'revision': ctx['revision'],
                  'mode': 'advisory', 'status': status, 'action': action, 'effect': 'suggest_only',
                  'backend': self.reference, 'assessment': assessment,
                  'next_step': {'missing_fields': missing, 'inspect_resource_ids': resources,
                                'question_hint': hint},
                  'policy_version': self.policy_version, 'reason_codes': reasons, 'task_executed': False}
        RESPONSE.validate(result)
        return result

    @staticmethod
    def bounded_put(mapping, key, value):
        mapping[key] = value
        mapping.move_to_end(key)
        while len(mapping) > 512:
            mapping.popitem(last=False)

    def evaluate(self, request):
        # Shape-invalid requests are rejected by transport with HTTP 400, not treated as assessments.
        from buildchoice.desktop.contracts import REQUEST
        REQUEST.validate(request)
        try:
            validate_request(request)
        except (ValueError, ValidationError):
            return self.failure(request, 'UNSUPPORTED', 'INVALID_SNAPSHOT_INTEGRITY')
        with self.lock:
            ctx = request['context']
            key = (ctx['host_session_id'], ctx.get('agent_id'), ctx['context_handle'])
            cache_key = (ctx['host_session_id'], request['request_id'])
            fingerprint = digest(request)
            old = self.revisions.get(key)
            if old and (ctx['revision'] < old[0] or
                        (ctx['revision'] == old[0] and request['snapshot']['snapshot_sha256'] != old[1])):
                return self.failure(request, 'STALE', 'STALE_OR_CONFLICTING_REVISION')
            if cache_key in self.cache:
                old_hash, result = self.cache[cache_key]
                if old_hash != fingerprint:
                    return self.failure(request, 'STALE', 'REQUEST_ID_REUSED_WITH_DIFFERENT_CONTENT')
                return deepcopy(result)
            self.bounded_put(self.revisions, key, (ctx['revision'], request['snapshot']['snapshot_sha256']))
            try:
                assessment = self.backend.assess(request['snapshot'])
                ASSESSMENT.validate(assessment)
                if assessment['backend'] != self.reference:
                    raise ValueError('BACKEND_REFERENCE_MISMATCH')
                if assessment['status'] != 'OK':
                    result = self.response(request, assessment['status'], None, assessment,
                                           assessment['reason_codes'])
                else:
                    states = assessment['field_states']
                    if states is None:
                        action = assessment['action_advice']
                    else:
                        candidates = {c['field_id'] for c in request['snapshot']['candidates']}
                        if any(not set(v) <= candidates for v in states.values()):
                            raise ValueError('MODEL_RETURNED_UNKNOWN_FIELD')
                        unread = any(r['read_state'] == 'unread' for r in request['snapshot']['resources'])
                        action = compose(states, unread)
                    result = self.response(request, 'OK', action, assessment,
                                           ['ADVISORY_ONLY', 'COVERAGE_NOT_INDEPENDENTLY_VERIFIED'])
            except UnsupportedInput:
                result = self.failure(request, 'UNSUPPORTED', 'BACKEND_INPUT_OUT_OF_SCOPE')
            except Exception:
                # Logs and responses intentionally omit supplied evidence and arbitrary exception text.
                import logging
                logging.getLogger(__name__).error('Backend assessment failed', exc_info=False)
                result = self.failure(request, 'ERROR', 'BACKEND_INFERENCE_FAILED')
            self.bounded_put(self.cache, cache_key, (fingerprint, deepcopy(result)))
            return result


def compose(states, unread):
    missing = set(states['required']) - set(states['resolved'])
    return ('PASS' if not missing else 'INSPECT'
            if unread and missing & set(states['indexed']) else 'ASK')
