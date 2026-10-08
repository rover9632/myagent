'use client';

import AssistantMessage from './AssistantMessage';
import UserBubble from './UserBubble';
import type { ChatMessage } from '@/lib/types';

export default function MessageRow({
  msg,
  streaming,
}: {
  msg: ChatMessage;
  streaming: boolean;
}) {
  if (msg.role === 'user') return <UserBubble msg={msg} />;
  return <AssistantMessage msg={msg} streaming={streaming} />;
}
