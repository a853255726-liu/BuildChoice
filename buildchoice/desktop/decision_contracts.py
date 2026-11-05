"""Versioned V3 wire contracts. This module never infers authorization."""
import json
from copy import deepcopy
from pathlib import Path
from jsonschema import Draft202012Validator, ValidationError

SCHEMA_PATH = Path(__file__).resolve().parents[2] / 'docs/contracts/decision-v3.schema.json'
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding='utf-8'))


def validate_options(options, recommended):
    ids=[option['id'] for option in options]
    if len(ids)!=len(set(ids)):raise ValueError('Duplicate option ID')
    if recommended is not None and recommended not in ids:
        raise ValueError('Recommendation is not an offered option')
    keys=[option['option_key'] for option in options if option.get('option_key')]
    if len(keys)!=len(set(keys)):raise ValueError('Duplicate stable option key')


def validate(kind, value):
    if kind in ('Candidate','ScreenRequest'):
        value=deepcopy(value)
        if kind=='ScreenRequest' and isinstance(value,dict):value.setdefault('phase','unspecified')
        candidates=[value] if kind=='Candidate' else value.get('candidates',[])
        for candidate in candidates:
            if isinstance(candidate,dict):
                for name,default in {'risk_flags':[],
                    'evidence_refs':[],'recommended_option_id':None,'recommendation_reason':''}.items():
                    candidate.setdefault(name,default)
    try:Draft202012Validator({**SCHEMA, '$ref': '#/$defs/' + kind}).validate(value)
    except ValidationError as error:
        path='.'.join(map(str,error.absolute_path)) or kind
        raise ValueError(json.dumps({'code':'INVALID_CONTRACT','field':path,
            'message':error.message[:350],'expected':error.validator_value if error.validator in ('enum','required','type') else error.validator},
            ensure_ascii=False)) from None
    if kind=='Candidate':validate_options(value['options'],value['recommended_option_id'])
    if kind=='Card':validate_options(value['options'],value['recommendation']['option_id'] if value['recommendation'] else None)
    if kind == 'ScreenRequest':
        if value.get('suggested_action')=='ASK_NOW' and not value['candidates']:
            raise ValueError('ASK_NOW requires a candidate with offered options')
        ids = [c['candidate_id'] for c in value['candidates']]
        if len(ids) != len(set(ids)):
            raise ValueError('Duplicate request-local candidate ID')
        dimensions=[entry['dimension'] for entry in value.get('coverage',[])]
        if len(dimensions)!=len(set(dimensions)):
            raise ValueError('Duplicate coverage dimension')
        for entry in value.get('coverage',[]):
            if not set(entry.get('candidate_ids',[]))<=set(ids):
                raise ValueError('Coverage references an unknown request-local candidate')
        for candidate in value['candidates']:
            validate_options(candidate['options'],candidate['recommended_option_id'])
    return value


def input_schema(kind):
    """Advertise the existing contract with only its reachable definitions."""
    needed={kind};pending=[kind]
    def references(value):
        if isinstance(value,dict):
            if '$ref' in value:yield value['$ref'].rsplit('/',1)[-1]
            for child in value.values():yield from references(child)
        elif isinstance(value,list):
            for child in value:yield from references(child)
    while pending:
        for reference in references(SCHEMA['$defs'][pending.pop()]):
            if reference not in needed:needed.add(reference);pending.append(reference)
    definitions={key:deepcopy(SCHEMA['$defs'][key]) for key in sorted(needed)}
    if kind=='ScreenRequest':
        # Stage is archival metadata, not a business judgment or model input requirement.
        definitions[kind]['properties'].pop('phase',None)
    return {'$ref':'#/$defs/'+kind,'$defs':definitions}
