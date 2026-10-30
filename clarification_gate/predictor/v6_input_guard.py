"""Conservative CLI boundary checks; not evidence-semantic verification."""
import re
from clarification_gate.predictor.evidence_fields_v6 import public_pairs


def validate_cli_input(given):
    keys={'task','conversation','evidence','available_resources','inspection_log'}
    if not isinstance(given,dict) or set(given)!=keys:
        raise ValueError('Unsupported snapshot keys or container')
    if not isinstance(given['task'],str) or not given['task'].strip():
        raise ValueError('Task must be nonempty text')
    for name in ('conversation','evidence','available_resources','inspection_log'):
        if not isinstance(given[name],list):raise ValueError('Snapshot containers must be lists')
    if any(not isinstance(e,dict) or not isinstance(e.get('source_id'),str) or not isinstance(e.get('content'),str) for e in given['evidence']):
        raise ValueError('Evidence must contain text with explicit source IDs')
    ids=[e['source_id'] for e in given['evidence']]
    if len(ids)!=len(set(ids)):raise ValueError('Duplicate evidence IDs are unsupported')
    evidence={e['source_id']:e['content'] for e in given['evidence']}
    if 'e3' in evidence and given['conversation']:
        raise ValueError('Inventory prototype has no conversation reconciliation; supply a reviewed current snapshot')
    if 'e3' in evidence and given['inspection_log']:
        raise ValueError('Inventory prototype has no inspection-log reconciliation')
    if len(given['available_resources'])>1:
        raise ValueError('Multiple resources are outside the controlled prototype')
    for resource in given['available_resources']:
        if not isinstance(resource,dict) or resource.get('resource_id')!='r1':
            raise ValueError('Resource identity is outside the controlled prototype')
        locator=resource.get('locator')
        if not isinstance(locator,str) or not locator:
            raise ValueError('Resource locator is required')
        if resource.get('read_state') not in ('read','unread'):
            raise ValueError('Unknown resource read state')
        if resource.get('read_state')=='unread':
            token=r'(?<![A-Za-z0-9_./\\-])'+re.escape(locator)+r'(?![A-Za-z0-9_/\\-]|\.[A-Za-z0-9_])'
            if not re.search(token,evidence.get('e2','')):
                raise ValueError('Unread resource locator does not match its public index')
    public_pairs(given)
