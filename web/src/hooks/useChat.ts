'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import { applyEvent, finalize, localId, markInterrupted, newAssistantMessage } from '@/lib/reducer';
import { parseSSE } from '@/lib/sse';
import { createThread, deriveTitle, emptyStore, loadStore, saveStore, type Store } from '@/lib/store';
import type { ChatMessage, Thread } from '@/lib/types';

type AssistantMsg = Extract<ChatMessage, { role: 'assistant' }>;

export function useChat() {
  const [store, setStore] = useState<Store>(emptyStore());
  const [hydrated, setHydrated] = useState(false);
  const [streamingIds, setStreamingIds] = useState<Set<string>>(new Set());

  // Mirror of the latest store for synchronous reads inside handlers (send(),
  // beforeunload). Written in an effect, never during render.
  const storeRef = useRef(store);
  useEffect(() => {
    storeRef.current = store;
  }, [store]);
  const abortRef = useRef<AbortController | null>(null);

  // Trailing-throttled persistence; beforeunload flushes mid-stream bytes so a
  // refresh keeps the partial reply (store.load repairs it on next open).
  useEffect(() => {
    if (!hydrated) return;
    const id = setTimeout(() => saveStore(store), 600);
    return () => clearTimeout(id);
  }, [store, hydrated]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const flush = () => saveStore(storeRef.current);
    window.addEventListener('beforeunload', flush);
    return () => window.removeEventListener('beforeunload', flush);
  }, []);

  useEffect(() => {
    const loaded = loadStore();
    if (loaded.threads.length === 0) {
      const t = createThread();
      loaded.threads = [t];
      loaded.activeId = t.id;
    } else if (!loaded.activeId || !loaded.threads.some((t) => t.id === loaded.activeId)) {
      loaded.activeId = loaded.threads[0].id;
    }
    // One-time localStorage hydration: must stay async or the first client
    // render diverges from the server-rendered "加载中…" shell.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setStore(loaded);
    setHydrated(true);
  }, []);

  const patchThread = useCallback((threadId: string, fn: (t: Thread) => Thread) => {
    setStore((s) => ({
      ...s,
      threads: s.threads.map((t) => (t.id === threadId ? fn(t) : t)),
    }));
  }, []);

  const patchAssistant = useCallback(
    (threadId: string, msgId: string, fn: (m: AssistantMsg) => AssistantMsg) => {
      patchThread(threadId, (t) => ({
        ...t,
        updatedAt: Date.now(),
        messages: t.messages.map((m) =>
          m.role === 'assistant' && m.id === msgId ? fn(m as AssistantMsg) : m,
        ),
      }));
    },
    [patchThread],
  );

  const newChat = useCallback(() => {
    setStore((s) => {
      const active = s.threads.find((t) => t.id === s.activeId);
      if (active && active.messages.length === 0) return s; // reuse empty thread
      const t = createThread();
      return { ...s, threads: [t, ...s.threads], activeId: t.id };
    });
  }, []);

  const selectThread = useCallback((id: string) => {
    setStore((s) => ({ ...s, activeId: id }));
  }, []);

  const deleteThread = useCallback((id: string) => {
    abortRef.current?.abort();
    setStore((s) => {
      const threads = s.threads.filter((t) => t.id !== id);
      if (threads.length === 0) {
        const t = createThread();
        return { ...s, threads: [t], activeId: t.id };
      }
      return { ...s, threads, activeId: s.activeId === id ? (threads[0]?.id ?? null) : s.activeId };
    });
  }, []);

  const setStreaming = useCallback((id: string, on: boolean) => {
    setStreamingIds((prev) => {
      const next = new Set(prev);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });
  }, []);

  const streamingIdsRef = useRef<string[]>([]);
  useEffect(() => {
    streamingIdsRef.current = [...streamingIds];
  }, [streamingIds]);

  const send = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || trimmed.length > 20000) return;
      if (streamingIdsRef.current.length > 0) return; // one stream at a time

      // Build the new thread state synchronously from the latest snapshot.
      const cur = storeRef.current;
      let thread = cur.threads.find((t) => t.id === cur.activeId) ?? createThread();
      const userMsg: ChatMessage = { role: 'user', id: localId('u'), text: trimmed, ts: Date.now() };
      const assistant = newAssistantMessage();
      thread = {
        ...thread,
        title:
          thread.messages.length === 0 && thread.title === '新对话'
            ? deriveTitle(trimmed)
            : thread.title,
        messages: [...thread.messages, userMsg, assistant],
        updatedAt: Date.now(),
      };
      const threadId = thread.id;
      const assistantId = assistant.id;

      setStore((s) => ({
        ...s,
        threads: [thread, ...s.threads.filter((t) => t.id !== thread.id)],
        activeId: threadId,
      }));

      const controller = new AbortController();
      abortRef.current = controller;
      setStreaming(threadId, true);

      // `live` is the authoritative copy of the streaming assistant message;
      // React state mirrors it per event.
      let live: AssistantMsg = assistant;
      const commit = (m: AssistantMsg) => {
        live = m;
        patchAssistant(threadId, assistantId, () => m);
      };

      try {
        const res = await fetch('/api/chat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message: trimmed, thread_id: threadId }),
          signal: controller.signal,
        });
        if (!res.ok || !res.body) {
          const detail = await res.text().catch(() => '');
          commit({
            ...finalize(live),
            error: `请求失败 (${res.status})${detail ? `: ${detail.slice(0, 200)}` : ''}`,
          });
          return;
        }

        let sawTerminal = false;
        for await (const ev of parseSSE(res.body)) {
          if (ev.type === 'done' || ev.type === 'error') sawTerminal = true;
          commit(applyEvent(live, ev));
        }
        if (!sawTerminal) commit(markInterrupted(live));
      } catch (err) {
        if ((err as Error)?.name === 'AbortError') {
          commit(markInterrupted(live, '已停止生成'));
        } else {
          commit({ ...finalize(live), error: `网络错误: ${(err as Error).message}` });
        }
      } finally {
        setStreaming(threadId, false);
        if (abortRef.current === controller) abortRef.current = null;
      }
    },
    [setStreaming, patchAssistant],
  );

  const stop = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const activeThread = store.threads.find((t) => t.id === store.activeId) ?? null;
  const activeStreaming = activeThread ? streamingIds.has(activeThread.id) : false;

  return {
    hydrated,
    threads: [...store.threads].sort((a, b) => b.updatedAt - a.updatedAt),
    activeThread,
    activeStreaming,
    streamingIds,
    newChat,
    selectThread,
    deleteThread,
    send,
    stop,
  };
}
