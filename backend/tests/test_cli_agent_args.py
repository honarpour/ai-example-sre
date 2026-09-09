"""Fast tests for cli_agent's argument construction — no subprocess spawned.
`--bare` mode (PLAN.md Phase 7d) is untestable end-to-end without a real
ANTHROPIC_API_KEY, so this at least locks in which flag set gets built."""
from __future__ import annotations

from app.config import get_settings
from app.orchestrator.cli_agent import _bare_mode_args, _base_args


def test_no_api_key_omits_bare_flag(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    get_settings.cache_clear()
    assert _bare_mode_args() == []
    args = _base_args(mcp_config_path="/tmp/x.json", session_id="s", resume=False)
    assert "--bare" not in args
    get_settings.cache_clear()


def test_api_key_set_adds_bare_flag(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-123")
    get_settings.cache_clear()
    assert _bare_mode_args() == ["--bare"]
    args = _base_args(mcp_config_path="/tmp/x.json", session_id="s", resume=False)
    assert "--bare" in args
    # --bare still comes before --mcp-config so the CLI's own compatibility contract
    # (documented as "provide context via ... --mcp-config" alongside --bare) is met.
    assert args.index("--bare") < args.index("--mcp-config")
    get_settings.cache_clear()


def test_no_model_omits_model_flag():
    args = _base_args(mcp_config_path="/tmp/x.json", session_id="s", resume=False)
    assert "--model" not in args


def test_model_kwarg_adds_model_flag():
    args = _base_args(
        mcp_config_path="/tmp/x.json", session_id="s", resume=False, model="claude-haiku-4-5"
    )
    assert args[args.index("--model") + 1] == "claude-haiku-4-5"


def test_phase_a_and_phase_b_can_use_different_models(monkeypatch):
    """CLAUDE_MODEL_PHASE_A overrides CLAUDE_MODEL for phase A only — the cost lever
    documented in config.py. run_synthesis (phase B) always uses CLAUDE_MODEL."""
    monkeypatch.setenv("CLAUDE_MODEL", "claude-opus-5")
    monkeypatch.setenv("CLAUDE_MODEL_PHASE_A", "claude-haiku-4-5")
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.claude_model == "claude-opus-5"
        assert settings.claude_model_phase_a == "claude-haiku-4-5"
        # phase A resolution logic, mirrored from cli_agent.stream_investigate
        assert (settings.claude_model_phase_a or settings.claude_model) == "claude-haiku-4-5"
    finally:
        get_settings.cache_clear()


def test_phase_a_falls_back_to_claude_model_when_unset(monkeypatch):
    monkeypatch.setenv("CLAUDE_MODEL", "claude-opus-5")
    monkeypatch.delenv("CLAUDE_MODEL_PHASE_A", raising=False)
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert (settings.claude_model_phase_a or settings.claude_model) == "claude-opus-5"
    finally:
        get_settings.cache_clear()
