"""Core data model: the backlog as a dependency-ordered hierarchy.

Epic -> Story -> Task. A Task is the unit of progress: nothing counts as done
until it is implemented, gated (tests pass), and committed.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Optional


class TaskStatus(str, Enum):
    TODO = "todo"
    DOING = "doing"
    DONE = "done"
    BLOCKED = "blocked"  # gate failed after exhausting retries; workspace reverted


class Risk(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class Task:
    id: str
    title: str
    description: str = ""
    acceptance_criteria: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    risk: Risk = Risk.LOW
    files: list[str] = field(default_factory=list)
    status: TaskStatus = TaskStatus.TODO
    attempts: int = 0
    # `action` is used by the offline stub backend to make the task self-contained
    # (a deterministic set of files to write). The Claude backend ignores it and
    # produces real edits via the SDK instead.
    action: dict = field(default_factory=dict)
    # Command (argv list) run as the per-task gate, relative to the workspace.
    test_cmd: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["risk"] = self.risk.value
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Task":
        d = dict(d)
        d["risk"] = Risk(d.get("risk", "low"))
        d["status"] = TaskStatus(d.get("status", "todo"))
        return cls(**d)


@dataclass
class Story:
    id: str
    title: str
    tasks: list[Task] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"id": self.id, "title": self.title, "tasks": [t.to_dict() for t in self.tasks]}

    @classmethod
    def from_dict(cls, d: dict) -> "Story":
        return cls(id=d["id"], title=d["title"], tasks=[Task.from_dict(t) for t in d.get("tasks", [])])


@dataclass
class Epic:
    id: str
    title: str
    stories: list[Story] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"id": self.id, "title": self.title, "stories": [s.to_dict() for s in self.stories]}

    @classmethod
    def from_dict(cls, d: dict) -> "Epic":
        return cls(id=d["id"], title=d["title"], stories=[Story.from_dict(s) for s in d.get("stories", [])])


@dataclass
class Backlog:
    epics: list[Epic] = field(default_factory=list)

    # --- traversal helpers ---
    def all_tasks(self) -> list[Task]:
        return [t for e in self.epics for s in e.stories for t in s.tasks]

    def all_stories(self) -> list[Story]:
        return [s for e in self.epics for s in e.stories]

    def find_task(self, task_id: str) -> Optional[Task]:
        for t in self.all_tasks():
            if t.id == task_id:
                return t
        return None

    def story_of(self, task_id: str) -> Optional[Story]:
        for s in self.all_stories():
            if any(t.id == task_id for t in s.tasks):
                return s
        return None

    def topological_tasks(self) -> list[Task]:
        """Return tasks in dependency order. Raises on cycles."""
        tasks = {t.id: t for t in self.all_tasks()}
        ordered: list[Task] = []
        visiting: set[str] = set()
        done: set[str] = set()

        def visit(tid: str) -> None:
            if tid in done:
                return
            if tid in visiting:
                raise ValueError(f"dependency cycle detected at task {tid}")
            visiting.add(tid)
            for dep in tasks[tid].depends_on:
                if dep in tasks:
                    visit(dep)
            visiting.discard(tid)
            done.add(tid)
            ordered.append(tasks[tid])

        for tid in tasks:
            visit(tid)
        return ordered

    def progress(self) -> dict:
        tasks = self.all_tasks()
        counts = {s.value: 0 for s in TaskStatus}
        for t in tasks:
            counts[t.status.value] += 1
        counts["total"] = len(tasks)
        return counts

    # --- serialization ---
    def to_dict(self) -> dict:
        return {"epics": [e.to_dict() for e in self.epics]}

    @classmethod
    def from_dict(cls, d: dict) -> "Backlog":
        return cls(epics=[Epic.from_dict(e) for e in d.get("epics", [])])

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_json(cls, text: str) -> "Backlog":
        return cls.from_dict(json.loads(text))


@dataclass
class Question:
    id: str
    text: str
    why: str = ""  # why this matters / what it unblocks
    answer: Optional[str] = None
