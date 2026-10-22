import { useEffect, useState } from 'react';
import { api, ApiError } from './api';

const KEYS = ['1', '2', '3', '4', '5', '6', '7', '8', '9', 'clear', '0', 'back'];

function mmss(s: number) {
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

export default function PinPad({ onSuccess, onCancel }: { onSuccess: () => void; onCancel?: () => void }) {
  const [pin, setPin] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);

  async function submit(value: string) {
    setBusy(true);
    try {
      await api.post('/api/auth/login', { pin: value });
      onSuccess();
    } catch (e) {
      setPin('');
      const d = e instanceof ApiError ? e.body?.detail : null;
      if (d?.reason === 'locked') setMessage(`Too many wrong tries. Try again in ${mmss(d.retry_after_s)}.`);
      else if (d?.reason === 'wrong') setMessage(`Wrong PIN. ${d.tries_left} ${d.tries_left === 1 ? 'try' : 'tries'} left.`);
      else if (d?.reason === 'unset') setMessage('No PIN is set yet. Set one on the kiosk with "python -m core.admin set-pin".');
      else setMessage('Could not reach the kiosk.');
    } finally {
      setBusy(false);
    }
  }

  function press(key: string) {
    if (busy) return;
    setMessage('');
    if (key === 'clear') return setPin('');
    if (key === 'back') return setPin((p) => p.slice(0, -1));
    const next = (pin + key).slice(0, 6);
    setPin(next);
    if (next.length === 6) void submit(next);
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (/^\d$/.test(e.key)) press(e.key);
      else if (e.key === 'Backspace') press('back');
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });

  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-8 p-6">
      <div className="text-center">
        <h1 className="text-2xl font-semibold">Staff access</h1>
        <p className="muted mt-1">Enter the 6-digit PIN.</p>
      </div>
      <div className="flex gap-3" aria-label={`${pin.length} of 6 digits entered`}>
        {Array.from({ length: 6 }, (_, i) => (
          <span key={i} className={`h-4 w-4 rounded-full ${i < pin.length ? 'bg-ink' : 'border-2 border-neutral-300'}`} />
        ))}
      </div>
      <p className="min-h-6 text-center font-semibold text-accent" role="alert">{message}</p>
      <div className="grid grid-cols-3 gap-3">
        {KEYS.map((k) => (
          <button
            key={k}
            type="button"
            disabled={busy}
            onClick={() => press(k)}
            className={`h-20 w-20 rounded-full text-2xl font-semibold ${
              k === 'clear' || k === 'back' ? 'text-base text-neutral-600' : 'border border-neutral-200 bg-white shadow-sm active:bg-neutral-100'
            }`}
          >
            {k === 'clear' ? 'Clear' : k === 'back' ? '⌫' : k}
          </button>
        ))}
      </div>
      {onCancel && <button className="btn-secondary" onClick={onCancel}>Back to kiosk</button>}
    </div>
  );
}
