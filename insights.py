from __future__ import annotations

import json
import os
from collections import Counter
from typing import Iterable

import requests

from delivery_data import DeliverySnapshot, TodayDeliverySnapshot
from fetcher import NewsItem


def _extract_keywords(titles: Iterable[str]) -> Counter:
    stopwords = {
        "the",
        "and",
        "for",
        "with",
        "from",
        "into",
        "after",
        "over",
        "just",
        "gets",
        "why",
        "how",
        "today",
        "stock",
        "stocks",
        "market",
        "india",
        "indian",
        "nifty",
        "sensex",
        "bse",
        "nse",
    }
    words: list[str] = []
    for title in titles:
        for token in title.lower().replace(",", " ").replace(".", " ").split():
            token = token.strip("()[]{}'\"-:;!?")
            if len(token) < 3 or token in stopwords:
                continue
            words.append(token)
    return Counter(words)


def _delivery_context(snapshot: DeliverySnapshot | TodayDeliverySnapshot | None) -> str:
    if not snapshot or not snapshot.has_data:
        return "NSE delivery data was unavailable."
    if isinstance(snapshot, TodayDeliverySnapshot):
        top = snapshot.stocks[:10]
        lines = [f"{s.symbol} {s.delivery_percent:.1f}%" for s in top]
        return f"Top delivery % stocks today ({snapshot.trade_date}):\n" + ", ".join(lines)
    lines = []
    for sector in snapshot.sectors[:8]:
        leaders = ", ".join(
            f"{item.symbol} {item.avg_delivery_percent:.1f}%"
            for item in sector.leaders[:3]
        )
        if leaders:
            lines.append(f"{sector.sector}: {leaders}")
    return "\n".join(lines) or "NSE delivery data was unavailable."


def fallback_insights(
    items: list[NewsItem],
    max_points: int = 4,
    delivery_snapshot: DeliverySnapshot | TodayDeliverySnapshot | None = None,
) -> list[str]:
    if not items:
        return ["No major Indian stock market headlines were captured today."]

    keywords = _extract_keywords(item.title for item in items)
    top_words = [word for word, _ in keywords.most_common(3)]
    insights: list[str] = []

    if top_words:
        insights.append(f"Dominant Indian market themes in headlines: {', '.join(top_words)}.")

    if any("nifty" in item.title.lower() or "sensex" in item.title.lower() for item in items):
        insights.append("Nifty/Sensex direction is a key focus in current Indian market coverage.")

    if any("results" in item.title.lower() or "earnings" in item.title.lower() for item in items):
        insights.append("Quarterly results and management commentary may drive stock-specific moves.")

    if delivery_snapshot and delivery_snapshot.has_data:
        if isinstance(delivery_snapshot, TodayDeliverySnapshot):
            top = delivery_snapshot.stocks[0]
            insights.append(
                f"Highest delivery % today: {top.symbol} at {top.delivery_percent:.1f}%, "
                f"suggesting strong institutional accumulation."
            )
        else:
            strongest = []
            for sector in delivery_snapshot.sectors:
                if sector.leaders:
                    s = sector.leaders[0]
                    strongest.append((sector.sector, s.avg_delivery_percent, s.symbol))
            strongest.sort(key=lambda row: row[1], reverse=True)
            if strongest:
                sector, pct, symbol = strongest[0]
                insights.append(
                    f"Highest recent delivery interest is in {sector}, led by {symbol} at {pct:.1f}% average delivery."
                )

    unique_sources = {item.source for item in items if item.source}
    insights.append(f"Coverage is coming from {len(unique_sources)} different Indian market news sources.")

    return insights[:max_points]


def generate_ai_insights(
    items: list[NewsItem],
    api_key: str,
    model: str = "llama-3.3-70b-versatile",
    max_points: int = 4,
    timeout_seconds: int = 25,
    delivery_snapshot: DeliverySnapshot | TodayDeliverySnapshot | None = None,
) -> list[str]:
    if not api_key or not items:
        return fallback_insights(items, max_points=max_points, delivery_snapshot=delivery_snapshot)

    headlines = "\n".join(f"- {item.title}" for item in items[:12])
    delivery = _delivery_context(delivery_snapshot)
    prompt = (
        "You are an Indian equity market assistant. Based only on the headlines and NSE delivery "
        "summary below, generate "
        f"{max_points} concise, non-advisory insights as a JSON array of strings. Include which "
        "sectors look relatively constructive or weak for the coming week, but avoid price targets, "
        "buy/sell calls, and investment advice.\n\n"
        f"Headlines:\n{headlines}\n\n"
        f"NSE delivery summary, last available week:\n{delivery}"
    )

    try:
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
                "max_tokens": 300,
            },
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        output_text = response.json()["choices"][0]["message"]["content"].strip()
        output_text = output_text.replace("```json", "").replace("```", "").strip()
        parsed = json.loads(output_text)
        if isinstance(parsed, list):
            cleaned = [str(x).strip() for x in parsed if str(x).strip()]
            if cleaned:
                return cleaned[:max_points]
    except Exception:
        pass

    return fallback_insights(items, max_points=max_points, delivery_snapshot=delivery_snapshot)


def load_openai_key(env_var_name: str = "GROQ_API_KEY") -> str:
    return os.getenv(env_var_name, "").strip()
