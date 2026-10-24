'use client';

import type { ChatMessage } from '@/lib/types';
import { formatBytes } from '@/lib/uploads';

type UserMsg = Extract<ChatMessage, { role: 'user' }>;

export default function UserBubble({ msg }: { msg: UserMsg }) {
  return (
    <div className="mb-6 flex flex-col items-end">
      <div className="max-w-[80%] whitespace-pre-wrap break-words rounded-2xl bg-[#e8e8e8] px-4 py-2.5 text-[15px] leading-relaxed text-gray-900">
        {msg.text}
      </div>
      {msg.attachments && msg.attachments.length > 0 && (
        <div className="mt-1.5 flex max-w-[80%] flex-wrap justify-end gap-1.5">
          {msg.attachments.map((a) => (
            <span
              key={a.path}
              className="inline-flex max-w-full items-center gap-1.5 rounded-lg border border-gray-200 bg-white px-2 py-1 text-xs text-gray-600"
            >
              <span aria-hidden>📎</span>
              <span className="max-w-48 truncate">{a.name}</span>
              <span className="shrink-0 text-gray-400">{formatBytes(a.size)}</span>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
