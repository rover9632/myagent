'use client';

import Link from 'next/link';
import { useCallback, useEffect, useState } from 'react';

import ProfileView from '@/components/ProfileView';
import { clearAuth, loadAuth, type Auth } from '@/lib/auth';
import { getMe, type MeProfile } from '@/lib/me';

type State =
  | { kind: 'checking' }
  | { kind: 'anon' }
  | { kind: 'unreachable' }
  | { kind: 'ready'; auth: Auth; profile: MeProfile };

// getMe doubles as the session probe on this route; state only ever lands via
// the promise callback, never synchronously in an effect body (app/page.tsx
// keeps the same shape for the React lint rules).
async function computeState(): Promise<State> {
  const stored = loadAuth();
  if (!stored) return { kind: 'anon' };
  const res = await getMe(stored.token);
  if (res.ok) return { kind: 'ready', auth: stored, profile: res.data };
  if (res.status === 401) {
    clearAuth();
    return { kind: 'anon' };
  }
  return { kind: 'unreachable' };
}

// Same tri-state philosophy as app/page.tsx: only a real 401 clears the local
// session — a proxy 502/network failure shows a retry card and keeps it.
export default function ProfilePage() {
  const [state, setState] = useState<State>({ kind: 'checking' });

  useEffect(() => {
    let alive = true;
    computeState().then((s) => {
      if (alive) setState(s);
    });
    return () => {
      alive = false;
    };
  }, []);

  const probe = useCallback(() => {
    setState({ kind: 'checking' });
    computeState().then(setState);
  }, []);

  const onUnauthorized = useCallback(() => {
    clearAuth();
    setState({ kind: 'anon' });
  }, []);

  return (
    <div className="flex min-h-screen flex-col bg-[#f9f9f9] text-gray-900">
      <header className="flex items-center gap-4 border-b border-[#ececec] bg-white px-5 py-3">
        <Link
          href="/"
          className="text-sm text-gray-500 transition hover:text-gray-800"
        >
          ← 返回聊天
        </Link>
        <h1 className="text-sm font-semibold tracking-tight">个人中心</h1>
      </header>
      <main className="flex-1 px-4 py-6 sm:px-6">
        {state.kind === 'checking' && (
          <div className="flex h-64 items-center justify-center text-gray-400">加载中…</div>
        )}
        {state.kind === 'anon' && (
          <div className="mx-auto mt-16 w-full max-w-sm rounded-2xl border border-[#ececec] bg-white p-8 text-center shadow-sm">
            <p className="mb-4 text-sm text-gray-600">请先登录后再访问个人中心</p>
            <Link
              href="/"
              className="block w-full rounded-lg bg-gray-900 px-3 py-2 text-sm font-medium text-white transition hover:bg-gray-700"
            >
              前往登录
            </Link>
          </div>
        )}
        {state.kind === 'unreachable' && (
          <div className="mx-auto mt-16 w-full max-w-sm rounded-2xl border border-[#ececec] bg-white p-8 text-center shadow-sm">
            <p className="mb-4 text-sm text-gray-600">后端不可达，请确认服务已启动</p>
            <button
              onClick={() => void probe()}
              className="w-full rounded-lg bg-gray-900 px-3 py-2 text-sm font-medium text-white transition hover:bg-gray-700"
            >
              重试
            </button>
          </div>
        )}
        {state.kind === 'ready' && (
          <ProfileView auth={state.auth} profile={state.profile} onUnauthorized={onUnauthorized} />
        )}
      </main>
    </div>
  );
}
