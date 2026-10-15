import { useState, type FormEvent } from 'react';
import { api, type TestResult } from '../api';

const STATUS = {
  answered: ['Answered', 'bg-ink text-white'],
  unmatched: ['No match: the kiosk says it does not have that information', 'bg-accent text-white'],
  offline: ['Language model unreachable: the kiosk shows the touch menu', 'bg-neutral-300'],
} as const;

export default function TestQuestion() {
  const [question, setQuestion] = useState('');
  const [result, setResult] = useState<TestResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function ask(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError('');
    try {
      setResult(await api.post<TestResult>('/api/kb/test', { question }));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <h2 className="text-xl font-semibold">Test a question</h2>
      <form className="card flex gap-2" onSubmit={ask}>
        <input className="input" value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="What would a visitor ask?" />
        <button className="btn" disabled={busy || !question.trim()}>{busy ? 'Asking…' : 'Ask'}</button>
      </form>
      {error && <p className="font-semibold text-accent">{error}</p>}
      {result && (
        <>
          <div className="card space-y-2">
            <span className={`inline-block rounded-full px-3 py-1 text-sm font-semibold ${STATUS[result.status][1]}`}>{STATUS[result.status][0]}</span>
            {result.answer && <p className="text-lg">{result.answer}</p>}
          </div>
          <div className="card space-y-3">
            <p className="font-semibold">Closest matches</p>
            <p className="muted">Matches below the line (score {result.threshold.toFixed(2)}) are not sent to the language model.</p>
            {result.hits.map((h, i) => (
              <div key={i} className="space-y-1">
                <div className="relative h-2 rounded-full bg-neutral-100">
                  <div className={`h-2 rounded-full ${h.score >= result.threshold ? 'bg-ink' : 'bg-neutral-400'}`} style={{ width: `${Math.max(0, h.score) * 100}%` }} />
                  <div className="absolute top-[-4px] h-4 w-0.5 bg-accent" style={{ left: `${result.threshold * 100}%` }} />
                </div>
                <p className="text-sm"><span className="font-semibold">{h.score.toFixed(2)} · {h.title}</span>{h.heading && ` · ${h.heading}`}</p>
                <p className="muted line-clamp-3">{h.text}</p>
              </div>
            ))}
            {result.hits.length === 0 && <p className="muted">The knowledge base is empty.</p>}
          </div>
        </>
      )}
    </div>
  );
}
