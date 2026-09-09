from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Must run before get_settings() is ever called — see the Field(default_factory=...) note
# below. `.env` lives at the repo root, one level above `backend/`. A real gap until now:
# .env.example existed since Phase 0 but nothing ever actually loaded a .env file.
load_dotenv(Path(__file__).resolve().parents[2] / ".env")


def _cors_origins() -> list[str]:
    # Stripped so "http://a, http://b" (a space after the comma) doesn't silently
    # produce " http://b", which would never match a real Origin header.
    return [o.strip() for o in os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(",")]


class Settings(BaseModel):
    """Every field uses `default_factory`, not a plain default, deliberately: a plain
    `= os.environ.get(...)` default is computed ONCE at class-definition time (i.e. at
    first import of this module) and then reused for every `Settings()` call for the rest
    of the process — `lru_cache` on `get_settings()` below would then be caching a value
    that was already frozen before it ever ran. `default_factory` re-reads the environment
    on every `Settings()` construction instead, which is what makes `get_settings.cache_clear()`
    plus `monkeypatch.setenv` actually work in tests (see test_cli_agent_args.py) rather than
    silently doing nothing. In production this distinction doesn't matter — env vars don't
    change during a running process either way — but it's what makes the *pattern* correct."""

    data_source: str = Field(default_factory=lambda: os.environ.get("DATA_SOURCE", "mock"))
    """'mock' (default) or 'live'. Mock never requires credentials. This is the GitHub source's
    switch specifically — GitHub-live is still unimplemented (PLAN.md Phase 7a, deferred), so
    this is always 'mock' in practice today, but the field is named generically (not
    `github_data_source`) because it was the only source when Phase 1 introduced it, and
    renaming it now would be a gratuitous break for no behavior change."""

    observability_data_source: str = Field(
        default_factory=lambda: os.environ.get("OBSERVABILITY_DATA_SOURCE", "mock")
    )
    """'mock' (default) or 'live' (PLAN.md Phase 7b — a self-hosted Prometheus/Loki/GlitchTip
    stack, see observability-stack/). Independent of `data_source` deliberately: this project's
    Phase 7 sequencing does GitHub and observability live-cutover on different timelines, so a
    single flag couldn't express "observability is live, GitHub still isn't" — which is exactly
    the state this project is actually in."""

    prometheus_url: str = Field(
        default_factory=lambda: os.environ.get("PROMETHEUS_URL", "http://localhost:9090")
    )
    loki_url: str = Field(default_factory=lambda: os.environ.get("LOKI_URL", "http://localhost:3100"))
    glitchtip_url: str | None = Field(default_factory=lambda: os.environ.get("GLITCHTIP_URL"))
    glitchtip_api_token: str | None = Field(
        default_factory=lambda: os.environ.get("GLITCHTIP_API_TOKEN")
    )
    glitchtip_org_slug: str | None = Field(
        default_factory=lambda: os.environ.get("GLITCHTIP_ORG_SLUG")
    )
    glitchtip_project_slug: str | None = Field(
        default_factory=lambda: os.environ.get("GLITCHTIP_PROJECT_SLUG")
    )

    claude_binary: str = Field(default_factory=lambda: os.environ.get("CLAUDE_BINARY", "claude"))
    claude_model: str | None = Field(default_factory=lambda: os.environ.get("CLAUDE_MODEL"))
    """Optional explicit --model override for the `claude` CLI. Used for phase B (synthesis,
    the reasoning step actually being graded) and the eval judge. Unset = CLI default."""

    claude_model_phase_a: str | None = Field(
        default_factory=lambda: os.environ.get("CLAUDE_MODEL_PHASE_A")
    )
    """Optional override for phase A (evidence gathering) specifically. Falls back to
    `claude_model` when unset, so nothing changes for anyone not using this. Phase A is
    mechanical tool orchestration — call a tool, read the result, decide the next call — not
    the reasoning step this project is graded on, so a cheaper/faster model is a reasonable
    choice here without touching phase B's quality. This is the single biggest token-cost
    lever available without changing the architecture: phase A is where the overwhelming
    majority of an investigation's tool-calling turns happen."""

    anthropic_api_key: str | None = Field(
        default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY")
    )
    """When set, the CLI is invoked with `--bare` (see PLAN.md Phase 7d): a minimal-footprint
    mode that skips the full Claude Code system prompt, hooks, and plugin loading, and drops
    the ~$0.10-0.15/investigation fixed overhead measured in Phase 0. `--bare` requires
    API-key auth rather than the CLI's interactive OAuth login, which is exactly the tradeoff
    that makes this the right default once a real key is available: no dependency on staying
    logged into an interactive session. Unset (the default) keeps today's OAuth-based
    invocation unchanged, so nothing about local dev without a key regresses."""

    max_concurrent_investigations: int = Field(
        default_factory=lambda: int(os.environ.get("MAX_CONCURRENT_INVESTIGATIONS", "2"))
    )
    investigation_timeout_s: int = Field(
        default_factory=lambda: int(os.environ.get("INVESTIGATION_TIMEOUT_S", "120"))
    )
    """Wall-clock bound on a phase A run. This CLI build exposes no `--max-turns` flag (a
    previous `max_agent_turns` config field was removed as dead code for exactly that reason
    — see PLAN.md's review pass), so a genuinely runaway agent would otherwise only ever be
    caught here, expensively, at the very end. `max_tool_calls` below is the cheaper, earlier
    guard for that same failure mode."""

    max_tool_calls: int = Field(default_factory=lambda: int(os.environ.get("MAX_TOOL_CALLS", "50")))
    """Soft-then-hard budget on phase A tool calls. Stated as guidance in the phase-A prompt
    (`_phase_a_prompt`) so the model tries to converge economically, and enforced as a hard
    ceiling by `runner.py`: if a run is still calling tools past this count, the stream is cut
    short and synthesis proceeds on whatever evidence was gathered so far — with a warning
    surfaced in the UI — instead of letting a looping agent burn cost until the wall-clock
    timeout above fails the whole investigation outright.

    50, not the originally-guessed 20: this project's own recorded live runs (PLAN.md Phase 2)
    used 22 tool calls for the simplest scenario (bad-deploy) and 32 for the hardest
    (downstream-dependency) — both correct, non-looping investigations. A first-pass default of
    20 would have clipped both. Set with real headroom above the highest observed value rather
    than a guess about what "should" be enough."""

    cors_origins: list[str] = Field(default_factory=_cors_origins)


@lru_cache
def get_settings() -> Settings:
    return Settings()
