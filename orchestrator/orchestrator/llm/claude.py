"""Claude Agent SDK backend — the real intelligence.

This reuses Anthropic's agent loop (tool use, file editing, multi-step
reasoning) and confines it to a single responsibility per call. The state
machine still owns the control flow; Claude only fills in each step.

Requires:  pip install claude-agent-sdk   and  ANTHROPIC_API_KEY in the env.

Note: methods that need structured output ask for JSON and parse it
defensively. `implement` runs an agent with file tools whose working directory
is the build workspace, so edits land exactly where the gate will check them.
"""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from ..models import Backlog, Question, Task
from .base import ImplementResult, ReviewResult


def _require_sdk():
    try:
        import claude_agent_sdk  # noqa: F401
    except ImportError as e:  # pragma: no cover - depends on optional dep
        raise RuntimeError(
            "The 'claude' backend needs the Claude Agent SDK.\n"
            "  pip install claude-agent-sdk\n"
            "and set ANTHROPIC_API_KEY. Until then, run with --llm stub."
        ) from e
    return claude_agent_sdk


def _extract_json(text: str) -> dict:
    """Pull the first JSON object out of a model response."""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise ValueError(f"no JSON found in model output:\n{text[:500]}")
    return json.loads(m.group(0))


class ClaudeBackend:
    name = "claude"

    def __init__(self, model: str = "claude-opus-4-8"):
        self.model = model
        self._sdk = _require_sdk()

    # --- low level: one-shot text completion via the agent SDK ---
    async def _ask(self, prompt: str, cwd: Path | None = None, allow_edits: bool = False) -> str:
        sdk = self._sdk
        options_kwargs: dict = {"model": self.model}
        if cwd is not None:
            options_kwargs["cwd"] = str(cwd)
        if allow_edits:
            options_kwargs["allowed_tools"] = ["Read", "Write", "Edit", "Bash"]
            options_kwargs["permission_mode"] = "acceptEdits"
        options = sdk.ClaudeAgentOptions(**options_kwargs)

        chunks: list[str] = []
        async for message in sdk.query(prompt=prompt, options=options):
            text = getattr(message, "text", None)
            if text:
                chunks.append(text)
            for block in getattr(message, "content", []) or []:
                btext = getattr(block, "text", None)
                if btext:
                    chunks.append(btext)
        return "".join(chunks)

    def _run(self, coro):
        return asyncio.run(coro)

    # --- role agents ---
    def plan(self, spec: str) -> Backlog:
        prompt = (
            "You are the Planner. Decompose this spec into an agile backlog.\n"
            "Return ONLY JSON shaped like: {\"epics\":[{\"id\":\"E1\",\"title\":..,"
            "\"stories\":[{\"id\":\"S1\",\"title\":..,\"tasks\":[{\"id\":\"T1\","
            "\"title\":..,\"description\":..,\"acceptance_criteria\":[..],"
            "\"depends_on\":[..],\"risk\":\"low|medium|high\",\"files\":[..],"
            "\"test_cmd\":[\"...\"]}]}]}]}.\n"
            "Tasks must be small, independently verifiable, and ordered by depends_on.\n\n"
            f"SPEC:\n{spec}"
        )
        data = _extract_json(self._run(self._ask(prompt)))
        return Backlog.from_dict(data)

    def clarify(self, spec: str, backlog: Backlog) -> list[Question]:
        prompt = (
            "You are the Clarifier. List the open questions that must be answered "
            "BEFORE writing code. Return ONLY JSON: {\"questions\":[{\"id\":\"Q1\","
            "\"text\":..,\"why\":..}]}.\n\n"
            f"SPEC:\n{spec}\n\nBACKLOG:\n{backlog.to_json()}"
        )
        data = _extract_json(self._run(self._ask(prompt)))
        return [Question(**q) for q in data.get("questions", [])]

    def implement(self, task: Task, workspace: Path, decisions: str) -> ImplementResult:
        prompt = (
            "You are the Implementer. Implement exactly this task in the current "
            "working directory. Keep the change minimal and write tests so the gate "
            f"command `{' '.join(task.test_cmd) or '(define one)'}` passes.\n\n"
            f"TASK {task.id}: {task.title}\n{task.description}\n"
            f"ACCEPTANCE:\n- " + "\n- ".join(task.acceptance_criteria) + "\n\n"
            f"DECISIONS SO FAR:\n{decisions}"
        )
        out = self._run(self._ask(prompt, cwd=workspace, allow_edits=True))
        return ImplementResult(summary=out[:500], files_changed=task.files)

    def review(self, task: Task, workspace: Path, gate_output: str) -> ReviewResult:
        prompt = (
            "You are the Reviewer. The gate already passed. Review the change for "
            "correctness, scope creep, and acceptance-criteria coverage. Return ONLY "
            "JSON: {\"approved\":true|false,\"findings\":[..]}.\n\n"
            f"TASK {task.id}: {task.title}\nGATE OUTPUT:\n{gate_output[:2000]}"
        )
        data = _extract_json(self._run(self._ask(prompt, cwd=workspace)))
        return ReviewResult(approved=bool(data.get("approved")), findings=data.get("findings", []))

    def retro(self, backlog: Backlog) -> str:
        prompt = (
            "You are the Retro agent. Given this backlog state, summarize what was "
            "completed, what is blocked, and concrete plan adjustments for next sprint.\n\n"
            f"{backlog.to_json()}"
        )
        return self._run(self._ask(prompt))
