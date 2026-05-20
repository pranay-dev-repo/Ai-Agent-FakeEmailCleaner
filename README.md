# Daily Stock News Agent

This project fetches stock market news headlines, builds a daily post, saves it to disk, and can optionally publish it to a webhook.
It also adds AI-generated insight bullets at the top of each post.

## 1) Install

```powershell
pip install -r requirements.txt
```

## 2) Run manually

```powershell
python main.py
```

This creates:
- `agent_config.json` (if missing)
- a post file in `posts/`

## 3) Optional webhook posting

Set environment variable `NEWS_WEBHOOK_URL` and run:

```powershell
python main.py --publish
```

## 4) Optional OpenAI-powered insights

By default, insights are enabled.
- If `OPENAI_API_KEY` exists, the agent uses OpenAI for richer insight bullets.
- If not, it falls back to deterministic headline-based insights.

Set API key in PowerShell:

```powershell
$env:OPENAI_API_KEY="your_api_key_here"
```

You can tune behavior in `agent_config.json`:
- `insights_enabled`
- `insights_max_points`
- `openai_api_key_env`
- `openai_model`

## 5) Run daily on Windows (Task Scheduler)

Example: run every day at 8:30 AM.

```powershell
schtasks /Create /SC DAILY /TN "DailyStockNewsAgent" /TR "powershell -NoProfile -ExecutionPolicy Bypass -Command \"cd 'D:\Ai_Projects\AI_Agent'; python main.py --publish\"" /ST 08:30
```

To check it:

```powershell
schtasks /Query /TN "DailyStockNewsAgent" /V /FO LIST
```
