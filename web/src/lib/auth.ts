// Client-side auth: localStorage session + calls through the /api/auth proxies.
// The token is a per-login session token issued by the FastAPI backend.

export type Auth = { token: string; username: string; expiresAt?: string };

const KEY = 'myagent.auth.v1';

export function loadAuth(): Auth | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<Auth>;
    if (typeof parsed.token !== 'string' || !parsed.token) return null;
    if (typeof parsed.username !== 'string' || !parsed.username) return null;
    return {
      token: parsed.token,
      username: parsed.username,
      ...(typeof parsed.expiresAt === 'string' ? { expiresAt: parsed.expiresAt } : {}),
    };
  } catch {
    return null;
  }
}

export function saveAuth(a: Auth): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(KEY, JSON.stringify(a));
  } catch {
    // Storage full/blocked — the session still works in-memory for this tab.
  }
}

export function clearAuth(): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.removeItem(KEY);
  } catch {
    // ignore
  }
}

export function authHeader(token: string): Record<string, string> {
  return { Authorization: `Bearer ${token}` };
}

export type AuthResult =
  | { ok: true; auth: Auth }
  | { ok: false; status: number; error: string }; // status 0 = network failure

async function postAuth(
  path: '/api/auth/login' | '/api/auth/register',
  username: string,
  password: string,
): Promise<AuthResult> {
  let res: Response;
  try {
    res = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
  } catch {
    return { ok: false, status: 0, error: 'network' };
  }
  const text = await res.text().catch(() => '');
  if (!res.ok) return { ok: false, status: res.status, error: text.slice(0, 200) };
  try {
    const body = JSON.parse(text) as { token?: unknown; username?: unknown; expires_at?: unknown };
    if (typeof body.token !== 'string' || typeof body.username !== 'string') {
      return { ok: false, status: res.status, error: 'malformed auth response' };
    }
    return {
      ok: true,
      auth: {
        token: body.token,
        username: body.username,
        ...(typeof body.expires_at === 'string' ? { expiresAt: body.expires_at } : {}),
      },
    };
  } catch {
    return { ok: false, status: res.status, error: 'malformed auth response' };
  }
}

export function login(username: string, password: string): Promise<AuthResult> {
  return postAuth('/api/auth/login', username, password);
}

export function register(username: string, password: string): Promise<AuthResult> {
  return postAuth('/api/auth/register', username, password);
}

// Fire-and-forget server-side revoke; local state is cleared regardless.
export async function logout(token: string): Promise<void> {
  try {
    await fetch('/api/auth/logout', { method: 'POST', headers: authHeader(token) });
  } catch {
    // best effort
  }
}

export type SessionState = 'valid' | 'invalid' | 'unreachable';

// Tri-state on purpose: a backend outage (502/500/network) must NOT log the
// user out — only a real 401 from the backend means the session is dead.
export async function checkSession(token: string): Promise<SessionState> {
  try {
    const res = await fetch('/api/auth/me', { headers: authHeader(token) });
    if (res.ok) return 'valid';
    if (res.status === 401) return 'invalid';
    return 'unreachable';
  } catch {
    return 'unreachable';
  }
}
