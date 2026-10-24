import { NextRequest } from 'next/server';

import { backendUrl, browserAuth, notConfigured, relayError, relayJson, unauthorized } from '@/lib/backend';

// NOTE: no runtime/dynamic segment exports — with cacheComponents enabled
// (Next 16) they are errors, and POST handlers already run per-request.
export async function POST(req: NextRequest): Promise<Response> {
  const base = backendUrl();
  if (!base) return notConfigured('api/auth/logout');

  const authorization = browserAuth(req);
  if (!authorization) return unauthorized('api/auth/logout');

  try {
    const upstream = await fetch(`${base}/v1/auth/logout`, {
      method: 'POST',
      headers: { Authorization: authorization },
      signal: req.signal,
    });
    return await relayJson(upstream); // 204 stays 204
  } catch (err) {
    return relayError(err, 'api/auth/logout');
  }
}
