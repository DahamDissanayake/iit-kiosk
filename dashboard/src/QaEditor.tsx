export type Pair = [string, string];

export default function QaEditor({ pairs, onChange }: { pairs: Pair[]; onChange: (p: Pair[]) => void }) {
  const set = (i: number, j: 0 | 1, v: string) =>
    onChange(pairs.map((p, k) => (k === i ? ((j === 0 ? [v, p[1]] : [p[0], v]) as Pair) : p)));
  return (
    <div className="space-y-3">
      {pairs.map(([q, a], i) => (
        <div key={i} className="grid gap-2 rounded-xl border border-neutral-200 p-3">
          <input className="input" placeholder="Question" value={q} onChange={(e) => set(i, 0, e.target.value)} />
          <textarea className="input" rows={2} placeholder="Answer" value={a} onChange={(e) => set(i, 1, e.target.value)} />
          {pairs.length > 1 && (
            <button type="button" className="justify-self-end text-sm font-semibold text-accent" onClick={() => onChange(pairs.filter((_, k) => k !== i))}>
              Remove
            </button>
          )}
        </div>
      ))}
      <button type="button" className="btn-secondary" onClick={() => onChange([...pairs, ['', '']])}>Add another</button>
    </div>
  );
}
