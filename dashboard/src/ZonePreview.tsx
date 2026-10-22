import { useEffect, useRef, useState } from 'react';
import { api, type Preview } from './api';

// Draws the detection zone and live person boxes. Coordinates only: no camera image exists here.
export default function ZonePreview({ band, minFrac, mirror }: { band: number; minFrac: number; mirror: boolean }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [missing, setMissing] = useState(false);

  useEffect(() => {
    let live = true;
    const load = () =>
      api.get<Preview>('/api/vision/preview')
        .then((p) => { if (live) { setPreview(p); setMissing(false); } })
        .catch(() => live && setMissing(true));
    load();
    const t = window.setInterval(load, 500);
    return () => { live = false; window.clearInterval(t); };
  }, []);

  useEffect(() => {
    const c = canvas.current;
    if (!c) return;
    const g = c.getContext('2d')!;
    const W = c.width, H = c.height;
    g.clearRect(0, 0, W, H);
    g.fillStyle = '#F5F5F5';
    g.fillRect(0, 0, W, H);
    const left = ((1 - band) / 2) * W, right = ((1 + band) / 2) * W;
    g.fillStyle = 'rgba(225,37,27,0.08)';
    g.fillRect(left, 0, right - left, H);
    g.strokeStyle = '#E1251B';
    g.setLineDash([6, 4]);
    g.strokeRect(left, 0, right - left, H);
    g.setLineDash([]);
    g.fillStyle = '#E1251B';
    g.fillRect(6, H - minFrac * H, 6, minFrac * H); // minimum box height guide
    if (!preview) return;
    const sx = W / preview.w, sy = H / preview.h;
    for (const [x1, y1, x2, y2, score] of preview.boxes) {
      const cx = ((x1 + x2) / 2 / preview.w) * 2 - 1;
      const inZone = (y2 - y1) / preview.h >= minFrac && Math.abs(cx) <= band;
      const bx = mirror ? W - x2 * sx : x1 * sx;
      g.strokeStyle = inZone ? '#111317' : '#A3A3A3';
      g.lineWidth = inZone ? 3 : 1.5;
      g.strokeRect(bx, y1 * sy, (x2 - x1) * sx, (y2 - y1) * sy);
      g.fillStyle = g.strokeStyle;
      g.font = '12px system-ui';
      g.fillText(score.toFixed(2), bx + 4, y1 * sy + 14);
    }
  }, [preview, band, minFrac, mirror]);

  return (
    <div className="space-y-2">
      <canvas ref={canvas} width={320} height={240} className="w-full max-w-md rounded-xl border border-neutral-200" />
      <p className="muted">
        {missing
          ? 'No live boxes: the camera service is not running.'
          : 'Black boxes count as in the zone. The red band is "in front"; the red bar on the left is the minimum height. No image is captured or saved.'}
      </p>
    </div>
  );
}
