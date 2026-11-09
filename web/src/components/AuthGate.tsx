'use client';

import { useState, type FormEvent } from 'react';

import { login, register, type Auth } from '@/lib/auth';

// Mirrors of the backend rules — instant feedback only; the backend stays
// authoritative (its 422 detail is surfaced verbatim below).
const USERNAME_RE = /^[a-zA-Z][a-zA-Z0-9_-]{3,31}$/;
const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
// Loose on purpose: the backend normalizes to E.164 (default region +86) and
// is the real validator.
const PHONE_RE = /^\+?[0-9\s-]{6,20}$/;

type Props = { onAuthed: (a: Auth) => void };

// Map proxy/backend responses to a human-readable Chinese error line.
function mapError(status: number, raw: string, isLogin: boolean): string {
  if (status === 0) return '后端不可达，请确认服务已启动';
  if (isLogin && status === 401) return '用户名或密码错误';
  if (status === 409) {
    if (raw.includes('email already exists')) return '该邮箱已被注册';
    if (raw.includes('phone already exists')) return '该手机号已被注册';
    return '用户名已被注册';
  }
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
  const [account, setAccount] = useState(''); // login: username / email / phone
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [phone, setPhone] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError('');
    const emailTrim = email.trim();
    const phoneTrim = phone.trim();
    if (mode === 'login') {
      // One account box for username/email/phone — no username regex here;
      // anything that doesn't match a user is a plain 401.
      if (!account.trim()) {
        setError('请输入用户名、邮箱或手机号');
        return;
      }
      if (!password) {
        setError('请输入密码');
        return;
      }
    } else {
      if (!USERNAME_RE.test(username)) {
        setError('用户名需为 4-32 位，以英文字母开头，可含数字、_ 或 -');
        return;
      }
      if (emailTrim && !EMAIL_RE.test(emailTrim)) {
        setError('邮箱格式不正确');
        return;
      }
      if (phoneTrim && !PHONE_RE.test(phoneTrim)) {
        setError('手机号格式不正确');
        return;
      }
      if (password.length < 8) {
        setError('密码至少 8 位');
        return;
      }
      if (confirm !== password) {
        setError('两次输入的密码不一致');
        return;
      }
    }
    setBusy(true);
    try {
      const res =
        mode === 'login'
          ? await login(account.trim(), password)
          : await register({
              username,
              password,
              email: emailTrim || undefined,
              phone: phoneTrim || undefined,
            });
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
          {mode === 'login' ? (
            <label className="block text-sm">
              <span className="mb-1 block text-gray-600">账号</span>
              <input
                value={account}
                onChange={(e) => setAccount(e.target.value)}
                autoComplete="username"
                autoFocus
                className={inputClass}
                placeholder="用户名 / 邮箱 / 手机号"
              />
            </label>
          ) : (
            <>
              <label className="block text-sm">
                <span className="mb-1 block text-gray-600">用户名</span>
                <input
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  autoComplete="username"
                  autoFocus
                  className={inputClass}
                  placeholder="4-32 位，以英文字母开头"
                />
              </label>
              <label className="block text-sm">
                <span className="mb-1 block text-gray-600">邮箱（选填）</span>
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  autoComplete="email"
                  className={inputClass}
                  placeholder="用于登录，可选"
                />
              </label>
              <label className="block text-sm">
                <span className="mb-1 block text-gray-600">手机号（选填）</span>
                <input
                  type="tel"
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                  autoComplete="tel"
                  className={inputClass}
                  placeholder="默认中国大陆 +86"
                />
              </label>
            </>
          )}
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
          {mode === 'register' && (
            <label className="block text-sm">
              <span className="mb-1 block text-gray-600">确认密码</span>
              <input
                type="password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                autoComplete="new-password"
                className={inputClass}
                placeholder="再次输入密码"
              />
            </label>
          )}
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
