"""Model-contract and browser-policy tests (audit v0.2 sections 6-11).

These cover four defects that shipped in v0.2:

* the Google default model had been shut down;
* every provider sent ``temperature``, which the current Anthropic models
  reject with a 400;
* the structured layer forced a sampling parameter on every call;
* unticking "Allow browser rendering" did not stop a browser probe.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from scraper_app.ai import capabilities, structured
from scraper_app.ai.base import Completion, LLMProvider, Usage
from scraper_app.ai.providers.anthropic_provider import AnthropicProvider
from scraper_app.ai.providers.google_provider import GoogleProvider
from scraper_app.ai.providers.litellm_provider import LiteLLMProvider
from scraper_app.ai.providers.openai_provider import OpenAIProvider


class Tiny(BaseModel):
    value: str


class RecordingProvider(LLMProvider):
    """Captures exactly what the structured layer asks for."""

    name = "recording"
    label = "Recording"
    default_model = "claude-sonnet-5"

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def availability(self):
        from scraper_app.ai.base import AIAvailability

        return AIAvailability(True)

    def complete(self, prompt, *, system=None, model=None, max_tokens=1500, temperature=None):
        self.calls.append({"max_tokens": max_tokens, "temperature": temperature})
        return Completion(text='{"value": "ok"}', usage=Usage(provider=self.name))


# --------------------------------------------------------------- capabilities
@pytest.mark.parametrize(
    "model,expected",
    [
        ("claude-sonnet-5", False),
        ("claude-opus-5", False),
        ("claude-fable-5", False),
        ("claude-haiku-4-5", True),
        ("gpt-4o-mini", True),
        ("gemini-3.7-flash", True),
        ("", True),
    ],
)
def test_temperature_support_by_model(model, expected):
    assert capabilities.for_model(model).supports_temperature is expected


def test_sampling_kwargs_are_dropped_for_models_that_reject_them():
    """Sonnet 5 returns a 400 when temperature is set, so it must not be sent."""
    assert capabilities.for_model("claude-sonnet-5").sampling_kwargs(0.0) == {}
    assert capabilities.for_model("gpt-4o-mini").sampling_kwargs(0.0) == {"temperature": 0.0}


def test_sampling_kwargs_omitted_when_none_requested():
    assert capabilities.for_model("gpt-4o-mini").sampling_kwargs(None) == {}


# ------------------------------------------------------------- structured layer
def test_structured_layer_does_not_force_a_sampling_parameter():
    provider = RecordingProvider()
    result = structured.call_structured(provider, instruction="x", schema=Tiny)
    assert result.ok
    assert provider.calls[0]["temperature"] is None


# ------------------------------------------------------------- model defaults
def test_no_provider_defaults_to_a_retired_model():
    """gemini-2.0-flash has been shut down; nothing may default to it."""
    retired = {"gemini-2.0-flash", "gemini-1.5-flash", "gemini-pro"}
    for provider in (AnthropicProvider(), OpenAIProvider(), GoogleProvider(), LiteLLMProvider()):
        assert provider.default_model not in retired, provider.name
        assert provider.default_model, provider.name


@pytest.mark.parametrize(
    "provider_cls,env_var,override",
    [
        (AnthropicProvider, "SRWS_ANTHROPIC_MODEL", "claude-haiku-4-5"),
        (OpenAIProvider, "SRWS_OPENAI_MODEL", "gpt-4.1-mini"),
        (GoogleProvider, "SRWS_GOOGLE_MODEL", "gemini-3.6-flash"),
    ],
)
def test_model_is_overridable_by_environment(monkeypatch, provider_cls, env_var, override):
    """A provider deprecation must be fixable by configuration, not a release."""
    import importlib

    monkeypatch.setenv(env_var, override)
    module = importlib.import_module(provider_cls.__module__)
    importlib.reload(module)
    reloaded = getattr(module, provider_cls.__name__)
    assert reloaded.default_model == override

    # Leave the module as the rest of the suite expects it.
    monkeypatch.delenv(env_var, raising=False)
    importlib.reload(module)


# ------------------------------------------------------------- browser policy
def test_browser_opt_out_is_passed_to_the_profiler():
    """Unticking the box must forbid a browser probe, not merely not force one."""
    from pathlib import Path

    home = Path(__file__).resolve().parents[2] / "src" / "scraper_app" / "ui" / "home.py"
    source = home.read_text(encoding="utf-8")

    # The call must consult the user's choice rather than always passing None.
    assert "use_browser=None" in source
    assert 'st.session_state.get("allow_browser", True)' in source
    assert "else False" in source


def test_profiler_never_probes_when_browser_is_disabled(server, monkeypatch):
    """End-to-end: use_browser=False must not call the network probe."""
    from scraper_app.discovery import profiler

    called = {"probe": False}

    def fake_probe(*args, **kwargs):
        called["probe"] = True
        return {
            "available": False,
            "reason": "should not be called",
            "api_candidates": [],
            "html": "",
        }

    monkeypatch.setattr(profiler, "profile_source", profiler.profile_source)
    import scraper_app.discovery.network_probe as network_probe

    monkeypatch.setattr(network_probe, "probe_with_browser", fake_probe)

    # js_page.html looks JavaScript-heavy, which is exactly when the probe would run.
    profile = profiler.profile_source(server.url("/js_page.html"), use_browser=False)
    assert called["probe"] is False
    assert profile.requires_js is True  # detection still reports it, it just does not act
