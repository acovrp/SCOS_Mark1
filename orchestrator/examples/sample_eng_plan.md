# Engineering Plan — Greeting Tool (example)

**Stack.** Python 3.11, standard library only. No external dependencies.

**Architecture.**
- `greet.py` — pure function `greet(name="world") -> str`.
- `main.py` — thin CLI wrapper that reads `argv` and prints `greet(...)`.

**Testing.** Each module ships a self-checking test script that exits non-zero
on failure; that script is the task's gate.

**Sequencing.** Build the core function first, then the CLI on top of it.
