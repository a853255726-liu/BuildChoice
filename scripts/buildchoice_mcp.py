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
        'BuildChoice records implementation choices with source, ownership and version checks. '
        'Follow decision-discovery Skill for workflow. Core tools cover daily decisions; full tools '
        'add optional audit, memory management, implementation links and experimental verification. '
        'The LLM judges meaning, importance and timing. Source binding is not semantic approval '
        'or authorization for host operations. No automatic audit or independent validation claim.'))
    annotation = ToolAnnotations(readOnlyHint=True, destructiveHint=False,
                                 idempotentHint=False, openWorldHint=False)
    active_session = None
    listed_tool_names = None
    core_tools={'buildchoice_context','buildchoice_screen_candidates','buildchoice_card_activate',
        'buildchoice_reply_interpret','buildchoice_record_instruction','buildchoice_decision_document',
        'buildchoice_decision_status','buildchoice_experience','buildchoice_workspace_snapshot',
        'buildchoice_behavior_review','buildchoice_batch_decisions'}

    async def available_tools():
        tools = await server.list_tools()
        from buildchoice.desktop.decision_contracts import input_schema
        for tool in tools:
            product_contracts={'buildchoice_experience':'experience','buildchoice_workspace_snapshot':'snapshot',
                'buildchoice_behavior_review':'review','buildchoice_batch_decisions':'batch'}
            if tool.name in product_contracts:
                from buildchoice.desktop.product_contracts import input_schema as product_schema
                tool.inputSchema={'type':'object','properties':{'request':product_schema(product_contracts[tool.name])},
                    'required':['request'],'additionalProperties':False}
            if tool.name in ('buildchoice_screen_candidates','buildchoice_record_instruction'):
                contract=input_schema('ScreenRequest' if tool.name=='buildchoice_screen_candidates' else 'InstructionRequest');tool.inputSchema={'type':'object','properties':{'request':{'$ref':contract['$ref']}},'required':['request'],'additionalProperties':False,'$defs':contract['$defs']}
            elif tool.name=='buildchoice_decision_prepare_revision':
                contract=input_schema('Candidate');tool.inputSchema['properties']['candidate']={'$ref':contract['$ref']};tool.inputSchema['$defs']=contract['$defs']
        if read_runtime_settings(args.settings)['mode']=='off':
            tools=[t for t in tools if t.name.startswith('buildchoice_settings_') or t.name=='buildchoice_decision_status']
        elif decisions.settings()['mode']=='off':
            tools=[t for t in tools if t.name not in ('buildchoice_screen_candidates','buildchoice_card_activate','buildchoice_decision_prepare_revision','buildchoice_link_implementation','buildchoice_acceptance_prepare','buildchoice_verify_decision','buildchoice_memory','buildchoice_memory_manage','buildchoice_context','buildchoice_reply_interpret','buildchoice_record_instruction','buildchoice_decision_document',
                'buildchoice_experience','buildchoice_workspace_snapshot','buildchoice_behavior_review','buildchoice_batch_decisions')]
        if decisions.settings()['tool_profile']=='core':
            tools=[t for t in tools if t.name in core_tools or t.name.startswith('buildchoice_settings_')]
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
            tool_profile: Literal['日常', '完整'] | None = None

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
        require_enabled(advanced=True)
        from buildchoice.desktop.audit import Ledger
        return Ledger(WORKSPACE)

    def require_enabled(advanced=False):
        if read_runtime_settings(args.settings)['mode']=='off': raise ValueError('FEATURE_DISABLED')
        if advanced and decisions.settings()['tool_profile']!='full':raise ValueError('TOOL_PROFILE_REQUIRES_FULL')

    audit_write = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)

    @server.tool(annotations=audit_write,structured_output=True)
    def buildchoice_experience(request: dict) -> dict[str,Any]:
        """Task opt-in product scenarios: enable/save/present/acknowledge/freeze/status/document/close.
        Read the advertised action-specific contract. Preserve each behavior's user/decision/project/
        AI/unresolved origin. Saving/presenting is not approval. Display the full returned message;
        acknowledge only a later actual user message for that frozen presentation in this chat.
        freeze saves pre-development expectation versions, including their mixed review states.
        status recovers workspace tasks across chats; fresh confirmation never inherits old handles.
        document retries publication without duplicating versions. No long-term rule promotion.
        """
        require_enabled()
        return decisions.experience(request)

    @server.tool(annotations=audit_write,structured_output=True)
    def buildchoice_workspace_snapshot(request: dict) -> dict[str,Any]:
        """Capture actual local workspace text BEFORE editing, compare AFTER, extend before first edit.
        capture links a frozen expectation to explicit scopes; includes dirty/untracked/non-Git files.
        extend timing=already_modified marks missing history; never invent a pre-edit state.
        compare uses saved content, reports actual diffs, exclusions and attribution limits.
        Storage is outside the code workspace, bounded and private; prune removes content only.
        Scope/credential/link/large-file exclusions limit review conclusions. No commands are run.
        """
        require_enabled()
        return decisions.workspace_snapshot(request)

    @server.tool(annotations=audit_write,structured_output=True)
    def buildchoice_behavior_review(request: dict) -> dict[str,Any]:
        """Create evidence-limited behavior reviews against the comparison's ORIGINAL expectation.
        Judgment and evidence strength are separate. Specify behavior_ids actually checked; omitted
        frozen behaviors become unknown. A test log without real Hook observation is only a report
        file. Native tool observation IDs bind actual output/exit code, not semantic test coverage.
        Extra behaviors distinguish observed_change/preexisting/uncertain. Keep scope and limits.
        feedback binds current real user_message for fix/change_requirement/accept_extra/investigate/
        defer. Requirement changes need a trusted decision and revised scenario. Acceptance never
        proves tests passed or grants host permissions. A new review links previous_review_id.
        """
        require_enabled()
        return decisions.behavior_review(request)

    @server.tool(annotations=audit_write,structured_output=True)
    def buildchoice_batch_decisions(request: dict) -> dict[str,Any]:
        """Present up to three independent ASK_NOW decisions as one frozen task-scoped batch.
        Display full message, interpret a later actual user reply, submit only explicit answers.
        Submit checks ALL frozen versions and saves supplied selections atomically; unanswered,
        deferred/discussed items remain. Ambiguity is never whole-batch approval. Only frozen
        explicit recommendations may use selection_basis=current_recommendation. New conditions
        require revision/clarification. suspend retains pending history; re-present in a new chat.
        Single-card callers remain supported. No business semantic classifier or host authorization.
        """
        require_enabled()
        return decisions.batch_decisions(request)

    @server.tool(annotations=audit_write,structured_output=True)
    def buildchoice_screen_candidates(request: dict) -> dict[str,Any]:
        """Record LLM recommendations; validate structure, current citations and task ownership.
        Each candidate supplies suggested_action=ASK_NOW/INSPECT/DEFER/PROCEED. Importance,
        risk meaning, source applicability and semantic equivalence are LLM judgments.
        Read validation_status separately. Use buildchoice_context to reuse real sources.
        Omit phase; stage metadata is recorded by the server and does not affect routing.
        """
        require_enabled()
        return decisions.screen(request)

    @server.tool(annotations=annotation,structured_output=True)
    def buildchoice_context(session_handle: str, query: str = '', paths: list[str] | None = None,
                            task_id: str | None = None, since: str | None = None, max_chars: int = 12000) -> dict[str,Any]:
        """One bounded query for pending/answered/deferred decisions, project memory and current sources.
        paths reads workspace files and reuses valid receipts; no separate audit session is needed.
        since is a prior snapshot_id from this same chat, returning literal changes, not business impact.
        Inspect omitted/content_truncated. Reuse active cards and recorded choices after reconnect.
        This never confirms a choice, changes a rule or authorizes execution.
        """
        require_enabled()
        return decisions.context_bundle(session_handle,query,paths,task_id,since,max_chars)

    @server.tool(annotations=audit_write,structured_output=True)
    def buildchoice_reply_interpret(task_id: str, decision_id: str, revision: int,
                                    choice_id: Literal['A','B','C'], quote: str, reason: str,
                                    session_handle: str) -> dict[str,Any]:
        """Bind the LLM's reading of a real pending user reply to its current option/version.
        Supply an exact quote from the current user message and your interpretation reason.
        Only select when the user clearly chose this option; clarify questions, negations,
        competing options or changed requirements. Python verifies source/card/version, not meaning.
        Records llm_interpreted_user_reply with semantic_verified_by_program=false.
        Never use an Agent claim or document as user authorization; no host execution permission.
        """
        require_enabled()
        return decisions.interpret_reply(task_id,decision_id,revision,choice_id,quote,reason,session_handle)

    @server.tool(annotations=audit_write,structured_output=True)
    def buildchoice_record_instruction(request: dict) -> dict[str,Any]:
        """Record a clear current user instruction or scoped revision without requiring a card.
        First inspect buildchoice_context for the current decision_id/revision. Pass the full
        actual user_message (without Hook context), exact quote, reason and current session_handle.
        For updates supply decision_id and expected_revision; omit decision/choice_id to reaffirm
        an already recorded choice, or supply one selected decision.choice (no fake alternatives).
        For a new choice use expected_revision=0 and decision. choice_id may answer an existing proposal.
        Python verifies message hash, citation, ownership, version and retries, NOT intent or meaning.
        Only use for clear decisions, not questions, hypotheses or quoted instructions.
        Returns llm_interpreted_user_instruction, semantic_verified_by_program=false and document
        synchronization status. Pending document writes are retryable; never directly edit SQLite.
        This records a choice, never authorizes host execution or promotes a long-term rule.
        """
        require_enabled()
        return decisions.record_instruction(request)

    @server.tool(annotations=audit_write,structured_output=True)
    def buildchoice_decision_document(session_handle: str, task_id: str | None = None,
                                      include_archived: bool = False, write: bool = False,
                                      path: str = 'BUILDCHOICE_DECISIONS.md') -> dict[str,Any]:
        """Generate readable recorded choices, scope, provenance, pending items and literal changes.
        write=false returns Markdown; write=true atomically saves a generated project document.
        record_instruction already synchronizes the project document; do not write it again unless
        pending or explicitly exporting. To repair the canonical path omit task_id/include_archived.
        Task-specific or archived exports must use a separate filename, not the canonical project path.
        Existing user-authored files and linked/private paths are never overwritten.
        Changed references need LLM review; this does not revoke user choices or certify code.
        """
        require_enabled()
        return decisions.decision_document(session_handle,task_id,include_archived,write,path)

    @server.tool(annotations=audit_write,structured_output=True)
    def buildchoice_card_activate(task_id: str, decision_id: str, revision: int, idempotency_key: str,
                           session_handle: str | None = None) -> dict[str,Any]:
        """Activate exactly one unresolved card. Show the returned message in the current conversation.
        Activation is not proof of UI delivery. Replies must bind a real Hook message;
        direct parsing and LLM interpretation have distinct provenance.
        """
        require_enabled()
        return decisions.activate(task_id,decision_id,revision,idempotency_key,session_handle)

    @server.tool(annotations=annotation,structured_output=True)
    def buildchoice_memory(query: str = '', include_archived: bool = False,
                           session_handle: str | None = None) -> dict[str,Any]:
        """Recall project-local observed decisions across chats with a fresh Hook handle.
        Read before extracting candidates. References are suggestions; only explicitly pinned
        current rules may apply. Lists origin, conflicts and exact user lifecycle commands.
        A read never renews retention, promotes rules or creates confirmations. No host permission.
        """
        require_enabled(advanced=True)
        return decisions.memory(query,include_archived,session_handle)

    @server.tool(annotations=ToolAnnotations(readOnlyHint=False,destructiveHint=False,
                                             idempotentHint=True,openWorldHint=False),structured_output=True)
    def buildchoice_memory_manage(memory_id: str, revision: int, session_handle: str,
                                  action: Literal['promote','unpin','forget','restore']='promote') -> dict[str,Any]:
        """Apply the current real user's explicit memory request, never an Agent declaration.
        Read buildchoice_memory first. Hook-bound management_request must contain exactly one
        matching target and action; MCP rechecks confirmation, revision, scope, state and conflicts.
        Clarify ambiguous intent/targets in natural language; no ID input or second confirmation
        is needed for a clear request. Never invoke merely because a decision was confirmed.
        Does not create user choices, expand scope or grant execution permission.
        """
        require_enabled(advanced=True)
        return decisions.manage_memory(memory_id,revision,action,session_handle)

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
        require_enabled(advanced=True)
        return decisions.prepare_revision(task_id,decision_id,revision,candidate,reason,session_handle)

    @server.tool(annotations=audit_write,structured_output=True)
    def buildchoice_link_implementation(task_id: str, decision_id: str, revision: int, path: str, note: str,
                                       start_line: int | None = None, end_line: int | None = None,
                                       session_handle: str | None = None) -> dict[str,Any]:
        """Optional: associate an actual file with a current Hook-confirmed decision.
        Give a relative path, a short explanation and optional real line range. The server records
        a real file hash without executing Git or changing the file.
        The association is Agent-reported, not proof of correct implementation or human approval.
        Decision status reports links needing review after a revision or file change.
        """
        require_enabled(advanced=True)
        return decisions.link_implementation(task_id,decision_id,revision,path,note,start_line,end_line,session_handle)

    @server.tool(annotations=audit_write,structured_output=True)
    def buildchoice_acceptance_prepare(task_id: str, decision_id: str, revision: int,
                                      criteria: list[dict[str,Any]], session_handle: str,
                                      idempotency_key: str) -> dict[str,Any]:
        """Optional experiment only; normal testing and acceptance belong to Codex.
        Create immutable Agent-derived behavior criteria for the current Hook-confirmed decision.
        Never invoke as a routine development step or independent requirements certification.
        Each criterion: criterion_id, description, basis, required, evidence_type='behavior', test_ids.
        Test IDs are actual unittest IDs under module buildchoice_tests. This does not approve new
        product rules, separately confirm the criteria or execute tests. See acceptance-v1 schema.
        """
        require_enabled(advanced=True)
        return decisions.acceptance_prepare(task_id,decision_id,revision,criteria,session_handle,idempotency_key)

    @server.tool(annotations=audit_write,structured_output=True)
    def buildchoice_verify_decision(task_id: str, decision_id: str, revision: int, acceptance_id: str,
                                   code_evidence_refs: list[dict[str,Any]], session_handle: str,
                                   idempotency_key: str, execution_id: str | None = None) -> dict[str,Any]:
        """Optional experiment, only when explicitly requested; not independent certification.
        Normal tests and result interpretation belong to Codex. Record per-criterion checks
        using real code references and optional collector execution for compatibility.
        References: criterion_id, source_id, and pointer or quote from a real audit read.
        No command execution: run the collector explicitly through the existing authorized command
        path. A report path or Agent claim is not an execution receipt. Missing tests stay inconclusive.
        Returns historical verdict, current/stale applicability and current_pass within the declared scope.
        """
        require_enabled(advanced=True)
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
