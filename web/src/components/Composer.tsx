'use client';

import { useCallback, useRef, useState } from 'react';

type Props = {
  streaming: boolean;
  disabled: boolean;
  onSend: (text: string) => void;
  onStop: () => void;
};

const MAX_ROWS = 8;

export default function Composer({ streaming, disabled, onSend, onStop }: Props) {
  const [text, setText] = useState('');
  const taRef = useRef<HTMLTextAreaElement>(null);

  const autosize = useCallback(() => {
    const ta = taRef.current;
    if (!ta) return;
    ta.style.height = 'auto';
    const max = 22 * MAX_ROWS;
    ta.style.height = `${Math.min(ta.scrollHeight, max)}px`;
    ta.style.overflowY = ta.scrollHeight > max ? 'auto' : 'hidden';
  }, []);

  const submit = useCallback(() => {
    const t = text.trim();
    if (!t || streaming || disabled) return;
    onSend(t);
    setText('');
    requestAnimationFrame(autosize);
  }, [text, streaming, disabled, onSend, autosize]);

  const canSend = text.trim().length > 0 && !streaming && !disabled;

  return (
    <div className="shrink-0 px-4 pb-4">
      <div className="mx-auto flex w-full max-w-3xl items-end gap-2 rounded-2xl border border-gray-300 bg-white px-2 py-1.5 shadow-sm focus-within:border-gray-400">
        <button
          type="button"
          disabled
          title="即将支持"
          className="mb-1 flex h-8 w-8 shrink-0 cursor-not-allowed items-center justify-center rounded-full text-gray-300"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M12 5v14M5 12h14" />
          </svg>
        </button>

        <textarea
          ref={taRef}
          rows={1}
          value={text}
          disabled={disabled}
          placeholder={disabled ? '后端未就绪…' : '给 MyAgent 发送消息…'}
          onChange={(e) => {
            setText(e.target.value);
            autosize();
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              submit();
            }
          }}
          className="max-h-44 flex-1 resize-none bg-transparent py-1.5 text-[15px] leading-[22px] text-gray-900 outline-none placeholder:text-gray-400 disabled:opacity-50"
        />

        {streaming ? (
          <button
            type="button"
            onClick={onStop}
            title="停止生成"
            className="mb-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gray-900 text-white hover:bg-gray-700"
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
              <rect x="6" y="6" width="12" height="12" rx="2" />
            </svg>
          </button>
        ) : (
          <button
            type="button"
            onClick={submit}
            disabled={!canSend}
            title="发送"
            className="mb-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gray-900 text-white enabled:hover:bg-gray-700 disabled:cursor-not-allowed disabled:bg-gray-200 disabled:text-gray-400"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <path d="M12 19V5M5 12l7-7 7 7" />
            </svg>
          </button>
        )}
      </div>
      <p className="mx-auto mt-1.5 max-w-3xl text-center text-[11px] text-gray-400">
        对话记录仅保存在本浏览器；服务重启后模型不记得历史。
      </p>
    </div>
  );
}
