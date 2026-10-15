import { useCallback, useEffect, useState } from 'react';
import { api, KIOSK_URL, ON_KIOSK } from './api';
import PinPad from './PinPad';
import { useIdle } from './useIdle';
import Overview from './pages/Overview';
import Knowledge from './pages/Knowledge';
import TestQuestion from './pages/TestQuestion';
import Unmatched from './pages/Unmatched';
import Settings from './pages/Settings';
import Health from './pages/Health';

const PAGES = [
  ['overview', 'Overview', Overview],
  ['kb', 'Knowledge base', Knowledge],
  ['test', 'Test a question', TestQuestion],
  ['unmatched', 'Unmatched questions', Unmatched],
  ['settings', 'Settings', Settings],
  ['health', 'Health', Health],
] as const;
type PageId = (typeof PAGES)[number][0];

// Matches [admin] session_idle_s: the dashboard closes after 5 idle minutes (baseline 5.1).
const IDLE_MS = 5 * 60 * 1000;

export default function App() {
  const [authed, setAuthed] = useState<boolean | null>(null);
  const [page, setPage] = useState<PageId>('overview');

  useEffect(() => {
    api.get<{ auth: boolean }>('/api/auth/me').then((r) => setAuthed(r.auth)).catch(() => setAuthed(false));
    const onUnauthorized = () => setAuthed(false);
    window.addEventListener('kiosk:unauthorized', onUnauthorized);
    return () => window.removeEventListener('kiosk:unauthorized', onUnauthorized);
  }, []);

  const exit = useCallback(async () => {
    try { await api.post('/api/auth/logout'); } catch { /* already logged out */ }
    if (ON_KIOSK) location.href = KIOSK_URL;
    else { setAuthed(false); setPage('overview'); }
  }, []);

  useIdle(IDLE_MS, exit);

  if (authed === null) return <p className="p-8 muted">Loading…</p>;
  if (!authed) return <PinPad onSuccess={() => setAuthed(true)} onCancel={ON_KIOSK ? exit : undefined} />;

  const Current = PAGES.find(([id]) => id === page)![2];
  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-10 border-b border-neutral-200 bg-white">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-3">
          <h1 className="text-lg font-semibold">Kiosk dashboard</h1>
          <button className="btn-secondary" onClick={exit}>Exit</button>
        </div>
        <nav className="mx-auto flex max-w-5xl gap-1 overflow-x-auto px-3 pb-3">
          {PAGES.map(([id, label]) => (
            <button key={id} className={`tab ${page === id ? 'tab-active' : ''}`} onClick={() => setPage(id)}>
              {label}
            </button>
          ))}
        </nav>
      </header>
      <main className="mx-auto max-w-5xl p-4">
        <Current />
      </main>
    </div>
  );
}
