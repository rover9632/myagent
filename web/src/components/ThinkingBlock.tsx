'use client';

import { useState } from 'react';

import ToolCallRow from './ToolCallRow';
import type { Seg } from '@/lib/types';

type Props = {
  segs: Seg[];
  // When there is no final answer at all, keep thinking expanded by default:
  // the tool output is de-facto the only result of this turn.
  forceOpen?: boolean;
};

export default function ThinkingBlock({ segs, forceOpen = false }: Props) {
  const [userChoice, setUserChoice] = useState<boolean | null>(null);
  const open = userChoice ?? forceOpen;

  return (
    <div className="mb-2 max-w-xl rounded-lg border border-gray-200 bg-gray-50/60">
      <button
        onClick={() => setUserChoice(!open)}
        className="flex w-full items-center gap-1.5 px-3 py-1.5 text-left text-[13px] text-gray-500 hover:text-gray-700"
      >
        <svg
          width="12"
          height="12"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.5"
          className={`transition-transform ${open ? 'rotate-90' : ''}`}
        >
          <path d="M9 18l6-6-6-6" />
        </svg>
        <span className="font-medium">深度思考</span>
        <span className="text-[11px] text-gray-400">· {segs.length} 步</span>
      </button>
      {open && (
        <div className="border-t border-gray-100 px-3 py-2">
          {segs.map((seg, i) =>
            seg.kind === 'tool' ? (
              <ToolCallRow key={i} seg={seg} />
            ) : (
              <p
                key={i}
                className="whitespace-pre-wrap border-l-2 border-gray-200 py-0.5 pl-2.5 text-[13px] leading-relaxed text-gray-500"
              >
                {seg.buf}
              </p>
            ),
          )}
        </div>
      )}
    </div>
  );
}
