import { useEffect, useState } from 'react';
import { api, duration, type Health as H } from '../api';

function Item({ label, value, bad = false }: { label: string; value: string; bad?: boolean }) {
  return (
    <div className="card">
      <p className="muted">{label}</p>
      <p className={`text-xl font-semibold ${bad ? 'text-accent' : ''}`}>{value}</p>
    </div>
  );
}

const yesNo = (v: boolean | null, yes: string, no: string) => (v == null ? 'Checking…' : v ? yes : no);

export default function Health() {
  const [h, setH] = useState<H | null>(null);
  const [message, setMessage] = useState('');

  useEffect(() => {
    let live = true;
    const load = () => api.get<H>('/api/health/detail').then((d) => live && setH(d)).catch((e) => live && setMessage(e.message));
    load();
    const t = window.setInterval(load, 5000);
    return () => { live = false; window.clearInterval(t); };
  }, []);

  async function act(kind: 'restart' | 'shutdown') {
    const text = kind === 'restart'
      ? 'Restart the kiosk services? The screen will be blank for about 20 seconds.'
      : 'Shut down the kiosk? Wait 30 seconds before unplugging the power.';
    if (!window.confirm(text)) return;
    try {
      await api.post(`/api/system/${kind}`);
      setMessage(kind === 'restart' ? 'Restarting…' : 'Shutting down. Unplug after 30 seconds.');
    } catch (e) {
      setMessage(e instanceof Error ? e.message : String(e));
    }
  }

  if (!h) return <p className="muted">{message || 'Loading…'}</p>;
  const temp = h.cpu_temp_c;
  return (
    <div className="space-y-4">
      <h2 className="text-xl font-semibold">Health</h2>
      {message && <p className="font-semibold">{message}</p>}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <Item label="CPU temperature" value={temp != null ? `${temp.toFixed(0)} °C` : 'n/a'} bad={temp != null && temp >= 75} />
        <Item label="CPU load (1 min)" value={h.load1 != null ? h.load1.toFixed(2) : 'n/a'} />
        <Item label="Memory" value={h.mem_used_mb != null ? `${(h.mem_used_mb / 1024).toFixed(1)} of ${(h.mem_total_mb! / 1024).toFixed(1)} GB` : 'n/a'} />
        <Item label="Internet" value={yesNo(h.internet_ok, 'Connected', 'Offline')} bad={h.internet_ok === false} />
        <Item label="Last reply time" value={h.llm_last_reply_ms != null ? `${(h.llm_last_reply_ms / 1000).toFixed(1)} s` : '–'} />
        <Item label="Camera" value={h.camera_ok ? 'Working' : 'Not working'} bad={!h.camera_ok} />
        <Item label="Microphone" value={h.mic_ok ? 'Working' : 'Not working'} bad={!h.mic_ok} />
        <Item label="Running for" value={duration(h.uptime_s)} />
        <Item label="Service restarts" value={h.restarts != null ? String(h.restarts) : 'n/a'} />
      </div>
      <div className="card">
        <p className="mb-2 font-semibold">Recent problems</p>
        {h.errors.length === 0 ? (
          <p className="muted">None.</p>
        ) : (
          <ul className="space-y-1 text-sm">
            {h.errors.map((e, i) => (
              <li key={i}>
                <span className="muted">{new Date(e.ts * 1000).toLocaleTimeString()} </span>
                <span className={e.level === 'ERROR' ? 'font-semibold text-accent' : ''}>{e.message}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="flex flex-wrap gap-3">
        <button className="btn-secondary" disabled={h.dev} onClick={() => act('restart')}>Restart services</button>
        <button className="btn-danger" disabled={h.dev} onClick={() => act('shutdown')}>Shut down</button>
        {h.dev && <p className="muted self-center">Disabled in dev mode.</p>}
      </div>
    </div>
  );
}
