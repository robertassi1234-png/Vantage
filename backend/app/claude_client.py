"""Summarizes Fed statements using Claude Haiku."""

import json
import re

from app.config import settings

# Only the Fed summariser needs the Anthropic SDK, so it is loaded on first
# use rather than at startup. Measured in isolation the import costs about a
# third of a second; most of that is httpx and pydantic, which the app loads
# anyway, so deferring it saves roughly a tenth of a second off every cold
# start. Small, but it is a tenth of a second nobody waits for twice.
anthropic = None


def _sdk():
    global anthropic
    if anthropic is None:
        import anthropic as module

        anthropic = module
    return anthropic


MODEL = "claude-haiku-4-5"

SYSTEM_PROMPT = """You are a financial analyst assistant. You will be given the \
text of a Federal Reserve press release or FOMC statement. Analyze its tone and \
respond with ONLY a JSON object (no markdown fences, no commentary) matching this \
exact shape:

{"sentiment": "hawkish" | "dovish" | "neutral", "summary": "2-3 sentence plain-English summary", \
"key_takeaways": ["short bullet point", "short bullet point", "short bullet point"]}

"hawkish" means leaning toward tighter policy / rate hikes / inflation concern. \
"dovish" means leaning toward looser policy / rate cuts / growth concern. \
"neutral" means balanced or unchanged stance."""


class SummarizationError(Exception):
    pass


def _extract_json(raw_text: str) -> dict:
    match = re.search(r"\{.*\}", raw_text, re.DOTALL)
    if not match:
        raise SummarizationError("Claude response did not contain JSON")
    return json.loads(match.group(0))


def summarize_statement(statement_text: str) -> dict:
    if not settings.anthropic_api_key:
        raise SummarizationError("ANTHROPIC_API_KEY is not set")

    sdk = _sdk()
    client = sdk.Anthropic(api_key=settings.anthropic_api_key)

    truncated = statement_text[:12000]

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=600,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": truncated}],
        )
    except sdk.AuthenticationError as e:
        raise SummarizationError(
            "Your Anthropic API key was rejected. Check ANTHROPIC_API_KEY in your "
            "backend settings."
        ) from e
    except sdk.RateLimitError as e:
        raise SummarizationError(
            "Anthropic rate limit reached. Wait a minute and try again."
        ) from e
    except sdk.BadRequestError as e:
        message = str(getattr(e, "message", "")) or str(e)
        if "credit balance" in message.lower():
            raise SummarizationError(
                "Your Anthropic account is out of credit, so statements can't be "
                "summarized. Add credit at console.anthropic.com under Plans & Billing, "
                "then try again."
            ) from e
        raise SummarizationError(f"Anthropic rejected the request: {message}") from e
    except sdk.APIStatusError as e:
        raise SummarizationError(f"Anthropic API error: {e.message}") from e
    except sdk.APIConnectionError as e:
        raise SummarizationError(
            "Couldn't reach the Anthropic API. Check your network and try again."
        ) from e

    text = next((b.text for b in response.content if b.type == "text"), "")
    parsed = _extract_json(text)

    sentiment = str(parsed.get("sentiment", "neutral")).lower()
    if sentiment not in ("hawkish", "dovish", "neutral"):
        sentiment = "neutral"

    return {
        "sentiment": sentiment,
        "summary": parsed.get("summary", ""),
        "key_takeaways": parsed.get("key_takeaways", []),
    }
