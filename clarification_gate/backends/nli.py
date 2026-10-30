"""Real local FP32 NLI + LoRA inference. No simulated backend or truncation."""
import gc
import json
from clarification_gate.desktop.common import ROOT, file_sha, local_path
from clarification_gate.backends.base import UnsupportedInput

KINDS = ('required', 'resolved', 'indexed')


def project(snapshot):
    if snapshot['messages']:
        raise UnsupportedInput('Conversation reconciliation is not supported; provide a current snapshot')
    fields = snapshot['candidates']
    names = [c['name'] for c in fields]
    if len(fields) not in (2, 3) or len(set(x.casefold() for x in names)) != len(names):
        raise UnsupportedInput('Exactly two or three distinct candidate names are required')
    if any(' || ' in x or '\n' in x or '\r' in x for x in names):
        raise UnsupportedInput('Candidate names cannot contain inventory delimiters')
    evidence = {e['evidence_id']: e for e in snapshot['evidence']}
    if set(evidence) != {'e1', 'e2'}:
        raise UnsupportedInput('Provide e1=current evidence and e2=resource index, without dropping other evidence')
    resources = snapshot['resources']
    if len(resources) > 1 or any(r['read_state'] != 'unread' for r in resources):
        raise UnsupportedInput('At most one unread resource is supported; merge read evidence into e1')
    if any(e['resource_id'] is not None for e in evidence.values()):
        raise UnsupportedInput('Resource-linked evidence needs reconciliation not implemented by this backend')
    given = {'task': snapshot['task']['text'], 'conversation': [],
             'evidence': [{'source_id': k, 'content': evidence[k]['content']} for k in ('e1', 'e2')] +
                         [{'source_id': 'e3', 'content': 'Field inventory: ' + ' || '.join(names)}],
             'available_resources': [dict(resource_id='r1', locator=r['locator'], read_state='unread')
                                     for r in resources], 'inspection_log': []}
    return given, {c['name']: c['field_id'] for c in fields}


class NliBackend:
    def __init__(self, manifest, expected_sha256, device='cuda:0'):
        path = local_path(manifest)
        if file_sha(path) != expected_sha256:
            raise ValueError('Model manifest hash mismatch')
        self.manifest = m = json.loads(path.read_text(encoding='utf-8'))
        if m['manifest_version'] != 1 or m['router'] not in ('v10', 'v12'):
            raise ValueError('Unsupported model manifest')
        self.reference = {k: m[k] for k in ('backend_id', 'artifact_version',
                                          'input_projection_version', 'calibration_version')}
        self.reference['manifest_sha256'] = expected_sha256
        for section in [m['base'], *m['adapters'].values()]:
            for name, expected in section['sha256'].items():
                if file_sha(local_path(section['directory']) / name) != expected:
                    raise ValueError('Model/tokenizer artifact changed: ' + name)
        for source, expected in m['frozen_source_sha256'].items():
            if file_sha(local_path(source)) != expected:
                raise ValueError('Frozen inference dependency changed: ' + source)
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
        from peft import PeftModel
        torch.set_num_threads(4)
        torch.manual_seed(m['seed'])
        self.device = device
        if device.startswith('cuda') and not torch.cuda.is_available():
            raise RuntimeError('Configured CUDA device is unavailable')
        base = local_path(m['base']['directory'])
        self.tokenizer = AutoTokenizer.from_pretrained(base, local_files_only=True, trust_remote_code=False)
        self.models = {}
        for kind, adapter in m['adapters'].items():
            model = AutoModelForSequenceClassification.from_pretrained(
                base, local_files_only=True, dtype=torch.float32, trust_remote_code=False,
                attn_implementation='eager').to(device)
            model = PeftModel.from_pretrained(model, local_path(adapter['directory']),
                                             local_files_only=True, is_trainable=False)
            model.eval()
            self.models[kind] = model
        if m['router'] == 'v10':
            from clarification_gate.predictor.sentence_fields_v10 import public_pairs
            self.pairs = lambda given: public_pairs(given, m['arm'])
        else:
            from clarification_gate.predictor.shared_fields_v11 import public_pairs
            self.pairs = public_pairs
        self.inference_count = 0
        self.last_scores = None

    def assess(self, snapshot):
        import torch
        given, field_ids = project(snapshot)
        try:
            pairs, _ = self.pairs(given)
        except (ValueError, KeyError, TypeError, StopIteration) as e:
            raise UnsupportedInput(str(e)) from e
        scores = {}
        with torch.inference_mode():
            groups = {'shared': pairs} if 'shared' in self.models else {
                kind: [p for p in pairs if p['kind'] == kind] for kind in KINDS}
            for key, group in groups.items():
                for start in range(0, len(group), 8):
                    batch = group[start:start + 8]
                    encoded = self.tokenizer([p['premise'] for p in batch],
                                             [p['hypothesis'] for p in batch],
                                             padding=True, truncation=False, return_tensors='pt')
                    if encoded['input_ids'].shape[1] > 512:
                        raise UnsupportedInput('NLI pair exceeds 512 tokens; refusing silent truncation')
                    logits = self.models[key](**encoded.to(self.device)).logits.float()
                    if not torch.isfinite(logits).all():
                        raise RuntimeError('Non-finite NLI logits')
                    values = torch.sigmoid(logits[:, 0] - logits[:, 2]).cpu().tolist()
                    for p, value in zip(batch, values):
                        scores[(p['kind'], p['field'])] = float(value)
        self.inference_count += 1
        self.last_scores = {kind: {field: v for (k, field), v in scores.items() if k == kind}
                            for kind in KINDS}
        states = {kind: sorted(field_ids[name] for (k, name), value in scores.items()
                               if k == kind and value >= self.manifest['thresholds'][kind])
                  for kind in KINDS}
        return {'status': 'OK', 'backend': self.reference, 'kind': 'field_states',
                'field_states': states, 'action_advice': None,
                'score_semantics': 'nli_margin_score',
                'reason_codes': ['EXPERIMENTAL_MODEL', 'CURRENT_SNAPSHOT_ONLY', 'CANDIDATE_COVERAGE_UNVERIFIED']}

    def close(self):
        self.models.clear()
        gc.collect()
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
