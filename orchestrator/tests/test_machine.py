"""End-to-end tests for the orchestration machinery, all offline via the stub.

These prove the properties that matter for "no surprises, no breaking":
  - happy path builds verified, committed increments
  - a task that can't pass its gate is reverted and BLOCKED (workspace stays clean)
  - DONE tasks are skipped on resume
"""
from pathlib import Path

from orchestrator.config import Config
from orchestrator.machine import Orchestrator
from orchestrator.models import (
    Backlog,
    Epic,
    Question,
    Story,
    Task,
    TaskStatus,
)

PRD = "Build a greeting tool."
PLAN = "Python. A greet() function and a CLI."


def _cfg(tmp_path: Path, **kw) -> Config:
    return Config(
        state_dir=tmp_path / ".orchestrator",
        workspace_dir=tmp_path / "build",
        llm="stub",
        auto_approve=True,
        **kw,
    )


def test_happy_path_builds_and_commits(tmp_path: Path):
    orch = Orchestrator(_cfg(tmp_path))
    report = orch.run(PRD, PLAN)

    backlog = orch.store.load_backlog()
    assert all(t.status == TaskStatus.DONE for t in backlog.all_tasks())
    assert report.blocked == 0
    # Real artifacts exist in the workspace...
    assert (tmp_path / "build" / "greet.py").exists()
    assert (tmp_path / "build" / "main.py").exists()
    # ...and each task produced a commit.
    log = orch.git.log_oneline()
    assert "T1" in log and "T2" in log
    # Decisions + spec were persisted.
    assert orch.store.spec_path.exists()
    assert orch.store.decisions_path.exists()


def test_resume_skips_done_tasks(tmp_path: Path):
    orch = Orchestrator(_cfg(tmp_path))
    orch.run(PRD, PLAN)
    # Second pass: everything is DONE, so nothing new is built, no errors.
    report = orch.execute()
    assert report.done == 0  # nothing re-done
    backlog = orch.store.load_backlog()
    assert all(t.status == TaskStatus.DONE for t in backlog.all_tasks())


class _FailingBackend:
    """A backend whose single task can never pass its gate."""

    name = "failing"

    def plan(self, spec: str) -> Backlog:
        task = Task(
            id="TX",
            title="doomed task",
            files=["broken.py"],
            action={"files": {"broken.py": "# half-baked\n"}},
            test_cmd=["python", "-c", "import sys; sys.exit(1)"],
        )
        return Backlog(epics=[Epic(id="E1", title="e", stories=[Story(id="S1", title="s", tasks=[task])])])

    def clarify(self, spec, backlog):
        return []

    def implement(self, task, workspace, decisions):
        for rel, content in task.action.get("files", {}).items():
            (Path(workspace) / rel).write_text(content)
        from orchestrator.llm.base import ImplementResult

        return ImplementResult(summary="wrote broken file", files_changed=["broken.py"])

    def review(self, task, workspace, gate_output):
        from orchestrator.llm.base import ReviewResult

        return ReviewResult(approved=True)

    def retro(self, backlog):
        return "retro"


def test_failed_gate_reverts_and_blocks(tmp_path: Path):
    cfg = _cfg(tmp_path, max_attempts_per_task=2)
    orch = Orchestrator(cfg, backend=_FailingBackend())
    report = orch.run(PRD, PLAN)

    backlog = orch.store.load_backlog()
    task = backlog.find_task("TX")
    assert task.status == TaskStatus.BLOCKED
    assert task.attempts == 2  # exhausted the budget
    assert report.blocked == 1
    # Crucial: the broken increment was reverted — workspace is clean.
    assert not (tmp_path / "build" / "broken.py").exists()


def test_question_answers_recorded(tmp_path: Path):
    answers = {"Q1": "English only", "Q2": "CLI only"}
    orch = Orchestrator(
        _cfg(tmp_path),
        asker=lambda q: answers.get(q.id, "default"),
    )
    orch.ingest(PRD, PLAN)
    orch.plan()
    qs = orch.clarify()
    assert {q.id for q in qs} == {"Q1", "Q2"}
    decisions = orch.store.decisions_path.read_text()
    assert "English only" in decisions and "CLI only" in decisions
