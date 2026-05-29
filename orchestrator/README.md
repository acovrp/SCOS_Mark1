# AI Agile Orchestrator

An AI orchestrator that turns a **PRD + engineering plan** into working software
by running an agile loop — plan → clarify → implement → test → review → commit →
repeat — **one verified, reversible increment at a time.**

It is built so that *the risky parts can't surprise you*: the control flow,
quality gates, git isolation, and revert-on-failure are deterministic Python you
can unit-test offline, and the actual intelligence is a pluggable backend you
turn on when you're ready.

> Read [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the "why". This README
> is the "how".

## Why it won't break things

- **Isolated workspace** — the app is built in its own git repo (`build/`). The
  orchestrator never touches your real repo or `main`.
- **Hard gate per task** — tests must pass or the increment is `git reset --hard`
  reverted. Nothing half-baked is ever committed.
- **Budgets** — a task that can't pass its gate within N attempts is marked
  BLOCKED and the run stops cleanly. No runaway loops.
- **Resumable** — all state is on disk (`backlog.json`, `decisions.md`,
  `journal.md`); DONE tasks are skipped on resume.
- **Human gates** at the altitude you choose (`--autonomy task|story|epic`).

## Quickstart (offline, no API key)

```bash
cd orchestrator
pytest -q                     # 8 tests prove the machinery

# Run the walking skeleton on the example PRD with the deterministic stub:
python -m orchestrator --yes \
  --state-dir /tmp/demo/.orchestrator --workspace /tmp/demo/build \
  run --prd examples/sample_prd.md --eng-plan examples/sample_eng_plan.md

# See what it built (a real, runnable app):
(cd /tmp/demo/build && python main.py Ada)        # -> hello, Ada
git -C /tmp/demo/build log --oneline --graph --all
```

## Commands

```bash
python -m orchestrator init --prd PRD.md --eng-plan PLAN.md   # → spec.md
python -m orchestrator plan          # → backlog.json (review it!)
python -m orchestrator clarify       # answer open questions → decisions.md
python -m orchestrator run           # full pipeline
python -m orchestrator status        # live progress
python -m orchestrator resume        # continue after a pause
```

Flags: `--llm {stub,claude}` · `--autonomy {task,story,epic}` ·
`--state-dir DIR` · `--workspace DIR` · `--model NAME` · `--yes` (auto-approve).

## Going live with Claude

```bash
pip install claude-agent-sdk
export ANTHROPIC_API_KEY=...
python -m orchestrator --llm claude --autonomy story \
  run --prd PRD.md --eng-plan PLAN.md
```

The state machine is identical — only the backend changes. Have the Planner emit
real `test_cmd`s (your project's test/lint commands) and the same gate logic
guards real code.

## Layout

```
orchestrator/
  orchestrator/        # the package
    machine.py         # the state machine (control flow + gates)  ← the brain
    models.py          # Epic/Story/Task DAG
    state.py           # on-disk source of truth
    gates.py           # quality gate runner
    git_ops.py         # isolated-workspace git (branch / commit / revert)
    llm/base.py        # the backend interface (the 5 role agents)
    llm/stub.py        # deterministic offline backend
    llm/claude.py      # Claude Agent SDK backend
    cli.py             # CLI
  tests/               # offline end-to-end proofs of the machinery
  examples/            # sample PRD + engineering plan
  docs/ARCHITECTURE.md
```

## Status

This is the **walking skeleton + scaffold**: the full pipeline runs end-to-end
on the deterministic backend, with the Claude backend wired to the same
interface. Next steps are in the repo discussion — point it at a real PRD with
`--llm claude` once you've reviewed a dry-run plan.
