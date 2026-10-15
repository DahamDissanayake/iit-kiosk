import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { api, type Source, type SourceDetail, type SourceKind, type SourceList } from '../api';
import QaEditor, { type Pair } from '../QaEditor';

const KIND_LABEL: Record<SourceKind, string> = { text: 'Text', qa: 'Q&A', file: 'File', menu: 'Touch menu' };

function AddSource({ busy, onSubmit }: { busy: boolean; onSubmit: (data: FormData) => Promise<boolean> }) {
  const [kind, setKind] = useState<SourceKind>('text');
  const [title, setTitle] = useState('');
  const [text, setText] = useState('');
  const [pairs, setPairs] = useState<Pair[]>([['', '']]);
  const [file, setFile] = useState<File | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const data = new FormData();
    data.append('kind', kind);
    data.append('title', title);
    if (kind === 'text' || kind === 'menu') data.append('text', text);
    if (kind === 'qa') data.append('pairs', JSON.stringify(pairs.filter(([q, a]) => q.trim() && a.trim())));
    if (kind === 'file' && file) data.append('file', file);
    if (await onSubmit(data)) { setTitle(''); setText(''); setPairs([['', '']]); setFile(null); }
  }

  return (
    <form className="card space-y-3" onSubmit={submit}>
      <p className="font-semibold">Add content</p>
      <div className="flex flex-wrap gap-1">
        {(Object.keys(KIND_LABEL) as SourceKind[]).map((k) => (
          <button type="button" key={k} className={`tab ${kind === k ? 'tab-active' : ''}`} onClick={() => setKind(k)}>
            {k === 'file' ? 'Upload a file' : k === 'menu' ? 'Touch menu item' : k === 'qa' ? 'Questions and answers' : 'Paste text'}
          </button>
        ))}
      </div>
      <div>
        <label className="label">{kind === 'menu' ? 'Button label (the question)' : 'Title'}</label>
        <input className="input" value={title} onChange={(e) => setTitle(e.target.value)} placeholder={kind === 'file' ? 'Defaults to the file name' : ''} />
      </div>
      {(kind === 'text' || kind === 'menu') && (
        <div>
          <label className="label">{kind === 'menu' ? 'Answer the kiosk reads aloud' : 'Text (Markdown headings like "# Fees" are kept with their text)'}</label>
          <textarea className="input" rows={kind === 'menu' ? 3 : 8} value={text} onChange={(e) => setText(e.target.value)} />
        </div>
      )}
      {kind === 'qa' && <QaEditor pairs={pairs} onChange={setPairs} />}
      {kind === 'file' && (
        <div>
          <label className="label">PDF, Word (.docx), Markdown or text file, up to 20 MB</label>
          <input type="file" accept=".pdf,.docx,.md,.markdown,.txt" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </div>
      )}
      <button className="btn" disabled={busy || (kind === 'file' && !file)}>{busy ? 'Working…' : 'Add'}</button>
    </form>
  );
}

function EditSource({ source, busy, onClose, onSave }: {
  source: SourceDetail; busy: boolean; onClose: () => void; onSave: (patch: object) => void;
}) {
  const [title, setTitle] = useState(source.title);
  const [text, setText] = useState(source.text ?? '');
  const [pairs, setPairs] = useState<Pair[]>(source.pairs ?? [['', '']]);
  const editable = source.kind !== 'file';
  return (
    <div className="fixed inset-0 z-20 flex items-end justify-center bg-black/30 p-4 sm:items-center">
      <div className="card max-h-[90vh] w-full max-w-2xl space-y-3 overflow-y-auto">
        <p className="text-lg font-semibold">Edit {KIND_LABEL[source.kind].toLowerCase()}</p>
        <div>
          <label className="label">{source.kind === 'menu' ? 'Button label' : 'Title'}</label>
          <input className="input" value={title} onChange={(e) => setTitle(e.target.value)} />
        </div>
        {source.kind === 'qa' && <QaEditor pairs={pairs} onChange={setPairs} />}
        {(source.kind === 'text' || source.kind === 'menu') && (
          <textarea className="input" rows={10} value={text} onChange={(e) => setText(e.target.value)} />
        )}
        {!editable && (
          <>
            <p className="muted">Uploaded files can be renamed here. To change the content, delete it and upload the new file.</p>
            <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded-xl bg-neutral-50 p-3 text-sm">{source.text}</pre>
          </>
        )}
        <div className="flex justify-end gap-2">
          <button className="btn-secondary" onClick={onClose}>Cancel</button>
          <button
            className="btn"
            disabled={busy}
            onClick={() =>
              onSave(
                source.kind === 'qa'
                  ? { title, pairs: pairs.filter(([q, a]) => q.trim() && a.trim()) }
                  : editable ? { title, text } : { title },
              )
            }
          >
            Save
          </button>
        </div>
      </div>
    </div>
  );
}

export default function Knowledge() {
  const [list, setList] = useState<SourceList | null>(null);
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState<SourceDetail | null>(null);

  const load = useCallback(() => api.get<SourceList>('/api/kb/sources').then(setList).catch((e) => setMessage(e.message)), []);
  useEffect(() => { void load(); }, [load]);

  async function run(done: string, fn: () => Promise<unknown>): Promise<boolean> {
    setBusy(true);
    setMessage('');
    try {
      await fn();
      setMessage(done);
      await load();
      return true;
    } catch (e) {
      setMessage(e instanceof Error ? e.message : String(e));
      return false;
    } finally {
      setBusy(false);
    }
  }

  const toggle = (s: Source) => run(s.enabled ? 'Turned off.' : 'Turned on.', () => api.patch(`/api/kb/sources/${s.id}`, { enabled: !s.enabled }));
  const remove = (s: Source) => window.confirm(`Delete "${s.title}"? This cannot be undone.`) && run('Deleted.', () => api.del(`/api/kb/sources/${s.id}`));
  const reindex = () => window.confirm('Re-index everything? This can take a few minutes.') && run('Re-indexed.', () => api.post('/api/kb/reindex'));
  const edit = (s: Source) => api.get<SourceDetail>(`/api/kb/sources/${s.id}`).then(setEditing).catch((e) => setMessage(e.message));

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold">Knowledge base</h2>
        <button className="btn-secondary" disabled={busy} onClick={reindex}>Re-index all</button>
      </div>
      {list?.needs_reindex && (
        <p className="card border-accent font-semibold text-accent">The embedding model changed. Re-index before the kiosk can answer.</p>
      )}
      {message && <p className="font-semibold" role="status">{message}</p>}
      <AddSource busy={busy} onSubmit={(data) => run('Added. It is live for the next question.', () => api.form('/api/kb/sources', data))} />
      <div className="card overflow-x-auto p-0">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-neutral-200 text-neutral-500">
            <tr>
              <th className="p-3">Title</th><th className="p-3">Type</th><th className="p-3">Chunks</th>
              <th className="p-3">Added</th><th className="p-3">On</th><th className="p-3" />
            </tr>
          </thead>
          <tbody>
            {list?.sources.map((s) => (
              <tr key={s.id} className="border-b border-neutral-100 last:border-0">
                <td className="p-3 font-semibold">{s.title}</td>
                <td className="p-3">{KIND_LABEL[s.kind]}</td>
                <td className="p-3">{s.chunk_count}</td>
                <td className="p-3">{new Date(s.created_at).toLocaleDateString()}</td>
                <td className="p-3">
                  <button
                    role="switch"
                    aria-checked={s.enabled}
                    disabled={busy}
                    onClick={() => toggle(s)}
                    className={`h-7 w-12 rounded-full p-1 transition ${s.enabled ? 'bg-ink' : 'bg-neutral-300'}`}
                  >
                    <span className={`block h-5 w-5 rounded-full bg-white transition ${s.enabled ? 'translate-x-5' : ''}`} />
                  </button>
                </td>
                <td className="space-x-3 whitespace-nowrap p-3 text-right">
                  <button className="font-semibold" onClick={() => edit(s)}>Edit</button>
                  <button className="font-semibold text-accent" onClick={() => remove(s)}>Delete</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {list?.sources.length === 0 && <p className="muted p-4">No content yet.</p>}
      </div>
      {editing && (
        <EditSource
          source={editing}
          busy={busy}
          onClose={() => setEditing(null)}
          onSave={(patch) => run('Saved.', () => api.patch(`/api/kb/sources/${editing.id}`, patch)).then((ok) => ok && setEditing(null))}
        />
      )}
    </div>
  );
}
