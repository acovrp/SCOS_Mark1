# Architecture — AI Agile Orchestrator

## The one idea

The hard part of agentic software development is **not writing code** — models
already do that. The hard part is **drift**: step 40 quietly built on a wrong
assumption from step 6, and the whole thing is now broken in a way nobody can
unwind. Every design choice here exists to prevent drift and keep every step
reversible.

Three rules:

1. **Determinism wraps intelligence.** The control flow (what runs next, when to
   stop, when to ask the human) is plain Python — a state machine. The model
   only fills in each step. The model never decides the loop.
2. **The unit of progress is a verified, committed increment.** A task is DONE
   only after it is implemented → its gate passes → it is committed. If it can't
   pass its gate, it is **reverted**, not patched over.
3. **State lives on disk, not in the context window.** The orchestrator can be
   killed at any moment and resume exactly, because the backlog, decisions, and
   journal are files.

## Components

```
                ┌─────────────────────────────────────────────┐
   PRD ─┐       │              Orchestrator (machine.py)        │
        ├─INGEST│  deterministic state machine + human gates    │
 EngPlan┘       └───────────────┬─────────────────────────────-┘
                                │ calls role agents through one interface
                ┌───────────────▼──────────────┐
                │   LLMBackend  (llm/base.py)   │
                │  plan · clarify · implement · │
                │       review · retro          │
                └───────┬───────────────┬──────-┘
              stub.py ◄─┘               └─► claude.py
        (offline, deterministic)   (Claude Agent SDK, real)

  state.py  → spec.md · backlog.json · decisions.md · journal.md
  gates.py  → run tests/lint; all must pass or the increment is reverted
  git_ops.py→ workspace is its own repo; story branches; revert = reset --hard
```

The **same machine** drives both backends. You prove the machinery with `stub`
(no API key, no tokens), then flip `--llm claude` to go live. This is the core
safety property: the risky part (control flow, gating, git) is validated
deterministically.

## The pipeline

```
INGEST   merge PRD + eng plan into one canonical spec.md
PLAN     spec → backlog.json (Epic → Story → Task DAG)
  └ human reviews the plan
CLARIFY  surface open questions as a batch → recorded in decisions.md
  └ human answers
EXECUTE  topological order; per task:
           branch → implement → gate (tests/lint) →
             pass → review → commit → DONE
             fail → reset --hard (revert) → retry ≤ N → else BLOCKED + stop
         per story/epic boundary → human approves the merge to integration
RETRO    reflect, summarize, suggest plan adjustments
```

## Guardrails ("no surprises, no breaking")

| Risk | Mechanism |
|---|---|
| Drift / compounding error | Hard gate after every task; revert on failure |
| Breaking the codebase | Workspace is an isolated git repo; never touches host repo or `main` |
| Runaway loops | `max_attempts_per_task` budget → BLOCKED, not infinite retry |
| Lost work on crash | All state on disk; DONE tasks skipped on resume |
| Unwanted autonomy | Human gates at the `--autonomy` altitude (task/story/epic) |
| Silent wrong assumptions | CLARIFY phase + ADR-style `decisions.md` before any code |

## Autonomy dial

- `task` — approve before each task (safest; use while earning trust)
- `story` — build a whole story autonomously, then approve its merge **(default)**
- `epic` — build a whole epic autonomously, then approve its merge

Recommended rollout: walking skeleton → dry-run plan on the real PRD → execute
one epic at `task`/`story` gating → loosen as trust builds.

## Extending to the real Claude backend

`llm/claude.py` already implements the `LLMBackend` interface against the Claude
Agent SDK: `plan/clarify/review` request JSON and parse it; `implement` runs an
agent with file-editing tools whose working directory is the build workspace, so
edits land exactly where the gate checks them. Swap in real test/lint commands
per task (via the Planner's `test_cmd`) and the machine is unchanged.
```
pip install claude-agent-sdk && export ANTHROPIC_API_KEY=...
python -m orchestrator --llm claude run --prd PRD.md --eng-plan PLAN.md
```
