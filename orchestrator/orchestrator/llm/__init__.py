"""Pluggable LLM backends. The state machine only ever talks to `LLMBackend`."""
from __future__ import annotations

from ..config import Config
from .base import ImplementResult, LLMBackend, ReviewResult


def make_backend(config: Config) -> LLMBackend:
    if config.llm == "stub":
        from .stub import StubBackend

        return StubBackend()
    if config.llm == "claude":
        from .claude import ClaudeBackend

        return ClaudeBackend(model=config.model)
    raise ValueError(f"unknown llm backend: {config.llm!r}")


__all__ = ["LLMBackend", "ImplementResult", "ReviewResult", "make_backend"]
