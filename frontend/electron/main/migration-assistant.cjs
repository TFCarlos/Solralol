const { app, BrowserWindow, ipcMain } = require('electron');
const { Worker } = require('node:worker_threads');
const fs = require('node:fs');
const fsp = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');

let windowRef;
let config;
let current = {};
let worker;
let running = false;
let ownerWatch;
let allowWindowClose = false;
let journalMonitor;
let profileDirectory;
const PROCESS_POLL_MS = 400;
const TERMINAL_STATES = new Set(['complete', 'startup_verified', 'failed', 'recovery_required', 'startup_failed']);

function publish(value) {
  current = { ...current, ...value };
  if (windowRef && !windowRef.isDestroyed()) windowRef.webContents.send('migration:status', current);
}
async function writeJournal(value) {
  await fsp.mkdir(path.dirname(config.journalPath), { recursive: true });
  const temporary = `${config.journalPath}.${config.migrationId}.${process.pid}.tmp`;
  const handle = await fsp.open(temporary, 'w');
  try { await handle.writeFile(`${JSON.stringify(value, null, 2)}\n`, 'utf8'); await handle.sync(); }
  finally { await handle.close(); }
  await renameWithRetry(temporary, config.journalPath);
}
async function renameWithRetry(source, target) {
  let delay = 40;
  for (let attempt = 0; ; attempt++) {
    try { await fsp.rename(source, target); return; }
    catch (error) {
      if (!['EACCES', 'EPERM', 'EBUSY'].includes(error.code) || attempt >= 5) throw error;
      await new Promise((resolve) => setTimeout(resolve, delay));
      delay = Math.min(delay * 2, 500);
    }
  }
}
async function diagnostic(message) {
  try { await fsp.appendFile(config.logPath, `[${new Date().toISOString()}] ${message}\n`, 'utf8'); } catch {}
}
function processAlive(pid) {
  if (!Number.isInteger(Number(pid)) || Number(pid) <= 0 || Number(pid) === process.pid) return false;
  try { process.kill(Number(pid), 0); return true; } catch (error) { return error.code === 'EPERM'; }
}
async function setPhase(phase, message, extra = {}) {
  current = { ...current, ...extra, migrationId: config.migrationId, state: phase, phase, message, lastProgressAt: Date.now() };
  try { await writeJournal(current); } catch (error) { current.error = `No se pudo actualizar el registro: ${error.message}`; }
  await diagnostic(`pid=${process.pid} fase=${phase} mensaje=${message}${extra.error ? ` error=${extra.error}` : ''}`);
  publish(current);
}
async function waitForApplication() {
  await setPhase('waiting_for_shutdown', 'Esperando a que Solralol cierre y libere sus archivos.');
  let heartbeat = Date.now();
  while (processAlive(config.ownerPid) || processAlive(config.backendPid)) {
    publish({ state: 'waiting_for_shutdown', phase: 'closing', message: 'Cerrando Solralol y finalizando procesos propios…', lastProgressAt: Date.now() });
    await new Promise((resolve) => { ownerWatch = setTimeout(resolve, PROCESS_POLL_MS); ownerWatch.unref?.(); });
    if (Date.now() - heartbeat > 5000) { heartbeat = Date.now(); current.lastProgressAt = heartbeat; await writeJournal(current); }
  }
  await setPhase('validating', 'Verificando que los archivos estén disponibles.');
  startWorker();
}
function startWorker() {
  if (running) return;
  running = true;
  const workerPath = app.isPackaged
    ? path.join(process.resourcesPath, 'app.asar.unpacked', 'electron', 'main', 'storage-migration-worker.cjs')
    : path.join(__dirname, 'storage-migration-worker.cjs');
  worker = new Worker(workerPath, { workerData: config });
  worker.on('message', (message) => {
    if (message?.value) publish(message.value);
    if (message?.type === 'complete') { running = false; }
    if (message?.type === 'failed') { running = false; }
  });
  worker.on('error', (error) => { running = false; void setPhase('failed', 'No se pudo completar la migración. La ubicación original permanece activa.', { error: error.message }); });
  worker.on('exit', (code) => { if (running && code !== 0) { running = false; void setPhase('failed', 'El asistente terminó inesperadamente. La ubicación original permanece activa.', { error: `worker_exit_${code}` }); } });
}
async function createWindow() {
  windowRef = new BrowserWindow({
    width: 650, height: 570, minWidth: 570, minHeight: 510, resizable: true,
    frame: false, show: false, backgroundColor: '#101014', title: 'Migración de almacenamiento · Solralol',
    webPreferences: { preload: path.join(__dirname, '../preload/migration.cjs'), contextIsolation: true, sandbox: true, nodeIntegration: false },
  });
  windowRef.setMenuBarVisibility(false);
  await windowRef.loadFile(path.join(__dirname, '../migration-assistant.html'));
  windowRef.once('ready-to-show', () => windowRef.show());
  windowRef.on('close', (event) => {
    if (allowWindowClose) return;
    if (!TERMINAL_STATES.has(current.state)) { event.preventDefault(); return; }
    allowWindowClose = true;
    app.quit();
  });
  windowRef.on('closed', () => { windowRef = undefined; });
}

async function start(configPath) {
  if (!configPath) { app.quit(); return; }
  try {
    config = JSON.parse(fs.readFileSync(path.resolve(configPath), 'utf8'));
    current = { ...config.initialStatus, migrationId: config.migrationId, source: config.source, destination: config.destination,
      ownerPid: config.ownerPid, backendPid: config.backendPid, assistantPid: process.pid,
      state: 'waiting_for_assistant', phase: 'closing', message: 'Iniciando el asistente independiente…' };
    profileDirectory = path.join(os.tmpdir(), `solralol-migration-assistant-${config.migrationId}`);
    app.setPath('userData', profileDirectory);
    await app.whenReady();
    await createWindow();
    await setPhase('assistant_ready', 'Asistente preparado. Cerrando Solralol antes de copiar los datos.');
    await fsp.writeFile(config.ackPath, JSON.stringify({ migrationId: config.migrationId, pid: process.pid, readyAt: Date.now() }), 'utf8');
    await waitForApplication();
    journalMonitor = setInterval(async () => {
      try {
        const state = JSON.parse(await fsp.readFile(config.journalPath, 'utf8'));
        if (state.state === 'startup_verified' || state.state === 'startup_failed') publish(state);
      } catch {}
    }, 800);
  } catch (error) {
    if (config) await setPhase('failed', 'No se pudo iniciar el asistente de migración.', { error: error.message });
  }
}

ipcMain.on('migration:ready', (event) => {
  if (windowRef && event.sender === windowRef.webContents) event.sender.send('migration:status', current);
});
ipcMain.handle('migration:action', async (event, action) => {
  if (!windowRef || event.sender !== windowRef.webContents || !['close', 'retry', 'launch-source', 'launch-destination'].includes(action)) return false;
  if (action === 'close' && TERMINAL_STATES.has(current.state)) {
    allowWindowClose = true;
    app.quit();
    return true;
  }
  if (action === 'retry' && !running && ['failed', 'recovery_required'].includes(current.state)) {
    await setPhase('waiting_for_shutdown', 'Reintentando la migración.');
    await waitForApplication();
    return true;
  }
  if (action === 'launch-source' && ['failed', 'recovery_required', 'startup_failed'].includes(current.state)) {
    if (current.state === 'startup_failed') {
      await fsp.mkdir(path.dirname(config.pointerPath), { recursive: true });
      const rollback = `${config.pointerPath}.${config.migrationId}.rollback.tmp`;
      const handle = await fsp.open(rollback, 'w');
      try { await handle.writeFile(`${JSON.stringify({ data_root: config.source }, null, 2)}\n`, 'utf8'); await handle.sync(); }
      finally { await handle.close(); }
      await renameWithRetry(rollback, config.pointerPath);
    }
    await setPhase('launching_source', 'Se iniciará Solralol con la ubicación original.', { launchRoot: config.source });
    if (config.devMode) return true;
    const { spawn } = require('node:child_process');
    const child = spawn(config.executable, config.relaunchArgs || [], { cwd: config.cwd, detached: true, stdio: 'ignore', windowsHide: false,
      env: { ...process.env, SOLRALOL_DATA_DIR: config.source, SOLRALOL_MIGRATION_ID: config.migrationId } });
    child.unref();
    allowWindowClose = true;
    app.quit();
    return true;
  }
  if (action === 'launch-destination' && current.state === 'complete') {
    await setPhase('launching_destination', 'Se iniciará Solralol con la nueva ubicación.', { launchRoot: config.destination });
    if (config.devMode) return true;
    const { spawn } = require('node:child_process');
    const child = spawn(config.executable, config.relaunchArgs || [], { cwd: config.cwd, detached: true, stdio: 'ignore', windowsHide: false,
      env: { ...process.env, SOLRALOL_DATA_DIR: config.destination, SOLRALOL_MIGRATION_ID: config.migrationId } });
    child.unref();
    return true;
  }
  return false;
});
app.on('window-all-closed', () => { /* Keep the independent worker alive if the window is closed. */ });
app.on('before-quit', () => { clearTimeout(ownerWatch); });
app.on('will-quit', () => { if (profileDirectory) void fsp.rm(profileDirectory, { recursive: true, force: true }).catch(() => {}); });

module.exports = { start };
