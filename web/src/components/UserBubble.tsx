'use client';

import type { ChatMessage } from '@/lib/types';

type UserMsg = Extract<ChatMessage, { role: 'user' }>;

export default function UserBubble({ msg }: { msg: UserMsg }) {
  return (
    <div className="mb-6 flex justify-end">
      <div className="max-w-[80%] whitespace-pre-wrap break-words rounded-2xl bg-[#e8e8e8] px-4 py-2.5 text-[15px] leading-relaxed text-gray-900">
        {msg.text}
      </div>
    </div>
  );
}
