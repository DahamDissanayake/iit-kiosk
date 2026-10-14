// Per-frame character animation: the mouth light bar follows speech loudness,
// the eyes blink and follow the visitor. CSS handles everything else.
const clamp = (v) => Math.max(-1, Math.min(1, Number(v) || 0));

export function startBot(root, audio) {
  const mouth = root.querySelector('#mouth');
  const eyes = root.querySelector('#eyes');
  const eyeL = root.querySelector('#eyeL');
  const eyeR = root.querySelector('#eyeR');
  const meter = root.querySelector('#devMeter');
  let level = 0;
  let blink = 1;
  let nextBlink = performance.now() + 2500;
  const look = { x: 0, y: 0 };
  let target = { x: 0, y: 0 };

  function frame(now) {
    // Fast attack, slower release reads as natural speech.
    const want = audio.level();
    level += (want - level) * (want > level ? 0.55 : 0.22);
    const w = 20 + level * 56;
    const h = 4 + level * 6;
    mouth.setAttribute('x', (200 - w / 2).toFixed(1));
    mouth.setAttribute('width', w.toFixed(1));
    mouth.setAttribute('y', (206 - h / 2).toFixed(1));
    mouth.setAttribute('height', h.toFixed(1));
    mouth.setAttribute('opacity', (level > 0.02 ? 0.35 + level * 0.65 : 0).toFixed(2));
    if (meter) meter.style.width = `${Math.round(level * 100)}%`;

    if (now > nextBlink) {
      blink = 0.08;
      nextBlink = now + 2200 + Math.random() * 3500;
    }
    blink += (1 - blink) * 0.25;

    const state = root.dataset.state;
    const goal = state === 'thinking' ? { x: 0.5, y: -0.7 } : state === 'idle' ? { x: 0, y: 0 } : target;
    look.x += (goal.x - look.x) * 0.08;
    look.y += (goal.y - look.y) * 0.08;
    eyes.setAttribute('transform', `translate(${(look.x * 14).toFixed(1)} ${(look.y * 8).toFixed(1)})`);
    const ry = 13 * blink * (state === 'listening' ? 1.15 : 1);
    eyeL.setAttribute('ry', ry.toFixed(1));
    eyeR.setAttribute('ry', ry.toFixed(1));
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);

  return {
    lookAt(x, y = 0) {
      target = { x: clamp(x), y: clamp(y) };
    },
  };
}
