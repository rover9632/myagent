// Wire + domain types shared by the SSE client, reducer and store.

export type SandboxResult = {
  exit_code: number;
  stdout: string;
  stderr: string;
  duration_ms: number;
  timed_out: boolean;
  output_truncated: boolean;
};

export type SearchResult = {
  query: string;
  answer?: string | null;
  results?: { title?: string; url?: string; content?: string; score?: number }[];
};

export type ParsedToolResult =
  | SandboxResult
  | SearchResult
  | { raw: string }
  | Record<string, unknown>;

export type Seg =
  | { kind: 'text'; buf: string }
  | {
      kind: 'tool';
      name: string;
      input: Record<string, unknown>;
      running: boolean;
      result?: ParsedToolResult;
      startedAt: number;
      endedAt?: number;
    };

export type ChatMessage =
  | { role: 'user'; id: string; text: string; ts: number }
  | {
      role: 'assistant';
      id: string;
      segs: Seg[];
      answer: string | null;
      error?: string;
      // Set when the connection died before `done`; repaired on next load.
      partial?: boolean;
      ts: number;
    };

export type Thread = {
  id: string;
  title: string;
  createdAt: number;
  updatedAt: number;
  messages: ChatMessage[];
};

export type StreamEvent =
  | { type: 'start'; thread_id: string }
  | { type: 'token'; text: string }
  | { type: 'tool_start'; tool: string; input: Record<string, unknown> }
  | { type: 'tool_end'; tool: string; output: unknown }
  | { type: 'error'; message: string }
  | { type: 'done'; thread_id: string };

// Keep stored payloads bounded: anything larger is cut for display/persistence.
export const TOOL_RESULT_MAX_CHARS = 20_000;

export function capForStorage(s: string): string {
  return s.length > TOOL_RESULT_MAX_CHARS ? s.slice(0, TOOL_RESULT_MAX_CHARS) + '…[已截断]' : s;
}
