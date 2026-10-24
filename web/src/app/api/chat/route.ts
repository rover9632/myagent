import { NextRequest } from 'next/server';

// Same-origin proxy to the FastAPI backend. Two jobs:
// 1. Inject the bearer token server-side (never ships to the browser).
// 2. Forward the client's abort signal so closing the tab/Stop button cancels
//    the upstream LangGraph run instead of letting it burn sandbox minutes.
// NOTE: no `runtime`/`dynamic` segment configs — with cacheComponents enabled
// (Next 16) they are errors, and POST handlers already run per-request.

export async function POST(req: NextRequest): Promise<Response> {
  const backendUrl = process.env.BACKEND_URL;
  const token = process.env.BACKEND_API_TOKEN;
  if (!backendUrl || !token) {
    console.error('api/chat: BACKEND_URL / BACKEND_API_TOKEN not configured');
    return Response.json({ error: 'backend not configured' }, { status: 500 });
  }

  let body: { message?: unknown; thread_id?: unknown; attachments?: unknown };
  try {
    body = await req.json();
  } catch {
    return Response.json({ error: 'invalid json' }, { status: 400 });
  }

  const message = body.message;
  const threadId = body.thread_id;
  if (typeof message !== 'string' || message.length === 0 || message.length > 20000) {
    return Response.json({ error: 'invalid message' }, { status: 422 });
  }
  if (threadId != null && (typeof threadId !== 'string' || threadId.length > 200)) {
    return Response.json({ error: 'invalid thread_id' }, { status: 422 });
  }

  // Optional echo of previously uploaded files; shallow-validate and forward.
  // The backend re-validates every path against the thread workspace.
  let attachments: { name: string; path: string }[] | null = null;
  if (body.attachments != null) {
    const raw = body.attachments;
    const ok =
      Array.isArray(raw) &&
      raw.length <= 50 &&
      raw.every(
        (a): a is { name: string; path: string } =>
          typeof a === 'object' &&
          a !== null &&
          typeof (a as { name?: unknown }).name === 'string' &&
          (a as { name: string }).name.length >= 1 &&
          (a as { name: string }).name.length <= 200 &&
          typeof (a as { path?: unknown }).path === 'string' &&
          (a as { path: string }).path.length >= 1 &&
          (a as { path: string }).path.length <= 300,
      );
    if (!ok) return Response.json({ error: 'invalid attachments' }, { status: 422 });
    attachments = raw.map(({ name, path }) => ({ name, path }));
  }

  let upstream: Response;
  try {
    upstream = await fetch(`${backendUrl.replace(/\/$/, '')}/v1/agent/chat/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        message,
        thread_id: threadId ?? null,
        ...(attachments && attachments.length > 0 ? { attachments } : {}),
      }),
      signal: req.signal,
    });
  } catch (err) {
    if ((err as Error)?.name === 'AbortError') {
      return new Response(null, { status: 499 });
    }
    console.error('api/chat: upstream fetch failed:', err);
    return Response.json({ error: 'backend unreachable' }, { status: 502 });
  }

  // Non-stream errors (401/422/…) pass through as plain text — safe to buffer
  // because this branch never carries an SSE body.
  if (!upstream.ok || !upstream.body) {
    const text = await upstream.text().catch(() => '');
    return new Response(text, {
      status: upstream.status,
      headers: { 'Content-Type': 'text/plain; charset=utf-8' },
    });
  }

  // Hand the ReadableStream straight over: any await text()/json() here would
  // buffer the whole reply and break incremental SSE.
  return new Response(upstream.body, {
    headers: {
      'Content-Type': 'text/event-stream; charset=utf-8',
      'Cache-Control': 'no-cache, no-transform',
      Connection: 'keep-alive',
      'X-Accel-Buffering': 'no',
    },
  });
}
