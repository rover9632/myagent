// Shared server-side helpers for the /api/* proxy routes.
// The proxies forward the BROWSER's Authorization header (per-user login
// sessions); there is no server-side API secret anymore.

export function backendUrl(): string | null {
  const url = process.env.BACKEND_URL;
  return url ? url.replace(/\/$/, '') : null;
}

export function notConfigured(where: string): Response {
  console.error(`${where}: BACKEND_URL not configured`);
  return Response.json({ error: 'backend not configured' }, { status: 500 });
}

export function browserAuth(req: Request): string | null {
  const h = req.headers.get('authorization');
  return h && h.trim() ? h : null;
}

export function unauthorized(where: string): Response {
  console.error(`${where}: missing Authorization header`);
  return Response.json({ error: 'missing Authorization header' }, { status: 401 });
}

export function relayError(err: unknown, where: string): Response {
  if ((err as Error)?.name === 'AbortError') return new Response(null, { status: 499 });
  console.error(`${where}: upstream fetch failed:`, err);
  return Response.json({ error: 'backend unreachable' }, { status: 502 });
}

// Buffer-and-relay for tiny JSON bodies (auth + files). Preserves 204 empty.
export async function relayJson(upstream: Response): Promise<Response> {
  if (upstream.status === 204) return new Response(null, { status: 204 });
  const text = await upstream.text().catch(() => '');
  return new Response(text, {
    status: upstream.status,
    headers: {
      'Content-Type': upstream.headers.get('content-type') ?? 'text/plain; charset=utf-8',
    },
  });
}
