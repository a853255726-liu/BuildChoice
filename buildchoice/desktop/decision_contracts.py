"""Versioned V3 wire contracts. This module never infers authorization."""
import json
from pathlib import Path
from jsonschema import Draft202012Validator

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
    Draft202012Validator({**SCHEMA, '$ref': '#/$defs/' + kind}).validate(value)
    if kind=='Candidate':validate_options(value['options'],value['recommended_option_id'])
    if kind=='Card':validate_options(value['options'],value['recommendation']['option_id'] if value['recommendation'] else None)
    if kind == 'ScreenRequest':
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
