// WebSocket 전송. 재연결 정책은 session.js 가 onClose 에서 정한다.
let ws = null;
let _intentionalClose = false;

export function send(obj) {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
}

export function openSocket(url, { onOpen, onClose, onMessage }) {
  if (ws) {
    _intentionalClose = true;
    ws.close();
    ws = null;
  }
  ws = new WebSocket(url);
  ws.addEventListener('open', onOpen);
  ws.addEventListener('close', (ev) => {
    if (_intentionalClose) { _intentionalClose = false; return; }
    ws = null;
    onClose(ev);
  });
  ws.addEventListener('error', () => ws?.close());
  ws.addEventListener('message', (e) => {
    let msg;
    try { msg = JSON.parse(e.data); } catch { return; }
    onMessage(msg);
  });
}
