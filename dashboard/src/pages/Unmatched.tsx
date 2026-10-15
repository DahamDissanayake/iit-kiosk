import { useEffect, useState } from 'react';
import { api } from '../api';

interface Data { enabled: boolean; items: { id: number; ts: number; text: string }[] }

export default function Unmatched() {
  const [data, setData] = useState<Data | null>(null);
  const [error, setError] = useState('');
  useEffect(() => { api.get<Data>('/api/kb/unmatched').then(setData).catch((e) => setError(e.message)); }, []);

  if (error) return <p className="font-semibold text-accent">{error}</p>;
  if (!data) return <p className="muted">Loading…</p>;
  return (
    <div className="space-y-4">
      <h2 className="text-xl font-semibold">Unmatched questions</h2>
      {!data.enabled ? (
        <div className="card">
          <p className="font-semibold">Logging is off.</p>
          <p className="muted mt-1">
            This list stores what visitors asked when the kiosk had no answer, so it stays off unless IIT turns it on in
            Settings. When on, questions are kept for 30 days and the on-screen privacy notice says so.
          </p>
        </div>
      ) : data.items.length === 0 ? (
        <p className="muted">No unmatched questions yet.</p>
      ) : (
        <ul className="card divide-y divide-neutral-100 p-0">
          {data.items.map((q) => (
            <li key={q.id} className="p-3">
              <p>{q.text}</p>
              <p className="muted">{new Date(q.ts * 1000).toLocaleString()}</p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
