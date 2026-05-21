const crypto = require('crypto');

const REPO     = 'pranay-dev-repo/Ai-Agent-FakeEmailCleaner';
const GH_API   = 'https://api.github.com';
const ALLOWED_ACTIONS = new Set(['whitelist', 'blacklist']);

function ghHeaders(pat) {
  return {
    Authorization: `Bearer ${pat}`,
    Accept: 'application/vnd.github+json',
    'Content-Type': 'application/json',
    'X-GitHub-Api-Version': '2022-11-28',
    'User-Agent': 'email-cleaner-agent',
  };
}

async function fetchSession(pat) {
  const r = await fetch(`${GH_API}/repos/${REPO}/contents/docs/session.json`, {
    headers: ghHeaders(pat),
  });
  if (!r.ok) return null;
  const raw = await r.json();
  const data = JSON.parse(Buffer.from(raw.content, 'base64').toString('utf-8'));
  return { data, sha: raw.sha };
}

async function markSessionUsed(pat, session, sha) {
  const updated = { ...session, used: true };
  await fetch(`${GH_API}/repos/${REPO}/contents/docs/session.json`, {
    method: 'PUT',
    headers: ghHeaders(pat),
    body: JSON.stringify({
      message: 'chore: invalidate session token [skip ci]',
      content: Buffer.from(JSON.stringify(updated) + '\n').toString('base64'),
      sha,
    }),
  });
}

exports.handler = async (event) => {
  if (event.httpMethod === 'OPTIONS') {
    return {
      statusCode: 200,
      headers: {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'POST, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type',
      },
      body: '',
    };
  }

  if (event.httpMethod !== 'POST') {
    return { statusCode: 405, body: 'Method Not Allowed' };
  }

  let token, action, domains;
  try {
    ({ token, action, domains } = JSON.parse(event.body));
  } catch {
    return { statusCode: 400, body: 'Invalid JSON' };
  }

  if (!token || !action || !domains) {
    return { statusCode: 400, body: 'Missing required fields' };
  }
  if (!ALLOWED_ACTIONS.has(action)) {
    return { statusCode: 400, body: 'Invalid action' };
  }

  const pat = process.env.GITHUB_WORKFLOW_PAT;
  if (!pat) {
    return { statusCode: 500, body: 'Server misconfigured — missing PAT' };
  }

  // Load session
  const session = await fetchSession(pat);
  if (!session) {
    return { statusCode: 401, body: 'No active session found' };
  }

  // Validate token
  const tokenHash = crypto.createHash('sha256').update(token).digest('hex');
  if (tokenHash !== session.data.token_hash) {
    return { statusCode: 401, body: 'Invalid token' };
  }
  if (new Date(session.data.expires_at) < new Date()) {
    return { statusCode: 401, body: 'Session expired — wait for next daily report' };
  }
  if (session.data.used) {
    return { statusCode: 401, body: 'Session already used — wait for next daily report' };
  }

  // Mark used before calling workflow (prevents replay even if workflow call fails)
  await markSessionUsed(pat, session.data, session.sha);

  // Trigger workflow
  const wfResp = await fetch(
    `${GH_API}/repos/${REPO}/actions/workflows/manage_email_domains.yml/dispatches`,
    {
      method: 'POST',
      headers: ghHeaders(pat),
      body: JSON.stringify({ ref: 'main', inputs: { action, domains } }),
    }
  );

  const corsHeaders = { 'Access-Control-Allow-Origin': '*' };

  if (wfResp.status === 204) {
    return { statusCode: 204, headers: corsHeaders, body: '' };
  }
  const txt = await wfResp.text();
  return { statusCode: wfResp.status, headers: corsHeaders, body: txt };
};
