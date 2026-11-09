'use client';

import { useState, type FormEvent, type ReactNode } from 'react';

import type { Auth } from '@/lib/auth';
import { changePassword, patchMe, type MeProfile } from '@/lib/me';

// Mirrors of the backend rules — instant feedback only; the backend stays
// authoritative (its 422/409/403 detail is surfaced below).
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

function InfoRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 py-2">
      <span className="shrink-0 text-sm text-gray-500">{label}</span>
      <span className="min-w-0 text-right text-sm text-gray-900">{children}</span>
    </div>
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

export default function ProfileView({ auth, profile: initial, onUnauthorized }: Props) {
  const [profile, setProfile] = useState<MeProfile>(initial);

  // 资料编辑卡（表单每次全量提交 7 个字段，后端变更检测兜底）
  const [email, setEmail] = useState(initial.email ?? '');
  const [phone, setPhone] = useState(initial.phone ?? '');
  const [displayName, setDisplayName] = useState(initial.display_name ?? '');
  const [avatarUrl, setAvatarUrl] = useState(initial.avatar_url ?? '');
  const [bio, setBio] = useState(initial.bio ?? '');
  const [locale, setLocale] = useState(initial.locale);
  const [timezone, setTimezone] = useState(initial.timezone);
  const [profileBusy, setProfileBusy] = useState(false);
  const [profileError, setProfileError] = useState('');
  const [profileSaved, setProfileSaved] = useState(false);

  // 修改密码卡
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const [pwBusy, setPwBusy] = useState(false);
  const [pwError, setPwError] = useState('');
  const [pwDone, setPwDone] = useState(false);

  const [copied, setCopied] = useState(false);

  function syncForm(p: MeProfile) {
    setEmail(p.email ?? '');
    setPhone(p.phone ?? '');
    setDisplayName(p.display_name ?? '');
    setAvatarUrl(p.avatar_url ?? '');
    setBio(p.bio ?? '');
    setLocale(p.locale);
    setTimezone(p.timezone);
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

  async function submitProfile(e: FormEvent) {
    e.preventDefault();
    setProfileError('');
    setProfileSaved(false);
    const emailTrim = email.trim();
    const phoneTrim = phone.trim();
    if (emailTrim && !EMAIL_RE.test(emailTrim)) {
      setProfileError('邮箱格式不正确');
      return;
    }
    if (phoneTrim && !PHONE_RE.test(phoneTrim)) {
      setProfileError('手机号格式不正确');
      return;
    }
    setProfileBusy(true);
    try {
      const res = await patchMe(auth.token, {
        email: emailTrim || null,
        phone: phoneTrim || null,
        display_name: displayName.trim() || null,
        avatar_url: avatarUrl.trim() || null,
        bio: bio.trim() || null,
        locale,
        timezone,
      });
      if (res.ok) {
        setProfile(res.data);
        syncForm(res.data); // pick up server-canonical email/phone forms
        setProfileSaved(true);
      } else if (res.status === 401) {
        onUnauthorized();
      } else {
        setProfileError(mapError(res.status, res.error));
      }
    } finally {
      setProfileBusy(false);
    }
  }

  async function submitPassword(e: FormEvent) {
    e.preventDefault();
    setPwError('');
    setPwDone(false);
    if (next.length < 8) {
      setPwError('新密码至少 8 位');
      return;
    }
    if (new TextEncoder().encode(next).length > 72) {
      setPwError('新密码不能超过 72 字节（中文每字约 3 字节）');
      return;
    }
    if (confirm !== next) {
      setPwError('两次输入的新密码不一致');
      return;
    }
    setPwBusy(true);
    try {
      const res = await changePassword(auth.token, current, next);
      if (res.ok) {
        setCurrent('');
        setNext('');
        setConfirm('');
        setPwDone(true);
      } else if (res.status === 401) {
        onUnauthorized();
      } else {
        setPwError(mapError(res.status, res.error));
      }
    } finally {
      setPwBusy(false);
    }
  }

  // 兜底：库里存过选项之外的值时仍要能显示并保存
  const localeOptions = LOCALES.includes(locale) ? LOCALES : [locale, ...LOCALES];
  const tzOptions = TIMEZONES.includes(timezone) ? TIMEZONES : [timezone, ...TIMEZONES];

  const statusLabel: Record<string, string> = {
    active: '正常',
    disabled: '已禁用',
    locked: '已锁定',
    deleted: '已注销',
  };
  const statusActive = profile.status === 'active';

  return (
    <div className="mx-auto w-full max-w-2xl space-y-6 pb-16">
      {/* 账号信息（只读） */}
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
          <InfoRow label="邮箱">
            {profile.email ?? <span className="text-gray-400">未绑定</span>}
            <VerifiedBadge verifiedAt={profile.email_verified_at} />
          </InfoRow>
          <InfoRow label="手机号">
            {profile.phone ?? <span className="text-gray-400">未绑定</span>}
            <VerifiedBadge verifiedAt={profile.phone_verified_at} />
          </InfoRow>
        </div>
        <p className="mt-3 text-xs text-gray-400">
          用户名与状态不可自助修改；修改邮箱或手机号后验证状态会重置为未验证。
        </p>
      </section>

      {/* 资料编辑 */}
      <section className={cardClass}>
        <h2 className="mb-4 text-base font-semibold text-gray-900">资料编辑</h2>
        <form onSubmit={submitProfile} className="space-y-4">
          <Field label="邮箱">
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
              className={inputClass}
              placeholder="留空表示不绑定"
            />
          </Field>
          <Field label="手机号">
            <input
              type="tel"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              autoComplete="tel"
              className={inputClass}
              placeholder="默认中国大陆 +86，留空表示不绑定"
            />
          </Field>
          <Field label="昵称">
            <input
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              maxLength={100}
              className={inputClass}
              placeholder="显示名称（选填）"
            />
          </Field>
          <Field label="头像 URL">
            <input
              type="url"
              value={avatarUrl}
              onChange={(e) => setAvatarUrl(e.target.value)}
              className={inputClass}
              placeholder="https://… （暂不支持上传）"
            />
          </Field>
          <Field label="个人简介">
            <textarea
              value={bio}
              onChange={(e) => setBio(e.target.value)}
              rows={3}
              maxLength={5000}
              className={`${inputClass} resize-y`}
              placeholder="关于你（选填）"
            />
          </Field>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field label="语言">
              <select
                value={locale}
                onChange={(e) => setLocale(e.target.value)}
                className={inputClass}
              >
                {localeOptions.map((v) => (
                  <option key={v} value={v}>
                    {v}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="时区">
              <select
                value={timezone}
                onChange={(e) => setTimezone(e.target.value)}
                className={inputClass}
              >
                {tzOptions.map((v) => (
                  <option key={v} value={v}>
                    {v}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          {profileError && <p className="text-sm text-red-600">{profileError}</p>}
          {profileSaved && !profileError && <p className="text-sm text-green-700">保存成功</p>}
          <button type="submit" disabled={profileBusy} className={submitClass}>
            {profileBusy ? '保存中…' : '保存资料'}
          </button>
        </form>
      </section>

      {/* 修改密码 */}
      <section className={cardClass}>
        <h2 className="mb-4 text-base font-semibold text-gray-900">修改密码</h2>
        <form onSubmit={submitPassword} className="space-y-4">
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
          {pwError && <p className="text-sm text-red-600">{pwError}</p>}
          {pwDone && !pwError && (
            <p className="text-sm text-green-700">修改成功，其他设备的登录已失效</p>
          )}
          <button type="submit" disabled={pwBusy} className={submitClass}>
            {pwBusy ? '请稍候…' : '修改密码'}
          </button>
        </form>
      </section>
    </div>
  );
}
