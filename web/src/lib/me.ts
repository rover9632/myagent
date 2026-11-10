// Client for the profile center: mirrors app/schemas.py MeProfileResponse and
// goes through the same-origin /api/me* proxies with the browser's Bearer token.

import { authHeader } from './auth';

export type MeProfile = {
  id: string;
  username: string;
  email: string | null;
  phone: string | null;
  status: string;
  email_verified_at: string | null;
  phone_verified_at: string | null;
  last_login_at: string | null;
  last_login_ip: string | null;
  created_at: string;
  display_name: string | null;
  avatar_url: string | null;
  bio: string | null;
  locale: string;
  timezone: string;
};

export type MeResult =
  | { ok: true; data: MeProfile }
  | { ok: false; status: number; error: string }; // status 0 = network failure

export type MePatch = Partial<
  Pick<
    MeProfile,
    'email' | 'phone' | 'display_name' | 'avatar_url' | 'bio' | 'locale' | 'timezone'
  >
>;

// FastAPI errors are {detail}: a string, or a pydantic 422 array — take the first msg.
function errorText(text: string): string {
  try {
    const body = JSON.parse(text) as { detail?: unknown };
    if (typeof body.detail === 'string') return body.detail;
    if (Array.isArray(body.detail) && body.detail.length > 0) {
      const first = body.detail[0] as { msg?: unknown };
      if (typeof first?.msg === 'string') return first.msg;
    }
  } catch {
    // keep raw text
  }
  return text.slice(0, 300);
}

function parseError(status: number, text: string): MeResult {
  return { ok: false, status, error: errorText(text) };
}

async function getMeData(token: string): Promise<MeResult> {
  let res: Response;
  try {
    res = await fetch('/api/me', { headers: authHeader(token) });
  } catch {
    return { ok: false, status: 0, error: 'network' };
  }
  const text = await res.text().catch(() => '');
  if (!res.ok) return parseError(res.status, text);
  try {
    return { ok: true, data: JSON.parse(text) as MeProfile };
  } catch {
    return { ok: false, status: res.status, error: 'malformed profile response' };
  }
}

export function getMe(token: string): Promise<MeResult> {
  return getMeData(token);
}

// PATCH is exclude_unset on the backend: only the keys you send are written.
// The profile UI edits one field at a time and sends just that key; unchanged
// email/phone would also be a no-op for *_verified_at thanks to the store's
// change-detection, but relying on that is unnecessary now.
export async function patchMe(token: string, changes: MePatch): Promise<MeResult> {
  let res: Response;
  try {
    res = await fetch('/api/me', {
      method: 'PATCH',
      headers: { ...authHeader(token), 'Content-Type': 'application/json' },
      body: JSON.stringify(changes),
    });
  } catch {
    return { ok: false, status: 0, error: 'network' };
  }
  const text = await res.text().catch(() => '');
  if (!res.ok) return parseError(res.status, text);
  try {
    return { ok: true, data: JSON.parse(text) as MeProfile };
  } catch {
    return { ok: false, status: res.status, error: 'malformed profile response' };
  }
}

export type PasswordResult = { ok: boolean; status: number; error: string };

export async function changePassword(
  token: string,
  currentPassword: string,
  newPassword: string,
): Promise<PasswordResult> {
  let res: Response;
  try {
    res = await fetch('/api/me/password', {
      method: 'POST',
      headers: { ...authHeader(token), 'Content-Type': 'application/json' },
      body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
    });
  } catch {
    return { ok: false, status: 0, error: 'network' };
  }
  if (res.ok) return { ok: true, status: res.status, error: '' };
  const text = await res.text().catch(() => '');
  return { ok: false, status: res.status, error: errorText(text) };
}
