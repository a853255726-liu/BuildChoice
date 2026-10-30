"""Read actual local state for the control panel; never edits hook trust."""
import threading
import time
from datetime import datetime, timezone
from clarification_gate.desktop.auto_call import switch_status
from clarification_gate.desktop.common import ROOT, WORKSPACE

EVENTS = {'userpromptsubmit': '消息进入', 'pretooluse': '执行前检查',
          'posttooluse': '调用回执', 'stop': '结束前检查'}


def now():
    return datetime.now(timezone.utc).isoformat()


def inspect_hooks():
    from openai_codex.client import CodexClient, CodexConfig
    from openai_codex.generated.v2_all import HooksListResponse
    with CodexClient(CodexConfig(cwd=str(WORKSPACE))) as client:
        client.initialize()
        result = client.request('hooks/list', {'cwds': [str(WORKSPACE)]}, response_model=HooksListResponse)
    hooks, errors = [], []
    for entry in result.data:
        errors.extend(e.message if hasattr(e, 'message') else 'Hook配置读取失败' for e in entry.errors)
        for wrapped in entry.hooks:
            item = wrapped.root if hasattr(wrapped, 'root') else wrapped
            command = getattr(item, 'command', '')
            plugin_id = getattr(item, 'plugin_id', None)
            if (plugin_id != 'clarification-gate-controls@clarification-gate-local' and
                    not any(name in command for name in ('gate_required_call_hook.py', 'clarification_gate_plugin_hook.py'))):
                continue
            event = item.event_name.value.casefold()
            hooks.append({'event': event, 'label': EVENTS.get(event, event), 'enabled': item.enabled,
                          'trust': item.trust_status.value})
    ready = (set(h['event'] for h in hooks) == set(EVENTS) and not errors and
             all(h['enabled'] and h['trust'] in ('trusted', 'managed') for h in hooks))
    return {'status': 'ready' if ready else 'pending', 'all_ready': ready, 'items': hooks,
            'trusted_count': sum(h['enabled'] and h['trust'] in ('trusted', 'managed') for h in hooks),
            'required_count': 4, 'errors': errors, 'checked_at': now(), 'source': 'official hooks/list'}


class PanelState:
    def __init__(self):
        self.lock = threading.Lock()
        self.cached_hooks = None
        self.cache_time = 0

    def hooks(self, refresh=False):
        with self.lock:
            if self.cached_hooks is None or refresh or time.monotonic() - self.cache_time > 60:
                try:
                    value = inspect_hooks()
                except Exception:
                    value = {'status': 'unknown', 'all_ready': False, 'items': [], 'trusted_count': 0,
                             'required_count': 4, 'errors': ['暂时无法读取Codex Hook状态'],
                             'checked_at': now(), 'source': 'official hooks/list'}
                self.cached_hooks = value
                self.cache_time = time.monotonic()
            return self.cached_hooks

    def snapshot(self, refresh=False):
        switch = switch_status()
        hooks = self.hooks(refresh)
        try:
            if switch['mode'] == 'prompt':
                return {'switch': switch, 'hooks': hooks,
                        'service': {'status': 'NOT_REQUIRED', 'model_loaded': False, 'model': None},
                        'effective': 'prompt_ready' if hooks['all_ready'] else 'pending_trust',
                        'updated_at': now(), 'native_session_verified': False}
            from clarification_gate.desktop.client import GateClient
            # Only probe; viewing the UI does not launch or load a model.
            client = GateClient()
            raw = client.call('/healthz', timeout=1)
            if raw.get('config_sha256') != client.config['_config_sha256']:
                service = {'status': 'CONFIG_CHANGED', 'model_loaded': False, 'model': raw.get('active_backend')}
            else:
                service = {'status': raw['status'], 'model_loaded': raw['model_loaded'],
                           'model': raw['active_backend'], 'inference_count': raw['inference_count']}
        except Exception:
            service = {'status': 'UNAVAILABLE', 'model_loaded': False, 'model': None}
        effective = ('off' if switch['mode'] == 'off' else 'auto' if switch['mode'] == 'auto' else
                     'unknown' if hooks['status'] == 'unknown' else
                     'pending_trust' if not hooks['all_ready'] else
                     'model_unavailable' if service['status'] != 'OK' or not service['model_loaded'] else
                     'ready_for_new_session')
        return {'switch': switch, 'hooks': hooks, 'service': service, 'effective': effective,
                'updated_at': now(), 'native_session_verified': False}
