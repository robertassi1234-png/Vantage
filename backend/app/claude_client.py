"""Summarizes Fed statements using Claude Haiku."""

import json
import re

import anthropic

from app.config import settings

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

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    truncated = statement_text[:12000]

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=600,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": truncated}],
        )
    except anthropic.AuthenticationError as e:
        raise SummarizationError("Invalid Anthropic API key") from e
    except anthropic.RateLimitError as e:
        raise SummarizationError("Anthropic API rate limit reached") from e
    except anthropic.APIStatusError as e:
        raise SummarizationError(f"Anthropic API error: {e.message}") from e

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
