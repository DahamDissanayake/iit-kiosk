import { t } from './strings.js';
import { AudioEngine } from './audio.js';
import { startBot } from './bot.js';
import { connectBridge } from './bridge.js';
import { startTicker, bindTalk, bindKids, bindGear, bindSheet } from './controls.js';
import { bindDev } from './dev.js';

// The staff dashboard (M5) is served by kiosk-core on port 8080.
const ADMIN_URL = 'http://localhost:8080/';
const GEAR_HOLD_S = 3;

const root = document.getElementById('root');
const bubble = document.getElementById('bubble');
const privacy = document.getElementById('privacyText');

const audio = new AudioEngine();
const bot = startBot(root, audio);
const bridge = connectBridge(handle);
const send = (msg) => bridge.send(msg);
audio.onDrained = (id) => send({ type: 'speech.ended', id });

const refreshTalk = bindTalk(document.getElementById('talk'), document.getElementById('talkLabel'), root, send);
const kids = bindKids(document.getElementById('kids'), send);
const sheet = bindSheet(document.getElementById('sheet'), send);
const dev = bindDev(document.getElementById('dev'), root, send);
bindGear(document.getElementById('gear'), GEAR_HOLD_S, () => { location.href = ADMIN_URL; });
startTicker(document.getElementById('ticker'));
updatePrivacy();
refreshTalk();

let loadedVersion = null;

function say(text, partial = false) {
  if (!text) {
    bubble.classList.add('hide');
    return;
  }
  bubble.textContent = text;
  bubble.classList.toggle('partial', partial);
  bubble.classList.remove('hide');
}

function setState(state, text) {
  root.dataset.state = state;
  if (text !== undefined) say(text);
  else if (state === 'listening') say(t('listening'));
  else if (['idle', 'attentive', 'thinking', 'farewell'].includes(state)) say(null);
  if (state === 'idle') sheet.hide();
  audio.duckFor(state);
  refreshTalk();
}

function updatePrivacy() {
  privacy.textContent = root.dataset.camera === 'off' ? t('privacyOff') : t('privacy');
}

function handle(m) {
  switch (m.type) {
    case 'state': setState(m.state, m.text); break;
    case 'say': say(m.text); break;
    case 'stt': say(m.text, !m.final); break;
    case 'lookAt': bot.lookAt(m.x, m.y); break;
    case 'audio': audio.playPCM16(m.data, m.sampleRate || 22050, m.id); break;
    case 'stopAudio': audio.stop(); break;
    case 'camera': root.dataset.camera = m.ok ? 'on' : 'off'; updatePrivacy(); break;
    case 'music': audio.setMusic(m.url, m.volume); break;
    case 'menu': if (m.show) sheet.show(m.items || []); else sheet.hide(); break;
    case 'kids': kids.set(m.value); break;
    case 'dev': dev.show(m.enabled); break;
    case 'version':
      if (loadedVersion && loadedVersion !== m.version) location.reload();
      loadedVersion = m.version;
      break;
  }
}

// On the kiosk, Chromium runs with --autoplay-policy=no-user-gesture-required.
// On a laptop, the first touch unlocks audio.
addEventListener('pointerdown', () => audio.ensure(), { once: true });

window.kiosk = { setState, say, lookAt: bot.lookAt, audio, get state() { return root.dataset.state; } };
