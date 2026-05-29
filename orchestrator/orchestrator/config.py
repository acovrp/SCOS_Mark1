"""Runtime configuration and budgets.

Budgets exist to make runaway impossible: a task that cannot pass its gate
within `max_attempts_per_task` is reverted and marked BLOCKED rather than
spinning forever.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Config:
    # Where persistent orchestrator state lives (backlog, decisions, journal).
    state_dir: Path = Path(".orchestrator")
    # Where the target app is built. Kept separate from the orchestrator's own
    # source, and managed as its own git repo so we never touch the host repo.
    workspace_dir: Path = Path("build")

    # Backend: "stub" (deterministic, offline) or "claude" (Claude Agent SDK).
    llm: str = "stub"
    model: str = "claude-opus-4-8"

    # Where the human gate sits. "task" = approve every task (safest),
    # "story" = approve at story boundaries, "epic" = approve at epic boundaries.
    autonomy: str = "story"

    # Guardrails / budgets.
    max_attempts_per_task: int = 2

    # When True, human gates auto-approve (CI / non-interactive runs / tests).
    auto_approve: bool = False

    extra: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.state_dir = Path(self.state_dir)
        self.workspace_dir = Path(self.workspace_dir)
