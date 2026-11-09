import { NextRequest } from 'next/server';

import {
  backendUrl,
  browserAuth,
  notConfigured,
  relayError,
  relayJson,
  unauthorized,
} from '@/lib/backend';

// NOTE: no runtime/dynamic segment exports — with cacheComponents enabled
// (Next 16) they are errors; reading req.headers makes the GET run per-request.
// GET and PATCH share the file (multi-verb precedent: api/files).

export async function GET(req: NextRequest): Promise<Response> {
  const base = backendUrl();
  if (!base) return notConfigured('api/me');
  const authorization = browserAuth(req);
  if (!authorization) return unauthorized('api/me');
  try {
    const upstream = await fetch(`${base}/v1/me`, {
      headers: { Authorization: authorization },
      signal: req.signal,
    });
    return await relayJson(upstream);
  } catch (err) {
    return relayError(err, 'api/me');
  }
}

export async function PATCH(req: NextRequest): Promise<Response> {
  const base = backendUrl();
  if (!base) return notConfigured('api/me');

  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return Response.json({ error: 'invalid json' }, { status: 400 });
  }

  const authorization = browserAuth(req);
  if (!authorization) return unauthorized('api/me');

  try {
    const upstream = await fetch(`${base}/v1/me`, {
      method: 'PATCH',
      headers: { Authorization: authorization, 'Content-Type': 'application/json' },
      body: JSON.stringify(body), // 200/401/409/422 relayed verbatim
      signal: req.signal,
    });
    return await relayJson(upstream);
  } catch (err) {
    return relayError(err, 'api/me');
  }
}
