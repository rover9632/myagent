'use client';

import { useCallback, useEffect, useState } from 'react';

import AuthGate from '@/components/AuthGate';
import ChatApp from '@/components/ChatApp';
import { checkSession, clearAuth, loadAuth, logout, saveAuth, type Auth } from '@/lib/auth';

export default function Home() {
  const [auth, setAuth] = useState<Auth | null>(null);
  const [checking, setChecking] = useState(true);

  // One-shot session restore: 401 clears the dead token and shows the gate;
  // a backend outage (5xx/network) KEEPS the session — don't log users out
  // just because the server is briefly down.
  useEffect(() => {
    let alive = true;
    const stored = loadAuth();
    // No stored session resolves through the same async path ('invalid' with
    // stored=null): clearAuth() is a no-op and setAuth(null) is a bail-out,
    // and no setState happens synchronously in the effect body.
    const resolved = stored
      ? checkSession(stored.token)
      : Promise.resolve('invalid' as const);
    resolved.then((s) => {
      if (!alive) return;
      if (s === 'invalid') clearAuth();
      setAuth(s === 'invalid' ? null : stored);
      setChecking(false);
    });
    return () => {
      alive = false;
    };
  }, []);

  const onAuthed = useCallback((a: Auth) => {
    saveAuth(a);
    setAuth(a);
  }, []);

  const onUnauthorized = useCallback(() => {
    clearAuth();
    setAuth(null);
  }, []);

  const onLogout = useCallback(() => {
    const current = loadAuth();
    if (current) void logout(current.token); // best-effort server-side revoke
    clearAuth();
    setAuth(null);
  }, []);

  if (checking) {
    return <div className="flex h-screen items-center justify-center text-gray-400">加载中…</div>;
  }
  if (!auth) {
    return <AuthGate onAuthed={onAuthed} />;
  }
  // key remounts the whole chat shell on user switch (per-user store namespace).
  return <ChatApp key={auth.username} auth={auth} onUnauthorized={onUnauthorized} onLogout={onLogout} />;
}
