import {
  capForStorage,
  type ChatMessage,
  type ParsedToolResult,
  type Seg,
  type SearchResult,
  type StreamEvent,
} from './types';

let seq = 0;
export function localId(prefix: string): string {
  seq += 1;
  return `${prefix}-${Date.now().toString(36)}-${seq}`;
}

export function newAssistantMessage(): Extract<ChatMessage, { role: 'assistant' }> {
  return { role: 'assistant', id: localId('a'), segs: [], answer: null, ts: Date.now() };
}

// The event stream carries no call-id, so tool_end is paired with the LAST
// still-running tool segment of the same name. Concurrent same-name calls
// could mis-pair; the backend serializes tool calls, so this is acceptable.
export function applyEvent(
  msg: Extract<ChatMessage, { role: 'assistant' }>,
  ev: StreamEvent,
): Extract<ChatMessage, { role: 'assistant' }> {
  switch (ev.type) {
    case 'start':
      return msg;

    case 'token': {
      const last = msg.segs[msg.segs.length - 1];
      if (last && last.kind === 'text') {
        const segs = [...msg.segs.slice(0, -1), { ...last, buf: last.buf + ev.text }];
        return { ...msg, segs };
      }
      return { ...msg, segs: [...msg.segs, { kind: 'text', buf: ev.text }] };
    }

    case 'tool_start': {
      const seg: Seg = {
        kind: 'tool',
        name: ev.tool,
        input: ev.input,
        running: true,
        startedAt: Date.now(),
      };
      return { ...msg, segs: [...msg.segs, seg] };
    }

    case 'tool_end': {
      const idx = findRunningTool(msg.segs, ev.tool);
      if (idx < 0) {
        // Defensive: orphan end event (state lost to a reload) — show it finished.
        const seg: Seg = {
          kind: 'tool',
          name: ev.tool,
          input: {},
          running: false,
          result: unwrapToolOutput(ev.output),
          startedAt: Date.now(),
          endedAt: Date.now(),
        };
        return { ...msg, segs: [...msg.segs, seg] };
      }
      const segs = [...msg.segs];
      const target = segs[idx] as Extract<Seg, { kind: 'tool' }>;
      segs[idx] = {
        ...target,
        running: false,
        result: unwrapToolOutput(ev.output),
        endedAt: Date.now(),
      };
      return { ...msg, segs };
    }

    case 'error':
      return { ...finalize(msg), error: ev.message };

    case 'done':
      return finalize(msg);
  }
}

function findRunningTool(segs: Seg[], name: string): number {
  for (let i = segs.length - 1; i >= 0; i--) {
    const s = segs[i];
    if (s.kind === 'tool' && s.name === name && s.running) return i;
  }
  return -1;
}

// The final answer is the LAST non-blank text segment; everything before it
// (interleaved prose + tool calls) is "thinking". Text segments after the
// chosen answer index are not expected, but keep them visible in thinking.
export function finalize(
  msg: Extract<ChatMessage, { role: 'assistant' }>,
): Extract<ChatMessage, { role: 'assistant' }> {
  const segs = msg.segs.map((s) => (s.kind === 'tool' ? { ...s, running: false } : s));

  let answerIdx = -1;
  for (let i = segs.length - 1; i >= 0; i--) {
    const s = segs[i];
    if (s.kind === 'text' && s.buf.trim() !== '') {
      answerIdx = i;
      break;
    }
  }

  if (answerIdx < 0) {
    return { ...msg, segs, answer: null, partial: false };
  }
  const answer = (segs[answerIdx] as Extract<Seg, { kind: 'text' }>).buf;
  const kept = [...segs.slice(0, answerIdx), ...segs.slice(answerIdx + 1)];
  return { ...msg, segs: kept, answer, partial: false };
}

// Connection died before `done` (stop button, reload, backend crash).
export function markInterrupted(
  msg: Extract<ChatMessage, { role: 'assistant' }>,
  note = '连接中断，回复可能不完整',
): Extract<ChatMessage, { role: 'assistant' }> {
  return { ...finalize({ ...msg, partial: true }), error: msg.error ?? note, partial: false };
}

// tool_end.output is the LangChain ToolMessage dict: the real payload lives in
// output.content as a SECOND JSON string (SandboxResult or web-search payload).
export function unwrapToolOutput(output: unknown): ParsedToolResult {
  if (output && typeof output === 'object' && 'content' in output) {
    const content = (output as { content: unknown }).content;
    if (typeof content === 'string') {
      try {
        return capParsed(JSON.parse(content) as ParsedToolResult);
      } catch {
        return capParsed({ raw: content });
      }
    }
    if (content && typeof content === 'object') {
      return capParsed(content as ParsedToolResult);
    }
  }
  try {
    return capParsed({ raw: JSON.stringify(output) });
  } catch {
    return { raw: String(output) };
  }
}

function capParsed(r: ParsedToolResult): ParsedToolResult {
  if ('stdout' in r && typeof r.stdout === 'string') {
    const s = r as Extract<ParsedToolResult, { stdout: string }>;
    return { ...s, stdout: capForStorage(s.stdout), stderr: capForStorage(s.stderr ?? '') };
  }
  if ('raw' in r && typeof r.raw === 'string') {
    return { ...r, raw: capForStorage(r.raw) };
  }
  if ('query' in r) {
    const s = r as SearchResult;
    if (Array.isArray(s.results)) {
      return {
        ...s,
        results: s.results.map((item) => ({ ...item, content: capForStorage(item.content ?? '') })),
      };
    }
  }
  return r;
}
