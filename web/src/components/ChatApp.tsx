'use client';

import { useEffect, useState } from 'react';

import ChatWindow from '@/components/ChatWindow';
import Sidebar from '@/components/Sidebar';
import { useChat } from '@/hooks/useChat';
import type { Auth } from '@/lib/auth';
import { getMe } from '@/lib/me';

type Props = {
  auth: Auth;
  onUnauthorized: () => void;
  onLogout: () => void;
};

// The logged-in chat shell. Remounted per user via key={auth.username} in
// page.tsx so every piece of state (threads, store namespace) switches cleanly.
export default function ChatApp({ auth, onUnauthorized, onLogout }: Props) {
  const chat = useChat(auth, onUnauthorized);
  // null = unknown; the proxy validates before touching upstream, so an empty
  // body returns 422 when configured vs 500 "backend not configured".
  const [configured, setConfigured] = useState<boolean | null>(null);
  // Cosmetic only: the sidebar shows display_name when set, else the username.
  // Failures (incl. 401) silently keep the username — page.tsx already probes
  // the session, and real auth errors surface through the chat/stream calls.
  const [displayName, setDisplayName] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    getMe(auth.token).then((res) => {
      if (alive && res.ok) setDisplayName(res.data.display_name);
    });
    return () => {
      alive = false;
    };
  }, [auth.token]);

  useEffect(() => {
    let alive = true;
    fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{}',
    })
      .then((r) => alive && setConfigured(r.status !== 500))
      .catch(() => alive && setConfigured(false));
    return () => {
      alive = false;
    };
  }, []);

  if (!chat.hydrated) {
    return <div className="flex h-screen items-center justify-center text-gray-400">加载中…</div>;
  }

  return (
    <div className="flex h-screen overflow-hidden bg-white text-gray-900">
      <Sidebar
        threads={chat.threads}
        activeId={chat.activeThread?.id ?? null}
        streamingIds={chat.streamingIds}
        username={auth.username}
        displayName={displayName}
        onNew={chat.newChat}
        onSelect={chat.selectThread}
        onDelete={chat.deleteThread}
        onLogout={onLogout}
      />
      <ChatWindow
        thread={chat.activeThread}
        streaming={chat.activeStreaming}
        backendReady={configured !== false}
        onSend={chat.send}
        onStop={chat.stop}
        onUploadFile={chat.uploadFile}
      />
    </div>
  );
}
