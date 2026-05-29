"""The contract every backend (stub or Claude) must satisfy.

Each method maps to a role agent from the architecture:
  plan      -> Planner
  clarify   -> Clarifier
  implement -> Implementer (writes files into the workspace)
  review    -> Reviewer
  retro     -> Retro

The machine drives these in a fixed order with gates between them; the backend
supplies only the intelligence, never the control flow.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from ..models import Backlog, Question, Task


@dataclass
class ImplementResult:
    summary: str
    files_changed: list[str] = field(default_factory=list)


@dataclass
class ReviewResult:
    approved: bool
    findings: list[str] = field(default_factory=list)


class LLMBackend(Protocol):
    name: str

    def plan(self, spec: str) -> Backlog:
        """Decompose the spec into an epic/story/task DAG."""

    def clarify(self, spec: str, backlog: Backlog) -> list[Question]:
        """Surface ambiguities to resolve before any code is written."""

    def implement(self, task: Task, workspace: Path, decisions: str) -> ImplementResult:
        """Apply the change for `task` inside `workspace` (side effects on disk)."""

    def review(self, task: Task, workspace: Path, gate_output: str) -> ReviewResult:
        """Review the implemented change before it is committed."""

    def retro(self, backlog: Backlog) -> str:
        """Reflect on the sprint and suggest plan adjustments."""
