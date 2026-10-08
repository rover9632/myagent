import type { StreamEvent } from './types';

// Minimal SSE reader over fetch's ReadableStream. EventSource is not usable
// here: the request is a POST with an Authorization header.
// Wire format (fastapi.sse): `event: <type>\ndata: <single-line JSON>\n\n`,
// plus keepalive comment lines starting with ':' every 15s (must be skipped).
export async function* parseSSE(body: ReadableStream<Uint8Array>): AsyncGenerator<StreamEvent> {
  // Cast: DOM lib types TextDecoderStream.writable as WritableStream<BufferSource>,
  // which pipeThrough rejects despite accepting Uint8Array at runtime.
  const decoder = new TextDecoderStream() as unknown as TransformStream<Uint8Array, string>;
  const reader = body.pipeThrough(decoder).getReader();
  let buffer = '';

  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += value.replace(/\r\n/g, '\n');

      let sep: number;
      while ((sep = buffer.indexOf('\n\n')) >= 0) {
        const frame = buffer.slice(0, sep);
        buffer = buffer.slice(sep + 2);
        const ev = parseFrame(frame);
        if (ev) yield ev;
      }
    }
    // Trailing frame without final blank line (server killed mid-flush).
    const tail = parseFrame(buffer);
    if (tail) yield tail;
  } finally {
    reader.releaseLock();
  }
}

function parseFrame(frame: string): StreamEvent | null {
  let event = 'message';
  const dataLines: string[] = [];
  for (const line of frame.split('\n')) {
    if (!line || line.startsWith(':')) continue; // keepalive / comments
    if (line.startsWith('event:')) event = line.slice(6).trim();
    else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim());
  }
  if (!dataLines.length) return null;

  let payload: Record<string, unknown>;
  try {
    payload = JSON.parse(dataLines.join('\n'));
  } catch {
    return null;
  }

  switch (event) {
    case 'start':
    case 'done':
      return { type: event, thread_id: String(payload.thread_id ?? '') };
    case 'token':
      return { type: 'token', text: String(payload.text ?? '') };
    case 'tool_start':
      return {
        type: 'tool_start',
        tool: String(payload.tool ?? ''),
        input: (payload.input ?? {}) as Record<string, unknown>,
      };
    case 'tool_end':
      return { type: 'tool_end', tool: String(payload.tool ?? ''), output: payload.output };
    case 'error':
      return { type: 'error', message: String(payload.message ?? '未知错误') };
    default:
      return null;
  }
}
