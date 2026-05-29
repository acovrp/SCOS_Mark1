"""Git isolation for the build workspace.

The target app is built inside its own git repo (the workspace), never the host
repo. Each story runs on its own branch off `integration`; tasks commit onto it.
If a task's gate fails, we hard-reset to the pre-task SHA — the increment is
reverted, not patched over. This is the mechanism behind "no breaking".
"""
from __future__ import annotations

import subprocess
from pathlib import Path

INTEGRATION = "integration"


class GitWorkspace:
    def __init__(self, path: Path):
        self.path = Path(path)

    def _git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args],
            cwd=self.path,
            capture_output=True,
            text=True,
            check=check,
        )

    def ensure_repo(self) -> None:
        self.path.mkdir(parents=True, exist_ok=True)
        if (self.path / ".git").exists():
            return
        self._git("init", "-q")
        self._git("config", "user.email", "orchestrator@local")
        self._git("config", "user.name", "AI Orchestrator")
        # The workspace is a self-contained repo; never inherit signing config.
        self._git("config", "commit.gpgsign", "false")
        self._git("config", "tag.gpgsign", "false")
        # Seed an empty root commit so branching/reset always has a base.
        (self.path / ".gitkeep").write_text("")
        self._git("add", "-A")
        self._git("commit", "-q", "-m", "chore: initialize workspace")
        self._git("branch", "-M", INTEGRATION)

    def current_branch(self) -> str:
        return self._git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()

    def current_sha(self) -> str:
        return self._git("rev-parse", "HEAD").stdout.strip()

    def checkout_branch(self, name: str, base: str = INTEGRATION) -> None:
        # Create from base if missing, else just switch to it.
        exists = name in self._git("branch", "--list", name).stdout
        if exists:
            self._git("checkout", "-q", name)
        else:
            self._git("checkout", "-q", base)
            self._git("checkout", "-q", "-b", name)

    def commit_all(self, message: str) -> str:
        self._git("add", "-A")
        # Allow empty so a no-op task still records a checkpoint.
        self._git("commit", "-q", "--allow-empty", "-m", message)
        return self.current_sha()

    def reset_hard(self, sha: str) -> None:
        self._git("reset", "-q", "--hard", sha)
        self._git("clean", "-fdq")

    def merge_ff(self, branch: str, into: str = INTEGRATION) -> None:
        self._git("checkout", "-q", into)
        # --no-ff keeps a clear merge point per story; fall back to ff if needed.
        self._git("merge", "--no-ff", "-q", "-m", f"merge {branch} into {into}", branch)

    def log_oneline(self, limit: int = 20) -> str:
        return self._git("log", "--oneline", f"-{limit}", check=False).stdout.strip()
