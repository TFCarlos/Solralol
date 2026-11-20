import assert from 'node:assert/strict';

const endpoint = 'http://127.0.0.1:9230/json/list';
const pages = async () => (await (await fetch(endpoint)).json()).filter(item => item.type === 'page');
const main = (await pages()).find(item => item.url === 'http://127.0.0.1:5173/');
assert.ok(main, 'main Electron renderer must be open in dev:debug');
const socket = new WebSocket(main.webSocketDebuggerUrl);
await new Promise((resolve, reject) => {
  socket.addEventListener('open', resolve, {once: true});
  socket.addEventListener('error', reject, {once: true});
});
let sequence = 0;
const pending = new Map();
socket.addEventListener('message', event => {
  const message = JSON.parse(event.data);
  if (!message.id || !pending.has(message.id)) return;
  const {resolve, reject} = pending.get(message.id);
  pending.delete(message.id);
  if (message.error) reject(new Error(message.error.message)); else resolve(message.result);
});
function evaluate(expression) {
  const id = ++sequence;
  const response = new Promise((resolve, reject) => pending.set(id, {resolve, reject}));
  socket.send(JSON.stringify({id, method: 'Runtime.evaluate', params: {expression, awaitPromise: true, returnByValue: true}}));
  return response.then(result => {
    if (result.exceptionDetails) throw new Error(result.exceptionDetails.text);
    return result.result.value;
  });
}
async function until(predicate, label) {
  const deadline = Date.now() + 8000;
  while (Date.now() < deadline) {
    if (await predicate()) return;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw new Error(`Timed out waiting for ${label}`);
}
try {
  assert.equal(await evaluate('window.solralol.getOverlayEditing()'), false);
  for (let index = 0; index < 3; index++) {
    assert.equal(await evaluate('window.solralol.setOverlayEditing(true)'), true);
    await until(async () => (await pages()).filter(page => page.url.includes('?overlay=')).length >= 1, 'overlay preview window');
    assert.equal(await evaluate('window.solralol.setOverlayEditing(false)'), false);
    assert.ok((await pages()).some(page => page.id === main.id), 'main window survives overlay hide');
    assert.equal((await evaluate('window.solralol.getBackendStatus()')).state, 'ready');
  }
  console.log('Main renderer and Python backend survived three overlay edit visibility cycles.');
} finally {
  try { await evaluate('window.solralol.setOverlayEditing(false)'); } catch {}
  socket.close();
}
