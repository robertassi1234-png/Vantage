import pathlib
import subprocess
import sys

import anthropic
import httpx
import pytest

from app import claude_client
from app.claude_client import SummarizationError, summarize_statement

GOOD_JSON = (
    '{"sentiment": "hawkish", "summary": "Held rates steady.", '
    '"key_takeaways": ["Rate unchanged", "Inflation easing"]}'
)


class FakeTextBlock:
    type = "text"

    def __init__(self, text):
        self.text = text


class FakeResponse:
    def __init__(self, text):
        self.content = [FakeTextBlock(text)]


def install(monkeypatch, *, text=None, error=None):
    """Swap in a stub Anthropic client that returns `text` or raises `error`."""

    class FakeMessages:
        def create(self, **kwargs):
            if error is not None:
                raise error
            return FakeResponse(text)

    class FakeClient:
        def __init__(self, **kwargs):
            self.messages = FakeMessages()

    monkeypatch.setattr(anthropic, "Anthropic", FakeClient)


def api_error(cls, message):
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(400, request=request, json={"error": {"message": message}})
    return cls(message, response=response, body={"error": {"message": message}})


class TestSummarize:
    def test_parses_a_clean_response(self, monkeypatch):
        install(monkeypatch, text=GOOD_JSON)
        result = summarize_statement("FOMC text")
        assert result["sentiment"] == "hawkish"
        assert result["summary"] == "Held rates steady."
        assert result["key_takeaways"] == ["Rate unchanged", "Inflation easing"]

    def test_tolerates_markdown_fences_and_prose(self, monkeypatch):
        install(monkeypatch, text=f"Here you go:\n```json\n{GOOD_JSON}\n```\nHope that helps!")
        assert summarize_statement("text")["sentiment"] == "hawkish"

    def test_unexpected_sentiment_falls_back_to_neutral(self, monkeypatch):
        install(monkeypatch, text='{"sentiment": "spicy", "summary": "s", "key_takeaways": []}')
        assert summarize_statement("text")["sentiment"] == "neutral"

    def test_sentiment_is_case_insensitive(self, monkeypatch):
        install(monkeypatch, text='{"sentiment": "DOVISH", "summary": "s", "key_takeaways": []}')
        assert summarize_statement("text")["sentiment"] == "dovish"

    def test_missing_fields_do_not_crash(self, monkeypatch):
        install(monkeypatch, text='{"sentiment": "neutral"}')
        result = summarize_statement("text")
        assert result["summary"] == ""
        assert result["key_takeaways"] == []

    def test_response_without_json_raises(self, monkeypatch):
        install(monkeypatch, text="I could not analyse that.")
        with pytest.raises(SummarizationError, match="did not contain JSON"):
            summarize_statement("text")

    def test_missing_key_raises_before_calling_out(self, monkeypatch):
        monkeypatch.setattr(claude_client.settings, "anthropic_api_key", "")
        with pytest.raises(SummarizationError, match="ANTHROPIC_API_KEY is not set"):
            summarize_statement("text")

    def test_statement_text_is_truncated(self, monkeypatch):
        captured = {}

        class FakeMessages:
            def create(self, **kwargs):
                captured.update(kwargs)
                return FakeResponse(GOOD_JSON)

        class FakeClient:
            def __init__(self, **kwargs):
                self.messages = FakeMessages()

        monkeypatch.setattr(anthropic, "Anthropic", FakeClient)
        summarize_statement("x" * 50_000)
        assert len(captured["messages"][0]["content"]) == 12_000


class TestErrorMessages:
    """The whole point of these branches is that a non-technical user can act on them."""

    def test_no_credit_explains_where_to_add_it(self, monkeypatch):
        install(
            monkeypatch,
            error=api_error(
                anthropic.BadRequestError,
                "Your credit balance is too low to access the Anthropic API.",
            ),
        )
        with pytest.raises(SummarizationError) as excinfo:
            summarize_statement("text")

        message = str(excinfo.value)
        assert "out of credit" in message
        assert "console.anthropic.com" in message

    def test_other_bad_requests_keep_the_original_detail(self, monkeypatch):
        install(monkeypatch, error=api_error(anthropic.BadRequestError, "model not found"))
        with pytest.raises(SummarizationError, match="model not found"):
            summarize_statement("text")

    def test_bad_key_message_names_the_env_var(self, monkeypatch):
        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        response = httpx.Response(401, request=request, json={"error": {"message": "bad key"}})
        install(
            monkeypatch,
            error=anthropic.AuthenticationError("bad key", response=response, body=None),
        )
        with pytest.raises(SummarizationError, match="ANTHROPIC_API_KEY"):
            summarize_statement("text")

    def test_connection_error_is_translated(self, monkeypatch):
        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        install(
            monkeypatch,
            error=anthropic.APIConnectionError(request=request),
        )
        with pytest.raises(SummarizationError, match="Couldn't reach"):
            summarize_statement("text")


class TestStartupCost:
    """The SDK is loaded on demand, not when the app boots.

    A reader who never opens the Fed tracker should not wait for it. The
    saving is around a tenth of a second, which is worth having and easy to
    lose: a plain `import anthropic` at the top of this module would put the
    cost back on every cold start without anything failing, so the guarantee
    is asserted rather than assumed.
    """

    def test_importing_the_app_does_not_load_the_sdk(self):
        source = pathlib.Path(claude_client.__file__).read_text()
        assert "\nimport anthropic\n" not in source

        probe = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; import app.main; "
                "print('anthropic' in sys.modules)",
            ],
            capture_output=True,
            text=True,
            cwd=pathlib.Path(claude_client.__file__).parent.parent,
        )
        assert probe.returncode == 0, probe.stderr
        assert probe.stdout.strip() == "False", probe.stdout

    def test_the_summariser_still_gets_a_working_sdk(self, monkeypatch):
        claude_client.anthropic = None
        install(monkeypatch, text=GOOD_JSON)
        assert claude_client.summarize_statement("text")["sentiment"] == "hawkish"
        assert claude_client.anthropic is anthropic
