// Speech goes through the analyser (it drives the mouth). Music has its own gain path,
// so it never moves the mouth (baseline 4.4).
export class AudioEngine {
  constructor() {
    this.ctx = null;
    this.analyser = null;
    this.buf = null;
    this.nextTime = 0;
    this.live = new Set();
    this.lastId = null;
    this.onDrained = () => {};
    this.musicEl = null;
    this.musicGain = null;
    this.musicBase = 0.25;
  }

  ensure() {
    if (!this.ctx) {
      this.ctx = new AudioContext();
      this.analyser = this.ctx.createAnalyser();
      this.analyser.fftSize = 1024;
      this.analyser.connect(this.ctx.destination);
      this.buf = new Float32Array(this.analyser.fftSize);
    }
    if (this.ctx.state === 'suspended') this.ctx.resume();
    return this.ctx;
  }

  // Queue one base64 PCM16 mono chunk right after the previous one.
  playPCM16(base64, sampleRate, id) {
    const ctx = this.ensure();
    const bin = atob(base64);
    const n = bin.length >> 1;
    const samples = new Float32Array(n);
    for (let i = 0; i < n; i++) {
      let v = bin.charCodeAt(2 * i) | (bin.charCodeAt(2 * i + 1) << 8);
      if (v >= 0x8000) v -= 0x10000;
      samples[i] = v / 32768;
    }
    const buffer = ctx.createBuffer(1, n, sampleRate);
    buffer.copyToChannel(samples, 0);
    const src = ctx.createBufferSource();
    src.buffer = buffer;
    src.connect(this.analyser);
    this.nextTime = Math.max(this.nextTime, ctx.currentTime + 0.05);
    src.start(this.nextTime);
    this.nextTime += buffer.duration;
    if (id !== undefined) this.lastId = id;
    this.live.add(src);
    src.onended = () => {
      this.live.delete(src);
      if (this.live.size === 0) {
        this.nextTime = 0;
        this.onDrained(this.lastId);
      }
    };
  }

  stop() {
    for (const src of this.live) {
      src.onended = null;
      try { src.stop(); } catch { /* already stopped */ }
    }
    this.live.clear();
    this.nextTime = 0;
  }

  // Speech loudness 0..1 for the mouth.
  level() {
    if (!this.analyser || this.live.size === 0) return 0;
    this.analyser.getFloatTimeDomainData(this.buf);
    let sum = 0;
    for (const v of this.buf) sum += v * v;
    const rms = Math.sqrt(sum / this.buf.length);
    return Math.min(1, Math.max(0, (rms - 0.012) * 7));
  }

  setMusic(url, volume = this.musicBase) {
    const ctx = this.ensure();
    this.musicBase = volume;
    if (this.musicEl && url && this.musicEl.dataset.url === url) return; // volume change only
    if (this.musicEl) this.musicEl.pause();
    this.musicEl = null;
    if (!url) return;
    if (!this.musicGain) {
      this.musicGain = ctx.createGain();
      this.musicGain.connect(ctx.destination);
    }
    this.musicEl = new Audio(url);
    this.musicEl.dataset.url = url;
    this.musicEl.loop = true;
    ctx.createMediaElementSource(this.musicEl).connect(this.musicGain);
    this.musicGain.gain.value = this.musicBase;
    this.musicEl.play().catch(() => {});
  }

  // Full volume in Idle, 35% when someone is in the zone, silent while talking or listening.
  duckFor(state) {
    if (!this.musicGain) return;
    const target = state === 'idle' ? this.musicBase : state === 'attentive' ? this.musicBase * 0.35 : 0;
    const secs = state === 'idle' ? 2.5 : state === 'attentive' ? 0.6 : 0.3;
    const gain = this.musicGain.gain;
    const now = this.ctx.currentTime;
    gain.cancelScheduledValues(now);
    gain.setValueAtTime(gain.value, now);
    gain.linearRampToValueAtTime(target, now + secs);
  }
}
