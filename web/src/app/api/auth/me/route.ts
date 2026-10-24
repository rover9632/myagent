import { NextRequest } from 'next/server';

import { backendUrl, browserAuth, notConfigured, relayError, relayJson, unauthorized } from '@/lib/backend';

// NOTE: no runtime/dynamic segment exports — with cacheComponents enabled
// (Next 16) they are errors. Reading req.headers + the network fetch make
// this GET run at request time (prerender stops at runtime data).
export async function GET(req: NextRequest): Promise<Response> {
  const base = backendUrl();
  if (!base) return notConfigured('api/auth/me');

  const authorization = browserAuth(req);
  if (!authorization) return unauthorized('api/auth/me');

  try {
    const upstream = await fetch(`${base}/v1/auth/me`, {
      headers: { Authorization: authorization },
      signal: req.signal,
    });
    return await relayJson(upstream);
  } catch (err) {
    return relayError(err, 'api/auth/me');
  }
}
