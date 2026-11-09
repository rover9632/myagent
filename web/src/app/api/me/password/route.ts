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
// (Next 16) they are errors, and POST handlers already run per-request.
export async function POST(req: NextRequest): Promise<Response> {
  const base = backendUrl();
  if (!base) return notConfigured('api/me/password');

  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return Response.json({ error: 'invalid json' }, { status: 400 });
  }

  const authorization = browserAuth(req);
  if (!authorization) return unauthorized('api/me/password');

  try {
    const upstream = await fetch(`${base}/v1/me/password`, {
      method: 'POST',
      headers: { Authorization: authorization, 'Content-Type': 'application/json' },
      body: JSON.stringify(body), // 204/401/403/422 relayed verbatim
      signal: req.signal,
    });
    return await relayJson(upstream);
  } catch (err) {
    return relayError(err, 'api/me/password');
  }
}
