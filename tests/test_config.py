"""Config loading, key handling and redaction."""

import pytest

from tests.conftest import FAKE_KEY
from zalat.config import DEFAULT_KEY_HEADER, DEFAULT_MCP_URL, load_settings, redact
from zalat.errors import ConfigError


def test_loads_key_from_env_file(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(f'NANSEN_API_KEY="{FAKE_KEY}"\n', encoding="utf-8")
    s = load_settings(env)
    assert s.api_key == FAKE_KEY
    assert s.mcp_url == DEFAULT_MCP_URL
    assert s.key_header == DEFAULT_KEY_HEADER
    assert s.timeout == 30.0


def test_exported_env_var_beats_env_file(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("NANSEN_API_KEY=from_file\n", encoding="utf-8")
    monkeypatch.setenv("NANSEN_API_KEY", "from_env")
    assert load_settings(env).api_key == "from_env"


def test_overrides(monkeypatch):
    monkeypatch.setenv("NANSEN_API_KEY", FAKE_KEY)
    monkeypatch.setenv("NANSEN_MCP_URL", "https://example.test/mcp")
    monkeypatch.setenv("NANSEN_API_KEY_HEADER", "X-Api-Key")
    monkeypatch.setenv("ZALAT_TIMEOUT", "12")
    s = load_settings(None)
    assert (s.mcp_url, s.key_header, s.timeout) == ("https://example.test/mcp", "X-Api-Key", 12.0)
    assert load_settings(None, timeout=5).timeout == 5


@pytest.mark.parametrize("value", [None, "", "   ", "your_key_here", "'your_key_here'"])
def test_missing_or_placeholder_key(tmp_path, monkeypatch, value):
    if value is not None:
        monkeypatch.setenv("NANSEN_API_KEY", value)
    with pytest.raises(ConfigError, match="NANSEN_API_KEY is not set"):
        load_settings(tmp_path / "does-not-exist.env")


def test_bad_timeout(monkeypatch):
    monkeypatch.setenv("NANSEN_API_KEY", FAKE_KEY)
    monkeypatch.setenv("ZALAT_TIMEOUT", "soon")
    with pytest.raises(ConfigError):
        load_settings(None)


def test_repr_hides_key(monkeypatch):
    monkeypatch.setenv("NANSEN_API_KEY", FAKE_KEY)
    s = load_settings(None)
    assert FAKE_KEY not in repr(s)
    assert FAKE_KEY not in str(s)
    assert "***" in repr(s)


def test_redact():
    assert redact(f"header {FAKE_KEY} end", [FAKE_KEY]) == "header *** end"
    assert redact("nothing here", [FAKE_KEY, ""]) == "nothing here"
    assert redact("abcabc", ["abc", "abcabc"]) == "***"


def test_redact_defaults_to_loaded_key(monkeypatch):
    monkeypatch.setenv("NANSEN_API_KEY", FAKE_KEY)
    load_settings(None)
    monkeypatch.delenv("NANSEN_API_KEY")
    assert FAKE_KEY not in redact(f"x{FAKE_KEY}x")


def test_env_example_is_placeholder_and_gitignore_covers_env():
    from tests.conftest import ROOT

    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "NANSEN_API_KEY=your_key_here" in example
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8").split()
    assert ".env" in ignore and "reports/" in ignore


def test_min_gross_env(monkeypatch):
    monkeypatch.setenv("NANSEN_API_KEY", FAKE_KEY)
    assert load_settings(None).min_gross_usd is None
    monkeypatch.setenv("ZALAT_MIN_GROSS_USD", "2500")
    assert load_settings(None).min_gross_usd == 2500.0
    for bad in ("lots", "-5"):
        monkeypatch.setenv("ZALAT_MIN_GROSS_USD", bad)
        with pytest.raises(ConfigError):
            load_settings(None)


# ---- LunarCrush (optional) -------------------------------------------------------
from tests.conftest import FAKE_LC_KEY  # noqa: E402
from zalat.config import DEFAULT_LC_URL, Settings  # noqa: E402


def test_lunarcrush_key_optional(monkeypatch):
    monkeypatch.setenv("NANSEN_API_KEY", FAKE_KEY)
    s = load_settings(None)
    assert s.lunarcrush_key is None and s.lunarcrush_url == DEFAULT_LC_URL
    assert s.secrets() == [FAKE_KEY]
    for placeholder in ("", "  ", "your_key_here"):
        monkeypatch.setenv("LUNARCRUSH_API_KEY", placeholder)
        assert load_settings(None).lunarcrush_key is None  # never a ConfigError


def test_lunarcrush_key_loaded_redacted_and_url_override(tmp_path, monkeypatch):
    monkeypatch.setenv("NANSEN_API_KEY", FAKE_KEY)
    env = tmp_path / ".env"
    env.write_text(f"LUNARCRUSH_API_KEY={FAKE_LC_KEY}\nLUNARCRUSH_URL=https://lc.example/api4/\n",
                   encoding="utf-8")
    s = load_settings(env)
    assert s.lunarcrush_key == FAKE_LC_KEY and s.lunarcrush_url == "https://lc.example/api4"
    assert s.secrets() == [FAKE_KEY, FAKE_LC_KEY]
    assert FAKE_LC_KEY not in repr(s) and FAKE_KEY not in repr(s)
    assert "lunarcrush_key='***'" in repr(s)
    assert redact(f"a {FAKE_LC_KEY} b {FAKE_KEY}", s.secrets()) == "a *** b ***"


def test_redact_default_pool_includes_lunarcrush_env(monkeypatch):
    monkeypatch.setenv("LUNARCRUSH_API_KEY", "lc-only-in-env-123456")
    assert "lc-only-in-env-123456" not in redact("x lc-only-in-env-123456 y")


def test_settings_repr_without_lc_key():
    assert "lunarcrush_key=None" in repr(Settings(api_key=FAKE_KEY))
