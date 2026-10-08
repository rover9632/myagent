'use client';

import { useEffect, useRef } from 'react';

import Composer from './Composer';
import MessageRow from './MessageRow';
import type { Thread } from '@/lib/types';

type Props = {
  thread: Thread | null;
  streaming: boolean;
  backendReady: boolean;
  onSend: (text: string) => void;
  onStop: () => void;
};

export default function ChatWindow({ thread, streaming, backendReady, onSend, onStop }: Props) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const atBottomRef = useRef(true);

  // Auto-scroll only when the user is already near the bottom, so scrolling up
  // to re-read during a stream isn't fighting the tail of new tokens.
  useEffect(() => {
    const el = scrollRef.current;
    if (el && atBottomRef.current) el.scrollTop = el.scrollHeight;
  }, [thread?.messages]);

  const onScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    atBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  };

  const empty = !thread || thread.messages.length === 0;

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <div ref={scrollRef} onScroll={onScroll} className="flex-1 overflow-y-auto">
        {empty ? (
          <div className="flex h-full items-center justify-center">
            <div className="text-center">
              <h2 className="mb-1 text-2xl font-semibold text-gray-800">MyAgent</h2>
              <p className="text-sm text-gray-400">
                {backendReady ? '问我任何问题，我能跑代码、查资料。' : '正在等待后端就绪…'}
              </p>
            </div>
          </div>
        ) : (
          <div className="mx-auto w-full max-w-3xl px-4 py-6">
            {thread.messages.map((m) => (
              <MessageRow
                key={m.id}
                msg={m}
                streaming={streaming && m.role === 'assistant' && m.id === thread.messages[thread.messages.length - 1]?.id}
              />
            ))}
          </div>
        )}
      </div>
      <Composer streaming={streaming} disabled={!backendReady} onSend={onSend} onStop={onStop} />
    </div>
  );
}
