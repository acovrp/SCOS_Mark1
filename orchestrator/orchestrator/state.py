"""Persistent state — the source of truth lives on disk, not in context.

The orchestrator can be killed at any moment and resume perfectly because
everything it needs is here:

  spec.md        canonical, normalized spec (PRD + eng plan merged)
  backlog.json   the DAG of epics/stories/tasks with live status
  decisions.md   ADR-style log of every question the human answered
  journal.md     append-only event log (what happened, when)
"""
from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Optional

from .models import Backlog, Question


class Store:
    def __init__(self, state_dir: Path):
        self.dir = Path(state_dir)
        self.dir.mkdir(parents=True, exist_ok=True)

    # --- paths ---
    @property
    def spec_path(self) -> Path:
        return self.dir / "spec.md"

    @property
    def backlog_path(self) -> Path:
        return self.dir / "backlog.json"

    @property
    def decisions_path(self) -> Path:
        return self.dir / "decisions.md"

    @property
    def journal_path(self) -> Path:
        return self.dir / "journal.md"

    # --- spec ---
    def save_spec(self, text: str) -> None:
        self.spec_path.write_text(text)

    def load_spec(self) -> Optional[str]:
        return self.spec_path.read_text() if self.spec_path.exists() else None

    # --- backlog ---
    def save_backlog(self, backlog: Backlog) -> None:
        self.backlog_path.write_text(backlog.to_json())

    def load_backlog(self) -> Optional[Backlog]:
        if not self.backlog_path.exists():
            return None
        return Backlog.from_json(self.backlog_path.read_text())

    def has_backlog(self) -> bool:
        return self.backlog_path.exists()

    # --- decisions (ADR log) ---
    def record_decision(self, q: Question) -> None:
        ts = _now()
        block = (
            f"\n## {q.id} — {q.text}\n"
            f"- _asked:_ {ts}\n"
            f"- _why:_ {q.why or 'n/a'}\n"
            f"- **answer:** {q.answer if q.answer is not None else '(unanswered)'}\n"
        )
        _append(self.decisions_path, block, header="# Decision Log\n")

    # --- journal ---
    def log(self, event: str) -> None:
        _append(self.journal_path, f"- `{_now()}` {event}\n", header="# Journal\n")


def _now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def _append(path: Path, text: str, header: str = "") -> None:
    if not path.exists() and header:
        path.write_text(header)
    with path.open("a") as f:
        f.write(text)
