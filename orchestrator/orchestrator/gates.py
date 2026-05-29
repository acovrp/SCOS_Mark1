"""The quality gate: a task is only DONE if its gate passes.

A gate is one or more shell commands (tests, lint, typecheck) run inside the
workspace. All must exit 0. This is the single rule that prevents drift:
an increment that cannot prove itself is reverted, never merged.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class GateResult:
    passed: bool
    output: str

    def __bool__(self) -> bool:
        return self.passed


def run_gate(commands: list[list[str]], cwd: Path, timeout: int = 300) -> GateResult:
    if not commands:
        # No gate defined => treated as a vacuous pass, but logged loudly upstream.
        return GateResult(True, "(no gate command configured)")
    chunks: list[str] = []
    for cmd in commands:
        try:
            proc = subprocess.run(
                cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout
            )
        except subprocess.TimeoutExpired:
            chunks.append(f"$ {' '.join(cmd)}\nTIMEOUT after {timeout}s")
            return GateResult(False, "\n".join(chunks))
        chunks.append(
            f"$ {' '.join(cmd)}\n[exit {proc.returncode}]\n{proc.stdout}{proc.stderr}"
        )
        if proc.returncode != 0:
            return GateResult(False, "\n".join(chunks))
    return GateResult(True, "\n".join(chunks))
