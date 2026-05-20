from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import html
import re
from typing import Iterable
import xml.etree.ElementTree as ET

import requests


@dataclass
class NewsItem:
    title: str
    link: str
    summary: str
    source: str
    published_at: datetime | None


def _strip_html(text: str) -> str:
    cleaned = text.replace("<![CDATA[", "").replace("]]>", "")
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = html.unescape(cleaned)
    return " ".join(cleaned.split())


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except Exception:
        return None


def _node_text(parent: ET.Element, tag_names: Iterable[str]) -> str:
    for tag in tag_names:
        node = parent.find(tag)
        if node is not None and node.text:
            return node.text.strip()
    return ""


def _parse_rss(xml_text: str, feed_url: str) -> list[NewsItem]:
    items: list[NewsItem] = []
    root = ET.fromstring(xml_text)

    if root.tag.endswith("rss"):
        channel = root.find("channel")
        default_source = _node_text(channel, ["title"]) if channel is not None else feed_url
        for item in root.findall(".//item"):
            title = _node_text(item, ["title"])
            link = _node_text(item, ["link"])
            summary = _node_text(item, ["description"])
            source = _node_text(item, ["source"]) or default_source
            published_at = _parse_datetime(_node_text(item, ["pubDate"]))
            if title and link:
                items.append(
                    NewsItem(
                        title=title,
                        link=link,
                        summary=_strip_html(summary),
                        source=source,
                        published_at=published_at,
                    )
                )

    elif root.tag.endswith("feed"):
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        default_source = _node_text(root, ["atom:title", "title"]) or feed_url
        for entry in root.findall("atom:entry", ns):
            title = _node_text(entry, ["atom:title", "title"])
            summary = _node_text(entry, ["atom:summary", "summary"])
            source = default_source
            published_at = _parse_datetime(_node_text(entry, ["atom:published", "atom:updated"]))
            link = ""
            link_node = entry.find("atom:link", ns)
            if link_node is not None:
                link = link_node.attrib.get("href", "").strip()
            if title and link:
                items.append(
                    NewsItem(
                        title=title,
                        link=link,
                        summary=_strip_html(summary),
                        source=source,
                        published_at=published_at,
                    )
                )

    return items


def fetch_stock_news(feeds: list[str], max_items: int = 10, timeout_seconds: int = 15) -> list[NewsItem]:
    collected: list[NewsItem] = []
    seen_links: set[str] = set()
    headers = {"User-Agent": "Mozilla/5.0 (compatible; StockNewsAgent/1.0)"}

    for feed_url in feeds:
        try:
            response = requests.get(feed_url, timeout=timeout_seconds, headers=headers)
            response.raise_for_status()
            parsed_items = _parse_rss(response.text, feed_url)
            for item in parsed_items:
                if item.link in seen_links:
                    continue
                seen_links.add(item.link)
                collected.append(item)
        except Exception as exc:
            print(f"Failed to read feed '{feed_url}': {exc}")

    collected.sort(
        key=lambda n: n.published_at if n.published_at else datetime(1970, 1, 1, tzinfo=timezone.utc),
        reverse=True,
    )
    return collected[:max_items]
