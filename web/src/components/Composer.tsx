'use client';

import { useCallback, useRef, useState, type ChangeEvent } from 'react';

import {
  formatBytes,
  MAX_UPLOAD_BYTES,
  type PendingAttachment,
  type StoredAttachment,
} from '@/lib/uploads';

type Props = {
  streaming: boolean;
  disabled: boolean;
  threadId: string | null;
  onSend: (text: string, attachments?: StoredAttachment[]) => void;
  onStop: () => void;
  onUploadFile: (file: File) => Promise<StoredAttachment>;
};

const MAX_ROWS = 8;

let chipSeq = 0;

// NOTE: the parent keys this component by thread id, so switching threads
// remounts it and drops unsent chips (they belonged to the old workspace).
export default function Composer({
  streaming,
  disabled,
  threadId,
  onSend,
  onStop,
  onUploadFile,
}: Props) {
  const [text, setText] = useState('');
  const [pending, setPending] = useState<PendingAttachment[]>([]);
  const taRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const autosize = useCallback(() => {
    const ta = taRef.current;
    if (!ta) return;
    ta.style.height = 'auto';
    const max = 22 * MAX_ROWS;
    ta.style.height = `${Math.min(ta.scrollHeight, max)}px`;
    ta.style.overflowY = ta.scrollHeight > max ? 'auto' : 'hidden';
  }, []);

  const uploading = pending.some((p) => p.status === 'uploading');
  const canAttach = !disabled && !streaming && threadId !== null;

  const handleFiles = useCallback(
    (e: ChangeEvent<HTMLInputElement>) => {
      const files = Array.from(e.target.files ?? []);
      e.target.value = ''; // allow re-picking the exact same file
      for (const file of files) {
        const id = `chip-${Date.now()}-${chipSeq++}`;
        // Courtesy pre-check; the proxy/backend enforce the real limit (413).
        if (file.size > MAX_UPLOAD_BYTES) {
          setPending((prev) => [
            ...prev,
            { id, name: file.name, size: file.size, status: 'error', error: '超过 50MB 单文件上限' },
          ]);
          continue;
        }
        // No `accept` filter on the input: the backend allowlist (415) is
        // authoritative and errors surface on the chip.
        setPending((prev) => [...prev, { id, name: file.name, size: file.size, status: 'uploading' }]);
        onUploadFile(file)
          .then((saved) =>
            setPending((prev) => prev.map((p) => (p.id === id ? { ...p, status: 'done', saved } : p))),
          )
          .catch((err: unknown) =>
            setPending((prev) =>
              prev.map((p) =>
                p.id === id ? { ...p, status: 'error', error: (err as Error).message } : p,
              ),
            ),
          );
      }
    },
    [onUploadFile],
  );

  const submit = useCallback(() => {
    const t = text.trim();
    if (!t || streaming || disabled || uploading) return;
    const attachments = pending
      .filter(
        (p): p is PendingAttachment & { saved: StoredAttachment } =>
          p.status === 'done' && !!p.saved,
      )
      .map((p) => p.saved);
    onSend(t, attachments.length > 0 ? attachments : undefined);
    setText('');
    setPending([]);
    requestAnimationFrame(autosize);
  }, [text, streaming, disabled, uploading, pending, onSend, autosize]);

  const canSend = text.trim().length > 0 && !streaming && !disabled && !uploading;

  return (
    <div className="shrink-0 px-4 pb-4">
      <div className="mx-auto w-full max-w-3xl rounded-2xl border border-gray-300 bg-white shadow-sm focus-within:border-gray-400">
        <input ref={fileRef} type="file" multiple className="hidden" onChange={handleFiles} />

        {pending.length > 0 && (
          <div className="flex flex-wrap gap-1.5 px-2.5 pt-2.5">
            {pending.map((p) => (
              <span
                key={p.id}
                title={p.status === 'error' ? p.error : undefined}
                className={`inline-flex max-w-full items-center gap-1.5 rounded-lg border px-2 py-1 text-xs ${
                  p.status === 'error'
                    ? 'border-red-200 bg-red-50 text-red-700'
                    : 'border-gray-200 bg-gray-50 text-gray-700'
                }`}
              >
                <span aria-hidden>📎</span>
                <span className="max-w-40 truncate">{p.name}</span>
                <span className="shrink-0 text-gray-400">{formatBytes(p.size)}</span>
                {p.status === 'uploading' && <span className="shrink-0 text-gray-400">上传中…</span>}
                {p.status === 'error' && <span className="shrink-0">失败</span>}
                {/* × only detaches the chip from the next message; an uploaded
                    copy stays in the thread workspace (the backend directory
                    scan still makes it visible to the model). */}
                <button
                  type="button"
                  onClick={() => setPending((prev) => prev.filter((x) => x.id !== p.id))}
                  className="-mr-0.5 shrink-0 rounded px-0.5 text-gray-400 hover:text-gray-600"
                  title="移除"
                >
                  ×
                </button>
              </span>
            ))}
          </div>
        )}

        <div className="flex items-end gap-2 px-2 py-1.5">
          <button
            type="button"
            onClick={() => fileRef.current?.click()}
            disabled={!canAttach}
            title={canAttach ? '上传附件' : '暂不可用'}
            className="mb-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-gray-500 enabled:hover:bg-gray-100 disabled:cursor-not-allowed disabled:text-gray-300"
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
              title={uploading ? '附件上传中…' : '发送'}
              className="mb-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gray-900 text-white enabled:hover:bg-gray-700 disabled:cursor-not-allowed disabled:bg-gray-200 disabled:text-gray-400"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <path d="M12 19V5M5 12l7-7 7 7" />
              </svg>
            </button>
          )}
        </div>
      </div>
      <p className="mx-auto mt-1.5 max-w-3xl text-center text-[11px] text-gray-400">
        对话记录仅保存在本浏览器；服务重启后模型不记得历史。
      </p>
    </div>
  );
}
