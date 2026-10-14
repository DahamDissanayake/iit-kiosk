// WebSocket link to kiosk-core on the same host. Reconnects every 2 s.
export function connectBridge(onMessage) {
  let ws = null;
  const url = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`;

  function open() {
    ws = new WebSocket(url);
    ws.onmessage = (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch { return; }
      onMessage(msg);
    };
    ws.onclose = () => {
      ws = null;
      setTimeout(open, 2000);
    };
    ws.onerror = () => {};
  }
  open();

  return {
    send(obj) {
      if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
    },
  };
}
