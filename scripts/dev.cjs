const fs = require('node:fs');
const path = require('node:path');
const { spawn } = require('node:child_process');
const http = require('node:http');
const net = require('node:net');
const readline = require('node:readline');

const root = path.resolve(__dirname, '..');
const frontend = path.join(root, 'frontend');
const python = process.env.SOLRALOL_PYTHON || path.join(root, '.venv', 'Scripts', 'python.exe');
const debugging = process.argv.includes('--debug');
const viteEntry = path.join(frontend, 'node_modules', 'vite', 'bin', 'vite.js');
const electronLauncher = path.join(frontend, 'scripts', 'start-electron.cjs');
const rendererUrl = 'http://127.0.0.1:5173/';

let vite;
let electron;
let backendPid;
let migrationActive = false;
let shuttingDown = false;
let shutdownDeadline;
let shutdownCode = 0;
let viteClosed = true;
let electronClosed = true;
const watchers = [];
const electronSources = new Map();

function log(message) { console.log(`[solralol-dev] ${message}`); }
function status(component, state, details = {}) {
  if (process.env.SOLRALOL_DEV_CONTROL_CENTER !== '1') return;
  console.log(`__SOLRALOL_STATUS__:${JSON.stringify({ component, state, ...details })}`);
}
function hasExited(child) { return !child || child.exitCode !== null || child.signalCode !== null; }

const controlInput = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
controlInput.on('line', (line) => {
  let command;
  try { command = JSON.parse(line); } catch { return; }
  if (command?.type === 'restart-backend') {
    if (!electron?.connected || shuttingDown) { log('Cannot restart backend: Electron is not connected.'); return; }
    electron.send({ type: 'restart-backend' });
  } else if (command?.type === 'stop') {
    log('Development stop requested.');
    shutdown(0);
  }
});

function verifyPrerequisites() {
  for (const [label, target] of [['Python virtual environment', python], ['Vite', viteEntry]]) {
    if (!fs.existsSync(target)) throw new Error(`${label} not found: ${target}`);
  }
}

function ensureVitePortAvailable() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once('error', (error) => {
      if (error.code === 'EADDRINUSE') reject(new Error('Port 5173 is already occupied. Solralol development appears to be running; use its open window or stop that stack before starting another.'));
      else reject(error);
    });
    server.listen(5173, '127.0.0.1', () => server.close(resolve));
  });
}

function waitForVite() {
  return new Promise((resolve, reject) => {
    const started = Date.now();
    const check = () => {
      if (shuttingDown) return reject(new Error('Startup cancelled'));
      if (hasExited(vite)) return reject(new Error(`Vite exited with code ${vite.exitCode ?? vite.signalCode ?? 'unknown'}`));
      const request = http.get(rendererUrl, (response) => {
        let body = '';
        response.setEncoding('utf8');
        response.on('data', (chunk) => { body += chunk; });
        response.on('end', () => {
          if (response.statusCode === 200 && body.includes('/@vite/client')) return resolve();
          retry();
        });
      });
      request.setTimeout(1000, () => request.destroy());
      request.on('error', retry);
      function retry() {
        if (Date.now() - started > 45000) return reject(new Error('Timed out waiting for Vite at ' + rendererUrl));
        setTimeout(check, 250).unref();
      }
    };
    check();
  });
}

function stopChild(child, label) {
  if (!child || child.exitCode !== null || child.killed) return;
  log(`Stopping ${label}...`);
  if (label === 'Electron' && child.connected) {
    child.send({ type: 'shutdown' });
    return;
  }
  child.kill('SIGINT');
  const timer = setTimeout(() => {
    if (child.exitCode === null) child.kill('SIGTERM');
  }, 2500);
  timer.unref();
}

function forceStopChildTree(child, label) {
  if (hasExited(child) || !child.pid) return;
  log(`Graceful shutdown timed out; terminating the owned ${label} process tree.`);
  if (process.platform === 'win32') {
    const killer = spawn('taskkill.exe', ['/PID', String(child.pid), '/T', '/F'], { stdio: 'ignore', windowsHide: true });
    killer.on('error', () => child.kill('SIGKILL'));
  } else child.kill('SIGKILL');
}

function forceStopBackend(pid) {
  if (!pid) return;
  log(`Terminating the orphaned managed Python backend process tree (PID ${pid}).`);
  if (process.platform === 'win32') {
    const killer = spawn('taskkill.exe', ['/PID', String(pid), '/T', '/F'], { stdio: 'ignore', windowsHide: true });
    killer.on('error', () => {});
  } else {
    try { process.kill(pid, 'SIGKILL'); } catch {}
  }
}

function sourceDigest(file) {
  try { return require('node:crypto').createHash('sha256').update(fs.readFileSync(file)).digest('hex'); }
  catch (error) { return error.code === 'ENOENT' ? null : `unreadable:${error.code || 'error'}`; }
}

function installElectronWatchers() {
  const sources = ['main/bootstrap.cjs', 'main/index.cjs', 'main/migration-assistant.cjs', 'main/storage-migration-worker.cjs', 'preload/index.cjs', 'preload/migration.cjs'];
  for (const source of sources) electronSources.set(source, sourceDigest(path.join(frontend, 'electron', source)));
  let restartTimer;
  const changed = (relativeName) => {
    const candidates = relativeName && relativeName.endsWith('.cjs') && electronSources.has(relativeName)
      ? [relativeName]
      : relativeName ? [] : sources;
    if (!candidates.length) return;
    clearTimeout(restartTimer);
    restartTimer = setTimeout(() => {
      if (shuttingDown) return;
      const modified = candidates.filter((source) => {
        const digest = sourceDigest(path.join(frontend, 'electron', source));
        if (digest === electronSources.get(source)) return false;
        electronSources.set(source, digest);
        return true;
      });
      if (!modified.length || !electron?.connected) return;
      if (migrationActive) { log('Electron source restart deferred while the offline migration assistant is active.'); return; }
      log(`Electron source changed (${modified.join(', ')}); restarting desktop process.`);
      electron.send({ type: 'restart' });
    }, 350);
    restartTimer.unref();
  };
  for (const directory of ['main', 'preload']) {
    try {
      const watcher = fs.watch(path.join(frontend, 'electron', directory), { recursive: true }, (_event, filename) => {
        const name = filename?.toString() || '';
        changed(name ? `${directory}/${name}` : '');
      });
      watcher.on('error', (error) => console.error('[electron-watch]', error.message));
      watchers.push(watcher);
    } catch (error) { console.error('[electron-watch]', error.message); }
  }
}

function shutdown(code = 0) {
  if (shuttingDown) return;
  shuttingDown = true;
  shutdownCode = code;
  controlInput.close();
  process.stdin.pause();
  process.stdin.destroy();
  stopChild(electron, 'Electron');
  stopChild(vite, 'Vite');
  for (const watcher of watchers) watcher.close();
  shutdownDeadline = setTimeout(() => {
    forceStopChildTree(electron, 'Electron');
    forceStopChildTree(vite, 'Vite');
    forceStopBackend(backendPid);
    setTimeout(() => process.exit(code), 600).unref();
  }, Math.max(50000, Number(process.env.SOLRALOL_STACK_SHUTDOWN_TIMEOUT_MS) || 50000));
  shutdownDeadline.unref();
  finishShutdown();
}

function finishShutdown() {
  if (shuttingDown && electronClosed && viteClosed) {
    clearTimeout(shutdownDeadline);
    process.exitCode = shutdownCode;
  }
}

async function launch() {
  verifyPrerequisites();
  await ensureVitePortAvailable();
  log(`Starting Vite on 127.0.0.1:5173${debugging ? ' (debug enabled)' : ''}`);
  vite = spawn(process.execPath, [viteEntry, '--host', '127.0.0.1', '--port', '5173', '--strictPort'], {
    cwd: frontend,
    stdio: 'inherit',
    windowsHide: true,
    env: { ...process.env, NODE_ENV: 'development' },
  });
  viteClosed = false;
  vite.on('close', () => { viteClosed = true; finishShutdown(); });
  vite.on('error', (error) => { console.error('[vite] failed to start:', error.message); shutdown(1); });
  status('vite', 'starting', { detail: 'waiting for Vite HTTP readiness' });
  vite.on('exit', (code, signal) => {
    status('vite', shuttingDown ? 'stopped' : 'error', { code, signal: signal || undefined, detail: shuttingDown ? 'stopped' : 'Vite exited unexpectedly' });
    if (!shuttingDown) shutdown(code ?? 1); else finishShutdown();
  });

  waitForVite().then(() => {
    if (shuttingDown) return;
    status('vite', 'running', { pid: vite.pid, detail: 'HTTP ready' });
    installElectronWatchers();
    log('Vite is ready; starting the Electron desktop app and its managed Python backend.');
    const env = {
      ...process.env,
      NODE_ENV: 'development',
      SOLRALOL_PYTHON: python,
      ...(process.env.SOLRALOL_MANUAL_BACKEND === '1' ? { SOLRALOL_MANUAL_BACKEND: '1' } : {}),
      ...(debugging ? {
        SOLRALOL_ELECTRON_INSPECT_PORT: '9229',
        SOLRALOL_RENDERER_INSPECT_PORT: '9230',
        SOLRALOL_PYTHON_DEBUG_PORT: '5678',
      } : {}),
    };
    electron = spawn(process.execPath, [electronLauncher], { cwd: frontend, stdio: ['inherit', 'inherit', 'inherit', 'ipc'], windowsHide: true, env });
    electronClosed = false;
    electron.on('close', () => { electronClosed = true; finishShutdown(); });
    status('electron', 'starting', { pid: electron.pid, detail: 'waiting for main and renderer readiness' });
    electron.on('message', (message) => {
      if (message?.type === 'solralol-storage-migration-started') {
        migrationActive = true;
        status('electron', 'stopping', { detail: 'Asistente de migración independiente activo' });
        return;
      }
      if (message?.type === 'solralol-storage-migration-finished') {
        migrationActive = false;
        status('electron', 'starting', { detail: 'Iniciando Solralol con la ubicación confirmada' });
        return;
      }
      if (!message || message.type !== 'solralol-status' || !['electron', 'backend'].includes(message.component)) return;
      if (message.component === 'backend') {
        if (message.details?.pid) backendPid = Number(message.details.pid) || backendPid;
        if (message.state === 'stopped') backendPid = undefined;
      }
      status(message.component, message.state, { ...message.details, via: 'electron' });
    });
    electron.on('error', (error) => { status('electron', 'error', { detail: error.message }); console.error('[electron] failed to start:', error.message); shutdown(1); });
    electron.on('exit', (code, signal) => {
      if (!shuttingDown && code !== 0 && backendPid) {
        status('backend', 'error', { pid: backendPid, detail: 'Electron owner exited unexpectedly; orphan cleanup scheduled' });
        forceStopBackend(backendPid);
        backendPid = undefined;
      }
      status('electron', shuttingDown || code === 0 ? 'stopped' : 'error', { code, signal: signal || undefined, detail: shuttingDown || code === 0 ? 'stopped' : 'Electron exited unexpectedly' });
      if (!shuttingDown) shutdown(code ?? 1); else finishShutdown();
    });
    log('Electron process launched; waiting for its window and Python backend.');
  }).catch((error) => {
    status('vite', 'error', { pid: vite?.pid, detail: `HTTP readiness pending: ${error.message}; process left alive for diagnosis` });
    console.error('[solralol-dev]', error.message);
  });
}

launch().catch((error) => {
  console.error('[solralol-dev]', error.message);
  process.exitCode = 1;
});

process.on('SIGINT', () => shutdown(0));
process.on('SIGTERM', () => shutdown(0));
