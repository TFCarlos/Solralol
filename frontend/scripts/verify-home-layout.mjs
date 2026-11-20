import assert from 'node:assert/strict';

const debugPort = Number(process.env.SOLRALOL_RENDERER_INSPECT_PORT || 9230);
const endpoint = `http://127.0.0.1:${debugPort}`;
const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function json(path) {
  const response = await fetch(`${endpoint}${path}`);
  if (!response.ok) throw new Error(`DevTools endpoint returned ${response.status} for ${path}`);
  return response.json();
}

function connect(url) {
  const socket = new WebSocket(url);
  const pending = new Map();
  let nextId = 0;
  socket.addEventListener('message', (event) => {
    const message = JSON.parse(event.data);
    if (!message.id) return;
    const request = pending.get(message.id);
    if (!request) return;
    pending.delete(message.id);
    if (message.error) request.reject(new Error(message.error.message));
    else request.resolve(message.result);
  });
  const ready = new Promise((resolve, reject) => {
    socket.addEventListener('open', resolve, { once: true });
    socket.addEventListener('error', reject, { once: true });
  });
  return {
    async send(method, params = {}) {
      await ready;
      const id = ++nextId;
      return new Promise((resolve, reject) => {
        const timeout = setTimeout(() => { pending.delete(id); reject(new Error(`Timed out: ${method}`)); }, 10000);
        pending.set(id, {
          resolve: (value) => { clearTimeout(timeout); resolve(value); },
          reject: (error) => { clearTimeout(timeout); reject(error); },
        });
        socket.send(JSON.stringify({ id, method, params }));
      });
    },
    close() { socket.close(); },
  };
}

let version;
let targets;
try {
  [version, targets] = await Promise.all([json('/json/version'), json('/json/list')]);
} catch (error) {
  throw new Error(`No hay renderer DevTools en ${endpoint}. Inicia la aplicación con npm run dev:debug y vuelve a ejecutar npm run test:home-layout.`, { cause: error });
}
const target = targets.find((candidate) => candidate.type === 'page' && candidate.url.startsWith('http://127.0.0.1:5173'));
assert.ok(target, 'No Solralol renderer found. Start it with npm run dev:debug.');
const browser = connect(version.webSocketDebuggerUrl);
const page = connect(target.webSocketDebuggerUrl);

async function evaluate(expression) {
  const { result, exceptionDetails } = await page.send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
  if (exceptionDetails) throw new Error(exceptionDetails.text || 'Renderer evaluation failed');
  return result.value;
}

const { windowId, bounds: originalBounds } = await browser.send('Browser.getWindowForTarget', { targetId: target.id });
const originalSidebarCollapsed = await evaluate("document.querySelector('.app-shell')?.classList.contains('sidebar-collapsed')");
const measurements = [];

async function readHistory() {
  return evaluate(`(() => {
    const card = document.querySelector('.redesign-history-card');
    const list = document.querySelector('.redesign-match-list');
    const tiles = document.querySelector('.home-dashboard-tiles');
    const statistics = document.querySelector('.player-statistics-card');
    const sidebar = document.querySelector('.home-redesign-side');
    if (!card || !list || !tiles || !statistics || !sidebar) return null;
    const rect = card.getBoundingClientRect();
    const tileRect = tiles.getBoundingClientRect();
    return {
      height: rect.height,
      width: rect.width,
      documentHeight: document.documentElement.scrollHeight,
      documentWidth: document.documentElement.scrollWidth,
      viewportWidth: window.innerWidth,
      listHeight: list.clientHeight,
      listScrollHeight: list.scrollHeight,
      overflowY: getComputedStyle(list).overflowY,
      visibleRows: list.querySelectorAll('.redesign-match-row').length,
      footerVisible: Boolean(document.querySelector('.redesign-history-footer')),
      tileWidth: tileRect.width,
      tileColumns: getComputedStyle(tiles).gridTemplateColumns.split(' ').length,
      tileCount: [...tiles.children].length,
      sparklineCount: statistics.querySelectorAll('.player-stat-sparkline').length,
      redundantPanels: document.querySelectorAll('.soloq-evolution-card,.win-loss-card,.performance-insights-card').length,
      sidebarCards: sidebar.querySelectorAll(':scope > .card').length,
    };
  })()`);
}

async function settleHistory() {
  for (let attempt = 0; attempt < 20; attempt += 1) {
    const state = await readHistory();
    if (state) return state;
    await pause(50);
  }
  throw new Error('Recent match history card was not rendered.');
}

async function ensureVisibleRows(minimum) {
  for (let attempt = 0; attempt < 12; attempt += 1) {
    const rows = await evaluate("document.querySelectorAll('.redesign-match-list .redesign-match-row').length");
    if (rows >= minimum) return;
    const button = await evaluate("document.querySelector('.redesign-history-footer .load-more')?.textContent || null");
    if (!button) break;
    await evaluate("document.querySelector('.redesign-history-footer .load-more').click(); true");
    await pause(350);
  }
  const rows = await evaluate("document.querySelectorAll('.redesign-match-list .redesign-match-row').length");
  assert.ok(rows >= minimum, `Could not load ${minimum} rendered matches (only ${rows} available).`);
}

try {
  const initial = await settleHistory();
  assert.ok(initial.visibleRows > 0, 'The Home dashboard has no rendered history rows.');
  const beforeLoad = initial;
  await ensureVisibleRows(100);
  const afterLoad = await settleHistory();
  assert.equal(afterLoad.height, beforeLoad.height, 'Loading matches changed the outer history card height.');
  assert.equal(afterLoad.documentHeight, beforeLoad.documentHeight, 'Loading matches changed document height.');
  assert.ok(afterLoad.listScrollHeight > afterLoad.listHeight, 'The list does not overflow its own viewport.');
  assert.ok(['auto', 'scroll'].includes(afterLoad.overflowY), `Unexpected list overflow-y: ${afterLoad.overflowY}`);
  const moved = await evaluate("(() => { const list = document.querySelector('.redesign-match-list'); list.scrollTop = 0; const before = list.scrollTop; list.scrollTop = Math.min(180, list.scrollHeight); return { before, after: list.scrollTop }; })()");
  assert.ok(moved.after > moved.before, 'The internal match list did not scroll.');

  for (const [width, height] of [[1280, 720], [1600, 900], [1920, 1080], [2560, 1440]]) {
    await browser.send('Browser.setWindowBounds', { windowId, bounds: { ...originalBounds, windowState: 'normal', width, height } });
    await pause(300);
    const expanded = await settleHistory();
    assert.ok(expanded.documentWidth <= expanded.viewportWidth + 1, `Horizontal overflow at ${width}x${height}.`);
    assert.ok(expanded.height > expanded.listHeight, `History controls clipped at ${width}x${height}.`);
    assert.equal(expanded.tileCount, 6, `Expected six compact Home modules at ${width}x${height}.`);
    assert.equal(expanded.tileColumns, 2, `Expected paired dashboard modules at ${width}x${height}.`);
    assert.equal(expanded.redundantPanels, 0, 'Removed performance analysis panels are still rendered.');
    assert.ok(expanded.sparklineCount > 0, 'Player statistics have no historical sparklines.');
    assert.ok(expanded.sidebarCards >= 5, 'Right sidebar sections are missing.');
    measurements.push({ viewport: `${width}x${height}`, sidebar: 'expanded', ...expanded });
    await evaluate("document.querySelector('.sidebar-toggle')?.click(); true");
    await pause(320);
    const collapsed = await settleHistory();
    assert.ok(collapsed.documentWidth <= collapsed.viewportWidth + 1, `Horizontal overflow with collapsed sidebar at ${width}x${height}.`);
    measurements.push({ viewport: `${width}x${height}`, sidebar: 'collapsed', ...collapsed });
    await evaluate("document.querySelector('.sidebar-toggle')?.click(); true");
    await pause(320);
  }
  console.log(JSON.stringify({ pass: true, beforeLoad, afterLoad, scrollTopAfter: moved.after, layouts: measurements }, null, 2));
} finally {
  const currentCollapsed = await evaluate("document.querySelector('.app-shell')?.classList.contains('sidebar-collapsed')").catch(() => originalSidebarCollapsed);
  if (currentCollapsed !== originalSidebarCollapsed) await evaluate("document.querySelector('.sidebar-toggle')?.click(); true").catch(() => {});
  await browser.send('Browser.setWindowBounds', { windowId, bounds: originalBounds }).catch(() => {});
  page.close();
  browser.close();
}
