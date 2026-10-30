import hashlib
import json
from jsonschema import Draft202012Validator
from clarification_gate.desktop.common import ROOT, digest

SCHEMA = json.loads((ROOT / 'docs/contracts/gate-v1.schema.json').read_text(encoding='utf-8'))


def validator(kind):
    return Draft202012Validator({**SCHEMA, '$ref': '#/$defs/' + kind})


REQUEST = validator('Request')
ASSESSMENT = validator('Assessment')
RESPONSE = validator('Response')


def validate_request(request):
    REQUEST.validate(request)
    s = request['snapshot']
    if digest({k: v for k, v in s.items() if k != 'snapshot_sha256'}) != s['snapshot_sha256']:
        raise ValueError('SNAPSHOT_HASH_MISMATCH')
    for e in s['evidence']:
        if hashlib.sha256(e['content'].encode()).hexdigest() != e['content_sha256']:
            raise ValueError('EVIDENCE_HASH_MISMATCH')
    for items, key in [(s['candidates'], 'field_id'), (s['resources'], 'resource_id'),
                       (s['evidence'], 'evidence_id'), (s['messages'], 'message_id')]:
        ids = [x[key] for x in items]
        if len(ids) != len(set(ids)):
            raise ValueError('DUPLICATE_IDENTIFIERS')
    fields = {x['field_id'] for x in s['candidates']}
    resources = {x['resource_id'] for x in s['resources']}
    for r in s['resources']:
        if not set(r['indexed_fields']) <= fields:
            raise ValueError('UNKNOWN_INDEXED_FIELD')
    for e in s['evidence']:
        if e['resource_id'] is not None and e['resource_id'] not in resources:
            raise ValueError('UNKNOWN_EVIDENCE_RESOURCE')


def build_request(task, candidates, current_evidence, resource_index='', unread_resource=None,
                  host_session_id='local-client', context_handle=None, revision=1, request_id=None):
    """Convenience projection; completeness is declared, never verified by caller."""
    import uuid
    names = list(candidates)
    snapshot = {
        'snapshot_id': uuid.uuid4().hex, 'task': {'text': task, 'origin': 'user_message'},
        'messages': [],
        'evidence': [dict(evidence_id=k, origin='supplied_context', content=value,
                          content_sha256=hashlib.sha256(value.encode()).hexdigest(), resource_id=None)
                     for k, value in [('e1', current_evidence), ('e2', resource_index)]],
        'resources': ([dict(resource_id='r1', locator=unread_resource, read_state='unread',
                            indexed_fields=[])] if unread_resource else []),
        'candidates': [dict(field_id='f' + str(i + 1), name=name, origin='agent_inferred')
                       for i, name in enumerate(names)],
        'candidate_coverage': 'declared',
    }
    snapshot['snapshot_sha256'] = digest(snapshot)
    return {'schema_version': 'gate.v1', 'request_id': request_id or uuid.uuid4().hex,
            'context': {'host_session_id': host_session_id, 'turn_id': context_handle or snapshot['snapshot_id'],
                        'context_handle': context_handle or snapshot['snapshot_id'], 'revision': revision},
            'snapshot': snapshot, 'event': 'manual_evaluate'}
