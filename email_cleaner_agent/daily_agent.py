"""
Daily Email Cleaning Agent
--------------------------
Steps:
  1. Scan inbox -> collect all sender domains
  2. Find domains not already in bulk_trash.py or whitelist
  3. Classify new domains via Groq AI (or heuristics if no key)
  4. Auto-add spam domains to bulk_trash.py's DOMAINS_TO_TRASH list
  5. Run bulk-trash for all domains in the list
  6. Run email_cleaner.py for AI-based cleanup of remaining emails
"""

import os
import re
import ast
import json
import time
import subprocess
import sys
import base64
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from collections import Counter
from pathlib import Path

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCRIPT_DIR = Path(__file__).parent
CONFIG_FILE = SCRIPT_DIR / 'config.json'
BULK_TRASH_FILE = SCRIPT_DIR / 'bulk_trash.py'
DOMAIN_REVIEW_FILE = SCRIPT_DIR / 'domain_review.json'

# ── Gmail ──────────────────────────────────────────────────────────────────────

def get_gmail_service():
    creds = Credentials(
        token=None,
        refresh_token=os.environ['GOOGLE_REFRESH_TOKEN'],
        token_uri='https://oauth2.googleapis.com/token',
        client_id=os.environ['GOOGLE_CLIENT_ID'],
        client_secret=os.environ['GOOGLE_CLIENT_SECRET'],
        scopes=['https://www.googleapis.com/auth/gmail.modify'],
    )
    creds.refresh(Request())
    return build('gmail', 'v1', credentials=creds)


# ── Domain scanning ────────────────────────────────────────────────────────────

def scan_inbox_domains(service) -> Counter:
    EMAIL_RE = re.compile(r'<([^>]+)>', re.IGNORECASE)

    print('[1/5] Scanning inbox for sender domains...', flush=True)
    messages = []
    page_token = None
    while True:
        kwargs = {'userId': 'me', 'q': 'in:inbox', 'maxResults': 500}
        if page_token:
            kwargs['pageToken'] = page_token
        result = service.users().messages().list(**kwargs).execute()
        messages.extend(result.get('messages', []))
        page_token = result.get('nextPageToken')
        if not page_token:
            break
    print(f'      {len(messages)} inbox emails found', flush=True)

    domains: Counter = Counter()

    def handle(request_id, response, exception):
        if exception or not response:
            return
        try:
            sender = next(
                (h['value'] for h in response['payload']['headers'] if h['name'] == 'From'), ''
            )
            m = EMAIL_RE.search(sender)
            email = m.group(1).lower() if m else sender.strip().lower()
            if '@' in email:
                domains[email.split('@', 1)[1]] += 1
        except Exception:
            pass

    for i in range(0, len(messages), 100):
        batch = service.new_batch_http_request(callback=handle)
        for ref in messages[i:i + 100]:
            batch.add(service.users().messages().get(
                userId='me', id=ref['id'], format='metadata', metadataHeaders=['From']
            ))
        batch.execute()

    print(f'      {len(domains)} unique sender domains detected', flush=True)
    return domains


# ── bulk_trash.py helpers ──────────────────────────────────────────────────────

def load_trash_domains() -> set:
    content = BULK_TRASH_FILE.read_text(encoding='utf-8')
    match = re.search(r'DOMAINS_TO_TRASH\s*=\s*\[([^\]]*)\]', content, re.DOTALL)
    if not match:
        return set()
    return set(ast.literal_eval('[' + match.group(1) + ']'))


def append_to_bulk_trash(new_domains: list):
    if not new_domains:
        return
    content = BULK_TRASH_FILE.read_text(encoding='utf-8')
    # Find closing bracket of DOMAINS_TO_TRASH list
    match = re.search(r'(DOMAINS_TO_TRASH\s*=\s*\[)(.*?)(\n\])', content, re.DOTALL)
    if not match:
        print('  ERROR: Could not locate DOMAINS_TO_TRASH in bulk_trash.py', flush=True)
        return
    new_entries = ''.join(f'\n    "{d}",' for d in sorted(new_domains))
    updated = (
        content[: match.start()]
        + match.group(1)
        + match.group(2).rstrip(',') + ','
        + new_entries
        + match.group(3)
        + content[match.end():]
    )
    BULK_TRASH_FILE.write_text(updated, encoding='utf-8')
    print(f'      Appended {len(new_domains)} new spam domain(s) to bulk_trash.py', flush=True)


def write_domain_review_file(inbox_domains: Counter, review_domains: list, spam_new: list):
    payload = {
        'generated_at': datetime.now().isoformat(timespec='seconds'),
        'domains': [
            {
                'domain': domain,
                'inbox_count': inbox_domains.get(domain, 0),
                'ai_suggested': 'blacklist' if domain in spam_new else 'review',
            }
            for domain in sorted(review_domains, key=lambda d: (-inbox_domains.get(d, 0), d))
        ],
    }
    DOMAIN_REVIEW_FILE.write_text(json.dumps(payload, indent=2) + '\n', encoding='utf-8')
    print(f'      Review file updated: {DOMAIN_REVIEW_FILE.name}', flush=True)


# ── Domain classification ──────────────────────────────────────────────────────

SPAM_KEYWORDS = {
    'mailer', 'newsletter', 'campaign', 'email', 'promo', 'deals', 'notify',
    'notification', 'bulk', 'recruit', 'hiring', 'talent', 'staffing', 'hr',
    'jobs', 'career', 'placement', 'resourcing', 'consultants', 'solutions',
    'services', 'marketing', 'digital', 'inbox', 'dispatch', 'outreach',
    'em.', 'nl.', 'mg.', 'pnm.', 'am.', 'smt.',
}

def heuristic_is_spam(domain: str) -> bool:
    d = domain.lower()
    return any(kw in d for kw in SPAM_KEYWORDS)


def classify_with_groq(domains: list, api_key: str) -> list:
    try:
        from groq import Groq
    except ImportError:
        print('  groq package not installed — falling back to heuristics', flush=True)
        return [d for d in domains if heuristic_is_spam(d)]

    client = Groq(api_key=api_key)
    spam = []

    for i in range(0, len(domains), 20):
        batch = domains[i:i + 20]
        domain_lines = '\n'.join(f'- {d}' for d in batch)
        prompt = (
            'Classify each email sender domain as SPAM or LEGIT.\n\n'
            'SPAM = recruitment agencies, job portals, marketing mailers, '
            'promotional services, unknown/obscure domains, bulk emailers.\n'
            'LEGIT = banks, government agencies, well-known tech companies, '
            'financial institutions, services the user likely signed up for.\n\n'
            f'Domains:\n{domain_lines}\n\n'
            'Reply ONLY with valid JSON: {"domain.com": "SPAM", "other.com": "LEGIT"}'
        )
        try:
            resp = client.chat.completions.create(
                model='llama-3.3-70b-versatile',
                messages=[{'role': 'user', 'content': prompt}],
                temperature=0,
                max_tokens=600,
            )
            text = resp.choices[0].message.content.strip()
            json_match = re.search(r'\{.*?\}', text, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
                spam.extend(d for d, label in result.items() if label.upper() == 'SPAM')
        except Exception as e:
            print(f'  Groq error (batch {i // 20 + 1}): {e} — using heuristics', flush=True)
            spam.extend(d for d in batch if heuristic_is_spam(d))
        time.sleep(0.3)

    return spam


# ── Bulk trash (inline, same logic as bulk_trash.py) ──────────────────────────

def run_bulk_trash(service, trash_domains: set, whitelist_domains: set | None = None):
    print('[4/5] Running bulk trash...', flush=True)
    whitelist_domains = whitelist_domains or set()
    safe_trash_domains = {
        d for d in trash_domains
        if not any(d == w or d.endswith('.' + w) for w in whitelist_domains)
    }
    skipped = sorted(set(trash_domains) - safe_trash_domains)
    if skipped:
        print(f'      Skipping {len(skipped)} whitelisted domain(s) from bulk trash:', flush=True)
        for d in skipped:
            print(f'        KEEP {d}', flush=True)

    total = 0
    per_domain = {}
    for idx, domain in enumerate(sorted(safe_trash_domains)):
        # Rate limit: pause every 5 domains to stay within Gmail quota
        if idx > 0 and idx % 5 == 0:
            time.sleep(1)

        msg_ids = []
        page_token = None
        while True:
            kwargs = {'userId': 'me', 'q': f'in:inbox from:@{domain}', 'maxResults': 500}
            if page_token:
                kwargs['pageToken'] = page_token
            try:
                result = service.users().messages().list(**kwargs).execute()
            except HttpError as e:
                if 'rateLimitExceeded' in str(e):
                    for wait in [15, 30, 60]:
                        print(f'  Rate limit hit, sleeping {wait}s...', flush=True)
                        time.sleep(wait)
                        try:
                            result = service.users().messages().list(**kwargs).execute()
                            break
                        except HttpError:
                            continue
                    else:
                        print(f'  Skipping {domain} after repeated rate limits', flush=True)
                        break
                else:
                    raise
            msg_ids.extend([m['id'] for m in result.get('messages', [])])
            page_token = result.get('nextPageToken')
            if not page_token:
                break

        if not msg_ids:
            continue

        for i in range(0, len(msg_ids), 100):
            batch = service.new_batch_http_request()
            for mid in msg_ids[i:i + 100]:
                batch.add(service.users().messages().trash(userId='me', id=mid))
            try:
                batch.execute()
            except HttpError as e:
                print(f'  Batch error for {domain}: {e}', flush=True)
                time.sleep(2)

        total += len(msg_ids)
        per_domain[domain] = len(msg_ids)
        print(f'  [TRASHED {len(msg_ids):4d}] {domain}', flush=True)

    print(f'      Bulk trash done. Total trashed: {total}', flush=True)
    return total, per_domain


# ── Email report ──────────────────────────────────────────────────────────────

def send_report(service, to_email: str, stats: dict):
    if not to_email:
        print('  No report_email configured — skipping report', flush=True)
        return

    run_time = datetime.now().strftime('%Y-%m-%d %H:%M')

    new_spam_rows = ''.join(
        f'<tr><td>{d}</td></tr>' for d in sorted(stats['new_spam_domains'])
    ) or '<tr><td><i>None</i></td></tr>'

    trash_rows = ''.join(
        f'<tr><td>{d}</td><td style="text-align:right">{c}</td></tr>'
        for d, c in sorted(stats['trashed_per_domain'].items(), key=lambda x: -x[1])
    ) or '<tr><td colspan="2"><i>None</i></td></tr>'
    review_rows = ''.join(
        f'<tr><td>{d}</td><td style="text-align:right">{stats["inbox_domain_counts"].get(d, 0)}</td></tr>'
        for d in sorted(stats['review_domains'])
    ) or '<tr><td colspan="2"><i>None</i></td></tr>'

    html = f"""
<html><body style="font-family:Arial,sans-serif;color:#222;max-width:650px;margin:auto">
<h2 style="background:#1a73e8;color:#fff;padding:14px 20px;border-radius:6px;margin:0">
  Daily Email Cleaning Report &mdash; {run_time}
</h2>

<table style="width:100%;border-collapse:collapse;margin-top:16px">
  <tr style="background:#f1f3f4">
    <td style="padding:10px 14px;font-weight:bold">Inbox emails scanned</td>
    <td style="padding:10px 14px;text-align:right">{stats['inbox_total']:,}</td>
  </tr>
  <tr>
    <td style="padding:10px 14px;font-weight:bold">Unique sender domains</td>
    <td style="padding:10px 14px;text-align:right">{stats['unique_domains']:,}</td>
  </tr>
  <tr style="background:#f1f3f4">
    <td style="padding:10px 14px;font-weight:bold">New unknown domains found</td>
    <td style="padding:10px 14px;text-align:right">{stats['new_unknown_count']:,}</td>
  </tr>
  <tr>
    <td style="padding:10px 14px;font-weight:bold">New spam domains auto-added</td>
    <td style="padding:10px 14px;text-align:right">{len(stats['new_spam_domains']):,}</td>
  </tr>
  <tr style="background:#f1f3f4">
    <td style="padding:10px 14px;font-weight:bold">Total domains in trash list</td>
    <td style="padding:10px 14px;text-align:right">{stats['total_trash_domains']:,}</td>
  </tr>
  <tr style="background:#d93025;color:#fff">
    <td style="padding:10px 14px;font-weight:bold">Emails trashed this run</td>
    <td style="padding:10px 14px;text-align:right;font-weight:bold">{stats['bulk_trashed']:,}</td>
  </tr>
</table>

<h3 style="margin-top:24px;color:#5f6368">Review Domains</h3>
<p style="font-size:13px;color:#666;line-height:1.6">
  To move domains, open GitHub Actions &rarr; <b>Manage Email Domains</b>,
  click <b>Run workflow</b>, choose <b>whitelist</b> or <b>blacklist</b>,
  and paste one or more domains from this table.
</p>
<p style="font-size:13px">
  <a href="https://github.com/pranay-dev-repo/Ai-Agent-FakeEmailCleaner/actions/workflows/manage_email_domains.yml">
    Open Manage Email Domains workflow
  </a>
</p>
<table style="width:100%;border-collapse:collapse;font-size:13px">
  <tr style="background:#5f6368;color:#fff">
    <th style="padding:8px 12px;text-align:left">Domain</th>
    <th style="padding:8px 12px;text-align:right">Inbox count</th>
  </tr>
  {review_rows}
</table>

<h3 style="margin-top:24px;color:#1a73e8">New Spam Domains Detected</h3>
<table style="width:100%;border-collapse:collapse;font-size:13px">
  <tr style="background:#1a73e8;color:#fff"><th style="padding:8px 12px;text-align:left">Domain</th></tr>
  {new_spam_rows}
</table>

<h3 style="margin-top:24px;color:#d93025">Emails Trashed by Domain</h3>
<table style="width:100%;border-collapse:collapse;font-size:13px">
  <tr style="background:#d93025;color:#fff">
    <th style="padding:8px 12px;text-align:left">Domain</th>
    <th style="padding:8px 12px;text-align:right">Count</th>
  </tr>
  {trash_rows}
</table>

<p style="margin-top:24px;color:#666;font-size:12px">
  Sent by Email Cleaner Agent &bull; {run_time}
</p>
</body></html>
"""

    msg = MIMEMultipart('alternative')
    msg['Subject'] = f'Email Cleaning Report — {run_time} — {stats["bulk_trashed"]:,} trashed'
    msg['From'] = 'me'
    msg['To'] = to_email
    msg.attach(MIMEText(html, 'html'))

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    try:
        service.users().messages().send(userId='me', body={'raw': raw}).execute()
        print(f'  Report sent to {to_email}', flush=True)
    except HttpError as e:
        print(f'  Failed to send report: {e}', flush=True)


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    print('=' * 60, flush=True)
    print('  Daily Email Cleaning Agent', flush=True)
    print('=' * 60, flush=True)

    config = json.loads(CONFIG_FILE.read_text(encoding='utf-8'))
    whitelist = set(d.lower() for d in config.get('whitelist_domains', []))
    groq_api_key = config.get('groq_api_key', '') or os.environ.get('GROQ_API_KEY', '')
    report_email = config.get('report_email', '').strip()

    service = get_gmail_service()

    # Step 1: scan inbox domains
    inbox_domains = scan_inbox_domains(service)

    # Step 2: find new unknown domains
    existing_trash = load_trash_domains()
    known = existing_trash | whitelist

    new_domains = [d for d in inbox_domains if d not in known]
    print(f'\n[2/5] {len(new_domains)} new/unknown domains to classify '
          f'(not in trash list or whitelist)', flush=True)
    for d in sorted(new_domains):
        print(f'      {inbox_domains[d]:4d}  {d}', flush=True)

    # Step 3: classify new domains
    print(f'\n[3/5] Classifying new domains...', flush=True)
    if new_domains:
        if groq_api_key:
            print('      Using Groq AI classifier', flush=True)
            spam_new = classify_with_groq(new_domains, groq_api_key)
        else:
            print('      No Groq key — using keyword heuristics', flush=True)
            spam_new = [d for d in new_domains if heuristic_is_spam(d)]

        if spam_new:
            print(f'      Detected {len(spam_new)} new spam domain(s):', flush=True)
            for d in sorted(spam_new):
                print(f'        + {d}', flush=True)
            append_to_bulk_trash(spam_new)
        else:
            print('      No new spam domains detected', flush=True)
    else:
        print('      Nothing new to classify', flush=True)
        spam_new = []

    write_domain_review_file(inbox_domains, new_domains, spam_new)

    # Step 4: run bulk trash (reload list after any additions)
    all_trash_domains = load_trash_domains()
    print(f'\n      Total domains in trash list: {len(all_trash_domains)}', flush=True)
    bulk_trashed, trashed_per_domain = run_bulk_trash(service, all_trash_domains, whitelist)

    # Step 5: run email_cleaner.py
    print('\n[5/5] Running email_cleaner.py...', flush=True)
    result = subprocess.run(
        [sys.executable, '-u', str(SCRIPT_DIR / 'email_cleaner.py')],
        env=os.environ.copy(),
    )
    if result.returncode != 0:
        print('  email_cleaner.py exited with errors', flush=True)

    # Step 6: send report
    print('\n[6/6] Sending email report...', flush=True)
    stats = {
        'inbox_total': sum(inbox_domains.values()),
        'unique_domains': len(inbox_domains),
        'new_unknown_count': len(new_domains),
        'new_spam_domains': spam_new,
        'review_domains': new_domains,
        'inbox_domain_counts': dict(inbox_domains),
        'total_trash_domains': len(all_trash_domains),
        'bulk_trashed': bulk_trashed,
        'trashed_per_domain': trashed_per_domain,
    }
    send_report(service, report_email, stats)

    print('\n' + '=' * 60, flush=True)
    print('  Daily agent complete.', flush=True)
    print('=' * 60, flush=True)


if __name__ == '__main__':
    main()
