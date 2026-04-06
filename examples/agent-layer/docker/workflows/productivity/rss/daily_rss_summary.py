"""
RSS News Aggregator Workflow
Fetches RSS feeds, summarizes every article with LLM, stores in DB, sends report via email.
Runs automatically every 6 hours.
"""

from __future__ import annotations

import json
import hashlib
import logging
import feedparser
import asyncio
from pathlib import Path
from datetime import datetime
from typing import Any

import httpx

from app import db
from app.agent import chat_completion

logger = logging.getLogger(__name__)

__version__ = "1.0.0"

RUN_ON_STARTUP = False
RUN_EVERY_MINUTES = 360 # every 6 hours

# Add your RSS feeds here
RSS_FEEDS = [
    "https://www.reddit.com/r/LocalLLaMA/.rss",
    "https://www.reddit.com/r/selfhosted/.rss",
    "https://hnrss.org/newest",
    "https://www.theregister.com/headlines.atom",
    "https://lwn.net/headlines/rss",
]

SUMMARY_PROMPT = """
Du bist technischer News Redakteur.
Fasse diesen Artikel auf Deutsch kurz und präzise zusammen:
{title}

{content}

Nur das wichtigste in max 3 Sätzen. Keine Einleitungen.
"""


def _article_id(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()


def _already_processed(url: str) -> bool:
    aid = _article_id(url)
    with db.pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM rss_articles WHERE article_id = %s", (aid,))
            return cur.fetchone() is not None


def _mark_processed(url: str, title: str, summary: str) -> None:
    aid = _article_id(url)
    with db.pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO rss_articles (article_id, url, title, summary, fetched_at)
                VALUES (%s, %s, %s, %s, NOW())
                ON CONFLICT (article_id) DO NOTHING
            """, (aid, url, title, summary))
        conn.commit()


def daily_rss_summary(arguments: dict[str, Any]) -> str:
    """
    Run full RSS summary workflow: fetch all feeds, summarize new articles, generate report.
    """
    logger.info("Starting RSS summary workflow")

    new_articles = []

    for feed_url in RSS_FEEDS:
        try:
            logger.info(f"Fetching feed: {feed_url}")
            feed = feedparser.parse(feed_url)

            for entry in feed.entries[:10]:
                url = entry.link
                title = entry.title
                content = entry.get("summary", entry.get("description", ""))

                if _already_processed(url):
                    continue

                logger.info(f"Processing new article: {title}")

                # Summarize with local LLM
                try:
                    completion = asyncio.run(chat_completion({
                        "stream": False,
                        "messages": [
                            {
                                "role": "user",
                                "content": SUMMARY_PROMPT.format(title=title, content=content)
                            }
                        ],
                        "temperature": 0.3,
                        "max_tokens": 512
                    }))
                    summary = completion["choices"][0]["message"]["content"].strip()
                    _mark_processed(url, title, summary)

                    new_articles.append({
                        "title": title,
                        "url": url,
                        "summary": summary
                    })

                except Exception as e:
                    logger.error(f"Failed to summarize article {url}: {e}")
                    continue

        except Exception as e:
            logger.error(f"Failed to fetch feed {feed_url}: {e}")
            continue

    logger.info(f"Workflow completed. Found {len(new_articles)} new articles.")

    # Generate markdown report
    report = "# RSS News Summary\n\n"
    report += f"Generiert am: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"

    for article in new_articles:
        report += f"## [{article['title']}]({article['url']})\n\n"
        report += f"{article['summary']}\n\n---\n\n"

    # TODO: Send via email, save as file, send webhook

    # Write report to file
    report_path = Path(__file__).parent / "output" / "daily-summary.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    logger.info(f"Written markdown report to: {report_path.resolve()}")

    return json.dumps({
        "ok": True,
        "new_articles": len(new_articles),
        "report_file": str(report_path),
        "report": report
    }, ensure_ascii=False)


HANDLERS: dict[str, Any] = {
    "daily_rss_summary": daily_rss_summary,
}
