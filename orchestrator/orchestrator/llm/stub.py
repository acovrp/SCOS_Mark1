"""Deterministic, offline backend.

Its entire purpose is to let you exercise — and unit-test — the orchestration
machinery (planning -> clarify -> implement -> gate -> commit/revert -> resume)
without any network or API key. Tasks are self-contained: each carries an
`action` (files to write) and a `test_cmd` (its gate). The Claude backend
replaces this with real reasoning while the machine stays identical.
"""
from __future__ import annotations

from pathlib import Path

from ..models import Backlog, Epic, Question, Risk, Story, Task
from .base import ImplementResult, ReviewResult

# A tiny but real "app": a greet() function and a CLI that uses it. Each task
# ships a module + a self-checking test script (python <test> exits non-zero on
# failure), so the gate is genuine.
_GREET_PY = 'def greet(name="world"):\n    return f"hello, {name}"\n'
_GREET_TEST = (
    "from greet import greet\n"
    "assert greet() == 'hello, world'\n"
    "assert greet('ada') == 'hello, ada'\n"
    "print('greet ok')\n"
)
_CLI_PY = (
    "import sys\n"
    "from greet import greet\n\n"
    "def main(argv=None):\n"
    "    argv = sys.argv[1:] if argv is None else argv\n"
    "    name = argv[0] if argv else 'world'\n"
    "    return greet(name)\n\n"
    'if __name__ == "__main__":\n'
    "    print(main())\n"
)
_CLI_TEST = (
    "from main import main\n"
    "assert main([]) == 'hello, world'\n"
    "assert main(['sam']) == 'hello, sam'\n"
    "print('cli ok')\n"
)


class StubBackend:
    name = "stub"

    def plan(self, spec: str) -> Backlog:
        t1 = Task(
            id="T1",
            title="Greeting core",
            description="Pure function greet(name) -> 'hello, <name>'.",
            acceptance_criteria=["greet() returns 'hello, world'", "greet(x) returns 'hello, x'"],
            risk=Risk.LOW,
            files=["greet.py", "test_greet.py"],
            action={"files": {"greet.py": _GREET_PY, "test_greet.py": _GREET_TEST}},
            test_cmd=["python", "test_greet.py"],
        )
        t2 = Task(
            id="T2",
            title="CLI entrypoint",
            description="CLI that prints the greeting for argv[0].",
            acceptance_criteria=["`main([])` -> 'hello, world'", "`main(['x'])` -> 'hello, x'"],
            depends_on=["T1"],
            risk=Risk.LOW,
            files=["main.py", "test_main.py"],
            action={"files": {"main.py": _CLI_PY, "test_main.py": _CLI_TEST}},
            test_cmd=["python", "test_main.py"],
        )
        story = Story(id="S1", title="Core greeting feature", tasks=[t1, t2])
        epic = Epic(id="E1", title="Walking Skeleton", stories=[story])
        return Backlog(epics=[epic])

    def clarify(self, spec: str, backlog: Backlog) -> list[Question]:
        return [
            Question(
                id="Q1",
                text="Should the greeting be localized, or English-only for v1?",
                why="Determines whether greet() needs a locale parameter now.",
            ),
            Question(
                id="Q2",
                text="Is a CLI the only interface for v1, or is an HTTP endpoint also in scope?",
                why="Affects whether we add a web layer this sprint.",
            ),
        ]

    def implement(self, task: Task, workspace: Path, decisions: str) -> ImplementResult:
        files = task.action.get("files", {})
        for rel, content in files.items():
            dest = workspace / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content)
        return ImplementResult(
            summary=f"wrote {len(files)} file(s) for {task.id}",
            files_changed=list(files.keys()),
        )

    def review(self, task: Task, workspace: Path, gate_output: str) -> ReviewResult:
        # The gate already passed by the time review runs; the stub rubber-stamps.
        return ReviewResult(approved=True, findings=[])

    def retro(self, backlog: Backlog) -> str:
        p = backlog.progress()
        return f"Sprint complete: {p['done']}/{p['total']} tasks done, {p['blocked']} blocked."
