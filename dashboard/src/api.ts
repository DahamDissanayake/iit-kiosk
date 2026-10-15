export class ApiError extends Error {
  constructor(public status: number, public body: any) {
    const d = body?.detail;
    super(typeof d === 'string' ? d : d?.reason ?? `Request failed (${status})`);
  }
}

async function request<T>(method: string, path: string, body?: unknown, form = false): Promise<T> {
  const res = await fetch(path, {
    method,
    credentials: 'same-origin',
    headers: body !== undefined && !form ? { 'Content-Type': 'application/json' } : undefined,
    body: body === undefined ? undefined : form ? (body as FormData) : JSON.stringify(body),
  });
  const data = res.headers.get('content-type')?.includes('json') ? await res.json() : null;
  if (!res.ok) {
    if (res.status === 401 && !path.endsWith('/login')) window.dispatchEvent(new Event('kiosk:unauthorized'));
    throw new ApiError(res.status, data);
  }
  return data as T;
}

export const api = {
  get: <T>(path: string) => request<T>('GET', path),
  post: <T>(path: string, body?: unknown) => request<T>('POST', path, body ?? {}),
  put: <T>(path: string, body: unknown) => request<T>('PUT', path, body),
  patch: <T>(path: string, body: unknown) => request<T>('PATCH', path, body),
  del: <T>(path: string) => request<T>('DELETE', path),
  form: <T>(path: string, data: FormData) => request<T>('POST', path, data, true),
};

export const ON_KIOSK = ['localhost', '127.0.0.1'].includes(location.hostname);
export const KIOSK_URL = 'http://localhost:8765/';

export type Range = 'today' | 'all';
export interface Stats {
  counts: Record<string, number>;
  avg_conversation_s: number | null;
  avg_reply_ms: number | null;
  uptime_s: number;
}
export interface HourBucket { hour: number; encounters: number }
export type SourceKind = 'text' | 'qa' | 'file' | 'menu';
export interface Source {
  id: number; title: string; kind: SourceKind; filename: string | null; enabled: boolean;
  chunk_count: number; created_at: string; updated_at: string;
}
export interface SourceList { sources: Source[]; needs_reindex: boolean }
export interface SourceDetail extends Source { text?: string; pairs?: [string, string][] }
export interface Hit { title: string; heading: string; text: string; score: number }
export interface TestResult { status: 'answered' | 'unmatched' | 'offline'; answer: string | null; hits: Hit[]; threshold: number }
export interface Settings {
  volume: number; music_on: boolean; music_volume: number; quiet_mode: boolean;
  kids_default: boolean; greet_cooldown_s: number; dwell_s: number;
  min_box_height_frac: number; centre_band: number; approach_growth: number; mirror: boolean;
  log_unmatched_questions: boolean; min_score: number;
}
export interface Health {
  cpu_temp_c: number | null; load1: number | null; mem_used_mb: number | null; mem_total_mb: number | null;
  internet_ok: boolean | null; llm_last_reply_ms: number | null; camera_ok: boolean; mic_ok: boolean;
  uptime_s: number; restarts: number | null; dev: boolean;
  errors: { ts: number; level: string; logger: string; message: string }[];
}
export interface Preview { w: number; h: number; boxes: number[][] }

export function duration(s: number): string {
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
  return h ? `${h} h ${m} min` : `${m} min`;
}
