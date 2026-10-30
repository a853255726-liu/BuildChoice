"""Pinned local Transformers/PEFT inference using Mellea's QC formatter.

This is the documented fallback path, not a claim that the complete Mellea HF
backend or Codex Gate integration is working. Model errors are never CLEAR.
"""
import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault('HF_HOME', str(ROOT/'.cache/huggingface'))
os.environ.setdefault('HF_HUB_DISABLE_IMPLICIT_TOKEN', '1')
os.environ.setdefault('HF_HUB_DISABLE_TELEMETRY', '1')


def parse_output(raw):
    result = json.loads(raw)
    if not isinstance(result, dict) or not isinstance(result.get('clarification'), str):
        raise ValueError('QC output must be an object with a clarification string')
    if not result['clarification'].strip():
        raise ValueError('Empty clarification is not CLEAR')
    return result


class QCOutputError(ValueError):
    """Keep a malformed generation available to the diagnostic logger."""
    def __init__(self, raw, elapsed_seconds, cause):
        super().__init__(str(cause))
        self.model_raw_output = raw
        self.elapsed_seconds = elapsed_seconds


class IBMPredictor:
    def __init__(self):
        import torch
        from mellea.formatters.granite import IntrinsicsRewriter
        from peft import PeftModel
        from transformers import AutoModelForCausalLM, AutoTokenizer

        if not torch.cuda.is_available():
            raise RuntimeError('CUDA unavailable; CPU inference is not enabled implicitly')
        specs = json.loads((ROOT/'configs/models.json').read_text(encoding='utf-8'))
        base = ROOT/specs['base']['directory']
        adapter = ROOT/specs['adapter']['directory']/specs['adapter']['subfolder']
        for path in (base/'config.json', base/'model-00001-of-00002.safetensors',
                     base/'model-00002-of-00002.safetensors', adapter/'adapter_model.safetensors'):
            if not path.is_file():
                raise FileNotFoundError(f'Missing pinned model file: {path}. Run scripts/download_ibm.py first.')
        started = time.monotonic()
        self.tokenizer = AutoTokenizer.from_pretrained(str(base), local_files_only=True, trust_remote_code=False)
        model = AutoModelForCausalLM.from_pretrained(str(base), local_files_only=True,
                    trust_remote_code=False, dtype=torch.bfloat16, device_map='cuda:0', attn_implementation='sdpa')
        self.model = PeftModel.from_pretrained(model, str(adapter), local_files_only=True, is_trainable=False)
        self.model.eval()
        self.rewriter = IntrinsicsRewriter(config_file=adapter/'io.yaml')
        self.load_seconds = round(time.monotonic()-started, 3)

    def predict(self, prompt, documents=(), history=()):
        import torch
        from mellea.formatters.granite.base.util import (
            chat_completion_request_to_transformers_inputs, generate_with_transformers)
        started = time.monotonic()
        rewritten = self.rewriter.transform({
            'messages': list(history) + [{'role': 'user', 'content': prompt}],
            'extra_body': {'documents': [{'text': text} for text in documents]},
        })
        inputs, other = chat_completion_request_to_transformers_inputs(
            rewritten.model_dump(), self.tokenizer, self.model)
        if inputs['input_tokens'].shape[-1] > 4096:
            raise ValueError('Input exceeds smoke-test limit of 4096 tokens')
        inputs.update(max_new_tokens=256, max_time=60.0, do_sample=False, disable_compile=True)
        torch.cuda.reset_peak_memory_stats()
        # llguidance decorates its bitmask kernel with torch.compile. Windows
        # has no standard Triton wheel; run the same tensor operations eagerly.
        # Keep this scoped to inference rather than changing global torch config.
        with torch.inference_mode(), torch.compiler.set_stance('force_eager'):
            response = generate_with_transformers(self.tokenizer, self.model, inputs, other)
        raw = response.choices[0].message.content
        elapsed = round(time.monotonic()-started, 3)
        try:
            parsed = parse_output(raw)
        except (ValueError, TypeError) as exc:
            raise QCOutputError(raw, elapsed, exc) from exc
        usage = getattr(response, 'usage', None)
        if hasattr(usage, 'model_dump'):
            usage = usage.model_dump()
        return {'model_raw_output': raw, 'parsed': parsed,
                'elapsed_seconds': elapsed,
                'input_tokens': int(inputs['input_tokens'].shape[-1]),
                'usage': usage,
                'finish_reason': getattr(response.choices[0], 'finish_reason', None),
                'peak_allocated_mib': round(torch.cuda.max_memory_allocated()/1024**2, 1)}
