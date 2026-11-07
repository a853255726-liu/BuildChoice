"""Use the pinned SDK's actual Hook enums when checking a real install response."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from openai_codex.generated.v2_all import HookEventName

PACKAGE=Path(__file__).resolve().parents[1]/'plugins/buildchoice'
sys.path.insert(0,str(PACKAGE))
spec=importlib.util.spec_from_file_location('buildchoice_install_contract',PACKAGE/'install_local.py')
installer=importlib.util.module_from_spec(spec);spec.loader.exec_module(installer)


class PluginInstallContractTests(unittest.TestCase):
    def detail(self, events, servers=None):
        return SimpleNamespace(mcp_servers=['buildchoice'] if servers is None else servers,
            hooks=[SimpleNamespace(event_name=e) for e in events])

    def test_real_sdk_wire_events_are_accepted(self):
        events=[HookEventName('userPromptSubmit'),HookEventName('postToolUse')]
        installer.validate_components(self.detail(events))

    def test_missing_hook_is_still_rejected(self):
        with self.assertRaisesRegex(ValueError,'Hooks'):
            installer.validate_components(self.detail([HookEventName.user_prompt_submit]))

    def test_missing_mcp_server_is_still_rejected(self):
        with self.assertRaisesRegex(ValueError,'server'):
            installer.validate_components(self.detail([HookEventName.user_prompt_submit,HookEventName.post_tool_use],[]))


if __name__=='__main__':unittest.main()
