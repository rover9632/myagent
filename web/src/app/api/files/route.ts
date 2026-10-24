import { NextRequest } from 'next/server';

import {
  backendUrl,
  browserAuth,
  notConfigured,
  relayError,
  relayJson,
  unauthorized,
} from '@/lib/backend';

// Streaming proxy for attachment uploads to the FastAPI backend.
// POST /api/files: forwards the multipart body verbatim plus the BROWSER's
//   Authorization header (per-user sessions). NEVER call req.formData() here —
//   that would buffer the whole body (up to 50MB) a second time in Next's memory.
// GET /api/files?thread_id=: passthrough listing of the thread workspace.
// NOTE: no `runtime`/`dynamic` segment configs — with cacheComponents enabled
// (Next 16) they are errors, and POST/GET handlers already run per-request.

const MAX_UPLOAD_BYTES = 50 * 1024 * 1024; // mirrors backend upload_max_bytes

export async function POST(req: NextRequest): Promise<Response> {
  const base = backendUrl();
  if (!base) return notConfigured('api/files');

  const authorization = browserAuth(req);
  if (!authorization) return unauthorized('api/files');

  // Courtesy pre-check so oversized picks fail fast; the backend middleware
  // and chunked copy remain the authoritative enforcers.
  const length = req.headers.get('content-length');
  if (length && Number(length) > MAX_UPLOAD_BYTES) {
    return Response.json({ error: 'file too large' }, { status: 413 });
  }

  try {
    const upstream = await fetch(`${base}/v1/agent/files`, {
      method: 'POST',
      headers: {
        // Copy verbatim: carries the multipart boundary.
        'Content-Type': req.headers.get('content-type') ?? 'application/octet-stream',
        Authorization: authorization,
      },
      body: req.body,
      // Node's fetch requires `duplex` for streaming request bodies; the TS
      // lib types don't include it yet, hence the cast.
      duplex: 'half',
      signal: req.signal,
    } as RequestInit & { duplex: string });
    return await relayJson(upstream);
  } catch (err) {
    return relayError(err, 'api/files POST');
  }
}

export async function GET(req: NextRequest): Promise<Response> {
  const base = backendUrl();
  if (!base) return notConfigured('api/files');

  const authorization = browserAuth(req);
  if (!authorization) return unauthorized('api/files');

  const threadId = req.nextUrl.searchParams.get('thread_id');
  if (!threadId || threadId.length > 200) {
    return Response.json({ error: 'invalid thread_id' }, { status: 422 });
  }

  try {
    const upstream = await fetch(
      `${base}/v1/agent/files?thread_id=${encodeURIComponent(threadId)}`,
      { headers: { Authorization: authorization }, signal: req.signal },
    );
    return await relayJson(upstream);
  } catch (err) {
    return relayError(err, 'api/files GET');
  }
}
