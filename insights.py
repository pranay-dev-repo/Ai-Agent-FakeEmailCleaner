from __future__ import annotations

import json
import os
from collections import Counter
from typing import Iterable

import requests

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
    }
    words: list[str] = []
    for title in titles:
        for token in title.lower().replace(",", " ").replace(".", " ").split():
            token = token.strip("()[]{}'\"-:;!?")
            if len(token) < 3 or token in stopwords:
                continue
            words.append(token)
    return Counter(words)


def fallback_insights(items: list[NewsItem], max_points: int = 4) -> list[str]:
    if not items:
        return ["No major stock headlines were captured today."]

    keywords = _extract_keywords(item.title for item in items)
    top_words = [word for word, _ in keywords.most_common(3)]
    insights: list[str] = []

    if top_words:
        insights.append(f"Dominant themes in headlines: {', '.join(top_words)}.")

    if any("s&p" in item.title.lower() or "nasdaq" in item.title.lower() for item in items):
        insights.append("Index-level movement (S&P 500 or Nasdaq) is a key focus today.")

    if any("earnings" in item.title.lower() for item in items):
        insights.append("Earnings-related stories are influencing market attention.")

    unique_sources = {item.source for item in items if item.source}
    insights.append(f"Coverage is coming from {len(unique_sources)} different news sources.")

    return insights[:max_points]


def generate_ai_insights(
    items: list[NewsItem],
    api_key: str,
    model: str = "llama-3.3-70b-versatile",
    max_points: int = 4,
    timeout_seconds: int = 25,
) -> list[str]:
    if not api_key or not items:
        return fallback_insights(items, max_points=max_points)

    headlines = "\n".join(f"- {item.title}" for item in items[:12])
    prompt = (
        "You are a financial news assistant. Based only on the headlines below, generate "
        f"{max_points} concise, non-advisory market insights as a JSON array of strings. "
        "Avoid price targets and investment advice.\n\n"
        f"Headlines:\n{headlines}"
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

    return fallback_insights(items, max_points=max_points)


def load_openai_key(env_var_name: str = "GROQ_API_KEY") -> str:
    return os.getenv(env_var_name, "").strip()
