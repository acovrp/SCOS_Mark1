from pathlib import Path

from orchestrator.models import Backlog, Epic, Question, Risk, Story, Task, TaskStatus
from orchestrator.state import Store


def _backlog() -> Backlog:
    t1 = Task(id="T1", title="a", risk=Risk.LOW)
    t2 = Task(id="T2", title="b", depends_on=["T1"], status=TaskStatus.DONE)
    return Backlog(epics=[Epic(id="E1", title="e", stories=[Story(id="S1", title="s", tasks=[t1, t2])])])


def test_backlog_roundtrip():
    b = _backlog()
    restored = Backlog.from_json(b.to_json())
    assert restored.find_task("T2").status == TaskStatus.DONE
    assert restored.find_task("T1").risk == Risk.LOW
    assert [t.id for t in restored.topological_tasks()] == ["T1", "T2"]


def test_topological_detects_cycle():
    a = Task(id="A", title="a", depends_on=["B"])
    b = Task(id="B", title="b", depends_on=["A"])
    bl = Backlog(epics=[Epic(id="E", title="e", stories=[Story(id="S", title="s", tasks=[a, b])])])
    try:
        bl.topological_tasks()
        assert False, "expected cycle error"
    except ValueError:
        pass


def test_progress_counts():
    p = _backlog().progress()
    assert p["total"] == 2 and p["done"] == 1 and p["todo"] == 1


def test_store_persists(tmp_path: Path):
    store = Store(tmp_path / ".orch")
    store.save_spec("hello")
    store.save_backlog(_backlog())
    store.record_decision(Question(id="Q1", text="why?", why="because", answer="yes"))
    store.log("an event")
    assert store.load_spec() == "hello"
    assert store.load_backlog().find_task("T1") is not None
    assert "Q1" in store.decisions_path.read_text()
    assert "an event" in store.journal_path.read_text()
