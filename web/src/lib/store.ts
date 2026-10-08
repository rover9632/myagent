import { markInterrupted } from './reducer';
import type { ChatMessage, Thread } from './types';

const KEY = 'myagent.threads.v1';

export type Store = { v: 1; threads: Thread[]; activeId: string | null };

export function deriveTitle(firstUserMessage: string): string {
  const chars = Array.from(firstUserMessage.trim());
  return chars.length > 20 ? `${chars.slice(0, 20).join('')}…` : chars.join('') || '新对话';
}

export function emptyStore(): Store {
  return { v: 1, threads: [], activeId: null };
}

// Any stream that never saw `done` (tab refresh, crash) is stored as partial;
// repair it on load so the UI never shows a forever-running spinner.
function repair(msg: ChatMessage): ChatMessage {
  if (msg.role !== 'assistant') return msg;
  if (msg.partial) return markInterrupted(msg);
  if (msg.segs.some((s) => s.kind === 'tool' && s.running)) {
    return markInterrupted({ ...msg, partial: true });
  }
  return msg;
}

export function loadStore(): Store {
  if (typeof window === 'undefined') return emptyStore();
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return emptyStore();
    const parsed = JSON.parse(raw) as Store;
    if (parsed.v !== 1 || !Array.isArray(parsed.threads)) return emptyStore();
    return {
      v: 1,
      activeId: parsed.activeId ?? null,
      threads: parsed.threads.map((t) => ({ ...t, messages: t.messages.map(repair) })),
    };
  } catch {
    return emptyStore();
  }
}

// Persistence with quota handling: on QuotaExceededError, evict the oldest
// non-active threads and retry; as a last resort drop the oldest tool payloads.
export function saveStore(store: Store): boolean {
  if (typeof window === 'undefined') return false;
  const attempt = (s: Store): boolean => {
    try {
      window.localStorage.setItem(KEY, JSON.stringify(s));
      return true;
    } catch {
      return false;
    }
  };
  if (attempt(store)) return true;

  const evictable = store.threads
    .filter((t) => t.id !== store.activeId)
    .sort((a, b) => a.updatedAt - b.updatedAt);
  for (const victim of evictable) {
    const pruned: Store = {
      ...store,
      threads: store.threads.filter((t) => t.id !== victim.id),
    };
    if (attempt(pruned)) return true;
  }

  const slim: Store = {
    ...store,
    threads: store.threads.map((t) => ({
      ...t,
      messages: t.messages.map((m) =>
        m.role === 'assistant'
          ? {
              ...m,
              segs: m.segs.map((s) =>
                s.kind === 'tool' && s.result
                  ? { ...s, result: { raw: '（历史过长，输出内容未保留）' } }
                  : s,
              ),
            }
          : m,
      ),
    })),
  };
  return attempt(slim);
}

export function createThread(): Thread {
  const id =
    typeof crypto !== 'undefined' && 'randomUUID' in crypto
      ? crypto.randomUUID()
      : `t-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
  const now = Date.now();
  return { id, title: '新对话', createdAt: now, updatedAt: now, messages: [] };
}
