import os
import time
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

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

print('Fetching Social tab emails...', flush=True)
msg_ids = []
page_token = None
while True:
    kwargs = {'userId': 'me', 'labelIds': ['CATEGORY_SOCIAL'], 'maxResults': 500}
    if page_token:
        kwargs['pageToken'] = page_token
    result = service.users().messages().list(**kwargs).execute()
    msg_ids.extend([m['id'] for m in result.get('messages', [])])
    page_token = result.get('nextPageToken')
    if not page_token:
        break
    print(f'  Found {len(msg_ids)} so far...', flush=True)

print(f'Total Social emails found: {len(msg_ids)}', flush=True)

trashed = 0
for i in range(0, len(msg_ids), 100):
    batch = service.new_batch_http_request()
    for mid in msg_ids[i:i+100]:
        batch.add(service.users().messages().trash(userId='me', id=mid))
    try:
        batch.execute()
        trashed += min(100, len(msg_ids) - i)
        print(f'  Trashed {trashed}/{len(msg_ids)}...', flush=True)
    except HttpError as e:
        print(f'  Batch error: {e}', flush=True)
        time.sleep(2)

print(f'\nDone. Total Social emails trashed: {trashed}', flush=True)
