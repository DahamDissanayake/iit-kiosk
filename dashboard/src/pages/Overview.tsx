import { useEffect, useState } from 'react';
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { api, duration, type HourBucket, type Range, type Stats } from '../api';

const CARDS: [string, string][] = [
  ['encounter', 'Encounters'],
  ['greeting', 'Greetings'],
  ['conversation_start', 'Conversations'],
  ['question', 'Questions asked'],
  ['answered', 'Answered'],
  ['unmatched', 'No match'],
  ['fallback', 'Touch menu uses'],
  ['walkaway', 'Walked away'],
  ['decline', 'Said no thanks'],
];

export default function Overview() {
  const [range, setRange] = useState<Range>('today');
  const [stats, setStats] = useState<Stats | null>(null);
  const [hours, setHours] = useState<HourBucket[]>([]);
  const [error, setError] = useState('');

  useEffect(() => {
    let live = true;
    const load = () =>
      Promise.all([api.get<Stats>(`/api/stats?range=${range}`), api.get<HourBucket[]>(`/api/stats/hourly?range=${range}`)])
        .then(([s, h]) => { if (live) { setStats(s); setHours(h); setError(''); } })
        .catch((e) => live && setError(e.message));
    load();
    const timer = window.setInterval(load, 15000);
    return () => { live = false; window.clearInterval(timer); };
  }, [range]);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold">Overview</h2>
        <div className="flex gap-1 rounded-full bg-neutral-100 p-1">
          {(['today', 'all'] as Range[]).map((r) => (
            <button key={r} className={`tab ${range === r ? 'tab-active' : ''}`} onClick={() => setRange(r)}>
              {r === 'today' ? 'Today' : 'Since install'}
            </button>
          ))}
        </div>
      </div>
      {error && <p className="font-semibold text-accent">{error}</p>}
      {stats && (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            {CARDS.map(([key, label]) => (
              <div key={key} className="card">
                <p className="muted">{label}</p>
                <p className="text-3xl font-semibold">{stats.counts[key] ?? 0}</p>
              </div>
            ))}
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div className="card">
              <p className="muted">Average conversation</p>
              <p className="text-2xl font-semibold">{stats.avg_conversation_s != null ? `${Math.round(stats.avg_conversation_s)} s` : '–'}</p>
            </div>
            <div className="card">
              <p className="muted">Average time to first reply</p>
              <p className="text-2xl font-semibold">{stats.avg_reply_ms != null ? `${(stats.avg_reply_ms / 1000).toFixed(1)} s` : '–'}</p>
            </div>
            <div className="card">
              <p className="muted">Running for</p>
              <p className="text-2xl font-semibold">{duration(stats.uptime_s)}</p>
            </div>
          </div>
          <div className="card">
            <p className="mb-2 font-semibold">Busiest hours</p>
            <div className="h-56">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={hours}>
                  <XAxis dataKey="hour" tickFormatter={(h) => `${h}:00`} interval={2} fontSize={12} />
                  <YAxis allowDecimals={false} fontSize={12} width={32} />
                  <Tooltip formatter={(v) => [v, 'Encounters']} labelFormatter={(h) => `${h}:00`} />
                  <Bar dataKey="encounters" fill="#111317" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
