'use client';

import { useState } from 'react';

import type { ParsedToolResult, Seg, SandboxResult, SearchResult } from '@/lib/types';

type ToolSeg = Extract<Seg, { kind: 'tool' }>;

function isSandbox(r: ParsedToolResult | undefined): r is SandboxResult {
  return !!r && typeof r === 'object' && 'exit_code' in r && 'stdout' in r;
}
function isSearch(r: ParsedToolResult | undefined): r is SearchResult {
  return !!r && typeof r === 'object' && 'query' in r;
}

const TOOL_ICON: Record<string, string> = {
  bash_exec: '⌘',
  python_exec: '🐍',
  python_run_script: '🐍',
  web_search: '🔍',
};

export default function ToolCallRow({ seg }: { seg: ToolSeg }) {
  const [open, setOpen] = useState(false);
  const dur = seg.endedAt ? `${seg.endedAt - seg.startedAt}ms` : '';

  let status: string;
  let ok = true;
  if (seg.running) {
    status = '执行中…';
    ok = false;
  } else if (isSandbox(seg.result)) {
    const r = seg.result;
    status = r.timed_out ? '超时' : `exit ${r.exit_code}`;
    ok = !r.timed_out && r.exit_code === 0;
  } else if (isSearch(seg.result)) {
    status = `${seg.result.results?.length ?? 0} 条结果`;
  } else {
    status = '完成';
  }

  return (
    <div className="my-0.5">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 rounded px-1 py-0.5 text-left text-[13px] text-gray-600 hover:bg-gray-100"
      >
        <span className="w-4 text-center">{TOOL_ICON[seg.name] ?? '🔧'}</span>
        <span className="font-mono">{seg.name}</span>
        <span
          className={`rounded-full px-2 py-px text-[11px] ${
            seg.running
              ? 'animate-pulse bg-blue-100 text-blue-700'
              : ok
                ? 'bg-emerald-100 text-emerald-700'
                : 'bg-red-100 text-red-700'
          }`}
        >
          {status}
        </span>
        {dur && !seg.running && <span className="text-[11px] text-gray-400">{dur}</span>}
        <span className="ml-auto text-[10px] text-gray-400">{open ? '收起' : '详情'}</span>
      </button>

      {open && (
        <div className="mb-1 ml-6 space-y-1.5 border-l border-gray-200 pl-3">
          <pre className="max-h-40 overflow-auto whitespace-pre-wrap break-all rounded bg-gray-50 p-2 font-mono text-[11px] text-gray-600">
            {JSON.stringify(seg.input, null, 2)}
          </pre>
          {isSandbox(seg.result) && (
            <>
              {seg.result.stdout && (
                <pre className="max-h-60 overflow-auto whitespace-pre-wrap break-all rounded bg-gray-50 p-2 font-mono text-[11px]">
                  {seg.result.stdout}
                </pre>
              )}
              {seg.result.stderr && (
                <pre className="max-h-60 overflow-auto whitespace-pre-wrap break-all rounded bg-amber-50 p-2 font-mono text-[11px] text-amber-800">
                  {seg.result.stderr}
                </pre>
              )}
            </>
          )}
          {isSearch(seg.result) && (
            <div className="space-y-1">
              {seg.result.answer && <p className="text-xs text-gray-600">{seg.result.answer}</p>}
              {(seg.result.results ?? []).map((item, i) => (
                <div key={i} className="text-xs">
                  <a
                    href={item.url}
                    target="_blank"
                    rel="noreferrer"
                    className="font-medium text-blue-600 hover:underline"
                  >
                    {item.title ?? item.url}
                  </a>
                  <p className="line-clamp-2 text-gray-500">{item.content}</p>
                </div>
              ))}
            </div>
          )}
          {seg.result && !isSandbox(seg.result) && !isSearch(seg.result) && 'raw' in seg.result && (
            <pre className="max-h-60 overflow-auto whitespace-pre-wrap break-all rounded bg-gray-50 p-2 font-mono text-[11px]">
              {String((seg.result as { raw: unknown }).raw)}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}
