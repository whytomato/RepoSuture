"""Safe deterministic views over RepoSuture's canonical trace event stream."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import uuid
from collections.abc import Callable, Sequence
from contextlib import suppress
from enum import StrEnum
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from reposuture.reporting import RunReport, SanitizedTraceEvent


class AgentPhase(StrEnum):
    PREPARE = "PREPARE"
    OBSERVE = "OBSERVE"
    DECIDE = "DECIDE"
    ACT = "ACT"
    VERIFY = "VERIFY"
    REPLAN = "REPLAN"
    FINISH = "FINISH"


class TrajectoryView(StrEnum):
    COMPACT = "compact"
    VERBOSE = "verbose"
    OFF = "off"


class TrajectoryFormat(StrEnum):
    TEXT = "text"
    MARKDOWN = "markdown"


class ReplayView(StrEnum):
    COMPACT = "compact"
    VERBOSE = "verbose"


class TrajectoryRow(BaseModel):
    """A presentation-only projection of one sanitized trace event."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sequence: int = Field(ge=1)
    phase: AgentPhase
    turn: int | None = Field(default=None, ge=1)
    action: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=2_000)]
    result: Annotated[str, StringConstraints(strict=True, max_length=500)] = ""


class ReplayRun(BaseModel):
    """Validated immutable references to one completed local run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_directory: Path
    report_path: Path
    trace_path: Path
    report: RunReport
    events: tuple[SanitizedTraceEvent, ...]


class LiveTrajectoryRenderer:
    """Render each sanitized trace event as it is durably appended."""

    def __init__(
        self,
        *,
        view: TrajectoryView = TrajectoryView.COMPACT,
        sink: Callable[[str], None],
    ) -> None:
        self.view = view
        self.sink = sink

    def __call__(self, event: SanitizedTraceEvent) -> None:
        rendered = render_trajectory_text((event,), view=self.view)
        if rendered:
            self.sink(rendered)


def render_trajectory_text(
    events: Sequence[SanitizedTraceEvent],
    *,
    view: TrajectoryView = TrajectoryView.COMPACT,
) -> str:
    """Render safe trace semantics as deterministic plain text."""

    if view is TrajectoryView.OFF:
        return ""
    lines: list[str] = []
    for event in events:
        for row in trajectory_rows_for_event(event, view=view):
            lines.extend(_text_lines(row))
    return "\n".join(lines) + ("\n" if lines else "")


def load_trace_events(trace_path: Path) -> tuple[SanitizedTraceEvent, ...]:
    """Load and validate the bounded canonical JSONL event stream."""

    events: list[SanitizedTraceEvent] = []
    with trace_path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                raise ValueError(f"trace line {line_number} is blank")
            try:
                event = SanitizedTraceEvent.model_validate_json(line)
            except Exception as exc:
                raise ValueError(f"trace line {line_number} is malformed") from exc
            expected = len(events) + 1
            if event.sequence != expected:
                if any(existing.sequence == event.sequence for existing in events):
                    raise ValueError(
                        f"trace contains duplicate sequence number {event.sequence}"
                    )
                raise ValueError(
                    f"trace sequence is non-monotonic: expected {expected}, "
                    f"found {event.sequence}"
                )
            events.append(event)
    if not events:
        raise ValueError("trace.jsonl contains no events")
    return tuple(events)


def load_replay_run(path: Path) -> ReplayRun:
    """Validate a completed run without executing Git, Maven, a model, or a network call."""

    try:
        entry = path.expanduser().resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"replay path does not exist: {path}") from exc
    if entry.is_dir():
        run_directory = entry
    elif entry.is_file() and entry.name in {"report.json", "trace.jsonl"}:
        run_directory = entry.parent
    else:
        raise ValueError("replay PATH must be a run directory, report.json, or trace.jsonl")

    report_path = _run_file(run_directory, "report.json")
    trace_path = _run_file(run_directory, "trace.jsonl")
    if report_path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError("report.json exceeds the replay size limit")
    if trace_path.stat().st_size > 32 * 1024 * 1024:
        raise ValueError("trace.jsonl exceeds the replay size limit")
    try:
        raw_report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("report.json is malformed or violates the report schema") from exc
    raw_report = _prepare_replay_report_payload(run_directory, raw_report)
    try:
        report = RunReport.model_validate(raw_report)
    except Exception as exc:
        raise ValueError("report.json is malformed or violates the report schema") from exc
    events = load_trace_events(trace_path)
    if any(event.run_id != report.run_id for event in events):
        raise ValueError("trace event run id does not match report.json")
    if events[-1].event_type != "run_finished":
        raise ValueError("trace does not end with run_finished")
    if events[-1].status != report.final_status.value:
        raise ValueError("trace final status does not match report.json")

    resolved_artifacts: dict[str, Path] = {}
    for name, configured in report.artifacts.items():
        resolved_artifacts[name] = _referenced_run_file(
            run_directory,
            Path(configured),
            label=f"artifacts[{name!r}]",
        )
    if resolved_artifacts.get("report") != report_path:
        raise ValueError("report artifact path does not identify the loaded report.json")
    if resolved_artifacts.get("trace") != trace_path:
        raise ValueError("trace artifact path does not identify the loaded trace.jsonl")

    for name, metadata in report.artifact_metadata.items():
        artifact = resolved_artifacts.get(name)
        metadata_path = _referenced_run_file(
            run_directory,
            metadata.path,
            label=f"artifact_metadata[{name!r}]",
        )
        if artifact is None or metadata_path != artifact:
            raise ValueError(f"artifact metadata path is inconsistent for {name}")
        if artifact.stat().st_size > 64 * 1024 * 1024:
            raise ValueError(f"artifact exceeds the replay size limit for {name}")
        size, digest = _hash_file(artifact)
        if size != metadata.size_bytes or digest != metadata.sha256:
            raise ValueError(f"artifact metadata checksum is inconsistent for {name}")

    return ReplayRun(
        run_directory=run_directory,
        report_path=report_path,
        trace_path=trace_path,
        report=report,
        events=events,
    )


def render_replay(
    replay: ReplayRun,
    *,
    view: TrajectoryView,
    markdown: bool,
) -> str:
    """Render the same semantic event projection used by the live observer."""

    if markdown:
        return render_trajectory_markdown(replay.report, replay.events, view=view)
    return render_trajectory_text(replay.events, view=view)


def write_replay_output(replay: ReplayRun, path: Path, content: str) -> Path:
    """Write replay output outside the immutable source artifact directory."""

    destination = path.expanduser().resolve(strict=False)
    if destination == replay.run_directory or destination.is_relative_to(
        replay.run_directory
    ):
        raise ValueError("replay output cannot be inside the replay run directory")
    write_trajectory_markdown(destination, content)
    return destination


def render_trajectory_markdown(
    report: RunReport,
    events: Sequence[SanitizedTraceEvent],
    *,
    view: TrajectoryView = TrajectoryView.VERBOSE,
) -> str:
    """Derive a safe, replayable Markdown trajectory from report and trace evidence."""

    rows = [
        row
        for event in events
        for row in trajectory_rows_for_event(event, view=view)
    ]
    budget = _budget_summary(events)
    rollback_count = sum(
        1
        for event in events
        if event.event_type == "agent_replan_requested"
        and "CANDIDATE_REVERTED" in _safe_replan_reasons(event.metadata.get("reasons"))
    )
    lines = [
        "# Agent Trajectory",
        "",
        f"- Run ID: `{_markdown_text(report.run_id, maximum=160)}`",
        f"- Case ID: `{_markdown_text(report.task_id, maximum=160)}`",
        "- Provider and model: "
        f"`{_markdown_text(report.provider or 'unknown', maximum=64)}` / "
        f"`{_markdown_text(report.model or 'unknown', maximum=256)}`",
        f"- Final deterministic status: **{report.final_status.value}**",
        f"- Start time: `{report.start_time.isoformat()}`",
        f"- End time: `{report.end_time.isoformat()}`",
        f"- Duration: `{report.total_duration:.3f}s`",
        f"- Budget usage: {budget}",
        "",
        "## Goal",
        "",
        _markdown_text(report.issue_title or report.task_id, maximum=300),
        "",
        _markdown_text(
            report.issue_description or "No public issue description was recorded.",
            maximum=2_000,
        ),
        "",
        "## Timeline",
        "",
        "| Seq | Phase | Turn | Action / Observation | Result |",
        "|---:|---|---:|---|---|",
    ]
    lines.extend(
        "| "
        f"{row.sequence} | {row.phase.value} | {row.turn or ''} | "
        f"{_markdown_cell(row.action)} | {_markdown_cell(row.result)} |"
        for row in rows
    )
    lines.extend(
        [
            "",
            "## Verification",
            "",
            f"- Baseline target test: **{report.baseline_test_result.outcome.value}**",
            "- Candidate target tests: "
            f"{_candidate_target_count(report)}; "
            f"latest **{report.patched_target_test_result.outcome.value}**",
            "- Regression executions: "
            f"{report.regression_execution_count}; latest "
            f"**{report.regression_result.outcome.value}**",
            f"- Candidate rollback events: {rollback_count}",
            "- Final correctness evidence: deterministic Git, Maven, JUnit, and "
            "repository-integrity checks",
            "",
            "## Metrics",
            "",
            f"- Model turns: {report.total_model_turns}",
            f"- Tool calls: {report.total_tool_calls}",
            "- Tool calls by name: " + _tool_counts_text(report.tool_calls_by_name),
            f"- Patch attempts: {report.total_patch_attempts}",
            f"- Target-test executions: {report.target_test_execution_count}",
            f"- Regression executions: {report.regression_execution_count}",
            "- Tokens: "
            f"input={report.input_token_usage}, output={report.output_token_usage}, "
            f"reasoning={report.reasoning_token_usage}",
            f"- Model latency: {report.model_latency_seconds:.3f}s",
            f"- Test duration: {report.test_execution_duration_seconds:.3f}s",
            "",
            "## Final Result",
            "",
            f"**{report.final_status.value}**. This status is determined by deterministic "
            "verification, never by the model's final message.",
        ]
    )
    final_patch = report.artifact_metadata.get("final_patch")
    if report.patch_applied and report.patch_sha256 and final_patch is not None:
        lines.extend(
            [
                "",
                "Verified Patch artifact: `final.patch` "
                f"(SHA-256 `{final_patch.sha256}`).",
            ]
        )
    if report.presentation_warning:
        lines.extend(
            [
                "",
                "Presentation warning: "
                + _markdown_text(report.presentation_warning, maximum=500),
            ]
        )
    return "\n".join(lines) + "\n"


def write_trajectory_markdown(path: Path, content: str) -> None:
    """Atomically write a generated trajectory without altering trace evidence."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".trj-{uuid.uuid4().hex[:12]}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8", newline="\n")
        temporary.replace(path)
    finally:
        with suppress(OSError):
            temporary.unlink(missing_ok=True)


def trajectory_rows_for_event(
    event: SanitizedTraceEvent,
    *,
    view: TrajectoryView,
) -> tuple[TrajectoryRow, ...]:
    """Project one already-sanitized event without reconstructing model reasoning."""

    metadata = event.metadata
    if event.event_type == "worktree_created":
        commit = _safe_text(metadata.get("base_commit"), maximum=40)
        short_commit = commit[:8] if commit else "unknown"
        return (
            _row(
                event,
                AgentPhase.PREPARE,
                f"Creating isolated worktree at commit {short_commit}",
            ),
        )
    if event.event_type == "agent_execution_started":
        return (_row(event, AgentPhase.PREPARE, "Failure reproduced; Agent execution started"),)
    if event.event_type == "model_request_started":
        turn = _positive_int(metadata.get("model_turn"))
        maximum = _positive_int(metadata.get("max_model_turns"))
        label = f"Model turn {turn}/{maximum}" if turn and maximum else f"Model turn {turn or '?'}"
        if view is TrajectoryView.VERBOSE:
            label += _decision_budget_suffix(metadata)
        return (_row(event, AgentPhase.DECIDE, label, turn=turn),)
    if event.event_type == "tool_call_requested":
        tool = _safe_text(metadata.get("tool_name"), maximum=128) or "unknown_tool"
        arguments = metadata.get("arguments")
        suffix = _format_arguments(tool, arguments if isinstance(arguments, dict) else {}, view)
        suffix += _action_budget_suffix(metadata, view)
        turn = _positive_int(metadata.get("model_turn"))
        return (_row(event, AgentPhase.ACT, tool + suffix, result="REQUESTED", turn=turn),)
    if event.event_type == "tool_execution_completed":
        tool = _safe_text(metadata.get("tool_name"), maximum=128) or "unknown_tool"
        observation = metadata.get("observation")
        action = _format_observation(
            tool,
            observation if isinstance(observation, dict) else {},
            event.status,
            view,
        )
        if view is TrajectoryView.VERBOSE and event.duration is not None:
            action += f"; duration={event.duration:.3f}s"
        turn = _positive_int(metadata.get("model_turn"))
        return (_row(event, AgentPhase.OBSERVE, action, result=event.status, turn=turn),)
    if event.event_type == "patch_attempted":
        patch_attempt = _positive_int(metadata.get("patch_attempt_id")) or 1
        if event.status == "ACCEPTED":
            files = metadata.get("affected_files")
            count = len(files) if isinstance(files, list) else 0
            noun = "file" if count == 1 else "files"
            action = (
                f"Patch attempt {patch_attempt} accepted; "
                f"{count} production {noun} changed"
            )
        else:
            code = _safe_text(metadata.get("error_code"), maximum=100) or event.status
            action = f"Patch attempt {patch_attempt} rejected; error_code={code}"
            remaining = _nonnegative_int(metadata.get("patch_attempts_remaining"))
            if view is TrajectoryView.VERBOSE and remaining is not None:
                action += f"; patches_remaining={remaining}"
        turn = _positive_int(metadata.get("model_turn"))
        return (_row(event, AgentPhase.OBSERVE, action, result=event.status, turn=turn),)
    if event.event_type == "target_test_completed":
        phase = _safe_text(metadata.get("phase"), maximum=20)
        target_attempt = _positive_int(metadata.get("patch_attempt_id"))
        label = "Baseline target test" if phase == "baseline" else "Target test"
        if target_attempt is not None and phase != "baseline":
            label += f" (Patch {target_attempt})"
        return (
            _row(
                event,
                AgentPhase.VERIFY,
                label,
                result=_status_with_duration(event, view),
            ),
        )
    if event.event_type == "regression_test_completed":
        regression_attempt = _positive_int(metadata.get("patch_attempt_id"))
        label = "Regression suite" + (
            f" (Patch {regression_attempt})" if regression_attempt else ""
        )
        return (
            _row(
                event,
                AgentPhase.VERIFY,
                label,
                result=_status_with_duration(event, view),
            ),
        )
    if event.event_type == "agent_replan_requested":
        reasons = _safe_replan_reasons(metadata.get("reasons"))
        reason_set = set(reasons)
        if "REGRESSION_FAILED" in reason_set and "CANDIDATE_REVERTED" in reason_set:
            action = "Candidate reverted; regression diagnostic returned to Agent"
        elif "TARGET_TEST_FAILED" in reason_set and "CANDIDATE_REVERTED" in reason_set:
            action = "Candidate reverted; target-test diagnostic returned to Agent"
        elif "PATCH_REJECTED" in reason_set:
            action = "Patch rejection diagnostic returned to Agent"
        else:
            action = "Verification feedback returned to Agent"
        if reasons:
            action += " reasons=" + ",".join(reasons)
        next_turn = _positive_int(metadata.get("next_model_turn"))
        if view is TrajectoryView.VERBOSE and next_turn is not None:
            action += f" next_turn={next_turn}"
        return (_row(event, AgentPhase.REPLAN, action, result=event.status),)
    if event.event_type == "agent_finished":
        metrics = _finish_metrics(metadata)
        return (_row(event, AgentPhase.FINISH, event.status, result=metrics),)
    return ()


def _row(
    event: SanitizedTraceEvent,
    phase: AgentPhase,
    action: str,
    *,
    result: str = "",
    turn: int | None = None,
) -> TrajectoryRow:
    return TrajectoryRow(
        sequence=event.sequence,
        phase=phase,
        turn=turn,
        action=_safe_text(action, maximum=2_000),
        result=_safe_text(result, maximum=500),
    )


def _text_lines(row: TrajectoryRow) -> list[str]:
    if row.phase is AgentPhase.DECIDE:
        parts = row.action.removeprefix("Model turn ").split("/", maxsplit=1)
        turn_label = parts[0]
        maximum = parts[1] if len(parts) == 2 else None
        heading = (
            f"[TURN {turn_label}/{maximum}] DECIDE"
            if maximum
            else f"[TURN {turn_label}] DECIDE"
        )
        return [heading]
    if row.phase is AgentPhase.ACT:
        return [f"[ACTION]  {row.action}"]
    if row.phase is AgentPhase.VERIFY:
        label = row.action
        dots = "." * max(1, 48 - len(label))
        return [f"[VERIFY]  {label} {dots} {row.result}"]
    if row.phase is AgentPhase.FINISH:
        lines = [f"[FINISH]  {row.action}"]
        if row.result:
            lines.append(f"          {row.result}")
        return lines
    label = f"[{row.phase.value}]"
    return [f"{label} {row.action}"]


def _format_arguments(tool: str, arguments: dict[str, object], view: TrajectoryView) -> str:
    preferred = {
        "list_files": ("path", "max_depth"),
        "search_code": ("query", "path", "file_type"),
        "read_file": ("path", "start_line", "end_line"),
        "apply_patch": ("patch_size", "patch_sha256"),
        "run_target_test": (),
        "git_diff": (),
    }.get(tool, ())
    if view is TrajectoryView.COMPACT and tool == "apply_patch":
        preferred = ("patch_size",)
    rendered: list[str] = []
    for key in preferred:
        if key not in arguments:
            continue
        value = arguments[key]
        if isinstance(value, str):
            safe_value = json.dumps(
                _safe_text(value, maximum=300), ensure_ascii=False
            )
            rendered.append(f"{key}={safe_value}")
        elif value is None or isinstance(value, (bool, int, float)):
            rendered.append(f"{key}={str(value).lower() if isinstance(value, bool) else value}")
    return (" " + " ".join(rendered)) if rendered else ""


def _format_observation(
    tool: str,
    observation: dict[str, object],
    status: str,
    view: TrajectoryView,
) -> str:
    truncated = observation.get("truncated") is True
    if tool == "search_code" and isinstance(observation.get("match_count"), int):
        count = observation["match_count"]
        noun = "match" if count == 1 else "matches"
        return f"search_code returned {count} {noun}; truncated={str(truncated).lower()}"
    if tool == "list_files" and isinstance(observation.get("count"), int):
        return (
            f"list_files returned {observation['count']} files; "
            f"truncated={str(truncated).lower()}"
        )
    if tool == "read_file" and isinstance(observation.get("lines_returned"), int):
        detail = f"read_file returned {observation['lines_returned']} lines"
        if view is TrajectoryView.VERBOSE and isinstance(observation.get("bytes_returned"), int):
            detail += f", {observation['bytes_returned']} bytes"
        return detail + f"; truncated={str(truncated).lower()}"
    code = _safe_text(observation.get("error_code"), maximum=100)
    return f"{tool} returned {status}" + (f"; error_code={code}" if code else "")


def _finish_metrics(metadata: dict[str, object]) -> str:
    turns = _nonnegative_int(metadata.get("model_turns"))
    tools = _nonnegative_int(metadata.get("tool_calls"))
    patches = _nonnegative_int(metadata.get("patch_attempts"))
    duration = metadata.get("duration_seconds")
    duration_text = f"{float(duration):.1f}s" if isinstance(duration, (int, float)) else "unknown"
    return f"turns={turns or 0} tools={tools or 0} patches={patches or 0} duration={duration_text}"


def _safe_replan_reasons(value: object) -> list[str]:
    allowed = {
        "PATCH_REJECTED",
        "TARGET_TEST_FAILED",
        "REGRESSION_FAILED",
        "CANDIDATE_REVERTED",
    }
    if not isinstance(value, list):
        return []
    return [item for item in value[:4] if isinstance(item, str) and item in allowed]


def _positive_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 1 else None


def _nonnegative_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _safe_text(value: object, *, maximum: int) -> str:
    if not isinstance(value, str):
        return ""
    redacted = re.sub(
        r"(?i)authorization\s*:\s*bearer\s+[^\s,;]+",
        "<redacted>",
        value,
    )
    redacted = re.sub(
        r"(?i)\bbearer\s+[A-Za-z0-9._-]{8,}",
        "<redacted>",
        redacted,
    )
    redacted = re.sub(
        r"(?i)\bsk(?:-or)?-[A-Za-z0-9_-]{8,}",
        "<redacted>",
        redacted,
    )
    redacted = re.sub(
        r"(?i)\b(?:OPENAI_API_KEY|OPENROUTER_API_KEY)\s*=\s*[^\s,;]+",
        "<redacted>",
        redacted,
    )
    return " ".join(redacted.replace("\x00", "").split())[:maximum]


def _decision_budget_suffix(metadata: dict[str, object]) -> str:
    tool_calls = _nonnegative_int(metadata.get("tool_calls"))
    max_tools = _positive_int(metadata.get("max_tool_calls"))
    patches = _nonnegative_int(metadata.get("patch_attempts"))
    max_patches = _positive_int(metadata.get("max_patch_attempts"))
    counters: list[str] = []
    if tool_calls is not None and max_tools is not None:
        counters.append(f"tools={tool_calls}/{max_tools}")
    if patches is not None and max_patches is not None:
        counters.append(f"patches={patches}/{max_patches}")
    return " " + " ".join(counters) if counters else ""


def _action_budget_suffix(
    metadata: dict[str, object], view: TrajectoryView
) -> str:
    if view is not TrajectoryView.VERBOSE:
        return ""
    tool_call = _positive_int(metadata.get("tool_call_number"))
    max_tools = _positive_int(metadata.get("max_tool_calls"))
    patches_remaining = _nonnegative_int(metadata.get("patch_attempts_remaining"))
    counters: list[str] = []
    if tool_call is not None and max_tools is not None:
        counters.append(f"tools={tool_call}/{max_tools}")
    if patches_remaining is not None:
        counters.append(f"patches_remaining={patches_remaining}")
    return " " + " ".join(counters) if counters else ""


def _status_with_duration(
    event: SanitizedTraceEvent, view: TrajectoryView
) -> str:
    if view is TrajectoryView.VERBOSE and event.duration is not None:
        return f"{event.status} ({event.duration:.3f}s)"
    return event.status


def _budget_summary(events: Sequence[SanitizedTraceEvent]) -> str:
    metadata = next(
        (
            event.metadata
            for event in events
            if event.event_type == "agent_execution_started"
        ),
        {},
    )
    limits = {
        "turns": metadata.get("max_model_turns"),
        "tools": metadata.get("max_tool_calls"),
        "patches": metadata.get("max_patch_attempts"),
        "target-tests": metadata.get("max_target_test_executions"),
        "regressions": metadata.get("max_regression_executions"),
        "wall-seconds": metadata.get("max_wall_clock_seconds"),
    }
    rendered = [
        f"{name}<={value}"
        for name, value in limits.items()
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0
    ]
    return ", ".join(rendered) if rendered else "not recorded"


def _candidate_target_count(report: RunReport) -> int:
    return report.target_test_execution_count - 1 if report.target_test_execution_count else 0


def _tool_counts_text(counts: dict[str, int]) -> str:
    if not counts:
        return "none"
    return ", ".join(
        f"`{_markdown_text(name, maximum=100)}`={count}"
        for name, count in sorted(counts.items())
    )


def _markdown_text(value: str, *, maximum: int) -> str:
    return _safe_text(value, maximum=maximum).replace("`", "\\`")


def _markdown_cell(value: str) -> str:
    return _safe_text(value, maximum=500).replace("|", "\\|")


def _run_file(run_directory: Path, name: str) -> Path:
    candidate = (run_directory / name).resolve(strict=False)
    if candidate.parent != run_directory:
        raise ValueError(f"{name} escapes run directory")
    if not candidate.is_file():
        raise ValueError(f"completed run is missing {name}")
    return candidate.resolve(strict=True)


def _referenced_run_file(run_directory: Path, path: Path, *, label: str) -> Path:
    candidate = path if path.is_absolute() else run_directory / path
    resolved = candidate.resolve(strict=False)
    if resolved == run_directory or not resolved.is_relative_to(run_directory):
        raise ValueError(f"{label} escapes run directory")
    if not resolved.is_file():
        raise ValueError(f"{label} does not identify a regular run artifact")
    return resolved.resolve(strict=True)


def _prepare_replay_report_payload(
    run_directory: Path,
    payload: object,
) -> object:
    """Preflight portable paths and safely remap coherent legacy absolute reports."""

    if not isinstance(payload, dict):
        return payload
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, dict):
        return payload
    string_artifacts = {
        name: Path(configured)
        for name, configured in artifacts.items()
        if isinstance(name, str) and isinstance(configured, str)
    }
    if len(string_artifacts) != len(artifacts):
        return payload

    if string_artifacts and all(path.is_absolute() for path in string_artifacts.values()):
        parents = {path.parent for path in string_artifacts.values()}
        if len(parents) == 1:
            return _remap_legacy_absolute_report(
                run_directory,
                payload,
                string_artifacts,
                parents.pop(),
            )

    for name, configured_path in string_artifacts.items():
        candidate = (
            configured_path
            if configured_path.is_absolute()
            else run_directory / configured_path
        )
        try:
            resolved = candidate.resolve(strict=False)
        except (OSError, RuntimeError) as exc:
            raise ValueError(f"artifacts[{name!r}] cannot be safely resolved") from exc
        if resolved == run_directory or not resolved.is_relative_to(run_directory):
            raise ValueError(f"artifacts[{name!r}] escapes run directory")
    return payload


def _remap_legacy_absolute_report(
    run_directory: Path,
    payload: dict[str, object],
    artifacts: dict[str, Path],
    legacy_directory: Path,
) -> dict[str, object]:
    """Remap one old all-absolute run only after local identity checks succeed."""

    report_reference = artifacts.get("report")
    trace_reference = artifacts.get("trace")
    if (
        report_reference is None
        or trace_reference is None
        or report_reference.name != "report.json"
        or trace_reference.name != "trace.jsonl"
    ):
        raise ValueError("legacy absolute artifact references are not a coherent run")

    metadata = payload.get("artifact_metadata")
    if not isinstance(metadata, dict):
        raise ValueError("legacy absolute artifact metadata is unavailable")
    rewritten = copy.deepcopy(payload)
    rewritten_artifacts = rewritten.get("artifacts")
    rewritten_metadata = rewritten.get("artifact_metadata")
    if not isinstance(rewritten_artifacts, dict) or not isinstance(rewritten_metadata, dict):
        raise ValueError("legacy absolute artifact metadata is malformed")

    relative_names: set[Path] = set()
    for name, configured in artifacts.items():
        try:
            relative = configured.relative_to(legacy_directory)
        except ValueError as exc:
            raise ValueError("legacy absolute artifacts do not share one run directory") from exc
        if not relative.parts or ".." in relative.parts or relative in relative_names:
            raise ValueError("legacy absolute artifact references are ambiguous")
        relative_names.add(relative)
        candidate = _referenced_run_file(
            run_directory,
            relative,
            label=f"artifacts[{name!r}]",
        )
        rewritten_artifacts[name] = relative.as_posix()
        if name == "report":
            continue

        raw_metadata = metadata.get(name)
        if not isinstance(raw_metadata, dict):
            raise ValueError(f"legacy artifact metadata is missing for {name}")
        metadata_path = raw_metadata.get("path")
        expected_size = raw_metadata.get("size_bytes")
        expected_sha256 = raw_metadata.get("sha256")
        if (
            not isinstance(metadata_path, str)
            or Path(metadata_path) != configured
            or isinstance(expected_size, bool)
            or not isinstance(expected_size, int)
            or expected_size < 0
            or not isinstance(expected_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None
        ):
            raise ValueError(f"legacy artifact metadata is inconsistent for {name}")
        size, digest = _hash_file(candidate)
        if size != expected_size or digest != expected_sha256:
            raise ValueError(f"artifact metadata checksum is inconsistent for {name}")
        rewritten_entry = rewritten_metadata.get(name)
        if not isinstance(rewritten_entry, dict):
            raise ValueError(f"legacy artifact metadata is malformed for {name}")
        rewritten_entry["path"] = relative.as_posix()
    return rewritten


def _hash_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()
