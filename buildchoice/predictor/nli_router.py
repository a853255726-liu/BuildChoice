"""Experimental NLI zero-shot action ranking, NOT a trained BuildChoice classifier.

Uses the same mutually exclusive entailment-logit softmax as Transformers'
ZeroShotClassificationPipeline. Scores are relative, not calibrated reliability.
"""
import hashlib
import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ACTIONS = ('PASS', 'INSPECT', 'ASK')
HYPOTHESES = (
    'The next step is to carry out the task using the information already provided, without further lookup or asking the user.',
    'The next step is to look up missing information in available files, documentation, or tools before deciding how to proceed.',
    'The next step is to ask the user for an important missing decision or requirement that the available evidence cannot resolve.',
)


def scores_from_logits(logits, entailment_id):
    import torch
    if logits.shape != (3, 3) or not torch.isfinite(logits).all():
        raise ValueError('Invalid NLI logits')
    return torch.softmax(logits[:, entailment_id].float(), dim=0)


def build_premise(prompt, documents, inspection_state):
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError('A non-empty task is required')
    if inspection_state not in ('not_inspected', 'provided_snapshot', 'no_local_workspace'):
        raise ValueError('Unknown inspection state')
    if inspection_state != 'provided_snapshot' and documents:
        raise ValueError('Documents conflict with inspection state')
    states = {
        'not_inspected': 'A local workspace is available. Its contents have not been inspected yet.',
        'provided_snapshot': 'The available local workspace files have been read and are provided below. No other local files are available in this snapshot.',
        'no_local_workspace': 'No local workspace or additional local documents have been provided.',
    }
    return ('TASK:\n'+prompt+'\n\nEVIDENCE STATUS:\n'+states[inspection_state]
            +'\n\nREAD EVIDENCE:\n'+('\n\n'.join(documents) if documents else '(none)'))


class NLIBuildChoicePredictor:
    def __init__(self, device='cuda:0'):
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
        os.environ.setdefault('HF_HUB_OFFLINE', '1')
        spec = json.loads((ROOT/'configs/classifier.json').read_text(encoding='utf-8'))
        path = ROOT/spec['directory']
        self.device = torch.device(device)
        started = time.monotonic()
        self.tokenizer = AutoTokenizer.from_pretrained(path, local_files_only=True, trust_remote_code=False)
        # FP32 avoids the numerical-stability caveat on the original model card.
        self.model = AutoModelForSequenceClassification.from_pretrained(
            path, local_files_only=True, trust_remote_code=False, dtype=torch.float32,
            attn_implementation='eager').to(self.device).eval()
        self.nli_labels = {int(k): v.lower() for k, v in self.model.config.id2label.items()}
        if set(self.nli_labels.values()) != {'entailment', 'neutral', 'contradiction'}:
            raise ValueError('Expected an NLI checkpoint, not a random action head')
        self.entailment_id = next(k for k, v in self.nli_labels.items() if v == 'entailment')
        self.max_length = min(512, self.model.config.max_position_embeddings)
        if self.device.type == 'cuda':
            torch.cuda.synchronize(self.device)
        self.load_seconds = time.monotonic()-started
        self.parameter_count = sum(p.numel() for p in self.model.parameters())

    def _forward_pairs(self, premise, hypotheses):
        import torch
        if self.device.type == 'cuda':
            torch.cuda.synchronize(self.device)
            torch.cuda.reset_peak_memory_stats(self.device)
        started = time.monotonic()
        premises = [premise]*len(hypotheses)
        full = self.tokenizer(premises, list(hypotheses), truncation=False)
        lengths = [len(ids) for ids in full['input_ids']]
        encoded = self.tokenizer(premises, list(hypotheses), padding=True,
                                 truncation='only_first', max_length=self.max_length,
                                 return_tensors='pt')
        # Persist exact model-visible IDs and tokenizer-decoded pairs, including truncation.
        used = {k: v.tolist() for k, v in encoded.items()}
        visible = [self.tokenizer.decode(ids, skip_special_tokens=False) for ids in used['input_ids']]
        with torch.inference_mode():
            logits = self.model(**encoded.to(self.device)).logits.float().cpu()
        if self.device.type == 'cuda':
            torch.cuda.synchronize(self.device)
        if not torch.isfinite(logits).all():
            raise ValueError('Non-finite model output')
        return logits, {
            'elapsed_seconds': round(time.monotonic()-started, 6),
            'original_pair_token_lengths': lengths,
            'used_pair_token_lengths': encoded['attention_mask'].sum(dim=1).tolist(),
            'truncated': any(n > self.max_length for n in lengths),
            'encoded_inputs': used, 'visible_pairs': visible,
            'encoded_sha256': hashlib.sha256(json.dumps(used, sort_keys=True).encode()).hexdigest(),
            'peak_allocated_mib': round(torch.cuda.max_memory_allocated(self.device)/1024**2, 2)
                if self.device.type == 'cuda' else None,
        }

    def predict(self, prompt, documents, inspection_state):
        premise = build_premise(prompt, documents, inspection_state)
        logits, details = self._forward_pairs(premise, HYPOTHESES)
        scores = scores_from_logits(logits, self.entailment_id)
        action = ACTIONS[int(scores.argmax())]
        return {**details, 'action': action, 'scores': dict(zip(ACTIONS, scores.tolist())),
                'nli_logits': logits.tolist(),
                'nli_probabilities': logits.softmax(dim=-1).tolist(),
                'score_margin': float(scores.topk(2).values.diff().abs()[0]),
                'scores_calibrated': False, 'fine_tuned_for_buildchoice': False}

    def check_nli(self, premise, hypothesis):
        logits, details = self._forward_pairs(premise, (hypothesis,))
        return {**details, 'premise': premise, 'hypothesis': hypothesis,
                'nli_label': self.nli_labels[int(logits[0].argmax())],
                'nli_probabilities': dict(zip(self.nli_labels.values(), logits[0].softmax(-1).tolist()))}
