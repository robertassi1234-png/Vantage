from app import fed_scraper
from app.fed_scraper import _parse_pubdate, _statement_id_from_url

RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item>
    <title>Federal Reserve issues FOMC statement</title>
    <link>https://www.federalreserve.gov/newsevents/pressreleases/monetary20260729a.htm</link>
    <pubDate>Wed, 29 Jul 2026 14:00:00 GMT</pubDate>
  </item>
  <item>
    <title>Minutes of the FOMC</title>
    <link>https://www.federalreserve.gov/newsevents/pressreleases/monetary20260617b.htm</link>
    <pubDate>Wed, 17 Jun 2026 18:00:00 GMT</pubDate>
  </item>
</channel></rss>"""

PAGE = """<html><body>
  <nav><a href="/">Home</a><a href="/about">About</a></nav>
  <div id="article">
    <p>The Committee decided to maintain the target range.</p>
    <p>Inflation has eased over the past year.</p>
  </div>
  <footer><p>Board of Governors of the Federal Reserve System</p></footer>
</body></html>"""


class FakeResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        return None


class FakeClient:
    def __init__(self, payload):
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url):
        return FakeResponse(self._payload)


def patch_client(monkeypatch, payload):
    monkeypatch.setattr(
        fed_scraper.httpx, "AsyncClient", lambda **kwargs: FakeClient(payload)
    )


class TestStatementId:
    def test_extracts_slug_from_url(self):
        url = "https://www.federalreserve.gov/newsevents/pressreleases/monetary20260729a.htm"
        assert _statement_id_from_url(url) == "monetary20260729a"

    def test_unparseable_url_falls_back_to_the_url(self):
        assert _statement_id_from_url("https://example.gov/no-extension") == (
            "https://example.gov/no-extension"
        )


class TestPubDate:
    def test_rfc822_becomes_iso_date(self):
        assert _parse_pubdate("Wed, 29 Jul 2026 14:00:00 GMT") == "2026-07-29"

    def test_garbage_is_passed_through_rather_than_crashing(self):
        assert _parse_pubdate("not a date") == "not a date"


class TestFetchRecentStatements:
    async def test_parses_feed_items(self, monkeypatch):
        patch_client(monkeypatch, RSS)
        refs = await fed_scraper.fetch_recent_statements()

        assert [r.id for r in refs] == ["monetary20260729a", "monetary20260617b"]
        assert refs[0].date == "2026-07-29"
        assert refs[0].title == "Federal Reserve issues FOMC statement"

    async def test_limit_is_respected(self, monkeypatch):
        patch_client(monkeypatch, RSS)
        assert len(await fed_scraper.fetch_recent_statements(limit=1)) == 1


class TestFetchStatementText:
    async def test_extracts_article_body(self, monkeypatch):
        patch_client(monkeypatch, PAGE)
        text = await fed_scraper.fetch_statement_text("https://example.gov/a.htm")

        assert "maintain the target range" in text
        assert "Inflation has eased" in text

    async def test_navigation_and_footer_are_excluded(self, monkeypatch):
        """Chrome text would poison the summary, so the article div is targeted."""
        patch_client(monkeypatch, PAGE)
        text = await fed_scraper.fetch_statement_text("https://example.gov/a.htm")

        assert "Home" not in text
        assert "Board of Governors" not in text

    async def test_page_without_article_div_still_returns_something(self, monkeypatch):
        patch_client(monkeypatch, "<html><body><main><p>Fallback body.</p></main></body></html>")
        text = await fed_scraper.fetch_statement_text("https://example.gov/a.htm")
        assert "Fallback body." in text

    async def test_empty_page_returns_empty_string(self, monkeypatch):
        patch_client(monkeypatch, "<html><body></body></html>")
        assert await fed_scraper.fetch_statement_text("https://example.gov/a.htm") == ""
