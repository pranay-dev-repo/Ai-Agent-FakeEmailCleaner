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
import hashlib
import secrets
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
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

def scan_inbox_domains(service, max_emails: int = 0) -> Counter:
    EMAIL_RE = re.compile(r'<([^>]+)>', re.IGNORECASE)

    print('[1/5] Scanning inbox for sender domains...', flush=True)
    messages = []
    page_token = None
    while True:
        fetch = min(500, max_emails - len(messages)) if max_emails else 500
        kwargs = {'userId': 'me', 'q': 'in:inbox', 'maxResults': fetch}
        if page_token:
            kwargs['pageToken'] = page_token
        result = service.users().messages().list(**kwargs).execute()
        messages.extend(result.get('messages', []))
        page_token = result.get('nextPageToken')
        if not page_token or (max_emails and len(messages) >= max_emails):
            break
    if max_emails:
        messages = messages[:max_emails]
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
        'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
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


# ── Bulk trash (batched domain search — 10 domains per query) ──────────────────

_BULK_BATCH = 10  # domains per Gmail search query

def run_bulk_trash(service, trash_domains: set, whitelist_domains: set | None = None):
    print('[4/5] Running bulk trash...', flush=True)
    whitelist_domains = whitelist_domains or set()
    safe_domains = sorted(
        d for d in trash_domains
        if not any(d == w or d.endswith('.' + w) for w in whitelist_domains)
    )
    skipped = sorted(set(trash_domains) - set(safe_domains))
    if skipped:
        print(f'      Skipping {len(skipped)} whitelisted domain(s):', flush=True)
        for d in skipped:
            print(f'        KEEP {d}', flush=True)

    if not safe_domains:
        return 0, {}

    total_queries = (len(safe_domains) + _BULK_BATCH - 1) // _BULK_BATCH
    print(f'      {len(safe_domains)} domains → {total_queries} batched queries', flush=True)
    all_ids = []

    for qi, i in enumerate(range(0, len(safe_domains), _BULK_BATCH), start=1):
        batch_domains = safe_domains[i:i + _BULK_BATCH]
        q = 'in:inbox (' + ' OR '.join(f'from:@{d}' for d in batch_domains) + ')'
        page_token = None
        batch_ids = []
        while True:
            kwargs = {'userId': 'me', 'q': q, 'maxResults': 500}
            if page_token:
                kwargs['pageToken'] = page_token
            for wait in [0, 15, 30, 60]:
                if wait:
                    print(f'  Rate limit — sleeping {wait}s...', flush=True)
                    time.sleep(wait)
                try:
                    result = service.users().messages().list(**kwargs).execute()
                    break
                except HttpError as e:
                    if 'rateLimitExceeded' in str(e) and wait < 60:
                        continue
                    raise
            batch_ids.extend(m['id'] for m in result.get('messages', []))
            page_token = result.get('nextPageToken')
            if not page_token:
                break
        if batch_ids:
            print(f'  [batch {qi}/{total_queries}] {len(batch_ids)} emails — {", ".join(batch_domains)}', flush=True)
        all_ids.extend(batch_ids)

    if not all_ids:
        print('      Nothing to trash.', flush=True)
        return 0, {}

    print(f'      Trashing {len(all_ids)} emails via batch API...', flush=True)
    for i in range(0, len(all_ids), 100):
        b = service.new_batch_http_request()
        for mid in all_ids[i:i + 100]:
            b.add(service.users().messages().trash(userId='me', id=mid))
        try:
            b.execute()
        except HttpError as e:
            print(f'  Batch trash error: {e}', flush=True)
            time.sleep(2)

    print(f'      Bulk trash done. Total trashed: {len(all_ids)}', flush=True)
    return len(all_ids), {}


# ── Subject keyword trash ──────────────────────────────────────────────────────

def trash_by_subject_keywords(service, keywords: list):
    if not keywords:
        return
    print('[4b] Trashing emails by subject keywords...', flush=True)
    for keyword in keywords:
        msg_ids = []
        page_token = None
        while True:
            kwargs = {'userId': 'me', 'q': f'in:inbox subject:"{keyword}"', 'maxResults': 500}
            if page_token:
                kwargs['pageToken'] = page_token
            try:
                result = service.users().messages().list(**kwargs).execute()
            except HttpError as e:
                print(f'  Error searching subject "{keyword}": {e}', flush=True)
                break
            msg_ids.extend([m['id'] for m in result.get('messages', [])])
            page_token = result.get('nextPageToken')
            if not page_token:
                break

        if not msg_ids:
            print(f'  subject:"{keyword}" — 0 found', flush=True)
            continue

        for i in range(0, len(msg_ids), 100):
            batch = service.new_batch_http_request()
            for mid in msg_ids[i:i + 100]:
                batch.add(service.users().messages().trash(userId='me', id=mid))
            try:
                batch.execute()
            except HttpError as e:
                print(f'  Batch error for subject "{keyword}": {e}', flush=True)

        print(f'  subject:"{keyword}" — trashed {len(msg_ids)}', flush=True)


# ── Domain management via email ────────────────────────────────────────────────

def _parse_domain_list(text: str) -> list:
    domains = []
    for part in re.split(r'[,\s]+', text):
        part = part.strip().lower().strip('()[]<>"\'-')
        if part and '.' in part and len(part) > 3:
            domains.append(part)
    return domains


def _get_email_body(payload) -> str:
    def _decode(part):
        data = part.get('body', {}).get('data', '')
        return base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore') if data else ''

    if payload.get('mimeType') == 'text/plain':
        return _decode(payload)
    for part in payload.get('parts', []):
        if part.get('mimeType') == 'text/plain':
            return _decode(part)
        for sub in part.get('parts', []):
            if sub.get('mimeType') == 'text/plain':
                return _decode(sub)
    return ''


def _make_mailto(to_email: str, subject: str, body: str = '') -> str:
    qs = f'subject={urllib.parse.quote(subject, safe="")}'
    if body:
        qs += f'&body={urllib.parse.quote(body, safe="")}'
    return f'mailto:{to_email}?{qs}'


DOCS_DIR = SCRIPT_DIR.parent / 'docs'
SESSION_FILE = DOCS_DIR / 'session.json'
REVIEW_BASE_URL = 'https://pranay-dev-repo.github.io/Ai-Agent-FakeEmailCleaner/review.html'


def generate_magic_session(review_url_base: str) -> str:
    """Generates a one-time token, writes docs/session.json, returns the magic link URL."""
    token = secrets.token_hex(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    expires = (datetime.now(timezone.utc) + timedelta(hours=25)).isoformat(timespec='seconds')
    payload = {
        'token_hash': token_hash,
        'expires_at': expires,
        'used': False,
    }
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    SESSION_FILE.write_text(json.dumps(payload) + '\n', encoding='utf-8')
    return f'{review_url_base}?t={token}'


def process_domain_management_emails(service, config: dict) -> tuple:
    """Read [EMAIL-CLEANER] emails, apply whitelist/blacklist actions, mark read."""
    print('[0/5] Checking for domain management emails...', flush=True)
    whitelist_add, blacklist_add, msg_ids = [], [], []

    try:
        result = service.users().messages().list(
            userId='me', q='subject:"[EMAIL-CLEANER]" is:unread', maxResults=50
        ).execute()
        messages = result.get('messages', [])
    except Exception as e:
        print(f'      Could not check management emails: {e}', flush=True)
        return [], []

    if not messages:
        print('      No pending management emails', flush=True)
        return [], []

    print(f'      Found {len(messages)} management email(s)', flush=True)
    for msg in messages:
        try:
            full = service.users().messages().get(userId='me', id=msg['id'], format='full').execute()
            subject = next(
                (h['value'] for h in full['payload']['headers'] if h['name'].lower() == 'subject'), ''
            )
            body = _get_email_body(full['payload'])
            msg_ids.append(msg['id'])

            if '[email-cleaner]' not in subject.lower():
                continue

            # Format: [EMAIL-CLEANER] whitelist domain.com  OR  blacklist domain.com
            parts = subject.split()
            for i, part in enumerate(parts):
                if part.lower() == 'whitelist' and i + 1 < len(parts):
                    whitelist_add.extend(_parse_domain_list(' '.join(parts[i + 1:])))
                elif part.lower() == 'blacklist' and i + 1 < len(parts):
                    blacklist_add.extend(_parse_domain_list(' '.join(parts[i + 1:])))

            # Format: [EMAIL-CLEANER] manage  with body containing WHITELIST:/BLACKLIST: lines
            if 'manage' in subject.lower() and body:
                for line in body.splitlines():
                    line = line.strip()
                    if line.upper().startswith('WHITELIST:'):
                        whitelist_add.extend(_parse_domain_list(line[len('WHITELIST:'):]))
                    elif line.upper().startswith('BLACKLIST:'):
                        blacklist_add.extend(_parse_domain_list(line[len('BLACKLIST:'):]))
        except Exception as e:
            print(f'      Error reading email {msg["id"]}: {e}', flush=True)

    # Mark all as read
    if msg_ids:
        batch = service.new_batch_http_request()
        for mid in msg_ids:
            batch.add(service.users().messages().modify(
                userId='me', id=mid, body={'removeLabelIds': ['UNREAD']}
            ))
        batch.execute()

    whitelist_add = list(dict.fromkeys(whitelist_add))
    blacklist_add = [d for d in dict.fromkeys(blacklist_add) if d not in whitelist_add]

    if whitelist_add:
        current = set(d.lower() for d in config.get('whitelist_domains', []))
        config['whitelist_domains'] = sorted(current | set(whitelist_add))
        CONFIG_FILE.write_text(json.dumps(config, indent=2) + '\n', encoding='utf-8')
        print(f'      Whitelisted: {", ".join(whitelist_add)}', flush=True)

    if blacklist_add:
        # Remove from whitelist if present
        config['whitelist_domains'] = [
            d for d in config.get('whitelist_domains', []) if d.lower() not in set(blacklist_add)
        ]
        CONFIG_FILE.write_text(json.dumps(config, indent=2) + '\n', encoding='utf-8')
        append_to_bulk_trash(blacklist_add)
        print(f'      Blacklisted: {", ".join(blacklist_add)}', flush=True)

    return whitelist_add, blacklist_add


# ── Email report ──────────────────────────────────────────────────────────────

def send_report(service, to_email: str, stats: dict):
    if not to_email:
        print('  No report_email configured — skipping report', flush=True)
        return

    run_time = datetime.now().strftime('%Y-%m-%d %H:%M')

    review_url = stats.get('review_url', REVIEW_BASE_URL)

    new_spam_rows = ''.join(
        f'<tr><td>{d}</td></tr>' for d in sorted(stats['new_spam_domains'])
    ) or '<tr><td><i>None</i></td></tr>'

    trash_rows = ''.join(
        f'<tr><td>{d}</td><td style="text-align:right">{c}</td></tr>'
        for d, c in sorted(stats['trashed_per_domain'].items(), key=lambda x: -x[1])
    ) or f'<tr><td colspan="2" style="color:#666"><i>Batched bulk trash — {stats["bulk_trashed"]:,} emails trashed across {len(load_trash_domains())} domains</i></td></tr>'
    to_email = stats.get('report_email', to_email)
    review_domain_list = sorted(stats['review_domains'])
    review_btn = (
        f'<a href="{review_url}"'
        ' style="display:inline-block;background:#1a73e8;color:#fff;padding:9px 20px;'
        'border-radius:5px;text-decoration:none;font-size:14px;font-weight:bold">'
        'Review &amp; Manage Domains</a>'
    )
    review_rows = ''.join(
        f'<tr style="background:{"#f8f9fa" if i % 2 == 0 else "#fff"}">'
        f'<td style="padding:8px 12px">{d}</td>'
        f'<td style="padding:8px 12px;text-align:right">{stats["inbox_domain_counts"].get(d, 0)}</td>'
        f'</tr>'
        for i, d in enumerate(review_domain_list)
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
<p style="font-size:13px;color:#666;line-height:1.8;margin-bottom:12px">
  Select multiple domains, then whitelist or blacklist them in one click.
</p>
{review_btn}
<table style="width:100%;border-collapse:collapse;font-size:13px;margin-top:14px">
  <tr style="background:#5f6368;color:#fff">
    <th style="padding:8px 12px;text-align:left">Domain</th>
    <th style="padding:8px 12px;text-align:right">Inbox</th>
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
    for attempt, wait in enumerate([0, 60, 120, 180], start=1):
        if wait:
            print(f'  Rate limit — waiting {wait}s before sending report (attempt {attempt})...', flush=True)
            time.sleep(wait)
        try:
            service.users().messages().send(userId='me', body={'raw': raw}).execute()
            print(f'  Report sent to {to_email}', flush=True)
            return
        except HttpError as e:
            if 'rateLimitExceeded' in str(e) and attempt < 4:
                continue
            print(f'  Failed to send report: {e}', flush=True)
            return


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

    # Step 0: process any pending domain management emails
    process_domain_management_emails(service, config)
    # Reload whitelist in case it was updated
    whitelist = set(d.lower() for d in config.get('whitelist_domains', []))

    # Step 1: scan inbox domains
    # MAX_SCAN_EMAILS env var set by workflow_dispatch input; absent on scheduled runs → scan all
    env_max = os.environ.get('MAX_SCAN_EMAILS', '').strip()
    max_scan = int(env_max) if env_max else int(config.get('max_scan_emails', 0))
    inbox_domains = scan_inbox_domains(service, max_emails=max_scan)

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

    # Step 4b: trash by subject keywords
    subject_keywords = config.get('subject_keywords_trash', [])
    trash_by_subject_keywords(service, subject_keywords)

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
    review_url_base = config.get('review_page_url', REVIEW_BASE_URL).rstrip('/')
    workflow_pat = os.environ.get('GITHUB_WORKFLOW_PAT', '')
    if workflow_pat:
        try:
            review_url = generate_magic_session(review_url_base)
            print(f'  Magic link session generated (expires 25h)', flush=True)
        except Exception as e:
            print(f'  Magic link generation failed: {e} — using plain URL', flush=True)
            review_url = review_url_base
    else:
        review_url = review_url_base
        print('  GITHUB_WORKFLOW_PAT not set — using plain review URL', flush=True)

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
        'report_email': report_email,
        'review_url': review_url,
    }
    send_report(service, report_email, stats)

    print('\n' + '=' * 60, flush=True)
    print('  Daily agent complete.', flush=True)
    print('=' * 60, flush=True)


if __name__ == '__main__':
    main()
