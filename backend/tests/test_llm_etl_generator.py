from unittest.mock import MagicMock

import httpx
import pytest

from app import llm_etl_generator as leg
from app.llm_etl_generator import _build_prompt

DDL = "CREATE TABLE dim_game (...)"
SAMPLE = "app_id,name\n1,Foo\n"


def test_first_attempt_has_no_retry_guidance():
    prompt = _build_prompt("csv", DDL, SAMPLE)
    assert "previous attempt" not in prompt.lower()
    assert "vectorized" not in prompt.lower()


def test_generic_error_retry_asks_to_fix_the_bug_not_vectorize():
    # A real logic bug (KeyError, IntegrityError, ...) should get the normal
    # "fix the bug" framing, not be told its algorithmic approach is the problem -
    # that framing is reserved for genuine timeouts (see the test below).
    prompt = _build_prompt(
        "csv", DDL, SAMPLE,
        previous_code="def run_etl(df, conn): ...",
        previous_error="KeyError: 'app_id'",
        previous_error_was_timeout=False,
    )
    assert "fix the bug" in prompt.lower()
    assert "vectorized" not in prompt.lower()
    assert "KeyError" in prompt


def test_timeout_retry_asks_to_avoid_per_row_python_loop():
    # Regression test for a real observed failure: 3 retries in a row all timed
    # out because "fix the bug" framing on a TimeoutError just produces another
    # differently-shaped but still row-by-row Python loop. The prompt must instead
    # explicitly steer away from per-row iteration when the previous failure was a
    # timeout specifically (not a logic error).
    prompt = _build_prompt(
        "json", DDL, SAMPLE,
        previous_code="def run_etl(df, conn): ...",
        previous_error="TimeoutError: Generated code did not finish within 90s",
        previous_error_was_timeout=True,
    )
    lowered = prompt.lower()
    assert "did not raise a logic error" in lowered
    assert "vectorized" in lowered
    assert "executemany" in lowered
    assert "fix the bug and return the corrected" not in lowered


def test_get_client_passes_a_bounded_http_timeout(monkeypatch):
    # Regression test: the Gemini API call itself used to have NO timeout at all -
    # a hung request could block a job forever with no recovery, unlike script
    # execution (which is genuinely bounded via subprocess kill). Confirms the
    # client is actually constructed with a timeout, not just that one exists.
    monkeypatch.setattr(leg.api_key_store, "get_api_key", lambda: "fake-key")
    captured = {}

    def fake_client(**kwargs):
        captured.update(kwargs)
        return MagicMock()

    monkeypatch.setattr(leg.genai, "Client", fake_client)

    leg._get_client()

    assert captured["api_key"] == "fake-key"
    assert captured["http_options"].timeout == leg.GEMINI_HTTP_TIMEOUT_SECONDS * 1000


def test_generate_etl_code_wraps_a_hung_network_call(monkeypatch):
    # Simulates the Gemini HTTP call itself hanging past the timeout (httpx's own
    # exception, which genai_errors.APIError does NOT catch) - must surface as a
    # clear GenerationTimeoutError, not an unhandled httpx exception or a silent hang.
    monkeypatch.setattr(leg.quota_guard, "check_and_reserve", lambda: None)
    fake_client = MagicMock()
    fake_client.models.generate_content.side_effect = httpx.ConnectTimeout("timed out")
    monkeypatch.setattr(leg, "_get_client", lambda: fake_client)

    with pytest.raises(leg.GenerationTimeoutError):
        leg.generate_etl_code("csv", DDL, SAMPLE)
