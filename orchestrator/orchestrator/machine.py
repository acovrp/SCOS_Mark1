"""The Orchestrator: a deterministic state machine over the backlog.

Pipeline:  INGEST -> PLAN -> [human gate] -> CLARIFY -> [human gate]
           -> EXECUTE (per task: branch, implement, gate, commit | revert)
           -> RETRO

Human gates sit at the altitude chosen by `config.autonomy`:
  "task"  -> approve before each task
  "story" -> autonomously build a story, then approve its merge
  "epic"  -> autonomously build an epic, then approve its merge

Everything is resumable: DONE tasks are skipped on re-run because status lives
in backlog.json on disk.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from .config import Config
from .gates import run_gate
from .git_ops import GitWorkspace
from .llm import LLMBackend, make_backend
from .models import Backlog, Question, Story, Task, TaskStatus
from .state import Store

# A human gate: given a prompt, return True to proceed.
Approver = Callable[[str], bool]
# A question asker: given a Question, return the answer string.
Asker = Callable[[Question], str]


def _auto_approve(_: str) -> bool:
    return True


def _auto_answer(q: Question) -> str:
    return "(deferred — using sensible default)"


@dataclass
class RunReport:
    planned: int = 0
    done: int = 0
    blocked: int = 0
    paused_at: Optional[str] = None
    notes: list[str] = field(default_factory=list)


class Orchestrator:
    def __init__(
        self,
        config: Config,
        approver: Optional[Approver] = None,
        asker: Optional[Asker] = None,
        backend: Optional[LLMBackend] = None,
    ):
        self.cfg = config
        self.store = Store(config.state_dir)
        self.backend = backend or make_backend(config)
        self.git = GitWorkspace(config.workspace_dir)
        self.approve: Approver = approver or (_auto_approve if config.auto_approve else _prompt_approver)
        self.ask: Asker = asker or (_auto_answer if config.auto_approve else _prompt_asker)

    # ---------- INGEST ----------
    def ingest(self, prd: str, eng_plan: str) -> str:
        spec = (
            "# Canonical Spec\n\n"
            "_Normalized from the PRD and engineering plan. Source of truth for planning._\n\n"
            "## Product Requirements (PRD)\n\n"
            f"{prd.strip()}\n\n"
            "## Engineering Plan\n\n"
            f"{eng_plan.strip()}\n"
        )
        self.store.save_spec(spec)
        self.store.log("INGEST: wrote canonical spec.md")
        return spec

    # ---------- PLAN ----------
    def plan(self) -> Backlog:
        spec = self.store.load_spec()
        if spec is None:
            raise RuntimeError("no spec.md — run ingest first")
        backlog = self.backend.plan(spec)
        self.store.save_backlog(backlog)
        p = backlog.progress()
        self.store.log(f"PLAN: {p['total']} tasks across {len(backlog.epics)} epic(s)")
        return backlog

    # ---------- CLARIFY ----------
    def clarify(self) -> list[Question]:
        spec = self.store.load_spec() or ""
        backlog = self._load_backlog()
        questions = self.backend.clarify(spec, backlog)
        for q in questions:
            q.answer = self.ask(q)
            self.store.record_decision(q)
        self.store.log(f"CLARIFY: resolved {len(questions)} question(s)")
        return questions

    # ---------- EXECUTE ----------
    def execute(self) -> RunReport:
        backlog = self._load_backlog()
        report = RunReport(planned=backlog.progress()["total"])
        self.git.ensure_repo()
        # Global dependency order; used to sequence tasks within each story.
        topo = {t.id: i for i, t in enumerate(backlog.topological_tasks())}
        decisions = self.store.decisions_path.read_text() if self.store.decisions_path.exists() else ""

        for epic in backlog.epics:
            for story in epic.stories:
                ok = self._run_story(story, backlog, topo, decisions, report)
                if not ok:
                    self._save(backlog)
                    return report  # paused or blocked -> stop cleanly, resumable
                # Story-level gate (also covers "task" autonomy).
                if self.cfg.autonomy in ("task", "story"):
                    if not self._merge_gate(f"story {story.id} ({story.title})"):
                        report.paused_at = story.id
                        self._save(backlog)
                        return report
                    self.git.merge_ff(f"story/{story.id}")
                    self.store.log(f"MERGE: story/{story.id} -> integration")
            if self.cfg.autonomy == "epic":
                if not self._merge_gate(f"epic {epic.id} ({epic.title})"):
                    report.paused_at = epic.id
                    self._save(backlog)
                    return report
                for story in epic.stories:
                    self.git.merge_ff(f"story/{story.id}")
                self.store.log(f"MERGE: epic {epic.id} stories -> integration")

        self._save(backlog)
        # report.done / report.blocked reflect work performed in THIS run
        # (incremented as tasks complete), not cumulative backlog state.
        return report

    def _run_story(self, story: Story, backlog: Backlog, topo: dict, decisions: str, report: RunReport) -> bool:
        self.git.checkout_branch(f"story/{story.id}")
        for task in sorted(story.tasks, key=lambda t: topo.get(t.id, 0)):
            if task.status == TaskStatus.DONE:
                continue  # resume: already built
            if self.cfg.autonomy == "task":
                if not self.approve(f"start task {task.id} ({task.title})?"):
                    report.paused_at = task.id
                    return False
            if not self._run_task(task, decisions, report):
                return False  # blocked -> stop
        return True

    def _run_task(self, task: Task, decisions: str, report: RunReport) -> bool:
        pre_sha = self.git.current_sha()
        task.status = TaskStatus.DOING
        for attempt in range(1, self.cfg.max_attempts_per_task + 1):
            task.attempts = attempt
            self.backend.implement(task, self.cfg.workspace_dir, decisions)
            gate = run_gate([task.test_cmd] if task.test_cmd else [], self.cfg.workspace_dir)
            if gate.passed:
                review = self.backend.review(task, self.cfg.workspace_dir, gate.output)
                if not review.approved:
                    self.store.log(f"REVIEW rejected {task.id}: {review.findings}")
                    self.git.reset_hard(pre_sha)
                    continue
                self.git.commit_all(f"{task.id}: {task.title}")
                task.status = TaskStatus.DONE
                report.done += 1
                self.store.log(f"DONE {task.id} (attempt {attempt})")
                return True
            self.store.log(f"GATE failed {task.id} attempt {attempt}")
            self.git.reset_hard(pre_sha)  # revert the broken increment
        # Exhausted retries -> block and leave workspace clean.
        task.status = TaskStatus.BLOCKED
        report.blocked += 1
        report.notes.append(f"{task.id} blocked after {self.cfg.max_attempts_per_task} attempts")
        self.store.log(f"BLOCKED {task.id}")
        return False

    # ---------- RETRO ----------
    def retro(self) -> str:
        backlog = self._load_backlog()
        summary = self.backend.retro(backlog)
        self.store.log(f"RETRO: {summary}")
        return summary

    # ---------- full pipeline ----------
    def run(self, prd: Optional[str] = None, eng_plan: Optional[str] = None) -> RunReport:
        if prd is not None and eng_plan is not None:
            self.ingest(prd, eng_plan)
        if not self.store.has_backlog():
            self.plan()
            self.clarify()
        return self.execute()

    # ---------- helpers ----------
    def _merge_gate(self, what: str) -> bool:
        return self.approve(f"review complete for {what} — merge to integration?")

    def _load_backlog(self) -> Backlog:
        backlog = self.store.load_backlog()
        if backlog is None:
            raise RuntimeError("no backlog.json — run plan first")
        return backlog

    def _save(self, backlog: Backlog) -> None:
        self.store.save_backlog(backlog)


def _prompt_approver(prompt: str) -> bool:  # pragma: no cover - interactive
    return input(f"[gate] {prompt} [y/N] ").strip().lower() in ("y", "yes")


def _prompt_asker(q: Question) -> str:  # pragma: no cover - interactive
    print(f"\n[question {q.id}] {q.text}\n  why: {q.why}")
    return input("  answer> ").strip()
