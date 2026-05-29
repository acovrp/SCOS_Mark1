# PRD — Greeting Tool (example)

**Problem.** Users want a tiny, dependable way to produce a friendly greeting.

**Goal.** Ship a greeting capability usable from the command line.

**User stories.**
- As a user, I run the tool and get `hello, world`.
- As a user, I pass a name and get `hello, <name>`.

**Non-goals (v1).** Localization, persistence, network APIs.

**Acceptance.** `greet()` and a CLI both return the correct string for the
default and named cases.
