'use client';

import type { Thread } from '@/lib/types';

type Props = {
  threads: Thread[];
  activeId: string | null;
  streamingIds: Set<string>;
  onNew: () => void;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
};

export default function Sidebar({
  threads,
  activeId,
  streamingIds,
  onNew,
  onSelect,
  onDelete,
}: Props) {
  return (
    <aside className="flex w-64 shrink-0 flex-col border-r border-[#ececec] bg-[#f9f9f9]">
      <div className="px-4 pb-2 pt-5">
        <h1
          className="text-lg font-semibold tracking-tight text-gray-900"
          title="服务重启后模型不记得历史(对话记录仅保存在本浏览器)"
        >
          MyAgent
        </h1>
      </div>

      <div className="px-3 pb-3">
        <button
          onClick={onNew}
          className="flex w-full items-center gap-2 rounded-lg border border-[#e2e2e2] bg-white px-3 py-2 text-sm font-medium text-gray-800 shadow-sm transition hover:bg-gray-50 active:scale-[0.99]"
        >
          <span className="text-base leading-none">+</span> 新建聊天
        </button>
      </div>

      <nav className="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
        {threads.map((t) => {
          const active = t.id === activeId;
          return (
            <div
              key={t.id}
              className={`group relative mb-0.5 flex items-center rounded-lg transition ${
                active ? 'bg-[#e8e8e8]' : 'hover:bg-[#efefef]'
              }`}
            >
              <button
                onClick={() => onSelect(t.id)}
                className="min-w-0 flex-1 truncate px-3 py-2 pr-8 text-left text-sm text-gray-800"
                title={t.title}
              >
                {streamingIds.has(t.id) && (
                  <span className="mr-1.5 inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-500 align-middle" />
                )}
                {t.title}
              </button>
              <button
                onClick={() => onDelete(t.id)}
                title="删除会话"
                className="absolute right-1.5 hidden rounded p-1 text-gray-400 hover:bg-white hover:text-gray-700 group-hover:block"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M3 6h18M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2m3 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" />
                </svg>
              </button>
            </div>
          );
        })}
      </nav>
    </aside>
  );
}
