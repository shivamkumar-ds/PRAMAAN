"""
Committed offline verification harness for the LLM provider layer.

Covers all four concrete providers (OpenAI, Qwen, Gemini, Mock) plus the
factory that selects between them. This is the merged harness produced by
the BidOps_Final consolidation: OpenAI's coverage (ported from the OpenAI
Build Week repository, where it replaced Qwen/Gemini/Vertex coverage
entirely) combined back with Vertex's full Qwen/Gemini/Vertex/Mock/factory
coverage (33 tests, independently re-verified passing during the
consolidation planning session) -- neither source file is complete on its
own for the canonical repo's provider layer.

No network access is used anywhere in this file. Every provider SDK
exception is constructed using the *real* exception classes from the
installed `openai` / `google-genai` packages (not hand-rolled fakes), so
these tests exercise the exact `except` clauses in llm_client.py against
the exact types those clauses are written to catch.
"""

import asyncio

import httpx
import openai
import pytest
from google.genai import errors as genai_errors

from app.agents import llm_client
from app.agents.llm_exceptions import (
    LLMAuthenticationError,
    LLMConnectionError,
    LLMProviderResponseError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from app.core.config import Settings, get_settings


# ---------------------------------------------------------------------------
# Fixtures: fast, isolated settings per test
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def fast_settings(monkeypatch):
    """
    Every test gets its own cache-cleared Settings with tiny backoff values
    (so retry-exhaustion tests run in milliseconds, not real seconds) and
    dummy credentials (never used -- every test substitutes a fake
    underlying SDK client, so no real network call is ever attempted).
    """
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("OPENAI_MAX_RETRIES", "2")
    monkeypatch.setenv("OPENAI_RETRY_BACKOFF_SECONDS", "0.01")
    monkeypatch.setenv("QWEN_API_KEY", "test-qwen-key")
    monkeypatch.setenv("QWEN_MAX_RETRIES", "2")
    monkeypatch.setenv("QWEN_RETRY_BACKOFF_SECONDS", "0.01")
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setenv("GEMINI_MAX_RETRIES", "2")
    monkeypatch.setenv("GEMINI_RETRY_BACKOFF_SECONDS", "0.01")
    monkeypatch.setenv("GEMINI_MAX_RETRY_DELAY_SECONDS", "0.05")

    get_settings.cache_clear()
    llm_client._get_openai_http_client.cache_clear()
    llm_client._get_qwen_http_client.cache_clear()
    llm_client._get_gemini_http_client.cache_clear()
    # Re-bind the module-level `settings` reference every client class reads,
    # the same way the module itself binds it once at import time.
    llm_client.settings = get_settings()

    yield

    get_settings.cache_clear()
    llm_client._get_openai_http_client.cache_clear()
    llm_client._get_qwen_http_client.cache_clear()
    llm_client._get_gemini_http_client.cache_clear()


def _fake_response(text: str):
    return type("FakeResponse", (), {"text": text})()


def _status_error(cls, code):
    req = httpx.Request("POST", "https://example.com")
    resp = httpx.Response(status_code=code, request=req)
    return cls("err", response=resp, body=None)


# ---------------------------------------------------------------------------
# OpenAI (operational reference implementation)
# ---------------------------------------------------------------------------


class FakeOpenAICompletions:
    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    async def create(self, **kwargs):
        self.calls += 1
        action = self.script.pop(0)
        if action == "ok":
            return type(
                "R", (), {"choices": [type("C", (), {"message": type("M", (), {"content": "hello from openai"})()})()]}
            )()
        raise action


def _install_fake_openai(client: "llm_client.OpenAIClient", script):
    fake = FakeOpenAICompletions(script)
    chat = type("Chat", (), {"completions": fake})()
    client._client = type("FakeOpenAIClient", (), {"chat": chat})()
    return fake


@pytest.mark.asyncio
async def test_openai_successful_completion():
    client = llm_client.OpenAIClient()
    fake = _install_fake_openai(client, ["ok"])
    result = await client.complete("system", "user")
    assert result == "hello from openai"


@pytest.mark.asyncio
async def test_openai_authentication_error_never_retried():
    client = llm_client.OpenAIClient()
    exc = _status_error(openai.AuthenticationError, 401)
    fake = _install_fake_openai(client, [exc])
    with pytest.raises(LLMAuthenticationError):
        await client.complete("system", "user")
    assert fake.calls == 1


@pytest.mark.asyncio
async def test_openai_rate_limit_recovers_on_retry():
    client = llm_client.OpenAIClient()
    exc = _status_error(openai.RateLimitError, 429)
    fake = _install_fake_openai(client, [exc, "ok"])
    result = await client.complete("system", "user")
    assert result == "hello from openai"
    assert fake.calls == 2


@pytest.mark.asyncio
async def test_openai_rate_limit_exhausts_retries():
    client = llm_client.OpenAIClient()
    exc = _status_error(openai.RateLimitError, 429)
    fake = _install_fake_openai(client, [exc, exc, exc])
    with pytest.raises(LLMRateLimitError):
        await client.complete("system", "user")
    assert fake.calls == 3  # max_retries=2 -> 3 total attempts


@pytest.mark.asyncio
async def test_openai_timeout_exhausts_retries():
    client = llm_client.OpenAIClient()
    exc = openai.APITimeoutError(request=httpx.Request("POST", "https://example.com"))
    fake = _install_fake_openai(client, [exc, exc, exc])
    with pytest.raises(LLMTimeoutError):
        await client.complete("system", "user")


@pytest.mark.asyncio
async def test_openai_connection_error_exhausts_retries():
    client = llm_client.OpenAIClient()
    exc = openai.APIConnectionError(request=httpx.Request("POST", "https://example.com"))
    fake = _install_fake_openai(client, [exc, exc, exc])
    with pytest.raises(LLMConnectionError):
        await client.complete("system", "user")


@pytest.mark.asyncio
async def test_openai_api_response_validation_error_caught_by_catchall():
    client = llm_client.OpenAIClient()
    resp = httpx.Response(status_code=200, request=httpx.Request("POST", "https://example.com"))
    exc = openai.APIResponseValidationError(response=resp, body=None)
    fake = _install_fake_openai(client, [exc])
    with pytest.raises(LLMProviderResponseError):
        await client.complete("system", "user")


def test_openai_client_is_a_shared_singleton():
    instances = [llm_client.OpenAIClient() for _ in range(5)]
    assert all(inst._client is instances[0]._client for inst in instances)


def test_openai_client_construction_uses_real_endpoint_by_default():
    """
    OpenAIClient must not point at any override base_url unless one is
    explicitly configured -- confirms the SDK is left to use its own real
    default endpoint.
    """
    client = llm_client._get_openai_http_client()
    assert str(client.base_url).rstrip("/") == "https://api.openai.com/v1"


def test_openai_client_construction_respects_base_url_override(monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example-proxy.test/v1")
    get_settings.cache_clear()
    llm_client._get_openai_http_client.cache_clear()
    llm_client.settings = get_settings()

    client = llm_client._get_openai_http_client()
    assert str(client.base_url).rstrip("/") == "https://example-proxy.test/v1"

    llm_client._get_openai_http_client.cache_clear()


# ---------------------------------------------------------------------------
# Gemini: successful path
# ---------------------------------------------------------------------------


class FakeAioModels:
    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    async def generate_content(self, **kwargs):
        self.calls += 1
        action = self.script.pop(0)
        if action == "ok":
            return _fake_response("hello from gemini")
        raise action  # action is a pre-built exception instance


def _install_fake_gemini(client: "llm_client.GeminiClient", script):
    fake_models = FakeAioModels(script)
    aio = type("Aio", (), {"models": fake_models})()
    client._client = type("FakeGenaiClient", (), {"aio": aio})()
    return fake_models


@pytest.mark.asyncio
async def test_gemini_successful_completion():
    client = llm_client.GeminiClient()
    fake = _install_fake_gemini(client, ["ok"])
    result = await client.complete("system", "user")
    assert result == "hello from gemini"
    assert fake.calls == 1


@pytest.mark.asyncio
async def test_gemini_authentication_error_401():
    client = llm_client.GeminiClient()
    exc = genai_errors.ClientError(401, {"message": "bad key", "status": "UNAUTHENTICATED"}, None)
    fake = _install_fake_gemini(client, [exc])
    with pytest.raises(LLMAuthenticationError):
        await client.complete("system", "user")
    assert fake.calls == 1  # never retried


@pytest.mark.asyncio
async def test_gemini_authentication_error_403():
    client = llm_client.GeminiClient()
    exc = genai_errors.ClientError(403, {"message": "forbidden", "status": "PERMISSION_DENIED"}, None)
    fake = _install_fake_gemini(client, [exc])
    with pytest.raises(LLMAuthenticationError):
        await client.complete("system", "user")
    assert fake.calls == 1


@pytest.mark.asyncio
async def test_gemini_rate_limit_error():
    client = llm_client.GeminiClient()
    exc = genai_errors.ClientError(429, {"message": "slow down", "status": "RESOURCE_EXHAUSTED"}, None)
    fake = _install_fake_gemini(client, [exc])
    with pytest.raises(LLMRateLimitError):
        await client.complete("system", "user")


@pytest.mark.asyncio
async def test_gemini_other_client_error_maps_to_provider_response_error():
    client = llm_client.GeminiClient()
    exc = genai_errors.ClientError(400, {"message": "bad model name", "status": "INVALID_ARGUMENT"}, None)
    fake = _install_fake_gemini(client, [exc])
    with pytest.raises(LLMProviderResponseError):
        await client.complete("system", "user")


@pytest.mark.asyncio
async def test_gemini_server_error():
    client = llm_client.GeminiClient()
    exc = genai_errors.ServerError(500, {"message": "internal", "status": "INTERNAL"}, None)
    fake = _install_fake_gemini(client, [exc])
    with pytest.raises(LLMProviderResponseError):
        await client.complete("system", "user")


@pytest.mark.asyncio
async def test_gemini_unknown_api_response_error():
    client = llm_client.GeminiClient()
    exc = genai_errors.UnknownApiResponseError("could not parse response")
    fake = _install_fake_gemini(client, [exc])
    with pytest.raises(LLMProviderResponseError):
        await client.complete("system", "user")


@pytest.mark.asyncio
async def test_gemini_timeout_error():
    client = llm_client.GeminiClient()
    exc = httpx.TimeoutException("timed out")
    fake = _install_fake_gemini(client, [exc])
    with pytest.raises(LLMTimeoutError):
        await client.complete("system", "user")


@pytest.mark.asyncio
async def test_gemini_connection_error():
    client = llm_client.GeminiClient()
    exc = httpx.ConnectError("connection refused")
    fake = _install_fake_gemini(client, [exc])
    with pytest.raises(LLMConnectionError):
        await client.complete("system", "user")


@pytest.mark.asyncio
async def test_gemini_generic_api_error_catchall():
    """
    A bare APIError (neither ClientError nor ServerError -- e.g. a status
    code outside both ranges) hits the final documented `except
    errors.APIError` branch, not an `except Exception` (there is none --
    see the M11.5 QA finding recorded in llm_client.py).
    """
    client = llm_client.GeminiClient()
    exc = genai_errors.APIError(0, {"message": "unexpected", "status": None}, None)
    fake = _install_fake_gemini(client, [exc])
    with pytest.raises(LLMProviderResponseError):
        await client.complete("system", "user")


def test_gemini_client_construction_configures_native_retry():
    """
    Verifies retry behavior the way it actually exists for Gemini: not a
    hand-rolled loop (there isn't one -- see GeminiClient's docstring),
    but the google-genai SDK's own retry mechanism, configured once at
    client construction. Confirms our Settings values actually reach the
    SDK's HttpRetryOptions rather than being silently ignored.
    """
    client = llm_client._get_gemini_http_client()
    retry_options = client._api_client._http_options.retry_options
    settings = get_settings()
    assert retry_options.attempts == settings.gemini_max_retries + 1
    assert retry_options.initial_delay == settings.gemini_retry_backoff_seconds
    assert retry_options.max_delay == settings.gemini_max_retry_delay_seconds
    assert retry_options.exp_base == 2


def test_gemini_client_is_a_shared_singleton():
    """Mirrors the Qwen singleton-reuse regression check (D-140, Fix 1)."""
    instances = [llm_client.GeminiClient() for _ in range(5)]
    assert all(inst._client is instances[0]._client for inst in instances)


# ---------------------------------------------------------------------------
# Vertex AI migration: construction branch, settings validation, and the
# one genuinely new auth-exception surface (ADC/IAM). Per the approved
# migration scope, ClientError/ServerError/UnknownApiResponseError/httpx
# handling above is unchanged and deliberately not re-tested here.
# ---------------------------------------------------------------------------


def test_gemini_client_construction_developer_mode_default(monkeypatch):
    """
    Default (no GEMINI_AUTH_MODE set) must remain exactly the pre-migration
    Developer API path -- this is the local-dev path and must not silently
    change behavior for anyone who hasn't opted into Vertex.

    Uses Settings(_env_file=None) deliberately: this test verifies the
    code's built-in default, which must hold regardless of what a real
    developer's local .env file happens to set (e.g. once Vertex is
    configured as a real option via GEMINI_AUTH_MODE=vertex in .env, this
    test would otherwise -- incorrectly -- start asserting against the
    developer's local configuration instead of the code's actual default).
    """
    monkeypatch.delenv("GEMINI_AUTH_MODE", raising=False)
    llm_client.settings = Settings(_env_file=None, gemini_api_key="test-gemini-key")
    llm_client._get_gemini_http_client.cache_clear()

    client = llm_client._get_gemini_http_client()
    assert client._api_client.vertexai is False

    llm_client._get_gemini_http_client.cache_clear()


def test_gemini_client_construction_vertex_mode(monkeypatch):
    """
    GEMINI_AUTH_MODE=vertex must construct the client in Vertex AI mode,
    with project/location passed through and no API key involved.
    """
    monkeypatch.setenv("GEMINI_AUTH_MODE", "vertex")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "asia-south1")
    get_settings.cache_clear()
    llm_client._get_gemini_http_client.cache_clear()
    llm_client.settings = get_settings()

    client = llm_client._get_gemini_http_client()
    assert client._api_client.vertexai is True
    assert client._api_client.project == "test-project"
    assert client._api_client.location == "asia-south1"

    # Explicit cache_clear (in addition to the fast_settings fixture's own
    # teardown) -- documents the exact regression this test is guarding
    # against: an lru_cache-d, no-argument factory silently returning a
    # stale client from a previous auth mode within the same process.
    llm_client._get_gemini_http_client.cache_clear()


def test_gemini_auth_mode_rejects_invalid_value(monkeypatch):
    """Settings must fail fast at startup, never silently fall back."""
    monkeypatch.setenv("GEMINI_AUTH_MODE", "not-a-real-mode")
    get_settings.cache_clear()
    with pytest.raises(Exception):  # pydantic.ValidationError wraps our ValueError
        get_settings()
    get_settings.cache_clear()


def test_gemini_auth_mode_vertex_requires_project(monkeypatch):
    """GEMINI_AUTH_MODE=vertex without GOOGLE_CLOUD_PROJECT must fail fast."""
    monkeypatch.setenv("GEMINI_AUTH_MODE", "vertex")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "")
    get_settings.cache_clear()
    with pytest.raises(Exception):
        get_settings()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_gemini_default_credentials_error_maps_to_authentication_error():
    """
    Vertex AI mode only: no ADC found at all (e.g. never ran
    `gcloud auth application-default login` locally, or no attached
    service account in production). Never retried, same policy as the
    existing ClientError(401/403) case.
    """
    from google.auth import exceptions as google_auth_exceptions

    client = llm_client.GeminiClient()
    exc = google_auth_exceptions.DefaultCredentialsError("no ADC found")
    fake = _install_fake_gemini(client, [exc])
    with pytest.raises(LLMAuthenticationError):
        await client.complete("system", "user")
    assert fake.calls == 1


@pytest.mark.asyncio
async def test_gemini_refresh_error_maps_to_authentication_error():
    """
    Vertex AI mode only: ADC was found, but a token refresh/impersonation
    call failed -- e.g. the Service Account Token Creator grant was
    revoked. Never retried, same policy as above.
    """
    from google.auth import exceptions as google_auth_exceptions

    client = llm_client.GeminiClient()
    exc = google_auth_exceptions.RefreshError("impersonation denied")
    fake = _install_fake_gemini(client, [exc])
    with pytest.raises(LLMAuthenticationError):
        await client.complete("system", "user")
    assert fake.calls == 1


# ---------------------------------------------------------------------------
# Qwen regression -- confirm D-139/D-140 behavior is genuinely unchanged
# ---------------------------------------------------------------------------


class FakeCompletions:
    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    async def create(self, **kwargs):
        self.calls += 1
        action = self.script.pop(0)
        if action == "ok":
            return type(
                "R", (), {"choices": [type("C", (), {"message": type("M", (), {"content": "hello from qwen"})()})()]}
            )()
        raise action


def _install_fake_qwen(client: "llm_client.QwenClient", script):
    fake = FakeCompletions(script)
    chat = type("Chat", (), {"completions": fake})()
    client._client = type("FakeOpenAIClient", (), {"chat": chat})()
    return fake


@pytest.mark.asyncio
async def test_qwen_successful_completion():
    client = llm_client.QwenClient()
    fake = _install_fake_qwen(client, ["ok"])
    result = await client.complete("system", "user")
    assert result == "hello from qwen"


@pytest.mark.asyncio
async def test_qwen_authentication_error_never_retried():
    client = llm_client.QwenClient()
    exc = _status_error(openai.AuthenticationError, 401)
    fake = _install_fake_qwen(client, [exc])
    with pytest.raises(LLMAuthenticationError):
        await client.complete("system", "user")
    assert fake.calls == 1


@pytest.mark.asyncio
async def test_qwen_rate_limit_recovers_on_retry():
    client = llm_client.QwenClient()
    exc = _status_error(openai.RateLimitError, 429)
    fake = _install_fake_qwen(client, [exc, "ok"])
    result = await client.complete("system", "user")
    assert result == "hello from qwen"
    assert fake.calls == 2


@pytest.mark.asyncio
async def test_qwen_rate_limit_exhausts_retries():
    client = llm_client.QwenClient()
    exc = _status_error(openai.RateLimitError, 429)
    fake = _install_fake_qwen(client, [exc, exc, exc])
    with pytest.raises(LLMRateLimitError):
        await client.complete("system", "user")
    assert fake.calls == 3  # max_retries=2 -> 3 total attempts


@pytest.mark.asyncio
async def test_qwen_timeout_exhausts_retries():
    client = llm_client.QwenClient()
    exc = openai.APITimeoutError(request=httpx.Request("POST", "https://example.com"))
    fake = _install_fake_qwen(client, [exc, exc, exc])
    with pytest.raises(LLMTimeoutError):
        await client.complete("system", "user")


@pytest.mark.asyncio
async def test_qwen_connection_error_exhausts_retries():
    client = llm_client.QwenClient()
    exc = openai.APIConnectionError(request=httpx.Request("POST", "https://example.com"))
    fake = _install_fake_qwen(client, [exc, exc, exc])
    with pytest.raises(LLMConnectionError):
        await client.complete("system", "user")


@pytest.mark.asyncio
async def test_qwen_api_response_validation_error_caught_by_catchall():
    """Regression check for D-140 Fix 2."""
    client = llm_client.QwenClient()
    resp = httpx.Response(status_code=200, request=httpx.Request("POST", "https://example.com"))
    exc = openai.APIResponseValidationError(response=resp, body=None)
    fake = _install_fake_qwen(client, [exc])
    with pytest.raises(LLMProviderResponseError):
        await client.complete("system", "user")


def test_qwen_client_is_a_shared_singleton():
    """Regression check for D-140 Fix 1."""
    instances = [llm_client.QwenClient() for _ in range(5)]
    assert all(inst._client is instances[0]._client for inst in instances)


# ---------------------------------------------------------------------------
# Mock provider regression
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mock_provider_still_functions():
    client = llm_client.MockLLMClient()
    # mock_extraction pattern-matches "Label: Value" lines out of the
    # embedded document text; a minimal prompt shape is enough to confirm
    # the call path itself works without asserting on extraction content,
    # which is mock_extraction.py's own concern, not this module's.
    result = await client.complete("system prompt", 'Document text:\n"""\nName: Test Person\n"""')
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Factory selection
# ---------------------------------------------------------------------------


def test_factory_defaults_to_mock(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    get_settings.cache_clear()
    llm_client.settings = get_settings()
    assert isinstance(llm_client.get_llm_client(), llm_client.MockLLMClient)


def test_factory_selects_openai(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    get_settings.cache_clear()
    llm_client.settings = get_settings()
    assert isinstance(llm_client.get_llm_client(), llm_client.OpenAIClient)


def test_factory_selects_qwen(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "qwen")
    get_settings.cache_clear()
    llm_client.settings = get_settings()
    assert isinstance(llm_client.get_llm_client(), llm_client.QwenClient)


def test_factory_selects_gemini(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    get_settings.cache_clear()
    llm_client.settings = get_settings()
    assert isinstance(llm_client.get_llm_client(), llm_client.GeminiClient)


def test_factory_unknown_provider_falls_back_to_mock(monkeypatch):
    """
    Documents existing, unchanged behavior: get_llm_client() only special-
    cases "openai", "qwen", and "gemini"; anything else (including a typo)
    silently falls back to Mock. Pre-existing factory behavior, recorded
    here so a future change to it is a deliberate decision, not an
    accidental regression.
    """
    monkeypatch.setenv("LLM_PROVIDER", "not-a-real-provider")
    get_settings.cache_clear()
    llm_client.settings = get_settings()
    assert isinstance(llm_client.get_llm_client(), llm_client.MockLLMClient)


# ---------------------------------------------------------------------------
# Configuration validation
# ---------------------------------------------------------------------------


def test_settings_openai_defaults(monkeypatch):
    monkeypatch.delenv("OPENAI_MAX_RETRIES", raising=False)
    monkeypatch.delenv("OPENAI_RETRY_BACKOFF_SECONDS", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    get_settings.cache_clear()
    settings = Settings(_env_file=None)
    assert settings.llm_provider == "mock"  # every real provider is opt-in; mock is the code default
    assert settings.openai_model == "gpt-5.6"
    assert settings.openai_timeout_seconds == 120.0
    assert settings.openai_max_retries == 3
    assert settings.openai_retry_backoff_seconds == 1.0
    assert settings.openai_base_url is None


def test_settings_gemini_defaults(monkeypatch):
    # The autouse `fast_settings` fixture deliberately overrides retry/backoff
    # env vars for speed elsewhere in this suite; unset them here so this
    # test actually observes Settings' real, un-overridden defaults. Also
    # bypass any real .env file on disk (_env_file=None) -- found during the
    # Vertex AI migration audit that this test silently depended on no real
    # .env existing in the working directory, which is false for any actual
    # developer checkout (LLM_PROVIDER has been set explicitly in .env since
    # M11.5).
    monkeypatch.delenv("GEMINI_MAX_RETRIES", raising=False)
    monkeypatch.delenv("GEMINI_RETRY_BACKOFF_SECONDS", raising=False)
    monkeypatch.delenv("GEMINI_MAX_RETRY_DELAY_SECONDS", raising=False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("GEMINI_AUTH_MODE", raising=False)
    settings = Settings(_env_file=None)
    assert settings.llm_provider == "mock"  # every real provider is opt-in; mock is the code default
    assert settings.gemini_model == "gemini-2.5-flash"
    assert settings.gemini_timeout_seconds == 30.0
    assert settings.gemini_max_retries == 3
    assert settings.gemini_retry_backoff_seconds == 1.0
    assert settings.gemini_max_retry_delay_seconds == 30.0
    assert settings.gemini_auth_mode == "developer"  # unchanged local-dev default


def test_settings_qwen_defaults_unchanged(monkeypatch):
    monkeypatch.delenv("QWEN_MAX_RETRIES", raising=False)
    monkeypatch.delenv("QWEN_RETRY_BACKOFF_SECONDS", raising=False)
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.qwen_model == "qwen-plus"
    assert settings.qwen_timeout_seconds == 30.0
    assert settings.qwen_max_retries == 3
    assert settings.qwen_retry_backoff_seconds == 1.0


def test_settings_secret_key_fail_fast_outside_development():
    """
    BidOps_Final Milestone 5: SECRET_KEY must not be the shipped insecure
    default outside a development environment.
    """
    with pytest.raises(Exception):
        Settings(
            _env_file=None,
            app_env="production",
            secret_key="dev-only-insecure-secret-change-me",
        )


def test_settings_secret_key_fail_fast_allows_development_default():
    """The same default is explicitly fine in development -- must not block a fresh local checkout."""
    settings = Settings(_env_file=None, app_env="development")
    assert settings.secret_key == "dev-only-insecure-secret-change-me"


def test_settings_secret_key_fail_fast_allows_real_secret_in_production():
    settings = Settings(_env_file=None, app_env="production", secret_key="a-real-random-secret")
    assert settings.secret_key == "a-real-random-secret"
