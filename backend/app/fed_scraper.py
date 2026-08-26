"""Scrapes recent FOMC statements from federalreserve.gov.

No API key needed. Uses the Fed's public RSS feed for monetary policy press
releases, then fetches the full statement text from each release's page.
"""

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup

RSS_FEED_URL = "https://www.federalreserve.gov/feeds/press_monetary.xml"
BASE_URL = "https://www.federalreserve.gov"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; VantageResearchApp/1.0; personal use)"
}


@dataclass
class FedStatementRef:
    id: str
    title: str
    url: str
    date: str  # ISO date string, best-effort


def _statement_id_from_url(url: str) -> str:
    # e.g. https://www.federalreserve.gov/newsevents/pressreleases/monetary20240320a.htm
    match = re.search(r"([\w-]+)\.htm$", url)
    return match.group(1) if match else url


async def fetch_recent_statements(limit: int = 10) -> list[FedStatementRef]:
    """Fetch the most recent monetary policy press releases from the RSS feed."""
    async with httpx.AsyncClient(timeout=15, headers=HEADERS, follow_redirects=True) as client:
        resp = await client.get(RSS_FEED_URL)
        resp.raise_for_status()

    root = ET.fromstring(resp.text)
    refs: list[FedStatementRef] = []
    for item in root.findall(".//item")[:limit]:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub_date = (item.findtext("pubDate") or "").strip()
        if not link:
            continue
        refs.append(
            FedStatementRef(
                id=_statement_id_from_url(link),
                title=title,
                url=link,
                date=_parse_pubdate(pub_date),
            )
        )
    return refs


def _parse_pubdate(pub_date: str) -> str:
    from email.utils import parsedate_to_datetime

    try:
        return parsedate_to_datetime(pub_date).date().isoformat()
    except (TypeError, ValueError):
        return pub_date


async def fetch_statement_text(url: str) -> str:
    """Fetch and extract the plain-text body of a Fed press release page."""
    async with httpx.AsyncClient(timeout=15, headers=HEADERS, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    content = soup.find("div", id="article") or soup.find(
        "div", class_=re.compile(r"col-xs-12.*col-md-8")
    )
    if content is None:
        content = soup.find("main") or soup.body

    if content is None:
        return ""

    paragraphs = [p.get_text(" ", strip=True) for p in content.find_all("p")]
    text = "\n\n".join(p for p in paragraphs if p)
    return text.strip()
