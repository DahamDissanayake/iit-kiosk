// Dev panel: fake visitors, typed questions, forced faults. Core ignores these
// messages unless it runs with --dev. "Preview state" only changes this page.
const STATES = ['idle', 'attentive', 'greeting', 'listening', 'thinking', 'speaking', 'farewell'];

export function bindDev(panel, root, send) {
  let enabled = new URLSearchParams(location.search).has('dev');

  for (const b of panel.querySelectorAll('[data-dev]')) {
    b.addEventListener('click', () => {
      const action = b.dataset.dev;
      if (action === 'camera' || action === 'internet') {
        const ok = b.dataset.ok === 'true';
        send({ type: 'dev', action, ok });
        b.dataset.ok = String(!ok);
        b.textContent = `${action === 'camera' ? 'Camera' : 'Internet'} ${ok ? 'fail' : 'restore'}`;
        return;
      }
      send({ type: 'dev', action });
    });
  }

  panel.querySelector('#devAsk').addEventListener('submit', (e) => {
    e.preventDefault();
    const input = panel.querySelector('#devQuestion');
    const text = input.value.trim();
    if (!text) return;
    send({ type: 'dev', action: 'ask', text });
    input.value = '';
  });

  const row = panel.querySelector('#devStates');
  for (const s of STATES) {
    const b = document.createElement('button');
    b.type = 'button';
    b.textContent = s;
    b.addEventListener('click', () => { root.dataset.state = s; });
    row.append(b);
  }

  addEventListener('keydown', (e) => {
    if (enabled && (e.key === 'd' || e.key === 'D') && e.target.tagName !== 'INPUT') panel.hidden = !panel.hidden;
  });

  return {
    show(on) {
      enabled = enabled || Boolean(on);
      panel.hidden = !enabled;
    },
  };
}
