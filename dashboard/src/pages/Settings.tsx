import { useEffect, useState, type FormEvent } from 'react';
import { api, type Settings as S } from '../api';
import ZonePreview from '../ZonePreview';

function Slider({ label, value, min, max, step, show, onChange }: {
  label: string; value: number; min: number; max: number; step: number; show: (v: number) => string; onChange: (v: number) => void;
}) {
  return (
    <label className="block">
      <span className="label flex justify-between"><span>{label}</span><span className="font-normal">{show(value)}</span></span>
      <input type="range" className="w-full accent-ink" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} />
    </label>
  );
}

function Toggle({ label, hint, checked, onChange }: { label: string; hint?: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex items-start justify-between gap-4">
      <span><span className="font-semibold">{label}</span>{hint && <span className="muted block">{hint}</span>}</span>
      <button type="button" role="switch" aria-checked={checked} onClick={() => onChange(!checked)}
        className={`mt-1 h-7 w-12 shrink-0 rounded-full p-1 transition ${checked ? 'bg-ink' : 'bg-neutral-300'}`}>
        <span className={`block h-5 w-5 rounded-full bg-white transition ${checked ? 'translate-x-5' : ''}`} />
      </button>
    </label>
  );
}

const pct = (v: number) => `${Math.round(v * 100)}%`;

function ChangePin() {
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [repeat, setRepeat] = useState('');
  const [message, setMessage] = useState('');

  async function save(e: FormEvent) {
    e.preventDefault();
    if (next !== repeat) return setMessage('The new PINs do not match.');
    try {
      await api.post('/api/auth/pin', { current, new: next });
      setMessage('PIN changed.');
      setCurrent(''); setNext(''); setRepeat('');
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err));
    }
  }

  const field = (label: string, value: string, set: (v: string) => void) => (
    <label className="block">
      <span className="label">{label}</span>
      <input className="input" inputMode="numeric" type="password" maxLength={6} value={value} onChange={(e) => set(e.target.value.replace(/\D/g, ''))} />
    </label>
  );
  return (
    <form className="card space-y-3" onSubmit={save}>
      <p className="font-semibold">Change PIN</p>
      {field('Current PIN', current, setCurrent)}
      {field('New 6-digit PIN', next, setNext)}
      {field('Repeat new PIN', repeat, setRepeat)}
      {message && <p className="font-semibold">{message}</p>}
      <button className="btn" disabled={current.length !== 6 || next.length !== 6}>Change PIN</button>
    </form>
  );
}

export default function Settings() {
  const [s, setS] = useState<S | null>(null);
  const [saved, setSaved] = useState<S | null>(null);
  const [message, setMessage] = useState('');

  useEffect(() => { api.get<S>('/api/settings').then((v) => { setS(v); setSaved(v); }).catch((e) => setMessage(e.message)); }, []);
  if (!s) return <p className="muted">{message || 'Loading…'}</p>;

  const set = <K extends keyof S>(key: K, value: S[K]) => { setS({ ...s, [key]: value }); setMessage(''); };
  const dirty = JSON.stringify(s) !== JSON.stringify(saved);

  async function save() {
    try {
      const v = await api.put<S>('/api/settings', s);
      setS(v); setSaved(v); setMessage('Saved.');
    } catch (e) {
      setMessage(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div className="space-y-4 pb-24">
      <h2 className="text-xl font-semibold">Settings</h2>

      <section className="card space-y-4">
        <p className="font-semibold">Sound</p>
        <Slider label="Speaker volume" value={s.volume} min={0} max={1} step={0.05} show={pct} onChange={(v) => set('volume', v)} />
        <Toggle label="Background music" checked={s.music_on} onChange={(v) => set('music_on', v)} />
        <Slider label="Music volume" value={s.music_volume} min={0} max={1} step={0.05} show={pct} onChange={(v) => set('music_volume', v)} />
        <Toggle label="Quiet mode" hint="No music, and the voice at half volume." checked={s.quiet_mode} onChange={(v) => set('quiet_mode', v)} />
      </section>

      <section className="card space-y-4">
        <p className="font-semibold">Visitors</p>
        <Toggle label="Start in kids mode" hint="Simple, encouraging language for every new visitor." checked={s.kids_default} onChange={(v) => set('kids_default', v)} />
        <Slider label="Wait before greeting the next visitor" value={s.greet_cooldown_s} min={5} max={120} step={5} show={(v) => `${v} s`} onChange={(v) => set('greet_cooldown_s', v)} />
      </section>

      <section className="card space-y-4">
        <p className="font-semibold">Detection zone</p>
        <ZonePreview band={s.centre_band} minFrac={s.min_box_height_frac} mirror={s.mirror} />
        <Slider label="How close (minimum person height)" value={s.min_box_height_frac} min={0.05} max={0.9} step={0.01} show={pct} onChange={(v) => set('min_box_height_frac', v)} />
        <Slider label="How central (width of the zone)" value={s.centre_band} min={0.1} max={1} step={0.05} show={pct} onChange={(v) => set('centre_band', v)} />
        <Slider label="Approach sensitivity (growth needed)" value={s.approach_growth} min={0.02} max={0.6} step={0.01} show={pct} onChange={(v) => set('approach_growth', v)} />
        <Slider label="Standing time before greeting" value={s.dwell_s} min={0.5} max={5} step={0.1} show={(v) => `${v.toFixed(1)} s`} onChange={(v) => set('dwell_s', v)} />
        <Toggle label="Mirror eye direction" hint="Turn on if the eyes look away from the visitor." checked={s.mirror} onChange={(v) => set('mirror', v)} />
      </section>

      <section className="card space-y-4">
        <p className="font-semibold">Answers</p>
        <Slider label="Match threshold" value={s.min_score} min={0} max={1} step={0.01} show={(v) => v.toFixed(2)} onChange={(v) => set('min_score', v)} />
        <p className="muted">Higher means fewer but safer answers. Check changes on "Test a question".</p>
      </section>

      <section className="card space-y-4">
        <p className="font-semibold">Privacy</p>
        <Toggle
          label="Keep unmatched questions"
          hint="Stores the words of questions the kiosk could not answer, for 30 days. Only turn on with IIT's agreement; the privacy notice will say so."
          checked={s.log_unmatched_questions}
          onChange={(v) => set('log_unmatched_questions', v)}
        />
      </section>

      <ChangePin />

      <div className="fixed inset-x-0 bottom-0 border-t border-neutral-200 bg-white p-3">
        <div className="mx-auto flex max-w-5xl items-center justify-end gap-3">
          {message && <p className="font-semibold">{message}</p>}
          <button className="btn-secondary" disabled={!dirty} onClick={() => { setS(saved); setMessage(''); }}>Undo</button>
          <button className="btn" disabled={!dirty} onClick={save}>Save settings</button>
        </div>
      </div>
    </div>
  );
}
