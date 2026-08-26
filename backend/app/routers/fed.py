from fastapi import APIRouter, HTTPException

from app import db
from app.claude_client import SummarizationError, summarize_statement
from app.fed_scraper import fetch_recent_statements, fetch_statement_text

router = APIRouter(prefix="/api/fed", tags=["fed"])


@router.get("/timeline")
def get_timeline(limit: int = 20) -> list[dict]:
    return db.get_fed_timeline(limit=limit)


@router.post("/refresh")
async def refresh_fed_timeline(max_new: int = 5) -> dict:
    """Fetch the latest statements from federalreserve.gov and summarize any
    that aren't already cached. Cheap to call repeatedly: statements already
    in the cache are skipped without hitting the Claude API."""
    try:
        refs = await fetch_recent_statements(limit=max_new)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch Fed statements: {e}") from e

    added: list[str] = []
    errors: list[str] = []

    def record_error(message: str) -> None:
        """Keep one copy of each distinct problem.

        A single root cause (an expired key, no API credit) otherwise repeats
        once per statement and buries the actual message.
        """
        if message not in errors:
            errors.append(message)

    for ref in refs:
        if db.statement_exists(ref.id):
            continue
        try:
            text = await fetch_statement_text(ref.url)
            if not text:
                record_error(f"Couldn't read the text of the {ref.date} statement.")
                continue
            summary = summarize_statement(text)
            db.save_fed_statement(
                statement_id=ref.id,
                date=ref.date,
                title=ref.title,
                url=ref.url,
                raw_text=text,
                summary=summary["summary"],
                sentiment=summary["sentiment"],
                key_takeaways=summary["key_takeaways"],
            )
            added.append(ref.id)
        except SummarizationError as e:
            record_error(str(e))
        except Exception as e:
            record_error(f"Couldn't process the {ref.date} statement: {e}")

    return {
        "added": added,
        "errors": errors,
        "timeline": db.get_fed_timeline(),
    }
