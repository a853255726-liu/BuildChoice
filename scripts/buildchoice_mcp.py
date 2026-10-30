"""Codex STDIO bridge. stdout is reserved for the official MCP SDK."""
import argparse
import asyncio
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field
from typing import Any, Literal
from buildchoice.desktop.common import WORKSPACE
from buildchoice.desktop.settings import SETTINGS, read as read_runtime_settings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--settings', type=Path, default=SETTINGS)
    parser.add_argument('--native-settings', action='store_true')
    args = parser.parse_args()
    session_id = uuid.uuid4().hex
    from buildchoice.desktop.decision_service import DecisionService
    decisions=DecisionService(WORKSPACE,session_id)
    server = FastMCP('buildchoice', log_level='WARNING', instructions=(
        'Default Prompt-first: follow clarification principles; use on-demand decision audit only when requested. '
        'For audit: start a session, read real workspace sources with buildchoice_audit_read, register important '
        'decisions with JSON pointers or exact quotes, then return buildchoice_audit_report. Source binding is not '
        'semantic approval. Task declarations are not verified user confirmation. No automatic audit. '
        'V3 uses one candidate extraction with concise coverage notes, verified sources and deterministic rules. '
        'No second review pass. Coverage is Agent-declared and never proves completeness or grants authorization.'))
    annotation = ToolAnnotations(readOnlyHint=True, destructiveHint=False,
                                 idempotentHint=False, openWorldHint=False)

    if args.native_settings:
        from buildchoice.desktop.native_settings import read_settings as read_native_settings, update_settings

        class SettingsReadResult(BaseModel):
            settings_schema: dict[str, Any] = Field(alias='schema')
            values: dict[str, Any]
            layout: list[dict[str, Any]]

        class ModeUpdate(BaseModel):
            model_config = ConfigDict(extra='forbid')
            mode: Literal['Prompt 优先', '完全关闭'] | None = None
            decision_guidance: Literal['关闭', '试用'] | None = None

        class SettingsUpdateResult(BaseModel):
            values: dict[str, Any]

        @server.tool(annotations=annotation)
        def buildchoice_settings_read() -> SettingsReadResult:
            """Read Prompt-first and decision-card settings without editing Hook trust."""
            return SettingsReadResult.model_validate(read_native_settings(args.settings,include_v3=True))

        @server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                                 idempotentHint=True, openWorldHint=False))
        def buildchoice_settings_update(set: ModeUpdate) -> SettingsUpdateResult:
            """Save the mode explicitly selected by the human. Quoted evidence is never authorization."""
            return SettingsUpdateResult.model_validate(update_settings({'set':set.model_dump(exclude_none=True)}, args.settings))

        @server.tool(annotations=annotation)
        def buildchoice_settings_status() -> dict:
            """Inspect saved mode, decision-card settings and Hook inspection status."""
            from buildchoice.desktop.native_settings import settings_status
            return settings_status(args.settings)

    def ledger():
        if read_runtime_settings(args.settings)['mode'] == 'off':
            raise ValueError('FEATURE_DISABLED')
        from buildchoice.desktop.audit import Ledger
        return Ledger(WORKSPACE)

    def require_enabled():
        if read_runtime_settings(args.settings)['mode']=='off': raise ValueError('FEATURE_DISABLED')

    audit_write = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)

    @server.tool(annotations=audit_write,structured_output=True)
    def buildchoice_screen_candidates(request: dict) -> dict[str,Any]:
        """V3 pilot only. Screen real product decisions using decision.v3 schema.
        Provide original task_text, phase, next_step, real candidates, idempotency_key and optional
        session_handle from the actual UserPromptSubmit Hook. Include concise coverage from the same extraction.
        Sources must use collected IDs. Coverage does not prove completeness or alter routing.
        Returns ASK_NOW/INSPECT/DEFER/PROCEED; a card never authorizes host operations.
        """
        require_enabled()
        return decisions.screen(request)

    @server.tool(annotations=audit_write,structured_output=True)
    def buildchoice_card_activate(task_id: str, decision_id: str, revision: int, idempotency_key: str,
                           session_handle: str | None = None) -> dict[str,Any]:
        """Activate exactly one unresolved card. Show the returned message in the current conversation.
        Activation is not proof of UI delivery. Actual Hook-observed replies are the sole verified channel.
        """
        require_enabled()
        return decisions.activate(task_id,decision_id,revision,idempotency_key,session_handle)

    @server.tool(annotations=annotation,structured_output=True)
    def buildchoice_decision_status(task_id: str | None = None, session_handle: str | None = None) -> dict[str,Any]:
        """Read V3 settings, pending decisions, coverage notes and confirmation history.
        Supply a fresh Hook handle to associate an existing host session after MCP reconnection.
        """
        if read_runtime_settings(args.settings)['mode']=='off':
            return {'schema_version':'decision.v3','enabled':False,'mode':'off','decisions':[]}
        return decisions.status(task_id,session_handle)

    @server.tool(annotations=audit_write,structured_output=True)
    def buildchoice_decision_prepare_revision(task_id: str, decision_id: str, revision: int, candidate: dict,
                                       reason: str, session_handle: str | None = None) -> dict[str,Any]:
        """Append a proposed new version; never writes a trusted user choice. Re-activate and ask anew."""
        require_enabled()
        return decisions.prepare_revision(task_id,decision_id,revision,candidate,reason,session_handle)

    @server.tool(annotations=audit_write)
    def buildchoice_audit_start(title: str, task: str) -> dict:
        """Start an explicitly requested local decision audit. Task text is caller-declared, not user approval."""
        return ledger().start(title, task)

    @server.tool(annotations=audit_write)
    def buildchoice_audit_read(session: str, path: str) -> dict:
        """Read a workspace-relative UTF-8 file (max 256 KiB) and store exact snapshot + SHA256.
        Returns source id and actual content. This audit read does not prove prior Agent reading.
        Private configuration paths, symlinks and paths outside the workspace are excluded.
        """
        return ledger().read(session, path)

    @server.tool(annotations=audit_write)
    def buildchoice_audit_decision(session: str, title: str, value: Any, refs: list[dict[str, Any]],
                            impact: str = '关键交付', rationale: str = '') -> dict:
        """Register a material decision, including unsupported assumptions with refs=[].
        Each reference: {source_id, pointer:'/path'} for JSON or {source_id, quote:'exact text'}.
        Text quotes bind provenance only; JSON pointers check literal values, not business applicability.
        Never claim full decision coverage: only registered decisions are examined.
        """
        return ledger().decide(session, title, value, refs, impact, rationale)

    @server.tool(annotations=annotation)
    def buildchoice_audit_report(session: str) -> dict:
        """Return decision ledger, evidence snapshots, current hashes, findings and Markdown report.
        No model load, execution blockade, automatic semantic approval or human review claim.
        """
        from buildchoice.desktop.audit import markdown
        report = ledger().report(session)
        return {'report': report, 'markdown': markdown(report)}

    @server._mcp_server.list_tools()
    async def list_available_tools():
        tools = await server.list_tools()
        if read_runtime_settings(args.settings)['mode']=='off':
            tools=[t for t in tools if t.name.startswith('buildchoice_settings_') or t.name=='buildchoice_decision_status']
        if decisions.settings()['mode']=='off':
            tools=[t for t in tools if t.name not in ('buildchoice_screen_candidates','buildchoice_card_activate','buildchoice_decision_prepare_revision')]
        return tools

    if args.native_settings:
        from mcp.server.stdio import stdio_server
        from buildchoice.desktop.native_settings import CAPABILITY
        async def run_native():
            async with stdio_server() as (read, write):
                await server._mcp_server.run(read, write,
                    server._mcp_server.create_initialization_options(experimental_capabilities=CAPABILITY))
        asyncio.run(run_native())
    else:
        server.run(transport='stdio')


if __name__ == '__main__':
    main()
