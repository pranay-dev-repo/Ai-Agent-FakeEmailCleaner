import os
import re
from collections import Counter
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import BatchHttpRequest

creds = Credentials(
    token=None,
    refresh_token=os.environ['GOOGLE_REFRESH_TOKEN'],
    token_uri='https://oauth2.googleapis.com/token',
    client_id=os.environ['GOOGLE_CLIENT_ID'],
    client_secret=os.environ['GOOGLE_CLIENT_SECRET'],
    scopes=['https://www.googleapis.com/auth/gmail.modify'],
)
creds.refresh(Request())
service = build('gmail', 'v1', credentials=creds)

print('Fetching all inbox message IDs...', flush=True)
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
print(f'Total emails: {len(messages)}', flush=True)

EMAIL_RE = re.compile(r'<([^>]+)>', re.IGNORECASE)
domains = Counter()
completed = 0
BATCH_SIZE = 100

def handle_response(request_id, response, exception):
    global completed
    completed += 1
    if exception:
        return
    try:
        sender = next((h['value'] for h in response['payload']['headers'] if h['name'] == 'From'), '')
        m = EMAIL_RE.search(sender)
        email = m.group(1).lower() if m else sender.strip().lower()
        if '@' in email:
            domains[email.split('@', 1)[1]] += 1
    except Exception:
        pass

print('Reading sender domains (batch requests)...', flush=True)
for i in range(0, len(messages), BATCH_SIZE):
    batch = service.new_batch_http_request(callback=handle_response)
    chunk = messages[i:i + BATCH_SIZE]
    for ref in chunk:
        batch.add(service.users().messages().get(
            userId='me', id=ref['id'], format='metadata',
            metadataHeaders=['From']
        ))
    batch.execute()
    if (i + BATCH_SIZE) % 500 == 0 or i + BATCH_SIZE >= len(messages):
        print(f'  {min(i + BATCH_SIZE, len(messages))}/{len(messages)} done...', flush=True)

output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'inbox_domains.txt')
with open(output_path, 'w', encoding='utf-8') as f:
    f.write(f"Total emails scanned: {len(messages)}\n")
    f.write(f"Unique domains: {len(domains)}\n\n")
    f.write(f"COUNT\tDOMAIN\n")
    for domain, count in domains.most_common():
        f.write(f"{count}\t{domain}\n")

print(f'\nDone! {len(domains)} unique domains. Saved to inbox_domains.txt', flush=True)
