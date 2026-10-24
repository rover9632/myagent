import { NextRequest } from 'next/server';

// Streaming proxy for attachment uploads to the FastAPI backend.
// POST /api/files: forwards the multipart body verbatim and injects the bearer
//   token server-side. NEVER call req.formData() here — that would buffer the
//   whole body (up to 50MB) a second time in Next's memory.
// GET /api/files?thread_id=: passthrough listing of the thread workspace.
// NOTE: no `runtime`/`dynamic` segment configs — with cacheComponents enabled
// (Next 16) they are errors, and POST/GET handlers already run per-request.

const MAX_UPLOAD_BYTES = 50 * 1024 * 1024; // mirrors backend upload_max_bytes

function backend(): { url: string; token: string } | null {
  const url = process.env.BACKEND_URL;
  const token = process.env.BACKEND_API_TOKEN;
  if (!url || !token) return null;
  return { url: url.replace(/\/$/, ''), token };
}

function notConfigured(): Response {
  console.error('api/files: BACKEND_URL / BACKEND_API_TOKEN not configured');
  return Response.json({ error: 'backend not configured' }, { status: 500 });
}

// Upstream responses here are tiny JSON (or short error text), so buffering
// them is fine — unlike api/chat there is no SSE stream to preserve.
async function relay(upstream: Response): Promise<Response> {
  const text = await upstream.text().catch(() => '');
  return new Response(text, {
    status: upstream.status,
    headers: {
      'Content-Type': upstream.headers.get('content-type') ?? 'text/plain; charset=utf-8',
    },
  });
}

function relayError(err: unknown, where: string): Response {
  if ((err as Error)?.name === 'AbortError') return new Response(null, { status: 499 });
  console.error(`api/files: ${where} upstream fetch failed:`, err);
  return Response.json({ error: 'backend unreachable' }, { status: 502 });
}

export async function POST(req: NextRequest): Promise<Response> {
  const b = backend();
  if (!b) return notConfigured();

  // Courtesy pre-check so oversized picks fail fast; the backend middleware
  // and chunked copy remain the authoritative enforcers.
  const length = req.headers.get('content-length');
  if (length && Number(length) > MAX_UPLOAD_BYTES) {
    return Response.json({ error: 'file too large' }, { status: 413 });
  }

  try {
    const upstream = await fetch(`${b.url}/v1/agent/files`, {
      method: 'POST',
      headers: {
        // Copy verbatim: carries the multipart boundary.
        'Content-Type': req.headers.get('content-type') ?? 'application/octet-stream',
        Authorization: `Bearer ${b.token}`,
      },
      body: req.body,
      // Node's fetch requires `duplex` for streaming request bodies; the TS
      // lib types don't include it yet, hence the cast.
      duplex: 'half',
      signal: req.signal,
    } as RequestInit & { duplex: string });
    return await relay(upstream);
  } catch (err) {
    return relayError(err, 'POST');
  }
}

export async function GET(req: NextRequest): Promise<Response> {
  const b = backend();
  if (!b) return notConfigured();

  const threadId = req.nextUrl.searchParams.get('thread_id');
  if (!threadId || threadId.length > 200) {
    return Response.json({ error: 'invalid thread_id' }, { status: 422 });
  }

  try {
    const upstream = await fetch(
      `${b.url}/v1/agent/files?thread_id=${encodeURIComponent(threadId)}`,
      { headers: { Authorization: `Bearer ${b.token}` }, signal: req.signal },
    );
    return await relay(upstream);
  } catch (err) {
    return relayError(err, 'GET');
  }
}
