"""AI Agile Orchestrator.

A deterministic state machine that drives role-specialized LLM agents to build
software from a PRD + engineering plan, one verified increment at a time.

Design principle: determinism wraps intelligence. The control flow (what runs
next, when to stop, when to ask the human) lives in plain Python. The
intelligence (plan, implement, review) lives behind a pluggable LLM backend.
"""

__version__ = "0.1.0"
