'use client';

import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react';

import type { Auth } from '@/lib/auth';
import { changePassword, patchMe, type MePatch, type MeProfile } from '@/lib/me';

// Mirrors of the backend rules — instant feedback only; the backend stays
// authoritative (its 422/409/403 detail is surfaced inside the edit modal).
const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
const PHONE_RE = /^\+?[0-9\s-]{6,20}$/;

const LOCALES = ['zh-CN', 'en-US'];
const TIMEZONES = [
  'Asia/Shanghai',
  'Asia/Urumqi',
  'Asia/Tokyo',
  'Asia/Singapore',
  'Asia/Kolkata',
  'Asia/Dubai',
  'Europe/Moscow',
  'Europe/Berlin',
  'Europe/London',
  'Europe/Paris',
  'America/New_York',
  'America/Chicago',
  'America/Denver',
  'America/Los_Angeles',
  'America/Sao_Paulo',
  'Australia/Sydney',
  'Pacific/Auckland',
  'UTC',
];

type Props = {
  auth: Auth;
  profile: MeProfile;
  onUnauthorized: () => void;
};

// 每个可修改字段对应一个编辑弹框；一次只 PATCH 一个字段。
type EditKey =
  | 'email'
  | 'phone'
  | 'display_name'
  | 'avatar_url'
  | 'bio'
  | 'locale'
  | 'timezone'
  | 'password';

type SaveResult = { status: 'ok' } | { status: 'unauth' } | { status: 'error'; msg: string };

function fmtDateTime(iso: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString('zh-CN');
}

// res.error from lib/me is already the unwrapped {detail} string.
function mapError(status: number, raw: string): string {
  if (status === 0) return '后端不可达，请稍后重试';
  if (status === 409) {
    if (raw.includes('email already exists')) return '该邮箱已被其他账号使用';
    if (raw.includes('phone already exists')) return '该手机号已被其他账号使用';
    return '该标识符已被占用';
  }
  if (status === 403 && raw.includes('current password is incorrect')) return '当前密码不正确';
  if (status === 404) return '账号不存在或已注销';
  return raw || `请求失败 (${status})`;
}

const inputClass =
  'w-full rounded-lg border border-[#e2e2e2] px-3 py-2 text-sm outline-none transition focus:border-gray-400';
const submitClass =
  'w-full rounded-lg bg-gray-900 px-3 py-2 text-sm font-medium text-white transition hover:bg-gray-700 disabled:opacity-50';
const cardClass = 'rounded-2xl border border-[#ececec] bg-white p-6 shadow-sm sm:p-8';

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block text-gray-600">{label}</span>
      {children}
    </label>
  );
}

function InfoRow({ label, action, children }: { label: string; action?: ReactNode; children: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 py-2">
      <span className="shrink-0 text-sm text-gray-500">{label}</span>
      <span className="flex min-w-0 flex-1 items-start justify-end gap-2 text-sm text-gray-900">
        <span className="min-w-0 break-words text-right">{children}</span>
        {action}
      </span>
    </div>
  );
}

function EditButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="shrink-0 rounded-md border border-[#e2e2e2] px-2 py-0.5 text-xs text-gray-500 transition hover:border-gray-400 hover:text-gray-800"
    >
      修改
    </button>
  );
}

function VerifiedBadge({ verifiedAt }: { verifiedAt: string | null }) {
  return verifiedAt ? (
    <span className="ml-2 inline-flex items-center rounded-full bg-green-50 px-2 py-0.5 text-xs text-green-700">
      已验证
    </span>
  ) : (
    <span className="ml-2 inline-flex items-center rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-500">
      未验证
    </span>
  );
}

// 通用编辑弹框外壳；onMouseDown 关闭只在遮罩上生效，框内拖拽选字不会误关。
function ModalShell({
  title,
  onClose,
  onSubmit,
  busy,
  error,
  submitLabel = '保存',
  children,
}: {
  title: string;
  onClose: () => void;
  onSubmit: (e: FormEvent) => void;
  busy: boolean;
  error: string;
  submitLabel?: string;
  children: ReactNode;
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4"
      onMouseDown={onClose}
    >
      <form
        onSubmit={onSubmit}
        className="w-full max-w-md rounded-2xl bg-white p-6 shadow-xl"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-base font-semibold text-gray-900">{title}</h3>
          <button
            type="button"
            onClick={onClose}
            aria-label="关闭"
            className="text-gray-400 transition hover:text-gray-700"
          >
            ✕
          </button>
        </div>
        {children}
        {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
        <div className="mt-5 flex gap-3">
          <button
            type="button"
            onClick={onClose}
            className="flex-1 rounded-lg border border-[#e2e2e2] px-3 py-2 text-sm text-gray-700 transition hover:bg-gray-50"
          >
            取消
          </button>
          <button type="submit" disabled={busy} className={`${submitClass} flex-1`}>
            {busy ? '提交中…' : submitLabel}
          </button>
        </div>
      </form>
    </div>
  );
}

// onSave 成功时由父组件关弹框（setEditing(null)），这里只在失败时留框显示错误。
function TextFieldEditor({
  title,
  label,
  initial,
  inputType = 'text',
  multiline = false,
  placeholder,
  maxLength,
  validate,
  onSave,
  onClose,
}: {
  title: string;
  label: string;
  initial: string;
  inputType?: 'text' | 'email' | 'tel' | 'url';
  multiline?: boolean;
  placeholder?: string;
  maxLength?: number;
  validate?: (v: string) => string | null;
  onSave: (v: string) => Promise<SaveResult>;
  onClose: () => void;
}) {
  const [value, setValue] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError('');
    const v = value.trim();
    const bad = validate ? validate(v) : null;
    if (bad) {
      setError(bad);
      return;
    }
    setBusy(true);
    try {
      const res = await onSave(v);
      if (res.status === 'error') setError(res.msg);
    } finally {
      setBusy(false);
    }
  }

  return (
    <ModalShell title={title} onClose={onClose} onSubmit={submit} busy={busy} error={error}>
      <Field label={label}>
        {multiline ? (
          <textarea
            value={value}
            onChange={(e) => setValue(e.target.value)}
            rows={4}
            maxLength={maxLength}
            placeholder={placeholder}
            className={`${inputClass} resize-y`}
          />
        ) : (
          <input
            type={inputType}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            maxLength={maxLength}
            placeholder={placeholder}
            className={inputClass}
          />
        )}
      </Field>
    </ModalShell>
  );
}

function SelectEditor({
  title,
  label,
  options,
  initial,
  onSave,
  onClose,
}: {
  title: string;
  label: string;
  options: string[];
  initial: string;
  onSave: (v: string) => Promise<SaveResult>;
  onClose: () => void;
}) {
  const [value, setValue] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError('');
    setBusy(true);
    try {
      const res = await onSave(value);
      if (res.status === 'error') setError(res.msg);
    } finally {
      setBusy(false);
    }
  }

  return (
    <ModalShell title={title} onClose={onClose} onSubmit={submit} busy={busy} error={error}>
      <Field label={label}>
        <select
          value={value}
          onChange={(e) => setValue(e.target.value)}
          className={inputClass}
        >
          {options.map((v) => (
            <option key={v} value={v}>
              {v}
            </option>
          ))}
        </select>
      </Field>
    </ModalShell>
  );
}

function PasswordEditor({
  onSave,
  onClose,
}: {
  onSave: (current: string, next: string) => Promise<SaveResult>;
  onClose: () => void;
}) {
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError('');
    if (!current) {
      setError('请输入当前密码');
      return;
    }
    if (next.length < 8) {
      setError('新密码至少 8 位');
      return;
    }
    if (new TextEncoder().encode(next).length > 72) {
      setError('新密码不能超过 72 字节（中文每字约 3 字节）');
      return;
    }
    if (confirm !== next) {
      setError('两次输入的新密码不一致');
      return;
    }
    setBusy(true);
    try {
      const res = await onSave(current, next);
      if (res.status === 'error') setError(res.msg);
    } finally {
      setBusy(false);
    }
  }

  return (
    <ModalShell
      title="修改密码"
      onClose={onClose}
      onSubmit={submit}
      busy={busy}
      error={error}
      submitLabel="修改密码"
    >
      <div className="space-y-4">
        <Field label="当前密码">
          <input
            type="password"
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
            autoComplete="current-password"
            className={inputClass}
          />
        </Field>
        <Field label="新密码">
          <input
            type="password"
            value={next}
            onChange={(e) => setNext(e.target.value)}
            autoComplete="new-password"
            className={inputClass}
            placeholder="至少 8 位，不超过 72 字节"
          />
        </Field>
        <Field label="确认新密码">
          <input
            type="password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            autoComplete="new-password"
            className={inputClass}
          />
        </Field>
      </div>
    </ModalShell>
  );
}

export default function ProfileView({ auth, profile: initial, onUnauthorized }: Props) {
  const [profile, setProfile] = useState<MeProfile>(initial);
  const [editing, setEditing] = useState<EditKey | null>(null);
  const [flash, setFlash] = useState('');
  const [copied, setCopied] = useState(false);
  const flashTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      if (flashTimer.current) clearTimeout(flashTimer.current);
    },
    [],
  );

  function showFlash(msg: string) {
    if (flashTimer.current) clearTimeout(flashTimer.current);
    setFlash(msg);
    flashTimer.current = setTimeout(() => setFlash(''), 4000);
  }

  async function copyId() {
    try {
      await navigator.clipboard.writeText(profile.id);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // clipboard blocked (non-HTTPS etc.) — the id stays visible on screen
    }
  }

  // PATCH 是 exclude_unset 语义：只发当前这一个键，其余字段不动。
  async function saveField(patch: MePatch): Promise<SaveResult> {
    const res = await patchMe(auth.token, patch);
    if (res.ok) {
      setProfile(res.data);
      setEditing(null);
      showFlash('修改成功');
      return { status: 'ok' };
    }
    if (res.status === 401) {
      onUnauthorized();
      return { status: 'unauth' };
    }
    return { status: 'error', msg: mapError(res.status, res.error) };
  }

  async function savePassword(currentPw: string, nextPw: string): Promise<SaveResult> {
    const res = await changePassword(auth.token, currentPw, nextPw);
    if (res.ok) {
      setEditing(null);
      showFlash('密码修改成功，其他设备的登录已失效');
      return { status: 'ok' };
    }
    if (res.status === 401) {
      onUnauthorized();
      return { status: 'unauth' };
    }
    return { status: 'error', msg: mapError(res.status, res.error) };
  }

  // 兜底：库里存过选项之外的值时弹框里仍要能显示并保存
  const localeOptions = LOCALES.includes(profile.locale)
    ? LOCALES
    : [profile.locale, ...LOCALES];
  const tzOptions = TIMEZONES.includes(profile.timezone)
    ? TIMEZONES
    : [profile.timezone, ...TIMEZONES];

  const statusLabel: Record<string, string> = {
    active: '正常',
    disabled: '已禁用',
    locked: '已锁定',
    deleted: '已注销',
  };
  const statusActive = profile.status === 'active';
  const unset = <span className="text-gray-400">未设置</span>;

  return (
    <div className="mx-auto w-full max-w-2xl space-y-6 pb-16">
      {flash && (
        <div className="rounded-lg border border-green-200 bg-green-50 px-4 py-2 text-sm text-green-700">
          {flash}
        </div>
      )}

      {/* 统一展示：每个字段只出现一次；可修改字段右侧带“修改”按钮，点击弹出编辑框 */}
      <section className={cardClass}>
        <h2 className="mb-3 text-base font-semibold text-gray-900">账号信息</h2>
        <div className="divide-y divide-[#f2f2f2]">
          <InfoRow label="用户名">{profile.username}</InfoRow>
          <InfoRow label="状态">
            <span
              className={`inline-flex items-center gap-1.5 text-sm ${
                statusActive ? 'text-green-700' : 'text-red-600'
              }`}
            >
              <span
                className={`h-2 w-2 rounded-full ${statusActive ? 'bg-green-500' : 'bg-red-500'}`}
              />
              {statusLabel[profile.status] ?? profile.status}
            </span>
          </InfoRow>
          <InfoRow label="用户 ID">
            <span className="break-all font-mono text-xs">{profile.id}</span>
            <button
              onClick={copyId}
              className="ml-2 shrink-0 text-xs text-gray-400 underline underline-offset-2 hover:text-gray-700"
            >
              {copied ? '已复制' : '复制'}
            </button>
          </InfoRow>
          <InfoRow label="注册时间">{fmtDateTime(profile.created_at)}</InfoRow>
          <InfoRow label="最近登录">
            {profile.last_login_at ? fmtDateTime(profile.last_login_at) : '—（从未登录）'}
            {profile.last_login_ip && (
              <span className="ml-2 text-xs text-gray-400">IP {profile.last_login_ip}</span>
            )}
          </InfoRow>
          <InfoRow label="邮箱" action={<EditButton onClick={() => setEditing('email')} />}>
            {profile.email ?? <span className="text-gray-400">未绑定</span>}
            <VerifiedBadge verifiedAt={profile.email_verified_at} />
          </InfoRow>
          <InfoRow label="手机号" action={<EditButton onClick={() => setEditing('phone')} />}>
            {profile.phone ?? <span className="text-gray-400">未绑定</span>}
            <VerifiedBadge verifiedAt={profile.phone_verified_at} />
          </InfoRow>
          <InfoRow
            label="昵称"
            action={<EditButton onClick={() => setEditing('display_name')} />}
          >
            {profile.display_name ?? unset}
          </InfoRow>
          <InfoRow
            label="头像 URL"
            action={<EditButton onClick={() => setEditing('avatar_url')} />}
          >
            {profile.avatar_url ?? unset}
          </InfoRow>
          <InfoRow label="个人简介" action={<EditButton onClick={() => setEditing('bio')} />}>
            {profile.bio ?? unset}
          </InfoRow>
          <InfoRow label="语言" action={<EditButton onClick={() => setEditing('locale')} />}>
            {profile.locale}
          </InfoRow>
          <InfoRow label="时区" action={<EditButton onClick={() => setEditing('timezone')} />}>
            {profile.timezone}
          </InfoRow>
          <InfoRow label="密码" action={<EditButton onClick={() => setEditing('password')} />}>
            <span className="text-gray-500">已设置</span>
          </InfoRow>
        </div>
        <p className="mt-3 text-xs text-gray-400">
          用户名与状态不可自助修改；各字段通过“修改”按钮单独保存；修改邮箱或手机号后验证状态会重置为未验证。
        </p>
      </section>

      {editing === 'email' && (
        <TextFieldEditor
          title="修改邮箱"
          label="邮箱"
          inputType="email"
          initial={profile.email ?? ''}
          placeholder="留空表示解绑"
          validate={(v) => (v && !EMAIL_RE.test(v) ? '邮箱格式不正确' : null)}
          onSave={(v) => saveField({ email: v || null })}
          onClose={() => setEditing(null)}
        />
      )}
      {editing === 'phone' && (
        <TextFieldEditor
          title="修改手机号"
          label="手机号"
          inputType="tel"
          initial={profile.phone ?? ''}
          placeholder="默认中国大陆 +86，留空表示解绑"
          validate={(v) => (v && !PHONE_RE.test(v) ? '手机号格式不正确' : null)}
          onSave={(v) => saveField({ phone: v || null })}
          onClose={() => setEditing(null)}
        />
      )}
      {editing === 'display_name' && (
        <TextFieldEditor
          title="修改昵称"
          label="昵称"
          initial={profile.display_name ?? ''}
          maxLength={100}
          placeholder="显示名称（选填），留空表示清除"
          onSave={(v) => saveField({ display_name: v || null })}
          onClose={() => setEditing(null)}
        />
      )}
      {editing === 'avatar_url' && (
        <TextFieldEditor
          title="修改头像 URL"
          label="头像 URL"
          inputType="url"
          initial={profile.avatar_url ?? ''}
          maxLength={2048}
          placeholder="https://… （暂不支持上传），留空表示清除"
          onSave={(v) => saveField({ avatar_url: v || null })}
          onClose={() => setEditing(null)}
        />
      )}
      {editing === 'bio' && (
        <TextFieldEditor
          title="修改个人简介"
          label="个人简介"
          initial={profile.bio ?? ''}
          multiline
          maxLength={5000}
          placeholder="关于你（选填），留空表示清除"
          onSave={(v) => saveField({ bio: v || null })}
          onClose={() => setEditing(null)}
        />
      )}
      {editing === 'locale' && (
        <SelectEditor
          title="修改语言"
          label="语言"
          options={localeOptions}
          initial={profile.locale}
          onSave={(v) => saveField({ locale: v })}
          onClose={() => setEditing(null)}
        />
      )}
      {editing === 'timezone' && (
        <SelectEditor
          title="修改时区"
          label="时区"
          options={tzOptions}
          initial={profile.timezone}
          onSave={(v) => saveField({ timezone: v })}
          onClose={() => setEditing(null)}
        />
      )}
      {editing === 'password' && (
        <PasswordEditor onSave={savePassword} onClose={() => setEditing(null)} />
      )}
    </div>
  );
}
