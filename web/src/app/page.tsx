'use client';

import { useEffect, useState } from 'react';

import ChatWindow from '@/components/ChatWindow';
import Sidebar from '@/components/Sidebar';
import { useChat } from '@/hooks/useChat';

export default function Home() {
  const chat = useChat();
  // null = unknown; the proxy validates before touching upstream, so an empty
  // body returns 422 when configured vs 500 "backend not configured".
  const [configured, setConfigured] = useState<boolean | null>(null);

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
        onNew={chat.newChat}
        onSelect={chat.selectThread}
        onDelete={chat.deleteThread}
      />
      <ChatWindow
        thread={chat.activeThread}
        streaming={chat.activeStreaming}
        backendReady={configured !== false}
        onSend={chat.send}
        onStop={chat.stop}
      />
    </div>
  );
}
