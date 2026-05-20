"""Run this ONCE to authorize Gmail access and save token.json."""
import os
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ['https://www.googleapis.com/auth/gmail.modify']
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CREDS_FILE = os.path.join(BASE_DIR, 'credentials.json')
TOKEN_FILE = os.path.join(BASE_DIR, 'token.json')


def main():
    if not os.path.exists(CREDS_FILE):
        print("ERROR: credentials.json not found in", BASE_DIR)
        print()
        print("To get it:")
        print("  1. Go to https://console.cloud.google.com/")
        print("  2. Create a project (or select existing)")
        print("  3. APIs & Services → Enable APIs → search 'Gmail API' → Enable")
        print("  4. APIs & Services → Credentials → Create Credentials → OAuth client ID")
        print("  5. Application type: Desktop app → Create → Download JSON")
        print("  6. Rename it to credentials.json and place it here:", BASE_DIR)
        return

    flow = InstalledAppFlow.from_client_secrets_file(CREDS_FILE, SCOPES)
    creds = flow.run_local_server(port=0)

    with open(TOKEN_FILE, 'w') as f:
        f.write(creds.to_json())

    print()
    print("Success! token.json saved.")
    print("You can now run email_cleaner.py")


if __name__ == '__main__':
    main()
