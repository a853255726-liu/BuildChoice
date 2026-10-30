"""Versioned V3 wire contracts. This module never infers authorization."""
import json
from pathlib import Path
from jsonschema import Draft202012Validator

SCHEMA_PATH = Path(__file__).resolve().parents[2] / 'docs/contracts/decision-v3.schema.json'
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding='utf-8'))


def validate(kind, value):
    Draft202012Validator({**SCHEMA, '$ref': '#/$defs/' + kind}).validate(value)
    if kind == 'ScreenRequest':
        ids = [c['candidate_id'] for c in value['candidates']]
        if len(ids) != len(set(ids)):
            raise ValueError('Duplicate request-local candidate ID')
        for candidate in value['candidates']:
            options = [o['id'] for o in candidate['options']]
            if len(options) != len(set(options)):
                raise ValueError('Duplicate option ID')
            if candidate['recommended_option_id'] is not None and candidate['recommended_option_id'] not in options:
                raise ValueError('Recommendation is not an offered option')
    return value
