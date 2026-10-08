'use client';

import { memo } from 'react';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

import ThinkingBlock from './ThinkingBlock';
import ToolCallRow from './ToolCallRow';
import type { ChatMessage } from '@/lib/types';

type AssistantMsg = Extract<ChatMessage, { role: 'assistant' }>;

// Answers only go through markdown; model text is untrusted, so raw HTML stays
// OFF (default) and thinking prose renders as plain pre-wrap text.
const MarkdownBlock = memo(function MarkdownBlock({ source }: { source: string }) {
  return (
    <div className="md-body text-[15px] leading-relaxed text-gray-900">
      <Markdown remarkPlugins={[remarkGfm]}>{source}</Markdown>
    </div>
  );
});

export default function AssistantMessage({ msg, streaming }: { msg: AssistantMsg; streaming: boolean }) {
  // While streaming there is no answer/thinking split yet (finalization happens
  // on `done`), so render segments inline in arrival order.
  if (streaming) {
    return (
      <div className="group mb-6 flex justify-start">
        <div className="max-w-[85%] min-w-0">
          {msg.segs.length === 0 && (
            <p className="text-[15px] text-gray-400">
              <span className="caret" />
            </p>
          )}
          {msg.segs.map((seg, i) => {
            const isLast = i === msg.segs.length - 1;
            if (seg.kind === 'tool') return <ToolCallRow key={i} seg={seg} />;
            return (
              <p
                key={i}
                className={`whitespace-pre-wrap text-[15px] leading-relaxed text-gray-900 ${isLast ? 'caret' : ''}`}
              >
                {seg.buf}
              </p>
            );
          })}
        </div>
      </div>
    );
  }

  return (
    <div className="mb-6 flex justify-start">
      <div className="max-w-[85%] min-w-0">
        {msg.segs.length > 0 && <ThinkingBlock segs={msg.segs} forceOpen={msg.answer === null} />}

        {msg.answer !== null ? (
          <MarkdownBlock source={msg.answer} />
        ) : (
          msg.segs.length === 0 && (
            <p className="text-sm text-gray-400">本轮没有文本回复</p>
          )
        )}

        {msg.error && (
          <div className="mt-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            {msg.error}
          </div>
        )}
      </div>
    </div>
  );
}
