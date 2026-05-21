import os
import re
import json
import base64
import logging
from concurrent.futures import ThreadPoolExecutor
from email.mime.text import MIMEText
from datetime import datetime, timedelta

import dns.resolver
import dns.exception
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = ['https://www.googleapis.com/auth/gmail.modify']
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, 'config.json')
TOKEN_FILE = os.path.join(BASE_DIR, 'token.json')
LOG_FILE = os.path.join(BASE_DIR, 'cleaner.log')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

EMAIL_RE = re.compile(r'<([^>]+)>', re.IGNORECASE)

DISPOSABLE_DOMAINS = {
    'mailinator.com', 'guerrillamail.com', 'yopmail.com', 'maildrop.cc',
    'trashmail.com', 'trashmail.net', 'trashmail.me', 'temp-mail.org',
    'throwaway.email', 'dispostable.com', 'fakeinbox.com', 'spam4.me',
    'mailcatch.com', 'getonemail.com', 'jetable.com', 'getnada.com',
}

_mx_cache: dict[str, bool] = {}


def has_mx_record(domain: str) -> bool:
    if domain in _mx_cache:
        return _mx_cache[domain]
    try:
        dns.resolver.resolve(domain, 'MX', lifetime=2)
        result = True
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer,
            dns.resolver.NoNameservers, dns.exception.Timeout):
        result = False
    _mx_cache[domain] = result
    return result


def load_config() -> dict:
    with open(CONFIG_FILE, 'r') as f:
        return json.load(f)


def get_gmail_service():
    client_id = os.environ.get('GOOGLE_CLIENT_ID')
    client_secret = os.environ.get('GOOGLE_CLIENT_SECRET')
    refresh_token = os.environ.get('GOOGLE_REFRESH_TOKEN')
    if client_id and client_secret and refresh_token:
        creds = Credentials(
            token=None, refresh_token=refresh_token,
            token_uri='https://oauth2.googleapis.com/token',
            client_id=client_id, client_secret=client_secret, scopes=SCOPES,
        )
        creds.refresh(Request())
        return build('gmail', 'v1', credentials=creds)
    if not os.path.exists(TOKEN_FILE):
        raise RuntimeError("No credentials found.")
    creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(TOKEN_FILE, 'w') as f:
                f.write(creds.to_json())
        else:
            raise RuntimeError("Token invalid — re-run setup_oauth.py.")
    return build('gmail', 'v1', credentials=creds)


def fetch_all_inbox(service, hours: int) -> list:
    cutoff = datetime.now() - timedelta(hours=hours)
    epoch = datetime(1970, 1, 2)
    query = 'in:inbox' if cutoff <= epoch else f'in:inbox after:{int(cutoff.timestamp())}'
    messages = []
    page_token = None
    while True:
        kwargs = {'userId': 'me', 'q': query, 'maxResults': 500}
        if page_token:
            kwargs['pageToken'] = page_token
        result = service.users().messages().list(**kwargs).execute()
        messages.extend(result.get('messages', []))
        page_token = result.get('nextPageToken')
        if not page_token:
            break
    return messages


def batch_fetch_metadata(service, message_refs: list) -> list:
    """Fetch From+Subject for all messages using Batch API. Returns list of dicts."""
    results = [None] * len(message_refs)
    index_map = {ref['id']: i for i, ref in enumerate(message_refs)}

    def handle(request_id, response, exception):
        if exception or not response:
            return
        try:
            headers = {h['name']: h['value'] for h in response['payload']['headers']}
            sender_raw = headers.get('From', '')
            m = EMAIL_RE.search(sender_raw)
            sender_email = m.group(1).lower() if m else sender_raw.strip().lower()
            msg_id = response['id']
            results[index_map[msg_id]] = {
                'id': msg_id,
                'sender_raw': sender_raw,
                'sender_email': sender_email,
                'domain': sender_email.split('@', 1)[1] if '@' in sender_email else '',
                'subject': headers.get('Subject', '(no subject)'),
                'snippet': response.get('snippet', ''),
            }
        except Exception:
            pass

    for i in range(0, len(message_refs), 100):
        batch = service.new_batch_http_request(callback=handle)
        for ref in message_refs[i:i + 100]:
            batch.add(service.users().messages().get(
                userId='me', id=ref['id'], format='metadata',
                metadataHeaders=['From', 'Subject'],
            ))
        batch.execute()
        done = min(i + 100, len(message_refs))
        if done % 1000 == 0 or done == len(message_refs):
            log.info('  Fetched metadata %d/%d', done, len(message_refs))

    return [r for r in results if r is not None]


def batch_trash(service, msg_ids: list):
    """Trash a list of message IDs using Batch API."""
    for i in range(0, len(msg_ids), 100):
        batch = service.new_batch_http_request()
        for mid in msg_ids[i:i + 100]:
            batch.add(service.users().messages().trash(userId='me', id=mid))
        try:
            batch.execute()
        except HttpError as e:
            log.warning('Batch trash error: %s', e)


def ai_detect_junk(emails: list, api_key: str) -> list:
    if not emails:
        return []
    try:
        from groq import Groq
    except ImportError:
        log.warning('groq not installed — AI detection skipped')
        return []

    client = Groq(api_key=api_key)
    numbered = '\n'.join(
        f"{i+1}. From: {e['sender_raw']} | Subject: {e['subject']} | Preview: {e['snippet'][:120]}"
        for i, e in enumerate(emails)
    )
    prompt = (
        'Return ONLY a JSON array of 1-based numbers for emails to trash. '
        'Return [] if none qualify.\n\n'
        f'{numbered}\n\nJSON array only:'
    )
    system = (
        'You are an email junk detector. Mark as junk: newsletters, marketing, spam, '
        'promotional offers, automated bulk emails. Keep: personal emails, receipts, '
        'security alerts, work messages. When uncertain, keep the email.'
    )
    try:
        response = client.chat.completions.create(
            model='llama-3.3-70b-versatile',
            messages=[
                {'role': 'system', 'content': system},
                {'role': 'user', 'content': prompt},
            ],
            temperature=0.1, max_tokens=512,
        )
        raw = response.choices[0].message.content.strip()
        raw = re.sub(r'^```[a-z]*\n?|\n?```$', '', raw).strip()
        indices = json.loads(raw)
        return [emails[i - 1]['id'] for i in indices if isinstance(i, int) and 1 <= i <= len(emails)]
    except Exception as exc:
        log.warning('Groq junk detection failed: %s', exc)
        return []


def run():
    log.info('=== Email cleaner started ===')
    config = load_config()

    blocklist = {e.lower() for e in config.get('blocklist', [])}
    whitelist_domains = [d.lower() for d in config.get('whitelist_domains', [])]
    ai_cfg = config.get('ai_detection', {})
    ai_enabled = ai_cfg.get('enabled', True)
    max_ai_emails = ai_cfg.get('max_emails_per_run', 50)
    api_key = os.environ.get('GROQ_API_KEY') or config.get('groq_api_key', '')
    hours = config.get('look_back_hours', 24)
    validate_senders = config.get('fake_email_detection', {}).get('enabled', True)
    report_email = os.environ.get('REPORT_EMAIL') or config.get('report_email', '')

    service = get_gmail_service()

    # Step 1: list all inbox message IDs
    message_refs = fetch_all_inbox(service, hours=hours)
    if not message_refs:
        log.info('No inbox emails found. Nothing to do.')
        return
    log.info('Found %d inbox emails. Fetching metadata via batch API...', len(message_refs))

    # Step 2: batch-fetch all metadata (100 per HTTP request)
    emails = batch_fetch_metadata(service, message_refs)
    log.info('Metadata fetched for %d emails.', len(emails))

    # Step 3: DNS check — once per unique domain (not per email)
    unique_domains = {e['domain'] for e in emails if e['domain']}
    log.info('Checking MX records for %d unique domains (parallel)...', len(unique_domains))
    with ThreadPoolExecutor(max_workers=20) as ex:
        futures = {d: ex.submit(has_mx_record, d) for d in unique_domains}
        domain_has_mx = {d: f.result() for d, f in futures.items()}
    log.info('MX check complete.')

    # Step 4: classify each email
    fake_trash = []
    blocklist_trash = []
    ai_candidates = []

    for email in emails:
        addr = email['sender_email']
        domain = email['domain']

        # Whitelist — pass straight to AI candidates
        if any(domain == w or domain.endswith('.' + w) for w in whitelist_domains):
            ai_candidates.append(email)
            continue

        # Fake sender check
        if validate_senders:
            if domain in DISPOSABLE_DOMAINS or not domain_has_mx.get(domain, True):
                fake_trash.append(email['id'])
                log.info('[FAKE/NO_MX] %s — %s', email['sender_raw'], email['subject'])
                continue

        # Static blocklist
        if addr in blocklist:
            blocklist_trash.append(email['id'])
            log.info('[BLOCKLIST] %s — %s', email['sender_raw'], email['subject'])
            continue

        ai_candidates.append(email)

    # Step 5: batch trash fake + blocklist emails
    log.info('Batch trashing %d fake-sender emails...', len(fake_trash))
    batch_trash(service, fake_trash)

    log.info('Batch trashing %d blocklist emails...', len(blocklist_trash))
    batch_trash(service, blocklist_trash)

    # Step 6: AI junk detection on remaining candidates
    ai_trashed = 0
    if ai_enabled and api_key and ai_candidates:
        batch_for_ai = ai_candidates[:max_ai_emails]
        log.info('Sending %d emails to Groq for junk detection...', len(batch_for_ai))
        junk_ids = ai_detect_junk(batch_for_ai, api_key)
        if junk_ids:
            batch_trash(service, junk_ids)
            ai_trashed = len(junk_ids)
        log.info('AI trashed %d additional emails.', ai_trashed)
    elif not api_key:
        log.warning('GROQ_API_KEY not set — AI detection skipped.')

    total = len(fake_trash) + len(blocklist_trash) + ai_trashed
    log.info('=== Done. Total trashed: %d ===', total)

    if report_email:
        _send_summary(service, report_email, len(fake_trash), len(blocklist_trash), ai_trashed, total)

    return total


def _send_summary(service, to, fake_count, blocklist_count, ai_count, total):
    body = (
        f"Email Cleaner Report — {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
        f"Total trashed : {total}\n"
        f"  Fake sender : {fake_count}\n"
        f"  Blocklist   : {blocklist_count}\n"
        f"  AI detected : {ai_count}\n"
    )
    mime = MIMEText(body)
    mime['to'] = to
    mime['subject'] = f'Email Cleaner Report — {total} trashed'
    raw = base64.urlsafe_b64encode(mime.as_bytes()).decode()
    try:
        service.users().messages().send(userId='me', body={'raw': raw}).execute()
        log.info('Summary sent to %s', to)
    except HttpError as e:
        log.warning('Failed to send summary: %s', e)


if __name__ == '__main__':
    run()
