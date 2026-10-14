import { t } from './strings.js';

// Rotating idle line: prompt, messages, and the Idea -> Launch journey.
export function startTicker(el) {
  const messages = t('ticker');
  const items = [{ prompt: true }, { text: messages[0] }, { journey: true }, ...messages.slice(1).map((text) => ({ text }))];
  let i = 0;
  let stepTimer = null;

  function render() {
    clearInterval(stepTimer);
    const item = items[i % items.length];
    el.replaceChildren();
    if (item.prompt) {
      const span = document.createElement('span');
      span.className = 'prompt';
      span.textContent = t('prompt');
      el.append(span);
    } else if (item.journey) {
      const row = document.createElement('div');
      row.className = 'journey';
      t('journey').forEach((word, k) => {
        if (k) {
          const arrow = document.createElement('em');
          arrow.textContent = '→';
          row.append(arrow);
        }
        const step = document.createElement('span');
        step.textContent = word;
        row.append(step);
      });
      el.append(row);
      const steps = row.querySelectorAll('span');
      let k = 0;
      steps[0].classList.add('on');
      stepTimer = setInterval(() => {
        k = Math.min(k + 1, steps.length - 1);
        steps[k].classList.add('on');
      }, 1200);
    } else {
      el.textContent = item.text;
    }
  }

  render();
  setInterval(() => {
    el.classList.add('fade');
    setTimeout(() => {
      i++;
      render();
      el.classList.remove('fade');
    }, 500);
  }, 6500);
}

// "Tap to talk" turns into "Stop" while the bot is talking or thinking.
export function bindTalk(btn, label, root, send) {
  const busy = () => ['greeting', 'thinking', 'speaking'].includes(root.dataset.state);
  btn.addEventListener('click', () => send({ type: 'ui', event: busy() ? 'stop' : 'talk' }));
  return function refresh() {
    label.textContent = busy() ? t('stop') : t('talk');
  };
}

export function bindKids(btn, send) {
  btn.textContent = t('kids');
  btn.addEventListener('click', () => {
    const on = btn.getAttribute('aria-pressed') !== 'true';
    btn.setAttribute('aria-pressed', String(on));
    send({ type: 'ui', event: 'kids', value: on });
  });
  return {
    set(on) {
      btn.setAttribute('aria-pressed', String(Boolean(on)));
    },
  };
}

// Opens only after a continuous press, so visitors do not open it by accident.
export function bindGear(btn, holdSeconds, onOpen) {
  let timer = null;
  btn.style.setProperty('--hold', `${holdSeconds}s`);
  const cancel = () => {
    clearTimeout(timer);
    timer = null;
    btn.classList.remove('holding');
  };
  btn.addEventListener('pointerdown', (e) => {
    e.preventDefault();
    btn.setPointerCapture(e.pointerId);
    btn.classList.add('holding');
    timer = setTimeout(() => {
      cancel();
      onOpen();
    }, holdSeconds * 1000);
  });
  for (const type of ['pointerup', 'pointercancel', 'lostpointercapture']) btn.addEventListener(type, cancel);
  btn.addEventListener('contextmenu', (e) => e.preventDefault());
}

export function bindSheet(sheet, send) {
  const grid = sheet.querySelector('#menuItems');
  const close = sheet.querySelector('#sheetClose');
  sheet.querySelector('#sheetTitle').textContent = t('menuTitle');
  close.textContent = t('menuClose');
  const hide = () => {
    sheet.classList.remove('open');
    sheet.setAttribute('aria-hidden', 'true');
  };
  close.addEventListener('click', hide);
  return {
    show(items) {
      grid.replaceChildren(
        ...items.map((item) => {
          const b = document.createElement('button');
          b.type = 'button';
          b.textContent = item.label;
          b.addEventListener('click', () => {
            hide();
            send({ type: 'ui', event: 'menu_item', value: item.id });
          });
          return b;
        }),
      );
      sheet.classList.add('open');
      sheet.setAttribute('aria-hidden', 'false');
    },
    hide,
  };
}
