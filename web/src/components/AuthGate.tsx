'use client';

import { useState, type FormEvent } from 'react';

import { login, register, type Auth } from '@/lib/auth';

// Mirror of the backend's USERNAME_RE — instant feedback, backend stays
// authoritative (its 422 detail is surfaced verbatim below).
const USERNAME_RE = /^[a-zA-Z0-9_-]{3,32}$/;

type Props = { onAuthed: (a: Auth) => void };

// Map proxy/backend responses to a human-readable Chinese error line.
function mapError(status: number, raw: string, isLogin: boolean): string {
  if (status === 0) return '后端不可达，请确认服务已启动';
  if (isLogin && status === 401) return '用户名或密码错误';
  if (status === 409) return '用户名已被注册';
  try {
    const detail = (JSON.parse(raw) as { detail?: unknown }).detail;
    if (typeof detail === 'string' && detail) return detail;
    if (Array.isArray(detail) && detail.length > 0) {
      // FastAPI/pydantic 422: show the first field error.
      const first = detail[0] as { msg?: unknown };
      if (typeof first?.msg === 'string') return first.msg;
    }
  } catch {
    // not JSON — fall through to the generic line
  }
  return `请求失败 (${status})`;
}

export default function AuthGate({ onAuthed }: Props) {
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError('');
    if (!USERNAME_RE.test(username)) {
      setError('用户名需为 3-32 位字母、数字、下划线或连字符');
      return;
    }
    if (mode === 'register' && password.length < 8) {
      setError('密码至少 8 位');
      return;
    }
    if (!password) {
      setError('请输入密码');
      return;
    }
    setBusy(true);
    try {
      const res =
        mode === 'login' ? await login(username, password) : await register(username, password);
      if (res.ok) {
        onAuthed(res.auth);
      } else {
        setError(mapError(res.status, res.error, mode === 'login'));
      }
    } finally {
      setBusy(false);
    }
  }

  const inputClass =
    'w-full rounded-lg border border-[#e2e2e2] px-3 py-2 text-sm outline-none transition focus:border-gray-400';

  return (
    <div className="flex h-screen items-center justify-center bg-[#f9f9f9] text-gray-900">
      <div className="w-full max-w-sm rounded-2xl border border-[#ececec] bg-white p-8 shadow-sm">
        <h1 className="mb-1 text-xl font-semibold tracking-tight">MyAgent</h1>
        <p className="mb-6 text-sm text-gray-500">
          {mode === 'login' ? '登录以继续' : '创建新账号'}
        </p>
        <form onSubmit={submit} className="space-y-4">
          <label className="block text-sm">
            <span className="mb-1 block text-gray-600">用户名</span>
            <input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              autoFocus
              className={inputClass}
              placeholder="3-32 位字母、数字、_ 或 -"
            />
          </label>
          <label className="block text-sm">
            <span className="mb-1 block text-gray-600">密码</span>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
              className={inputClass}
              placeholder={mode === 'register' ? '至少 8 位' : '请输入密码'}
            />
          </label>
          {error && <p className="text-sm text-red-600">{error}</p>}
          <button
            type="submit"
            disabled={busy}
            className="w-full rounded-lg bg-gray-900 px-3 py-2 text-sm font-medium text-white transition hover:bg-gray-700 disabled:opacity-50"
          >
            {busy ? '请稍候…' : mode === 'login' ? '登录' : '注册'}
          </button>
        </form>
        <p className="mt-5 text-center text-sm text-gray-500">
          {mode === 'login' ? '还没有账号？' : '已有账号？'}{' '}
          <button
            onClick={() => {
              setMode(mode === 'login' ? 'register' : 'login');
              setError('');
            }}
            className="font-medium text-gray-800 underline underline-offset-2 hover:text-gray-600"
          >
            {mode === 'login' ? '注册' : '登录'}
          </button>
        </p>
      </div>
    </div>
  );
}
