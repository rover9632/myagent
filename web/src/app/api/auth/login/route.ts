import { NextRequest } from 'next/server';

import { backendUrl, notConfigured, relayError, relayJson } from '@/lib/backend';

// NOTE: no runtime/dynamic segment exports — with cacheComponents enabled
// (Next 16) they are errors, and POST handlers already run per-request.
export async function POST(req: NextRequest): Promise<Response> {
  const base = backendUrl();
  if (!base) return notConfigured('api/auth/login');

  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return Response.json({ error: 'invalid json' }, { status: 400 });
  }

  // Pass the client's forwarded-IP chain through so the backend can record
  // last_login_ip against the real browser instead of this proxy's address.
  const xff = req.headers.get('x-forwarded-for');

  try {
    const upstream = await fetch(`${base}/v1/auth/login`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(xff ? { 'x-forwarded-for': xff } : {}),
      },
      body: JSON.stringify(body), // backend validates shape -> 401/422 relayed verbatim
      signal: req.signal,
    });
    return await relayJson(upstream);
  } catch (err) {
    return relayError(err, 'api/auth/login');
  }
}
