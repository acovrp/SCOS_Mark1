"""Command-line entrypoint.

  python -m orchestrator init  --prd PRD.md --eng-plan PLAN.md
  python -m orchestrator plan          # generate backlog, then review it
  python -m orchestrator clarify       # answer open questions
  python -m orchestrator run           # full pipeline (ingest if files given)
  python -m orchestrator status        # show live backlog progress
  python -m orchestrator resume        # continue execution from saved state

Global flags: --llm {stub,claude} --autonomy {task,story,epic}
              --state-dir DIR --workspace DIR --model NAME --yes
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import Config
from .machine import Orchestrator
from .models import TaskStatus


def _config_from_args(a: argparse.Namespace) -> Config:
    return Config(
        state_dir=Path(a.state_dir),
        workspace_dir=Path(a.workspace),
        llm=a.llm,
        model=a.model,
        autonomy=a.autonomy,
        auto_approve=a.yes,
    )


def _print_status(orch: Orchestrator) -> None:
    backlog = orch.store.load_backlog()
    if backlog is None:
        print("no backlog yet — run `plan`")
        return
    glyph = {
        TaskStatus.DONE: "[x]",
        TaskStatus.BLOCKED: "[!]",
        TaskStatus.DOING: "[~]",
        TaskStatus.TODO: "[ ]",
    }
    for epic in backlog.epics:
        print(f"\nEPIC {epic.id}: {epic.title}")
        for story in epic.stories:
            print(f"  STORY {story.id}: {story.title}")
            for t in story.tasks:
                print(f"    {glyph[t.status]} {t.id} {t.title}")
    p = backlog.progress()
    print(f"\n{p['done']}/{p['total']} done, {p['blocked']} blocked, {p['todo']} todo")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="orchestrator", description="AI Agile Orchestrator")
    parser.add_argument("--llm", default="stub", choices=["stub", "claude"])
    parser.add_argument("--model", default="claude-opus-4-8")
    parser.add_argument("--autonomy", default="story", choices=["task", "story", "epic"])
    parser.add_argument("--state-dir", default=".orchestrator")
    parser.add_argument("--workspace", default="build")
    parser.add_argument("--yes", action="store_true", help="auto-approve all gates (non-interactive)")

    sub = parser.add_subparsers(dest="cmd", required=True)
    p_init = sub.add_parser("init", help="ingest PRD + engineering plan")
    p_init.add_argument("--prd", required=True)
    p_init.add_argument("--eng-plan", required=True)
    sub.add_parser("plan", help="generate the backlog")
    sub.add_parser("clarify", help="resolve open questions")
    p_run = sub.add_parser("run", help="run the full pipeline")
    p_run.add_argument("--prd")
    p_run.add_argument("--eng-plan")
    sub.add_parser("status", help="show backlog progress")
    sub.add_parser("resume", help="continue execution")

    a = parser.parse_args(argv)
    cfg = _config_from_args(a)
    orch = Orchestrator(cfg)

    if a.cmd == "init":
        orch.ingest(Path(a.prd).read_text(), Path(a.eng_plan).read_text())
        print(f"wrote {orch.store.spec_path}")
    elif a.cmd == "plan":
        backlog = orch.plan()
        print(f"planned {backlog.progress()['total']} tasks")
        _print_status(orch)
    elif a.cmd == "clarify":
        qs = orch.clarify()
        print(f"resolved {len(qs)} question(s) -> {orch.store.decisions_path}")
    elif a.cmd == "run":
        prd = Path(a.prd).read_text() if a.prd else None
        plan = Path(a.eng_plan).read_text() if a.eng_plan else None
        report = orch.run(prd, plan)
        _print_status(orch)
        if report.paused_at:
            print(f"\nPAUSED at {report.paused_at} — re-run `resume` after review.")
        print(orch.retro())
    elif a.cmd == "status":
        _print_status(orch)
    elif a.cmd == "resume":
        report = orch.execute()
        _print_status(orch)
        if report.paused_at:
            print(f"\nPAUSED at {report.paused_at}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
