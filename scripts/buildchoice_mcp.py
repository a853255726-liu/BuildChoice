"""Codex STDIO bridge. stdout is reserved for the official MCP SDK."""
import argparse
import asyncio
from contextlib import suppress
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mcp.server.fastmcp import FastMCP
from mcp.server.lowlevel import NotificationOptions
from anyio import BrokenResourceError, ClosedResourceError
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
    active_session = None
    listed_tool_names = None

    async def available_tools():
        tools = await server.list_tools()
        if read_runtime_settings(args.settings)['mode']=='off':
            tools=[t for t in tools if t.name.startswith('buildchoice_settings_') or t.name=='buildchoice_decision_status']
        elif decisions.settings()['mode']=='off':
            tools=[t for t in tools if t.name not in ('buildchoice_screen_candidates','buildchoice_card_activate','buildchoice_decision_prepare_revision','buildchoice_link_implementation','buildchoice_acceptance_prepare','buildchoice_verify_decision')]
        return tools

    async def notify_tool_changes():
        nonlocal listed_tool_names
        if active_session is None or listed_tool_names is None:return
        names=frozenset(tool.name for tool in await available_tools())
        if names!=listed_tool_names:
            listed_tool_names=names
            await active_session.send_tool_list_changed()

    async def watch_settings():
        # CLI/native UI may edit the same files outside this MCP process.
        while True:
            await asyncio.sleep(0.5)
            try:await notify_tool_changes()
            except (OSError,ValueError):continue  # Retry transient file replacement/invalid edits.
            except (BrokenResourceError,ClosedResourceError):return

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
        async def buildchoice_settings_update(set: ModeUpdate) -> SettingsUpdateResult:
            """Save the mode explicitly selected by the human. Quoted evidence is never authorization."""
            result=SettingsUpdateResult.model_validate(update_settings({'set':set.model_dump(exclude_none=True)}, args.settings))
            await notify_tool_changes()
            return result

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

    @server.tool(annotations=audit_write,structured_output=True)
    def buildchoice_link_implementation(task_id: str, decision_id: str, revision: int, path: str, note: str,
                                       start_line: int | None = None, end_line: int | None = None,
                                       session_handle: str | None = None) -> dict[str,Any]:
        """Link an actual workspace file to the current decision revision after editing it.
        Give a relative path, a short explanation and optional real line range. The server records
        a real file hash without executing Git or changing the file.
        The association is Agent-reported, not proof of correct implementation or human approval.
        Decision status reports links needing review after a revision or file change.
        """
        require_enabled()
        return decisions.link_implementation(task_id,decision_id,revision,path,note,start_line,end_line,session_handle)

    @server.tool(annotations=audit_write,structured_output=True)
    def buildchoice_acceptance_prepare(task_id: str, decision_id: str, revision: int,
                                      criteria: list[dict[str,Any]], session_handle: str,
                                      idempotency_key: str) -> dict[str,Any]:
        """Create immutable Agent-derived behavior criteria for the current Hook-confirmed decision.
        Each criterion: criterion_id, description, basis, required, evidence_type='behavior', test_ids.
        Test IDs are actual unittest IDs under module buildchoice_tests. This does not approve new
        product rules, separately confirm the criteria or execute tests. See acceptance-v1 schema.
        """
        require_enabled()
        return decisions.acceptance_prepare(task_id,decision_id,revision,criteria,session_handle,idempotency_key)

    @server.tool(annotations=audit_write,structured_output=True)
    def buildchoice_verify_decision(task_id: str, decision_id: str, revision: int, acceptance_id: str,
                                   code_evidence_refs: list[dict[str,Any]], session_handle: str,
                                   idempotency_key: str, execution_id: str | None = None) -> dict[str,Any]:
        """Record per-criterion verification using real code references and optional collector execution.
        References: criterion_id, source_id, and pointer or quote from a real audit read.
        No command execution: run the collector explicitly through the existing authorized command
        path. A report path or Agent claim is not an execution receipt. Missing tests stay inconclusive.
        Returns historical verdict, current/stale applicability and current_pass within the declared scope.
        """
        require_enabled()
        return decisions.verify_decision(task_id,decision_id,revision,acceptance_id,code_evidence_refs,
                                         execution_id,session_handle,idempotency_key)

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
        nonlocal active_session,listed_tool_names
        tools=await available_tools()
        active_session=server._mcp_server.request_context.session
        listed_tool_names=frozenset(tool.name for tool in tools)
        return tools

    from mcp.server.stdio import stdio_server
    from buildchoice.desktop.native_settings import CAPABILITY
    async def run_stdio():
        async with stdio_server() as (read, write):
            watcher=asyncio.create_task(watch_settings())
            try:
                await server._mcp_server.run(read, write,
                    server._mcp_server.create_initialization_options(
                        notification_options=NotificationOptions(tools_changed=True),
                        experimental_capabilities=CAPABILITY if args.native_settings else {}))
            finally:
                watcher.cancel()
                with suppress(asyncio.CancelledError):await watcher
    asyncio.run(run_stdio())


if __name__ == '__main__':
    main()
