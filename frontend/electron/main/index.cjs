const { app, BrowserWindow, ipcMain, dialog, shell, protocol, globalShortcut } = require('electron');
const { spawn } = require('node:child_process');
const fsWatch = require('node:fs');
const fs = require('node:fs/promises');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const readline = require('node:readline');
const crypto = require('node:crypto');
const { Readable } = require('node:stream');
const { randomUUID } = require('node:crypto');
const { ApplicationShutdownCoordinator } = require('./shutdown-coordinator.cjs');
const { stopOwnedChild } = require('./owned-child-shutdown.cjs');

function bootstrapStorageRoot() {
  if (process.env.SOLRALOL_DATA_DIR?.trim()) return path.resolve(process.env.SOLRALOL_DATA_DIR.trim());
  const roaming = process.env.APPDATA || path.join(require('node:os').homedir(), 'AppData', 'Roaming');
  try {
    const pointer = JSON.parse(fsWatch.readFileSync(path.join(roaming, 'Solralol', 'storage.json'), 'utf8'));
    if (typeof pointer.data_root === 'string' && pointer.data_root.trim()) return path.resolve(pointer.data_root);
  } catch {}
  return path.join(require('node:os').homedir(), '.solralol');
}
let activeStorageRoot = bootstrapStorageRoot();
const legacyElectronDataRoot = app.getPath('userData');
try { app.setPath('userData', path.join(activeStorageRoot, 'electron')); } catch {}

protocol.registerSchemesAsPrivileged([{ scheme: 'solralol-recording', privileges: { standard: true, secure: true, supportFetchAPI: true, stream: true, corsEnabled: false } }]);

const hasSingleInstanceLock = app.requestSingleInstanceLock();
if (!hasSingleInstanceLock) app.quit();

// Keep the desktop UI usable at startup while allowing normal resize/maximize.
const MIN_WINDOW_WIDTH = 1280;
const MIN_WINDOW_HEIGHT = 800;

if (!app.isPackaged && process.env.SOLRALOL_RENDERER_INSPECT_PORT) {
  app.commandLine.appendSwitch('remote-debugging-address', '127.0.0.1');
  app.commandLine.appendSwitch('remote-debugging-port', process.env.SOLRALOL_RENDERER_INSPECT_PORT);
}

let windowRef;
let mainCloseIntent;
let screen;
let screenListenersRegistered = false;
let backend;
let backendLifecycle = 'starting';
let backendBootstrap;
let backendHealthTimer;
let backendHealthInFlight = false;
let sequence = 0;
let restartAttempts = 0;
let quitting = false;
let backendRestarting = false;
let migrationActive = false;
let migrationRecoveryRestarts = 0;
let migrationRestartScheduled = false;
let migrationOperationId;
let lastMigrationPhase;
let lastNotifiedAnalysisJob;
let analysisRecalculationMonitor;
const stoppingBackends = new WeakSet();
const closedBackends = new WeakSet();
const developmentWatchers = [];
const pending = new Map();
const allowlist = new Set(['app.bootstrap', 'riot.readiness', 'live.snapshot', 'champions.list', 'champions.analysis', 'champions.analysis.update', 'champions.analysis.update.status', 'champions.analysis.update.cancel', 'draft.snapshot', 'draft.import', 'meta.bootstrap', 'meta.tier', 'meta.notes', 'meta.assets', 'settings.public', 'settings.load', 'settings.update', 'settings.key.save', 'settings.key.clear', 'settings.audio-devices', 'settings.recording-test', 'analysis.settings.load', 'analysis.settings.defaults', 'analysis.settings.save', 'analysis.settings.recalculation.status', 'storage.info', 'storage.preview', 'storage.migrate.start', 'storage.migrate.status', 'storage.migrate.abort', 'recordings.list', 'recordings.source', 'recordings.thumbnail', 'recordings.review', 'recordings.review.generate', 'recordings.status', 'recordings.start', 'recordings.stop', 'recordings.delete', 'saved_matches.list', 'saved_matches.detail', 'saved_matches.sync', 'saved_matches.analysis.generate', 'saved_matches.delete.preview', 'saved_matches.delete', 'soloq_analyses.list', 'soloq_analyses.register', 'soloq_analyses.detail', 'soloq_analyses.achievements', 'soloq_analyses.delete.preview', 'soloq_analyses.delete', 'soloq_analyses.analysis.generate', 'soloq_analyses.analysis.status', 'soloq_analyses.combat.context', 'soloq_analyses.combat.generate', 'home.dashboard', 'home.counter', 'home.sync', 'home.matches', 'home.match.detail', 'home.clear-history', 'home.assets']);
const lanes = new Set(['top', 'jungle', 'mid', 'adc', 'support']);
const ranks = new Set(['emerald', 'emerald_plus', 'diamond', 'diamond_plus', 'master', 'master_plus']);
let diagnosticRoot;
const recordingFiles = new Map();
const recordingTokensByName = new Map();
const reviewWindows = new Map();
const deepAnalysisWindows = new Map();
const liveOverlayWindows = new Map();
const liveOverlayPayloads = new Map();
let liveOverlaySettings;
let lastLiveOverlayState;
let overlaySettingsRequest = false;
let overlayVisibility = {gameVisible:false, gameOccluded:true, coveredPanels:[]};
let overlayVisibilityTimer;
let overlayVisibilityBusy = false;
let overlayEditing = false;
const startupLogs = [];
const manualBackendLifecycle = process.env.SOLRALOL_MANUAL_BACKEND === '1';
// Give an active FFmpeg process time to write its MP4 index and sidecar when
// the backend receives EOF during an orderly application shutdown.
const backendShutdownTimeout = Math.max(90000, Number(process.env.SOLRALOL_BACKEND_SHUTDOWN_TIMEOUT_MS) || 90000);

function forceStopBackendTree(child) {
  if (!child || child.exitCode !== null || !child.pid) return;
  if (process.platform === 'win32') {
    const killer = spawn('taskkill.exe', ['/PID', String(child.pid), '/T', '/F'], { windowsHide: true, stdio: 'ignore' });
    killer.on('error', () => child.kill('SIGKILL'));
    killer.on('exit', (code) => { if (code !== 0 && child.exitCode === null) child.kill('SIGKILL'); });
  } else child.kill('SIGKILL');
}

function logDiagnostic(message) {
  const line = `${new Date().toISOString()} ${message}\n`;
  if (/failed|error|unavailable|rejected|invalid|exited unexpectedly|watcher/i.test(message)) console.error(message);
  if (!diagnosticRoot) { startupLogs.push(line); return; }
  fs.mkdir(diagnosticRoot, { recursive: true })
    .then(() => fs.appendFile(path.join(diagnosticRoot, 'desktop.log'), line, 'utf8'))
    .catch(() => {});
}

function windowLifecycleState(window) {
  if (!window || window.isDestroyed()) return 'closed';
  return window.isVisible() ? 'visible' : 'hidden';
}

function shutdownWindowContext() {
  return `main=${windowLifecycleState(windowRef)} overlays=${[...liveOverlayWindows]
    .map(([panel, window]) => `${panel}:${windowLifecycleState(window)}`).join(',') || 'none'}`;
}

function publishDevStatus(component, state, details = {}) {
  if (app.isPackaged || !process.send) return;
  try { process.send({ type: 'solralol-status', component, state, details }); } catch {}
}

function setBackendLifecycle(state, details = {}) {
  const changed = backendLifecycle !== state;
  backendLifecycle = state;
  if (state !== 'ready') backendBootstrap = undefined;
  if (state !== 'ready') {
    watchOverlayTab(false);
    watchOverlayVisibility(false);
    for (const overlay of liveOverlayWindows.values()) if (!overlay.isDestroyed()) overlay.hide();
  }
  const statusMap = { ready: 'running', starting: 'starting', restarting: 'restarting', error: 'error', stopped: 'stopped', stopping: 'stopping' };
  if (changed) publishDevStatus('backend', statusMap[state] || 'error', {
    pid: backend?.pid,
    detail: details.message || (state === 'ready' ? 'app.bootstrap health response received' : state),
  });
  if (changed && windowRef && !windowRef.isDestroyed()) windowRef.webContents.send('backend:status', { state, ...details });
  if (state === 'ready' || (state === 'error' && backend)) startBackendHealthMonitor();
  else {
    clearInterval(backendHealthTimer);
    backendHealthTimer = undefined;
  }
}

function startBackendHealthMonitor() {
  if (backendHealthTimer || quitting) return;
  backendHealthTimer = setInterval(() => {
    if (backendHealthInFlight || !backend || backendRestarting || quitting
      || (backendLifecycle !== 'ready' && backendLifecycle !== 'error')) return;
    backendHealthInFlight = true;
    requestBackend('app.bootstrap', {}, 4000)
      .catch(() => {})
      .finally(() => { backendHealthInFlight = false; });
  }, 5000);
  backendHealthTimer.unref();
}

function notifyAnalysisRecalculation(result) {
  if (!result?.id || result.state !== 'completed' || result.id === lastNotifiedAnalysisJob) return;
  lastNotifiedAnalysisJob = result.id;
  const message = { revision: result.revision, configurationHash: result.configurationHash, recalculated: result.recalculated || 0 };
  if (windowRef && !windowRef.isDestroyed()) windowRef.webContents.send('analysis:recalculated', message);
  if (windowRef && !windowRef.isDestroyed()) windowRef.webContents.send('home:saved-scores-changed');
  for (const candidate of deepAnalysisWindows.values()) {
    if (candidate && !candidate.isDestroyed()) candidate.webContents.send('analysis:recalculated', message);
  }
}

function monitorAnalysisRecalculation() {
  clearTimeout(analysisRecalculationMonitor);
  analysisRecalculationMonitor = undefined;
  if (quitting || backendLifecycle !== 'ready') return;
  requestBackend('analysis.settings.recalculation.status', {}, 5000).then((state) => {
    notifyAnalysisRecalculation(state);
    if (state?.state === 'queued' || state?.state === 'running') {
      analysisRecalculationMonitor = setTimeout(monitorAnalysisRecalculation, 1000);
      analysisRecalculationMonitor.unref?.();
    }
  }).catch((error) => logDiagnostic(`BattleScore recalculation status could not be read: ${error.message}`));
}

function validateRequest(method, params) {
  if (!params || typeof params !== 'object' || Array.isArray(params)) return false;
  if (method === 'draft.snapshot') return Object.keys(params).every((key) => ['champion', 'role', 'allies', 'enemies', 'manualBans'].includes(key))
    && (params.champion === undefined || (typeof params.champion === 'string' && params.champion.length <= 60))
    && (params.role === undefined || ['top', 'jungle', 'mid', 'adc', 'support'].includes(params.role))
    && ['allies', 'enemies'].every((key) => params[key] === undefined || (Array.isArray(params[key]) && params[key].length <= 5 && params[key].every((slot) => slot && typeof slot === 'object' && !Array.isArray(slot) && Object.keys(slot).every((field) => ['champion', 'role', 'locked'].includes(field)) && (slot.champion === undefined || (typeof slot.champion === 'string' && slot.champion.length <= 60)) && (slot.role === undefined || ['top', 'jungle', 'mid', 'adc', 'support', ''].includes(slot.role)) && (slot.locked === undefined || typeof slot.locked === 'boolean'))))
    && (params.manualBans === undefined || (params.manualBans && typeof params.manualBans === 'object' && !Array.isArray(params.manualBans) && Object.keys(params.manualBans).every((key) => ['allies', 'enemies'].includes(key)) && ['allies', 'enemies'].every((key) => params.manualBans[key] === undefined || (Array.isArray(params.manualBans[key]) && params.manualBans[key].length <= 5 && params.manualBans[key].every((name) => typeof name === 'string' && name.length <= 60)))));
  if (method === 'draft.import') return Object.keys(params).every((key) => ['kind', 'champion', 'role', 'pageIndex', 'enemies'].includes(key))
    && ['runes', 'build', 'spells', 'all'].includes(params.kind) && typeof params.champion === 'string' && params.champion.length <= 60
    && ['top', 'jungle', 'mid', 'adc', 'support'].includes(params.role)
    && (params.pageIndex === undefined || (Number.isInteger(params.pageIndex) && params.pageIndex >= 0 && params.pageIndex <= 1))
    && (params.enemies === undefined || (Array.isArray(params.enemies) && params.enemies.length <= 5 && params.enemies.every((name) => typeof name === 'string' && name.length <= 60)));
  if (method === 'app.bootstrap' || method === 'meta.bootstrap' || method === 'settings.public' || method === 'settings.load' || method === 'settings.audio-devices' || method === 'settings.recording-test' || method === 'home.clear-history' || method === 'saved_matches.list') return Object.keys(params).length === 0;
  if (['analysis.settings.load', 'analysis.settings.defaults', 'analysis.settings.recalculation.status'].includes(method)) return Object.keys(params).length === 0;
  if (method === 'analysis.settings.save') return Object.keys(params).length === 1 && params.configuration
    && typeof params.configuration === 'object' && !Array.isArray(params.configuration)
    && Buffer.byteLength(JSON.stringify(params.configuration), 'utf8') <= 32768;
  if (['storage.info', 'storage.migrate.status'].includes(method)) return Object.keys(params).length === 0;
  if (['storage.preview', 'storage.migrate.start'].includes(method)) return Object.keys(params).length === 1 && typeof params.path === 'string' && params.path.length > 0 && params.path.length <= 1024;
  if (method === 'storage.migrate.abort') return Object.keys(params).length === 1 && typeof params.migrationId === 'string' && params.migrationId.length <= 80;
  if (method === 'saved_matches.detail') return Object.keys(params).length === 1 && typeof params.id === 'string' && params.id.length > 0 && params.id.length <= 160;
  if (method === 'saved_matches.sync') return Object.keys(params).length === 1 && typeof params.id === 'string' && params.id.length > 0 && params.id.length <= 160;
  if (method === 'saved_matches.delete.preview') return Object.keys(params).length === 1 && typeof params.id === 'string' && params.id.length > 0 && params.id.length <= 160;
  if (method === 'saved_matches.delete') return Object.keys(params).length === 2 && typeof params.id === 'string' && params.id.length > 0 && params.id.length <= 160 && typeof params.manifestId === 'string' && /^[a-f0-9]{64}$/.test(params.manifestId);
  if (method === 'saved_matches.analysis.generate') return Object.keys(params).every((key) => ['id', 'force'].includes(key)) && typeof params.id === 'string' && params.id.length > 0 && params.id.length <= 160 && (params.force === undefined || typeof params.force === 'boolean');
  if (method === 'soloq_analyses.list') return Object.keys(params).length === 0;
  if (['soloq_analyses.register', 'soloq_analyses.detail', 'soloq_analyses.achievements', 'soloq_analyses.delete.preview'].includes(method)) return Object.keys(params).length === 1 && typeof params.matchId === 'string' && params.matchId.length > 0 && params.matchId.length <= 120;
  if (method === 'soloq_analyses.delete') return Object.keys(params).length === 2 && typeof params.matchId === 'string' && params.matchId.length > 0 && params.matchId.length <= 120 && typeof params.manifestId === 'string' && /^[a-f0-9]{64}$/.test(params.manifestId);
  if (method === 'soloq_analyses.analysis.generate') return Object.keys(params).every(key => ['matchId', 'force'].includes(key)) && typeof params.matchId === 'string' && params.matchId.length > 0 && params.matchId.length <= 120 && (params.force === undefined || typeof params.force === 'boolean');
  if (method === 'soloq_analyses.analysis.status') return Object.keys(params).length === 1 && typeof params.matchId === 'string' && params.matchId.length > 0 && params.matchId.length <= 120;
  if (['soloq_analyses.combat.context', 'soloq_analyses.combat.generate'].includes(method)) return Object.keys(params).length === 1 && typeof params.matchId === 'string' && params.matchId.length > 0 && params.matchId.length <= 120;
  if (method === 'meta.tier') return Object.keys(params).every((key) => ['role', 'region', 'force'].includes(key))
    && (params.role === undefined || ['top', 'jungle', 'mid', 'adc', 'support'].includes(params.role))
    && (params.region === undefined || ['all', 'na', 'euw', 'kr'].includes(params.region))
    && (params.force === undefined || typeof params.force === 'boolean');
  if (method === 'meta.notes') return Object.keys(params).every((key) => key === 'force')
    && (params.force === undefined || typeof params.force === 'boolean');
  if (method === 'meta.assets') return Object.keys(params).every((key) => ['champions', 'items', 'abilities', 'runes', 'spells', 'patch'].includes(key))
    && (params.champions === undefined || (Array.isArray(params.champions) && params.champions.length <= 20 && params.champions.every((value) => typeof value === 'string' && value.length <= 60)))
    && (params.items === undefined || (Array.isArray(params.items) && params.items.length <= 100 && params.items.every((value) => typeof value === 'string' && /^\d{1,8}$/.test(value))))
    && (params.abilities === undefined || (Array.isArray(params.abilities) && params.abilities.length <= 20 && params.abilities.every((value) => value && typeof value === 'object' && !Array.isArray(value) && Object.keys(value).length === 2 && typeof value.champion === 'string' && value.champion.length <= 60 && ['passive', 'q', 'w', 'e', 'r'].includes(value.slot))))
    && (params.runes === undefined || (Array.isArray(params.runes) && params.runes.length <= 100 && params.runes.every((value) => typeof value === 'string' && value.length <= 60 && !/[\\/\u0000-\u001f]/.test(value))))
    && (params.spells === undefined || (Array.isArray(params.spells) && params.spells.length <= 20 && params.spells.every((value) => typeof value === 'string' && value.length <= 60 && !/[\\/\u0000-\u001f]/.test(value))))
    && (params.patch === undefined || (typeof params.patch === 'string' && /^\d{1,2}\.\d{1,2}(?:\.\d{1,10}){0,2}$/.test(params.patch)));
  if (method === 'settings.update') return Object.keys(params).length === 1 && params.changes && typeof params.changes === 'object' && !Array.isArray(params.changes) && Object.keys(params.changes).length <= 32;
  if (method === 'settings.key.save') return Object.keys(params).length === 2 && ['riot', 'gemini'].includes(params.provider) && typeof params.apiKey === 'string' && params.apiKey.length <= 512;
  if (method === 'settings.key.clear') return Object.keys(params).length === 1 && ['riot', 'gemini'].includes(params.provider);
  if (method === 'home.dashboard' || method === 'home.sync' || method === 'home.matches') {
    return Object.keys(params).every((key) => key === 'offset' || key === 'limit')
      && (params.offset === undefined || (Number.isInteger(params.offset) && params.offset >= 0 && params.offset <= 100000))
      && (params.limit === undefined || (Number.isInteger(params.limit) && params.limit >= 1 && params.limit <= 100));
  }
  if (method === 'riot.readiness') return Object.keys(params).length === 0;
  if (method === 'live.snapshot') return Object.keys(params).length === 0;
  if (method === 'home.counter') return Object.keys(params).length === 0;
  if (method === 'recordings.list' || method === 'recordings.status' || method === 'recordings.start' || method === 'recordings.stop') return Object.keys(params).length === 0;
  if (method === 'recordings.source') return Object.keys(params).length === 1 && typeof params.id === 'string' && /^[a-f0-9-]{36}$/i.test(params.id);
  if (method === 'recordings.thumbnail') return Object.keys(params).length === 1 && typeof params.id === 'string' && /^[a-f0-9-]{36}$/i.test(params.id);
  if (method === 'recordings.review' || method === 'recordings.review.generate') return Object.keys(params).length === 1 && typeof params.id === 'string' && /^[a-f0-9-]{36}$/i.test(params.id);
  if (method === 'recordings.delete') return Object.keys(params).length === 1 && typeof params.name === 'string' && params.name.length <= 240 && path.basename(params.name) === params.name && /\.(mp4|mkv)$/i.test(params.name);
  if (method === 'home.match.detail') return Object.keys(params).length === 1
    && typeof params.matchId === 'string' && params.matchId.length > 0 && params.matchId.length <= 120;
  if (method === 'home.assets') return Object.keys(params).every((key) => ['champions', 'splashChampions', 'profileIconId'].includes(key))
    && Array.isArray(params.champions) && params.champions.length <= 20
    && params.champions.every((name) => typeof name === 'string' && name.length <= 80)
    && (params.splashChampions === undefined || (Array.isArray(params.splashChampions) && params.splashChampions.length <= 3
      && params.splashChampions.every((name) => typeof name === 'string' && name.length <= 80)))
    && (params.profileIconId === undefined || params.profileIconId === null
      || (Number.isInteger(params.profileIconId) && params.profileIconId > 0 && params.profileIconId <= 100000));
  if (method === 'champions.list') return Object.keys(params).every((key) => key === 'query') && (params.query === undefined || (typeof params.query === 'string' && params.query.length <= 80));
  if (method === 'champions.analysis') return Object.keys(params).every((key) => ['champion', 'lane', 'rank'].includes(key)) && typeof params.champion === 'string' && params.champion.length <= 50 && lanes.has(params.lane) && ranks.has(params.rank);
  if (method === 'champions.analysis.update') return Object.keys(params).every((key) => key === 'champion') && (params.champion === undefined || (typeof params.champion === 'string' && params.champion.length > 0 && params.champion.length <= 50));
  if (method === 'champions.analysis.update.status' || method === 'champions.analysis.update.cancel') return Object.keys(params).length === 0;
  return false;
}

function isTrustedRendererUrl(rawUrl) {
  try {
    const url = new URL(rawUrl);
    if (!app.isPackaged) return url.origin === 'http://127.0.0.1:5173' && url.pathname === '/';
    const expected = new URL(pathToFileURL(path.join(__dirname, '../../dist/index.html')).href);
    return url.protocol === 'file:' && url.pathname === expected.pathname && [...url.searchParams.keys()].every((key) => key === 'review')
      && (!url.searchParams.has('review') || /^[a-f0-9-]{36}$/i.test(url.searchParams.get('review')));
  } catch { return false; }
}

function startBackend() {
  if (quitting) return Promise.reject(new Error('Application is shutting down'));
  if (backend) return requestBackend('app.bootstrap');
  const development = !app.isPackaged;
  const root = development ? path.resolve(__dirname, '../../..') : path.join(process.resourcesPath, 'app');
  const executable = development
    ? (process.env.SOLRALOL_PYTHON || (process.platform === 'win32' ? 'python' : 'python3'))
    : path.join(process.resourcesPath, 'backend', 'SolralolBackend.exe');
  const debugPort = development && process.env.SOLRALOL_PYTHON_DEBUG_PORT;
  const args = development
    ? (debugPort ? ['-X', 'frozen_modules=off', '-u', '-m', 'debugpy', '--listen', `127.0.0.1:${debugPort}`, '-m', 'backend.protocol'] : ['-u', '-m', 'backend.protocol'])
    : [];
  const child = spawn(executable, args, {
    cwd: root, windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'],
    env: {
      ...process.env,
      SOLRALOL_DATA_DIR: activeStorageRoot,
      SOLRALOL_LEGACY_ELECTRON_DATA: legacyElectronDataRoot,
      PYTHONUTF8: '1',
      PYTHONPATH: root,
      ...(development ? {} : {
        SOLRALOL_BUNDLE_DATA_DIR: path.join(root, 'data'),
        SOLRALOL_BUNDLE_VERSION: app.getVersion(),
      }),
    },
  });
  backend = child;
  child.solralolBootStage = 'process_spawned';
  setBackendLifecycle(backendRestarting ? 'restarting' : 'starting');
  logDiagnostic(`Backend process started (${development ? 'development' : 'packaged'}; pid=${child.pid})`);
  const lines = readline.createInterface({ input: child.stdout });
  lines.on('line', (line) => {
    try {
      const message = JSON.parse(line);
      const waiter = pending.get(message.id);
      if (!waiter) return;
      clearTimeout(waiter.timeout);
      pending.delete(message.id);
      if (backend === child && !backendRestarting && !quitting && !stoppingBackends.has(child)) {
        if (waiter.method === 'app.bootstrap') {
          if (message.ok) {
            backendBootstrap = message.result;
            setBackendLifecycle('ready', { bootstrap: backendBootstrap });
          } else {
            setBackendLifecycle('error', { message: message.error?.message || 'Backend health check failed' });
          }
        }
      }
      if (message.ok) { restartAttempts = 0; waiter.resolve(message.result); }
      else waiter.reject(new Error(message.error?.message || 'Backend error'));
    } catch (error) { console.error('Invalid backend response', error); }
  });
  const diagnosticLines = readline.createInterface({ input: child.stderr });
  diagnosticLines.on('line', (line) => {
    if (line.startsWith('[BOOT] ')) {
      const stage = /\bstage=([a-z_]+)/.exec(line)?.[1];
      if (stage) child.solralolBootStage = stage;
      logDiagnostic(`Python ${line}`);
      if (process.connected || process.stderr.isTTY) console.error(`[solralol-backend] ${line}`);
      return;
    }
    console.error(`[solralol-backend] ${line}`);
  });
  child.on('error', (error) => {
    if (!quitting && !stoppingBackends.has(child)) setBackendLifecycle('error', { message: error.message });
  });
  child.on('close', (code) => {
    closedBackends.add(child);
    const expectedStop = quitting || stoppingBackends.has(child);
    logDiagnostic(expectedStop
      ? `Backend stopped normally (code=${code}; application lifecycle)`
      : `Backend exited unexpectedly (code=${code})`);
    if (migrationActive) logDiagnostic(`Backend disconnected during storage migration (${migrationOperationId || 'unknown'}; code=${code})`);
    for (const waiter of pending.values()) { clearTimeout(waiter.timeout); waiter.reject(new Error(`Backend exited (${code})`)); }
    pending.clear();
    if (backend === child) backend = undefined;
    if (backendRestarting && !quitting) setBackendLifecycle('restarting', { code });
    else if (expectedStop) setBackendLifecycle('stopped', { code });
    else setBackendLifecycle('error', { code, message: `Backend exited unexpectedly (code=${code})` });
    if (migrationActive && !expectedStop && !quitting && migrationRecoveryRestarts < 1) {
      migrationRecoveryRestarts += 1;
      backendRestarting = true;
      setBackendLifecycle('restarting', { code, message: 'Recuperando el estado de la migración' });
      logDiagnostic(`Backend exited during migration; one journal-based recovery restart scheduled (code=${code})`);
      setTimeout(() => startBackend().catch((error) => {
        backendRestarting = false;
        setBackendLifecycle('error', { message: error.message });
        logDiagnostic(`Migration recovery backend restart failed: ${error.message}`);
      }).finally(() => { backendRestarting = false; }), 700).unref();
      return;
    }
    if (!manualBackendLifecycle && !quitting && !stoppingBackends.has(child) && restartAttempts < 3) {
      setBackendLifecycle('restarting', { code });
      const delay = 500 * (2 ** restartAttempts++);
      setTimeout(() => {
        startBackend().catch((error) => {
          setBackendLifecycle('error', { message: error.message });
          logDiagnostic(`Automatic backend startup failed: ${error.message}`);
        });
      }, delay).unref();
    }
  });
  return requestBackend('app.bootstrap').then((bootstrap) => {
    backendBootstrap = bootstrap;
    setBackendLifecycle('ready', { bootstrap });
    logDiagnostic(`Backend ready (protocol=${bootstrap.protocolVersion})`);
    return bootstrap;
  }).catch(async (error) => {
    logDiagnostic(`[BOOT] Backend startup failed at ${child.solralolBootStage}: ${error.message}`);
    stoppingBackends.add(child);
    await stopOwnedChild(child, {
      timeoutMs: 3000,
      onTimeout: (owned) => logDiagnostic(`[BOOT] Backend pid=${owned.pid} did not exit after startup failure; terminating owned tree`),
      forceStop: forceStopBackendTree,
    });
    throw error;
  });
}

function stopBackend(child = backend) {
  if (!child) return Promise.resolve();
  stoppingBackends.add(child);
  if (closedBackends.has(child)) return Promise.resolve();
  return stopOwnedChild(child, {
    timeoutMs: backendShutdownTimeout,
    onTimeout: (owned) => logDiagnostic(
      `[Shutdown] Backend pid=${owned.pid} exceeded graceful timeout; terminating its owned process tree`,
    ),
    forceStop: forceStopBackendTree,
  });
}

const shutdownCoordinator = new ApplicationShutdownCoordinator({
  log: (message) => {
    if (message.startsWith('[Shutdown] Application close requested')) {
      logDiagnostic(`[APP] Shutdown origin ${message}; ${shutdownWindowContext()}`);
    }
    logDiagnostic(message);
  },
  stopIntake: () => {
    quitting = true;
    clearInterval(backendHealthTimer);
    backendHealthTimer = undefined;
    clearInterval(analysisRecalculationMonitor);
    analysisRecalculationMonitor = undefined;
    for (const watcher of developmentWatchers.splice(0)) {
      try { watcher.close(); } catch (error) { logDiagnostic(`[Shutdown] Watcher close failed: ${error.message}`); }
    }
    if (backend) setBackendLifecycle('stopping');
  },
  closeWindows: () => {
    for (const collection of [liveOverlayWindows, reviewWindows, deepAnalysisWindows]) {
      for (const window of collection.values()) {
        try { if (!window.isDestroyed()) window.close(); }
        catch (error) { logDiagnostic(`[Shutdown] Auxiliary window close failed: ${error.message}`); }
      }
      collection.clear();
    }
    try { if (windowRef && !windowRef.isDestroyed()) windowRef.close(); }
    catch (error) { logDiagnostic(`[Shutdown] Main window close failed: ${error.message}`); }
  },
  stopChildren: async () => {
    const ownedBackend = backend;
    if (ownedBackend) await stopBackend(ownedBackend);
  },
  finish: () => app.quit(),
});

function watchDirectory(directory, onChange, accepts) {
  try {
    const watcher = fsWatch.watch(directory, { recursive: true }, (_event, filename) => {
      const name = filename?.toString() || '';
      if (!name || accepts(name)) onChange(name);
    });
    watcher.on('error', (error) => logDiagnostic(`Development watcher error (${directory}): ${error.message}`));
    developmentWatchers.push(watcher);
  } catch (error) {
    logDiagnostic(`Could not watch development source (${directory}): ${error.message}`);
  }
}

function pythonSourceSnapshot(directories, rootFiles = []) {
  const started = Date.now();
  const snapshot = new Map();
  const visit = (directory) => {
    let entries;
    try { entries = fsWatch.readdirSync(directory, { withFileTypes: true }); } catch { return; }
    for (const entry of entries) {
      if (entry.name === '__pycache__' || entry.name.startsWith('.')) continue;
      const file = path.join(directory, entry.name);
      if (entry.isDirectory()) visit(file);
      else if (entry.isFile() && entry.name.endsWith('.py')) {
        try { snapshot.set(path.relative(path.resolve(__dirname, '../../..'), file), crypto.createHash('sha256').update(fsWatch.readFileSync(file)).digest('hex')); }
        catch {}
      }
    }
  };
  for (const directory of directories) visit(directory);
  const projectRoot = path.resolve(__dirname, '../../..');
  for (const name of rootFiles) {
    const file = path.join(projectRoot, name);
    try { snapshot.set(name, crypto.createHash('sha256').update(fsWatch.readFileSync(file)).digest('hex')); }
    catch { if (snapshot.has(name)) snapshot.delete(name); }
  }
  const elapsed = Date.now() - started;
  if (elapsed > 250) logDiagnostic(`Development Python source snapshot took ${elapsed} ms`);
  return snapshot;
}

function setupDevelopmentWatchers() {
  if (app.isPackaged || manualBackendLifecycle) return;
  const projectRoot = path.resolve(__dirname, '../../..');
  const pythonDirectories = ['backend', 'app/services', 'app/models', 'app/utils'];
  const watchedDirectories = pythonDirectories.map((directory) => path.join(projectRoot, directory));
  const rootPythonFiles = ['_paths.py', 'data_dragon.py'];
  let sourceDigests = pythonSourceSnapshot(watchedDirectories, rootPythonFiles);
  let backendTimer;
  const scheduleBackendRestart = () => {
    clearTimeout(backendTimer);
    backendTimer = setTimeout(async () => {
      if (quitting || backendRestarting) return;
      if (migrationActive) {
        logDiagnostic('Deferred development backend restart until storage migration finishes');
        scheduleBackendRestart();
        return;
      }
      const current = pythonSourceSnapshot(watchedDirectories, rootPythonFiles);
      const changed = new Set([...sourceDigests.keys(), ...current.keys()]);
      const modified = [...changed].filter((name) => sourceDigests.get(name) !== current.get(name));
      if (!modified.length) return;
      sourceDigests = current;
      backendRestarting = true;
      setBackendLifecycle('restarting');
      logDiagnostic(`Python source changed (${modified.join(', ')}); restarting backend`);
      try {
        await stopBackend();
        if (!quitting) await startBackend();
      } catch (error) {
        setBackendLifecycle('error', { message: error.message });
        logDiagnostic(`Automatic backend restart failed: ${error.message}`);
      } finally {
        backendRestarting = false;
      }
    }, 350);
    backendTimer.unref();
  };
  for (const directory of pythonDirectories) {
    // Python creates __pycache__ files while importing. They are not source
    // changes and must not trigger a synchronous source digest in Electron.
    watchDirectory(path.join(projectRoot, directory), scheduleBackendRestart,
      (name) => name.toLowerCase().endsWith('.py'));
  }
  try {
    const rootWatcher = fsWatch.watch(projectRoot, (_event, filename) => {
      const name = filename?.toString() || '';
      if (!name || rootPythonFiles.includes(name)) scheduleBackendRestart();
    });
    rootWatcher.on('error', (error) => logDiagnostic(`Development watcher error (${projectRoot}): ${error.message}`));
    developmentWatchers.push(rootWatcher);
  } catch (error) { logDiagnostic(`Could not watch development source (${projectRoot}): ${error.message}`); }

}

async function launchOfflineMigrationAssistant(prepared) {
  const roaming = process.env.APPDATA || path.join(require('node:os').homedir(), 'AppData', 'Roaming');
  const migrationRoot = path.join(roaming, 'Solralol', 'migrations');
  await fs.mkdir(migrationRoot, { recursive: true });
  const migrationId = prepared.migrationId || randomUUID();
  const journalPath = path.join(roaming, 'Solralol', 'migration.json');
  const configPath = path.join(migrationRoot, `${migrationId}.json`);
  const ackPath = path.join(migrationRoot, `${migrationId}.ready`);
  const config = {
    ...prepared, migrationId, journalPath, logPath: path.join(migrationRoot, `${migrationId}.log`), pointerPath: path.join(roaming, 'Solralol', 'storage.json'), ackPath,
    ownerPid: process.pid, backendPid: backend?.pid || null, devMode: !app.isPackaged,
    executable: process.execPath, cwd: app.getAppPath(), relaunchArgs: app.isPackaged ? [] : [app.getAppPath()],
  };
  await fs.writeFile(configPath, JSON.stringify(config, null, 2), 'utf8');
  await fs.rm(ackPath, { force: true });
  const child = spawn(process.execPath, [app.getAppPath(), '--solralol-storage-migration', configPath], {
    cwd: app.getAppPath(), detached: true, stdio: 'ignore', windowsHide: false, env: { ...process.env },
  });
  let spawnError;
  let childExited = false;
  child.on('error', (error) => { spawnError = error; });
  child.on('exit', () => { childExited = true; });
  child.unref();
  logDiagnostic(`Started offline migration assistant ${migrationId} (pid=${child.pid || 'unknown'})`);
  const deadline = Date.now() + 15000;
  while (Date.now() < deadline) {
    if (spawnError) throw spawnError;
    if (childExited) throw new Error('El asistente de migración se cerró antes de confirmar su inicio.');
    try {
      const ack = JSON.parse(await fs.readFile(ackPath, 'utf8'));
      if (ack.migrationId === migrationId && ack.pid) {
        migrationActive = true;
        if (!app.isPackaged && process.connected) process.send({ type: 'solralol-storage-migration-started', migrationId, journalPath, configPath });
        setTimeout(() => app.quit(), 300).unref();
        return;
      }
    } catch {}
    await new Promise((resolve) => setTimeout(resolve, 150));
  }
  try { child.kill(); } catch {}
  throw new Error('El asistente independiente no confirmó el inicio. Solralol seguirá usando la carpeta original.');
}

async function persistMigrationStartupResult(ok, errorMessage = '') {
  const migrationId = process.env.SOLRALOL_MIGRATION_ID;
  if (!migrationId) return;
  const roaming = process.env.APPDATA || path.join(require('node:os').homedir(), 'AppData', 'Roaming');
  const journalPath = path.join(roaming, 'Solralol', 'migration.json');
  try {
    const state = JSON.parse(await fs.readFile(journalPath, 'utf8'));
    if (state.migrationId !== migrationId) return;
    const expected = state.state === 'launching_source' ? state.source : state.destination;
    const correctRoot = path.resolve(activeStorageRoot).toLowerCase() === path.resolve(expected).toLowerCase();
    const succeeded = ok && correctRoot;
    const updated = { ...state, state: succeeded ? 'startup_verified' : 'startup_failed', phase: succeeded ? 'complete' : 'startup_failed',
      message: succeeded ? 'Solralol inició y confirmó la nueva ubicación.' : 'Solralol no pudo confirmar el inicio con la ubicación seleccionada.',
      startupRoot: activeStorageRoot, startupError: errorMessage || (!correctRoot ? 'La aplicación se inició con una raíz distinta a la solicitada.' : undefined), lastProgressAt: Date.now() };
    const temporary = `${journalPath}.${migrationId}.startup.tmp`;
    const handle = await fs.open(temporary, 'w');
    try { await handle.writeFile(`${JSON.stringify(updated, null, 2)}\n`, 'utf8'); await handle.sync(); }
    finally { await handle.close(); }
    await fs.rename(temporary, journalPath);
  } catch (error) { logDiagnostic(`Could not persist migration startup verification: ${error.message}`); }
}

function requestBackend(method, params = {}, timeoutOverride) {
  if (!allowlist.has(method) && !['overlay.tab-state', 'overlay.visibility'].includes(method)) return Promise.reject(new Error('Operation not allowed'));
  if (!backend || !backend.stdin.writable) {
    if (!backendRestarting && !quitting && (!backend || !stoppingBackends.has(backend))) setBackendLifecycle('error');
    return Promise.reject(new Error('Backend unavailable'));
  }
  const requestChild = backend;
  const id = `${++sequence}-${crypto.randomUUID()}`;
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => {
      pending.delete(id);
      if (method === 'app.bootstrap' && backend === requestChild && !backendRestarting && !quitting && !stoppingBackends.has(requestChild)) setBackendLifecycle('error');
      const stage = method === 'app.bootstrap' ? `; last Python stage: ${requestChild.solralolBootStage || 'process_spawned'}` : '';
      logDiagnostic(`Backend request timed out (method=${method}; pid=${requestChild.pid}${stage})`);
      reject(new Error(`Backend request timed out (${method}${stage})`));
    }, timeoutOverride ?? (method === 'home.sync' ? 120000 : method === 'meta.assets' ? 45000 : method === 'settings.recording-test' || method === 'settings.audio-devices' || method === 'recordings.stop' || method === 'recordings.list' ? 60000 : 15000));
    pending.set(id, { resolve, reject, timeout, method });
    requestChild.stdin.write(`${JSON.stringify({ protocol: 1, id, method, params })}\n`, (error) => {
      if (error) {
        clearTimeout(timeout);
        pending.delete(id);
        if (backend === requestChild && !backendRestarting && !quitting && !stoppingBackends.has(requestChild)) setBackendLifecycle('error', { message: error.message });
        reject(error);
      }
    });
  });
}

async function requestRecordings(method, params = {}) {
  if (method === 'recordings.review' || method === 'recordings.review.generate') {
    const entry = recordingFiles.get(params.id);
    if (entry?.active) throw new Error('La grabaciÃ³n sigue activa y aÃºn no se puede reproducir.');
    if (!entry) throw new Error('La grabación ya no está disponible. Actualiza la biblioteca.');
    const realFile = await fs.realpath(entry.file);
    if (path.dirname(realFile) !== entry.root) throw new Error('La grabación seleccionada no está disponible.');
    return requestBackend(method, { name: entry.name }, method.endsWith('.generate') ? 120000 : 30000);
  }
  if (method === 'recordings.source') {
    const entry = recordingFiles.get(params.id);
    if (entry?.active) return { state: 'unavailable' };
    if (!entry) return { state: 'missing' };
    try {
      const realFile = await fs.realpath(entry.file);
      if (path.dirname(realFile) !== entry.root) return { state: 'unavailable' };
      await fs.access(realFile, fsWatch.constants.R_OK);
      const stat = await fs.stat(realFile);
      return stat.isFile() ? { state: 'available', size: stat.size } : { state: 'missing' };
    } catch (error) {
      return error?.code === 'ENOENT' || error?.code === 'ENOTDIR'
        ? { state: 'missing' }
        : error?.code === 'EACCES' || error?.code === 'EPERM'
          ? { state: 'access_denied' }
          : { state: 'unavailable' };
    }
  }
  if (method === 'recordings.thumbnail') {
    const entry = recordingFiles.get(params.id);
    if (entry?.active) return { state: 'deferred', data: null };
    if (!entry) return { state: 'unavailable', data: null };
    try {
      const realFile = await fs.realpath(entry.file);
      if (path.dirname(realFile) !== entry.root) return { state: 'unavailable', data: null };
      return await requestBackend('recordings.thumbnail', { name: entry.name }, 60000);
    } catch (error) {
      logDiagnostic(`Recording thumbnail unavailable (${entry.name}; ${error?.code || error?.message || 'backend error'})`);
      return { state: 'unavailable', data: null };
    }
  }
  if (method !== 'recordings.list') {
    const result = await requestBackend(method, params);
    if (method === 'recordings.delete' && result?.deleted) {
      for (const [token, entry] of recordingFiles) if (entry.name === params.name) recordingFiles.delete(token);
      recordingTokensByName.delete(params.name);
    }
    return result;
  }
  const rows = await requestBackend('recordings.list', {});
  const settings = await requestBackend('settings.load', {});
  const root = path.resolve(settings.recording_output_dir || path.join(app.getPath('videos'), 'Solralol'));
  let realRoot;
  try {
    realRoot = await fs.realpath(root);
  } catch (error) {
    logDiagnostic(`Recording library directory unavailable (${error?.code || 'unknown'})`);
    throw new Error('No se puede acceder a la carpeta de grabaciones. Comprueba la ruta y sus permisos.');
  }
  if (!Array.isArray(rows)) throw new Error('El backend devolvió una biblioteca de grabaciones no válida.');
  const liveTokens = new Set();
  const result = await Promise.all(rows.map(async (row) => {
    if (!row || typeof row !== 'object' || Array.isArray(row) || typeof row.name !== 'string' || !row.name) {
      logDiagnostic('Recording library contained an invalid entry');
      throw new Error('El backend devolvió una grabación no válida.');
    }
    const file = path.resolve(root, row.name);
    if (path.dirname(file) !== root) {
      logDiagnostic(`Recording library entry rejected outside configured directory (${row.name})`);
      return { ...row, id: '', playbackUrl: null, available: false };
    }
    let realFile;
    try {
      realFile = await fs.realpath(file);
      if (path.dirname(realFile) !== realRoot) {
        logDiagnostic(`Recording library entry rejected outside canonical directory (${row.name})`);
        return { ...row, id: '', playbackUrl: null, available: false };
      }
      const stat = await fs.stat(realFile);
      if (!stat.isFile()) return { ...row, id: '', playbackUrl: null, available: false };
      await fs.access(realFile, fsWatch.constants.R_OK);
    } catch (error) {
      if (!['ENOENT', 'ENOTDIR', 'EACCES', 'EPERM'].includes(error?.code)) throw error;
      logDiagnostic(`Recording library entry unavailable (${row.name}; ${error.code})`);
      return { ...row, id: '', playbackUrl: null, available: false };
    }
    const token = recordingTokensByName.get(row.name) || crypto.randomUUID();
    recordingTokensByName.set(row.name, token);
    liveTokens.add(token);
    const isActive = row.active === true;
    recordingFiles.set(token, { file: realFile, name: row.name, root: realRoot, active: isActive });
    return { ...row, id: token, playbackUrl: isActive ? null : `solralol-recording://${token}/video`, available: !isActive };
  }));
  for (const [token, entry] of recordingFiles) if (!liveTokens.has(token) && !fsWatch.existsSync(entry.file)) recordingFiles.delete(token);
  return result;
}

function registerRecordingProtocol() {
protocol.handle('solralol-recording', async (request) => {
  let token = '';
  try {
    token = new URL(request.url).hostname;
    const entry = recordingFiles.get(token);
    if (!entry) {
      logDiagnostic(`Recording media unavailable (${token.slice(0, 8)}): authorized file missing`);
      return new Response(null, { status: 404, headers: { 'Cache-Control': 'no-store' } });
    }
    if (entry.active) return new Response(null, { status: 409, headers: { 'Cache-Control': 'no-store' } });
    const realFile = await fs.realpath(entry.file);
    if (path.dirname(realFile) !== entry.root) {
      logDiagnostic(`Recording media rejected outside canonical directory (${token.slice(0, 8)})`);
      return new Response(null, { status: 404, headers: { 'Cache-Control': 'no-store' } });
    }
    const stat = await fs.stat(realFile);
    if (!stat.isFile()) return new Response(null, { status: 404 });
    const range = request.method === 'GET' ? request.headers.get('range') : null;
    const headers = {
      'Accept-Ranges': 'bytes',
      'Content-Type': entry.file.toLowerCase().endsWith('.mkv') ? 'video/x-matroska' : 'video/mp4',
      'Cache-Control': 'no-store',
      'X-Content-Type-Options': 'nosniff',
    };
    if (!range || request.method === 'HEAD') {
      headers['Content-Length'] = String(stat.size);
      return new Response(request.method === 'HEAD' ? null : Readable.toWeb(fsWatch.createReadStream(realFile)), { status: 200, headers });
    }
    const match = /^bytes=(\d*)-(\d*)$/.exec(range);
    const invalidRange = () => new Response(null, { status: 416, headers: { ...headers, 'Content-Length': '0', 'Content-Range': `bytes */${stat.size}` } });
    if (!match || range.includes(',')) return invalidRange();
    let start;
    let end;
    if (!match[1]) {
      const suffixLength = Number(match[2]);
      if (!Number.isSafeInteger(suffixLength) || suffixLength <= 0 || stat.size <= 0) return invalidRange();
      start = Math.max(0, stat.size - suffixLength);
      end = stat.size - 1;
    } else {
      start = Number(match[1]);
      end = match[2] ? Number(match[2]) : stat.size - 1;
      if (match[2] && end < start) return invalidRange();
      end = Math.min(end, stat.size - 1);
    }
    if (!Number.isSafeInteger(start) || !Number.isSafeInteger(end) || start < 0 || start >= stat.size || start > end) return invalidRange();
    headers['Content-Length'] = String(end - start + 1);
    headers['Content-Range'] = `bytes ${start}-${end}/${stat.size}`;
    logDiagnostic(`Recording range served (${token.slice(0, 8)}): ${start}-${end}/${stat.size}`);
    return new Response(Readable.toWeb(fsWatch.createReadStream(realFile, { start, end })), { status: 206, headers });
  } catch (error) {
    logDiagnostic(`Recording protocol failure (${token.slice(0, 8) || 'unknown'}): ${error?.message || 'unknown error'}`);
    return new Response(null, { status: 500, headers: { 'Cache-Control': 'no-store' } });
  }
});
}

const OVERLAY_PANELS = ['gold', 'alerts', 'purchase', 'recall', 'ability'];
let overlayTabTimer;
let overlayTabBusy = false;
let overlayTabDown = false;

function watchOverlayTab(active) {
  const needed = active && OVERLAY_PANELS.some((panel) => panel !== 'ability' &&
    liveOverlaySettings?.overlay_panels?.[panel] !== false && liveOverlaySettings?.overlay_tab_only?.[panel]);
  if (!needed) {
    if (overlayTabTimer) clearInterval(overlayTabTimer);
    overlayTabTimer = undefined;
    overlayTabDown = false;
    return;
  }
  if (overlayTabTimer) return;
  overlayTabTimer = setInterval(() => {
    if (overlayTabBusy || backendLifecycle !== 'ready') return;
    overlayTabBusy = true;
    requestBackend('overlay.tab-state', {}, 1000).then((result) => {
      const down = Boolean(result?.down);
      if (down !== overlayTabDown) {
        overlayTabDown = down;
        if (lastLiveOverlayState) syncLiveOverlays(lastLiveOverlayState);
      }
    }).catch(() => {}).finally(() => { overlayTabBusy = false; });
  }, 100);
  overlayTabTimer.unref();
}

function applyLiveOverlaySettings(settings) {
  if (!settings || typeof settings !== 'object') return;
  liveOverlaySettings = settings;
  registerOverlayShortcut(settings.overlay_edit_shortcut);
  for (const panel of OVERLAY_PANELS) {
    const overlay = liveOverlayWindows.get(panel);
    if (!overlay || overlay.isDestroyed()) continue;
    try {
      const opacity = Math.max(0, Math.min(100, Number(settings.overlay_panel_opacity?.[panel] ?? 92))) / 100;
      if (Math.abs(overlay.getOpacity() - opacity) > 0.005) overlay.setOpacity(opacity);
      overlay.setIgnoreMouseEvents(!overlayEditing && (panel === 'ability' || panel === 'alerts' || Boolean(settings.overlay_panel_click_through?.[panel] ?? settings.overlay_click_through)), { forward: true });
      positionLiveOverlay(panel, overlay, settings);
    } catch (error) { logDiagnostic(`[OVERLAY] Settings application failed panel=${panel}: ${error.stack || error.message}`); }
  }
  if (lastLiveOverlayState) syncLiveOverlays(lastLiveOverlayState);
}

let registeredOverlayShortcut;
function registerOverlayShortcut(shortcut) {
  if (!app.isReady()) return;
  const accelerator = /^Control\+Alt\+Shift\+[A-Z]$/.test(shortcut || '') ? shortcut : 'Control+Alt+Shift+O';
  if (registeredOverlayShortcut === accelerator) return;
  if (registeredOverlayShortcut) globalShortcut.unregister(registeredOverlayShortcut);
  registeredOverlayShortcut = globalShortcut.register(accelerator, () => {
    try { setOverlayEditing(!overlayEditing); }
    catch (error) { logDiagnostic(`[OVERLAY] Editing shortcut failed: ${error.stack || error.message}`); }
  }) ? accelerator : undefined;
}

function setOverlayEditing(enabled) {
  overlayEditing = Boolean(enabled);
  for (const [panel, overlay] of liveOverlayWindows) {
    if (overlay.isDestroyed()) continue;
    try {
      overlay.setFocusable(overlayEditing);
      overlay.setIgnoreMouseEvents(!overlayEditing && (panel === 'ability' || panel === 'alerts' || Boolean(liveOverlaySettings?.overlay_panel_click_through?.[panel] ?? liveOverlaySettings?.overlay_click_through)), {forward:true});
      overlay.webContents.send('overlay:editing', overlayEditing);
    } catch (error) { logDiagnostic(`[OVERLAY] Editing state failed panel=${panel}: ${error.stack || error.message}`); }
  }
  if (windowRef && !windowRef.isDestroyed()) {
    try { windowRef.webContents.send('overlay:editing', overlayEditing); }
    catch (error) { logDiagnostic(`[OVERLAY] Main renderer editing notification failed: ${error.stack || error.message}`); }
  }
  syncLiveOverlays(lastLiveOverlayState || {state:'disconnected',source:'live',snapshot:null}, true);
}

function watchOverlayVisibility(active) {
  if (!active || overlayEditing || backendLifecycle !== 'ready') {
    if (overlayVisibilityTimer) clearInterval(overlayVisibilityTimer);
    overlayVisibilityTimer = undefined;
    overlayVisibility = {gameVisible:false, gameOccluded:true, coveredPanels:[]};
    return;
  }
  if (overlayVisibilityTimer) return;
  const check = () => {
    if (overlayVisibilityBusy || backendLifecycle !== 'ready') return;
    overlayVisibilityBusy = true;
    let overlays;
    try { overlays = [...liveOverlayWindows].filter(([, window]) => !window.isDestroyed()).map(([panel, window]) => {
      const bounds = window.getBounds();
      const a = screen.dipToScreenPoint({x:bounds.x,y:bounds.y});
      const b = screen.dipToScreenPoint({x:bounds.x+bounds.width,y:bounds.y+bounds.height});
      const handle = window.getNativeWindowHandle();
      const hwnd = handle.length >= 8 ? handle.readBigUInt64LE(0).toString() : String(handle.readUInt32LE(0));
      return {panel, hwnd, rect:{x:a.x,y:a.y,width:b.x-a.x,height:b.y-a.y}};
    }); } catch (error) {
      overlayVisibilityBusy = false;
      logDiagnostic(`[OVERLAY] Visibility geometry failed: ${error.stack || error.message}`);
      return;
    }
    requestBackend('overlay.visibility', {overlays}, 1100).then((result) => {
      const next = result && typeof result === 'object' ? result : {gameVisible:false,gameOccluded:true,coveredPanels:[]};
      if (JSON.stringify(next) !== JSON.stringify(overlayVisibility)) {
        overlayVisibility = next;
        if (lastLiveOverlayState) syncLiveOverlays(lastLiveOverlayState, true);
      }
    }).catch(() => {
      if (overlayVisibility.gameVisible || !overlayVisibility.gameOccluded) {
        overlayVisibility = {gameVisible:false,gameOccluded:true,coveredPanels:[]};
        if (lastLiveOverlayState) syncLiveOverlays(lastLiveOverlayState, true);
      }
    }).finally(() => { overlayVisibilityBusy = false; });
  };
  check();
  overlayVisibilityTimer = setInterval(check, 450);
  overlayVisibilityTimer.unref();
}
function positionLiveOverlay(panel, overlay, settings = liveOverlaySettings || {}) {
  const displayIndex = Number(lastLiveOverlayState?.snapshot?.gameMonitorIndex ?? settings.recording_monitor_index ?? -1);
  const displays = screen.getAllDisplays();
  const game = lastLiveOverlayState?.state === 'active' ? lastLiveOverlayState?.snapshot?.gameWindow : undefined;
  const raw = settings.overlay_positions?.[panel];
  let gameArea;
  if (game && Number.isFinite(game.x) && Number.isFinite(game.y) && game.width >= 640 && game.height >= 360) {
    const topLeft = screen.screenToDipPoint({x: game.x, y: game.y});
    const bottomRight = screen.screenToDipPoint({x: game.x + game.width, y: game.y + game.height});
    gameArea = {x:topLeft.x,y:topLeft.y,width:bottomRight.x-topLeft.x,height:bottomRight.y-topLeft.y};
  }
  const savedDisplay = !gameArea && Array.isArray(raw) ? screen.getDisplayMatching({x:Number(raw[0]),y:Number(raw[1]),width:80,height:80}) : undefined;
  const display = gameArea ? screen.getDisplayNearestPoint({x:Math.round(gameArea.x+gameArea.width/2),y:Math.round(gameArea.y+gameArea.height/2)})
    : savedDisplay || (Number.isInteger(displayIndex) && displayIndex >= 0 && displayIndex < displays.length
      ? displays[displayIndex] : screen.getPrimaryDisplay());
  const area = display.workArea;
  const scale = Math.max(0.5, Math.min(1.5, Number(settings.overlay_panel_scales?.[panel] ?? 1)));
  const slotSpacing = Math.max(43, Math.min(72, Number(settings.overlay_ability_slot_spacing ?? 47)));
  const width = Math.round((panel === 'purchase' ? 360 : panel === 'recall' ? 240 : panel === 'ability' ? 3 * slotSpacing + 65 : 320) * scale);
  const alertCount = overlayEditing ? 3 : Math.max(1, Math.min(3, lastLiveOverlayState?.snapshot?.overlay?.alerts?.length || 0));
  const height = Math.round((panel === 'alerts' ? alertCount * 86 + 12 : panel === 'recall' ? 250 : panel === 'gold' ? 220 : panel === 'purchase' ? 230 : panel === 'ability' ? 58 : 160) * scale);
  const base = gameArea || area;
  const defaults = {
    gold: [base.x + 20, base.y + 70], alerts: [base.x + base.width - width - 20, base.y + 70],
    purchase: [base.x + base.width - width - 20, base.y + base.height - height - 60],
    recall: [base.x + 20, base.y + 260],
    ability: [base.x + base.width * Number(settings.overlay_ability_hud_anchor?.x ?? 0.5) - width / 2,
      base.y + base.height * Number(settings.overlay_ability_hud_anchor?.y ?? 0.89) - height / 2],
  };
  const x = Array.isArray(raw) && Number.isFinite(Number(raw[0])) ? Number(raw[0]) : defaults[panel][0];
  const y = Array.isArray(raw) && Number.isFinite(Number(raw[1])) ? Number(raw[1]) : defaults[panel][1];
  const placement = gameArea || area;
  const target = { x: Math.max(placement.x, Math.min(placement.x + placement.width - Math.min(width,80), Math.round(x))),
    y: Math.max(placement.y, Math.min(placement.y + placement.height - Math.min(height,45), Math.round(y))), width, height };
  const old = overlay.getBounds();
  if (Object.keys(target).some((key) => target[key] !== old[key])) overlay.setBounds(target);
}

let overlayDisplayChangeTimer;
function repositionOverlaysAfterDisplayChange() {
  clearTimeout(overlayDisplayChangeTimer);
  overlayDisplayChangeTimer = setTimeout(() => {
    for (const [panel, overlay] of liveOverlayWindows) {
      if (!overlay.isDestroyed()) {
        try { positionLiveOverlay(panel, overlay); }
        catch (error) { logDiagnostic(`[OVERLAY] Display reposition failed panel=${panel}: ${error.stack || error.message}`); }
      }
    }
  }, 120);
}

function initializeDisplayManagement() {
  if (screenListenersRegistered) return;
  // Electron exposes screen only after app readiness. Keep this acquisition in
  // the centralized startup path so importing this module never touches it.
  screen = require('electron').screen;
  screen.on('display-added', repositionOverlaysAfterDisplayChange);
  screen.on('display-removed', repositionOverlaysAfterDisplayChange);
  screen.on('display-metrics-changed', repositionOverlaysAfterDisplayChange);
  screenListenersRegistered = true;
}

function disposeDisplayManagement() {
  if (!screenListenersRegistered || !screen) return;
  screen.removeListener('display-added', repositionOverlaysAfterDisplayChange);
  screen.removeListener('display-removed', repositionOverlaysAfterDisplayChange);
  screen.removeListener('display-metrics-changed', repositionOverlaysAfterDisplayChange);
  clearTimeout(overlayDisplayChangeTimer);
  overlayDisplayChangeTimer = undefined;
  screenListenersRegistered = false;
}

function liveOverlayPayload(state, panel) {
  const snapshot = state?.snapshot;
  if (!snapshot) return {state: state?.state, source: state?.source, snapshot: null,
    overlayPanelScale: liveOverlaySettings?.overlay_panel_scales?.[panel],
    abilitySlotSpacing: liveOverlaySettings?.overlay_ability_slot_spacing};
  const overlay = snapshot.overlay || {};
  const own = panel === 'gold' ? {gold: overlay.gold} : panel === 'alerts' ? {alerts: overlay.alerts}
    : panel === 'purchase' ? {recommendations: overlay.recommendations} : {};
  return {state: state.state, source: state.source, snapshot: {
    gameMode: snapshot.gameMode, gameTime: ['alerts', 'recall'].includes(panel) ? snapshot.gameTime : undefined,
    localPlayer: panel === 'ability' ? {championName: snapshot.localPlayer?.championName} : {},
    overlay: own,
    recommendations: panel === 'purchase' ? snapshot.recommendations : undefined,
    enemyShopTimers: panel === 'recall' ? snapshot.enemyShopTimers : undefined,
    pendingAbility: panel === 'ability' ? snapshot.pendingAbility : undefined,
    abilitySlotSpacing: panel === 'ability' ? liveOverlaySettings?.overlay_ability_slot_spacing : undefined,
    overlayPanelScale: liveOverlaySettings?.overlay_panel_scales?.[panel],
  }};
}

function createLiveOverlay(panel) {
  const overlay = new BrowserWindow({ width: 320, height: 160, show: false, frame: false,
    transparent: true, backgroundColor: '#00000000', resizable: false,
    minimizable: false, maximizable: false, focusable: overlayEditing, skipTaskbar: true,
    hasShadow: false, alwaysOnTop: true, fullscreenable: false,
    webPreferences: { preload: path.join(__dirname, '../preload/index.cjs'), contextIsolation: true,
      nodeIntegration: false, sandbox: true },
  });
  overlay.removeMenu();
  overlay.setAlwaysOnTop(true, 'screen-saver');
  overlay.setOpacity(Math.max(0, Math.min(100, Number(liveOverlaySettings?.overlay_panel_opacity?.[panel] ?? 92))) / 100);
  overlay.setIgnoreMouseEvents(!overlayEditing && (panel === 'ability' || panel === 'alerts' || Boolean(liveOverlaySettings?.overlay_panel_click_through?.[panel] ?? liveOverlaySettings?.overlay_click_through)), { forward: true });
  liveOverlayWindows.set(panel, overlay);
  logDiagnostic(`[OVERLAY] Created panel=${panel}; ${shutdownWindowContext()}`);
  try { positionLiveOverlay(panel, overlay); }
  catch (error) {
    liveOverlayWindows.delete(panel);
    overlay.destroy();
    throw error;
  }
  overlay.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  overlay.webContents.on('will-navigate', (event, target) => { if (!isTrustedRendererUrl(target)) event.preventDefault(); });
  overlay.webContents.on('did-finish-load', () => {
    if (lastLiveOverlayState && !overlay.isDestroyed()) overlay.webContents.send('overlay:live-state', liveOverlayPayload(lastLiveOverlayState, panel));
    overlay.webContents.send('overlay:editing', overlayEditing);
  });
  overlay.webContents.on('render-process-gone', (_event, details) => {
    logDiagnostic(`[OVERLAY] Renderer exited panel=${panel} reason=${details.reason} code=${details.exitCode}; ${shutdownWindowContext()}`);
    if (!overlay.isDestroyed()) overlay.close();
  });
  overlay.on('closed', () => {
    if (liveOverlayWindows.get(panel) === overlay) {
      liveOverlayWindows.delete(panel);
      liveOverlayPayloads.delete(panel);
    }
    clearTimeout(overlay.positionSaveTimer);
    logDiagnostic(`[OVERLAY] Closed panel=${panel}; ${shutdownWindowContext()}`);
  });
  overlay.on('moved', () => {
    if (!overlayEditing || overlay.isDestroyed() || !liveOverlaySettings) return;
    const {x, y} = overlay.getBounds();
    const previous = liveOverlaySettings.overlay_positions?.[panel];
    if (previous?.[0] === x && previous?.[1] === y) return;
    liveOverlaySettings.overlay_positions = {...liveOverlaySettings.overlay_positions, [panel]: [x, y]};
    clearTimeout(overlay.positionSaveTimer);
    overlay.positionSaveTimer = setTimeout(() => requestBackend('settings.update', {changes:{overlay_positions:{[panel]:[x,y]}}}).catch(() => {}), 400);
  });
  const target = path.join(__dirname, '../../dist/index.html');
  const loaded = app.isPackaged
    ? overlay.loadFile(target, { query: { overlay: panel } })
    : overlay.loadURL(`http://127.0.0.1:5173/?overlay=${panel}`);
  loaded.catch((error) => { logDiagnostic(`Live overlay failed to load (${error.message})`); if (!overlay.isDestroyed()) overlay.close(); });
  return overlay;
}

function syncLiveOverlays(state, visibilityOnly = false) {
  lastLiveOverlayState = state;
  if (!liveOverlaySettings) {
    if (!overlaySettingsRequest) {
      overlaySettingsRequest = true;
      requestBackend('settings.load').then(applyLiveOverlaySettings)
        .catch((error) => logDiagnostic(`Overlay settings unavailable (${error.message})`))
        .finally(() => { overlaySettingsRequest = false; });
    }
    return;
  }
  const active = state?.state === 'active' && state?.snapshot && state?.source === 'live';
  for (const panel of OVERLAY_PANELS) {
    try {
    const enabled = liveOverlaySettings.overlay_panels?.[panel] !== false;
    const contextual = panel === 'ability' ? Boolean(state.snapshot?.pendingAbility?.slot && state.snapshot?.gameWindow)
      : panel === 'alerts' ? Boolean(state.telemetry === 'current' && state.snapshot?.overlay?.alerts?.length) : true;
    const gameVisible = overlayVisibility.gameVisible && !overlayVisibility.gameOccluded
      && !overlayVisibility.coveredPanels?.includes(panel);
    const visible = Boolean(enabled && (overlayEditing || (active && gameVisible && contextual
      && (panel === 'ability' || !liveOverlaySettings.overlay_tab_only?.[panel] || overlayTabDown))));
    let overlay = liveOverlayWindows.get(panel);
    if (!overlay && visible) overlay = createLiveOverlay(panel);
    if (!overlay || overlay.isDestroyed()) continue;
    if (visible && !overlayEditing) positionLiveOverlay(panel, overlay);
    if (!visibilityOnly) {
      const payload = liveOverlayPayload(state, panel);
      const signature = JSON.stringify(payload);
      if (liveOverlayPayloads.get(panel) !== signature) {
        liveOverlayPayloads.set(panel, signature);
        overlay.webContents.send('overlay:live-state', payload);
      }
    }
    if (visible && !overlay.isVisible()) {
      overlay.showInactive();
      logDiagnostic(`[OVERLAY] Restored panel=${panel} reason=${overlayEditing ? 'editing' : 'game_visible'}`);
    } else if (!visible && overlay.isVisible()) {
      overlay.hide();
      const reason = !enabled ? 'disabled' : !active ? 'match_inactive' : !gameVisible ? 'game_occluded' : !contextual ? 'context_unavailable' : 'tab_restriction';
      logDiagnostic(`[OVERLAY] Hidden panel=${panel} reason=${reason}`);
    }
    } catch (error) {
      logDiagnostic(`[OVERLAY] Synchronization failed panel=${panel}: ${error.stack || error.message}`);
    }
  }
  watchOverlayTab(Boolean(active && !overlayEditing));
  watchOverlayVisibility(Boolean(active && !overlayEditing));
}

ipcMain.on('overlay:publish-live-state', (event, state) => {
  if (!trustedWindow({ sender: event.sender, senderFrame: event.senderFrame }) || !state || typeof state !== 'object'
    || !['disconnected','connected','lobby','champion_select','loading','active','game_ending','post_game'].includes(state.state)
    || !['current','stale','loading','unavailable'].includes(state.telemetry)
    || (state.snapshot && (typeof state.snapshot !== 'object' || !Array.isArray(state.snapshot.players) || state.snapshot.players.length > 10
      || !Array.isArray(state.snapshot.events) || state.snapshot.events.length > 100))) return;
  syncLiveOverlays(state);
});

ipcMain.handle('overlay:editing:get', (event) => trustedAppWindow(event) ? overlayEditing : false);
ipcMain.handle('overlay:editing:set', (event, enabled) => {
  if (!trustedAppWindow(event) || typeof enabled !== 'boolean') return false;
  setOverlayEditing(enabled);
  return overlayEditing;
});

function createWindow() {
  // Electron screen coordinates use DIP and workArea excludes the Windows taskbar.
  // On a smaller display, reduce the native minimum only enough to fit the usable area.
  const { workArea } = screen.getPrimaryDisplay();
  const minWidth = Math.max(1, Math.min(MIN_WINDOW_WIDTH, workArea.width));
  const minHeight = Math.max(1, Math.min(MIN_WINDOW_HEIGHT, workArea.height));
  const width = minWidth;
  const height = minHeight;
  const x = Math.round(workArea.x + (workArea.width - width) / 2);
  const y = Math.round(workArea.y + (workArea.height - height) / 2);

  windowRef = new BrowserWindow({
    x, y, width, height, minWidth, minHeight, backgroundColor: '#11110f',
    frame: false, titleBarStyle: 'hidden', titleBarOverlay: false,
    resizable: true, show: false, hasShadow: true,
    title: 'Solralol', webPreferences: {
      preload: path.join(__dirname, '../preload/index.cjs'), contextIsolation: true, nodeIntegration: false,
      sandbox: true,
    },
  });
  publishDevStatus('electron', 'starting', { pid: process.pid, detail: 'window created; waiting for renderer load' });
  windowRef.once('ready-to-show', () => windowRef?.show());
  const sendWindowState = () => {
    if (!windowRef || windowRef.isDestroyed()) return;
    windowRef.webContents.send('window:maximize-state', { maximized: windowRef.isMaximized() });
  };
  windowRef.on('maximize', sendWindowState);
  windowRef.on('unmaximize', sendWindowState);
  windowRef.removeMenu();
  windowRef.webContents.on('did-fail-load', (_event, code, description, url) => {
    publishDevStatus('electron', 'error', { pid: process.pid, detail: `renderer load failed (${code}): ${description}` });
    console.error(`Renderer navigation failed (${code}): ${description} [${url}]`);
  });
  windowRef.webContents.on('did-finish-load', () => {
    if (!windowRef || windowRef.isDestroyed() || !isTrustedRendererUrl(windowRef.webContents.getURL())) return;
    publishDevStatus('electron', 'running', { pid: process.pid, detail: 'renderer document loaded' });
  });
  windowRef.webContents.on('render-process-gone', (_event, details) => {
    publishDevStatus('electron', 'error', { pid: process.pid, detail: `renderer exited: ${details.reason} (${details.exitCode})` });
    console.error(`Renderer exited: ${details.reason} (${details.exitCode})`);
  });
  windowRef.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  windowRef.webContents.on('will-navigate', (event, target) => {
    if (!isTrustedRendererUrl(target)) event.preventDefault();
  });
  const loaded = app.isPackaged
    ? windowRef.loadFile(path.join(__dirname, '../../dist/index.html'))
    : windowRef.loadURL('http://127.0.0.1:5173');
  loaded.then(() => logDiagnostic('Renderer document loaded')).catch((error) => logDiagnostic(`Renderer load failed: ${error.message}`));
  windowRef.on('close', () => {
    const source = mainCloseIntent || (quitting ? 'application_quit' : 'native_main_window_close');
    mainCloseIntent = undefined;
    logDiagnostic(`[APP] Main window close event source=${source}; ${shutdownWindowContext()}`);
    void shutdownCoordinator.shutdown(source);
  });
  windowRef.on('closed', () => { logDiagnostic('[APP] Main window closed'); windowRef = undefined; });
}

ipcMain.handle('recordings:open-review', (event, id) => {
  if (!trustedWindow(event) || typeof id !== 'string' || !/^[a-f0-9-]{36}$/i.test(id)) return false;
  const entry = recordingFiles.get(id);
  if (entry?.active) return false;
  if (!entry) return false;
  const existing = reviewWindows.get(id);
  if (existing && !existing.isDestroyed()) { if (existing.isMinimized()) existing.restore(); existing.focus(); return true; }
  const { workArea } = screen.getPrimaryDisplay();
  const width = Math.min(1560, workArea.width);
  const height = Math.min(920, workArea.height);
  const review = new BrowserWindow({
    width, height, minWidth: Math.min(1120, workArea.width), minHeight: Math.min(700, workArea.height),
    backgroundColor: '#11110f', frame: false, titleBarStyle: 'hidden', titleBarOverlay: false, resizable: true, show: false,
    title: 'Repaso de partida · Solralol',
    webPreferences: { preload: path.join(__dirname, '../preload/index.cjs'), contextIsolation: true, nodeIntegration: false, sandbox: true },
  });
  reviewWindows.set(id, review);
  review.removeMenu();
  const sendReviewWindowState = () => { if (!review.isDestroyed()) review.webContents.send('window:maximize-state', { maximized: review.isMaximized() }); };
  review.on('maximize', sendReviewWindowState);
  review.on('unmaximize', sendReviewWindowState);
  review.once('ready-to-show', () => review.show());
  review.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  review.webContents.on('will-navigate', (navigation, target) => { if (!isTrustedRendererUrl(target)) navigation.preventDefault(); });
  review.on('closed', () => reviewWindows.delete(id));
  const target = path.join(__dirname, '../../dist/index.html');
  const loaded = app.isPackaged
    ? review.loadFile(target, { query: { review: id } })
    : review.loadURL(`http://127.0.0.1:5173/?review=${encodeURIComponent(id)}`);
  loaded.catch((error) => { logDiagnostic(`Review window failed to load (${error.message})`); if (!review.isDestroyed()) review.close(); });
  return true;
});

ipcMain.handle('soloq:open-analysis', (event, matchId) => {
  if (!trustedWindow(event) || typeof matchId !== 'string' || !/^[A-Za-z0-9_-]{1,120}$/.test(matchId)) return false;
  const existing = deepAnalysisWindows.get(matchId);
  if (existing && !existing.isDestroyed()) { if (existing.isMinimized()) existing.restore(); existing.focus(); return true; }
  const { workArea } = screen.getPrimaryDisplay();
  // El análisis necesita espacio para las comparativas y el marcador. Este
  // mínimo cabe en una pantalla de 1920×1080 y Electron lo aplica al redimensionar.
  const minWidth = 1440;
  const minHeight = 900;
  const analysisWindow = new BrowserWindow({
    width: Math.max(minWidth, Math.min(1680, workArea.width)),
    height: Math.max(minHeight, Math.min(1000, workArea.height)),
    minWidth, minHeight, maximizable: true, fullscreenable: true,
    backgroundColor: '#11110f', frame: false, titleBarStyle: 'hidden', titleBarOverlay: false,
    resizable: true, show: false, title: 'Análisis de partida · Solralol',
    webPreferences: { preload: path.join(__dirname, '../preload/index.cjs'), contextIsolation: true, nodeIntegration: false, sandbox: true },
  });
  deepAnalysisWindows.set(matchId, analysisWindow);
  analysisWindow.removeMenu();
  const sendWindowState = () => { if (!analysisWindow.isDestroyed()) analysisWindow.webContents.send('window:maximize-state', { maximized: analysisWindow.isMaximized() }); };
  analysisWindow.on('maximize', sendWindowState);
  analysisWindow.on('unmaximize', sendWindowState);
  analysisWindow.once('ready-to-show', () => analysisWindow.show());
  analysisWindow.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  analysisWindow.webContents.on('will-navigate', (navigation, target) => { if (!isTrustedRendererUrl(target)) navigation.preventDefault(); });
  analysisWindow.on('closed', () => deepAnalysisWindows.delete(matchId));
  const target = path.join(__dirname, '../../dist/index.html');
  const loaded = app.isPackaged
    ? analysisWindow.loadFile(target, { query: { analysis: matchId } })
    : analysisWindow.loadURL(`http://127.0.0.1:5173/?analysis=${encodeURIComponent(matchId)}`);
  loaded.catch((error) => { logDiagnostic(`SoloQ analysis window failed to load (${error.message})`); if (!analysisWindow.isDestroyed()) analysisWindow.close(); });
  return true;
});

ipcMain.handle('backend:request', (event, payload) => {
  if (!isTrustedRendererUrl(event.senderFrame?.url || '') || !payload || typeof payload.method !== 'string' || !allowlist.has(payload.method) || !validateRequest(payload.method, payload.params)) {
    throw new Error('Invalid request');
  }
  if (payload.method === 'storage.migrate.start') {
    migrationActive = true;
    migrationRestartScheduled = false;
    migrationOperationId = undefined;
    lastMigrationPhase = undefined;
  }
  return (payload.method.startsWith('recordings.') ? requestRecordings(payload.method, payload.params) : requestBackend(payload.method, payload.params, ['saved_matches.analysis.generate', 'soloq_analyses.analysis.generate', 'storage.preview', 'storage.migrate.start'].includes(payload.method) ? 120000 : undefined))
    .then((result) => {
      if (payload.method === 'storage.migrate.status') {
        migrationOperationId = result?.migrationId || migrationOperationId;
        if (result?.phase && result.phase !== lastMigrationPhase) {
          lastMigrationPhase = result.phase;
          logDiagnostic(`Storage migration ${migrationOperationId || 'unknown'} entered ${result.phase}`);
        }
        migrationActive = ['preparing', 'validating', 'copying', 'verifying', 'committing', 'reinitializing'].includes(result?.state);
        if (result?.state === 'complete') {
          migrationRecoveryRestarts = 0;
          migrationActive = false;
        } else if (['failed', 'recovery_required', 'cancelled'].includes(result?.state)) {
          migrationActive = false;
          logDiagnostic(`Storage migration entered ${result.state} (${result.migrationId || 'unknown'}; phase=${result.phase || 'unknown'})`);
        }
      }
      if (payload.method === 'analysis.settings.recalculation.status'
          && result?.state === 'completed') notifyAnalysisRecalculation(result);
      if (['saved_matches.sync', 'saved_matches.delete', 'saved_matches.analysis.generate',
           'soloq_analyses.list', 'soloq_analyses.register', 'soloq_analyses.detail',
           'soloq_analyses.delete', 'soloq_analyses.analysis.generate'].includes(payload.method)
          && windowRef && !windowRef.isDestroyed()) windowRef.webContents.send('home:saved-scores-changed');
      if (payload.method === 'analysis.settings.save' && result?.configuration) {
        const message = { revision: result.configuration.configuration_version, configurationHash: result.configuration.configuration_hash };
        for (const candidate of deepAnalysisWindows.values()) {
          if (candidate && !candidate.isDestroyed()) candidate.webContents.send('analysis:achievements-settings-changed', message);
        }
      }
      if (payload.method === 'settings.update') applyLiveOverlaySettings(result);
      if (payload.method === 'analysis.settings.save'
          && ['queued', 'running'].includes(result?.recalculation?.state)) monitorAnalysisRecalculation();
      if (payload.method === 'storage.migrate.start') {
        launchOfflineMigrationAssistant(result).catch((error) => {
          migrationActive = false;
          logDiagnostic(`Offline migration assistant could not start: ${error.message}`);
          requestBackend('storage.migrate.abort', { migrationId: result.migrationId }).catch((abortError) => logDiagnostic(`Could not release storage after assistant startup failure: ${abortError.message}`));
          if (windowRef && !windowRef.isDestroyed()) windowRef.webContents.send('solralol:migration-status', {
            ...result, state: 'failed', phase: 'failed', message: 'No se pudo iniciar el asistente. La carpeta original sigue activa.', error: error.message,
          });
        });
      }
      return result;
    })
    .catch((error) => {
      if (payload.method === 'storage.migrate.start') migrationActive = false;
      return ({
      __solralolError: {
        code: backendRestarting || backendLifecycle === 'stopping' || quitting ? 'backend_unavailable' : 'backend_request_failed',
        message: backendRestarting || backendLifecycle === 'stopping' || quitting
          ? 'El backend se está reiniciando o cerrando.'
          : (error?.message || 'No se pudo completar la solicitud al backend.'),
      },
      });
    });
});
ipcMain.handle('backend:status:get', (event) => trustedWindow(event)
  ? { state: backendLifecycle, ...(backendLifecycle === 'ready' && backendBootstrap ? { bootstrap: backendBootstrap } : {}) }
  : { state: 'error' });
function trustedWindow(event) {
  return windowRef && !windowRef.isDestroyed() && event.sender === windowRef.webContents && isTrustedRendererUrl(event.senderFrame?.url || '');
}
function trustedAppWindow(event) {
  if (!isTrustedRendererUrl(event.senderFrame?.url || '')) return null;
  if (windowRef && !windowRef.isDestroyed() && event.sender === windowRef.webContents) return windowRef;
  for (const candidate of reviewWindows.values()) if (candidate && !candidate.isDestroyed() && event.sender === candidate.webContents) return candidate;
  for (const candidate of deepAnalysisWindows.values()) if (candidate && !candidate.isDestroyed() && event.sender === candidate.webContents) return candidate;
  return null;
}
ipcMain.handle('window:minimize', (event) => { trustedAppWindow(event)?.minimize(); });
ipcMain.handle('window:close', (event) => {
  const target = trustedAppWindow(event);
  if (target === windowRef) mainCloseIntent = 'renderer_close_button';
  target?.close();
});
ipcMain.handle('window:toggle-maximize', (event) => {
  const target = trustedAppWindow(event);
  if (!target) return false;
  if (target.isMaximized()) target.unmaximize(); else target.maximize();
  return target.isMaximized();
});
ipcMain.handle('window:get-state', (event) => ({ maximized: trustedAppWindow(event)?.isMaximized() || false }));
ipcMain.handle('settings:get-displays', (event) => {
  if (!trustedWindow(event)) return [];
  return screen.getAllDisplays().map((display, index) => ({ index, width: display.size.width, height: display.size.height }));
});
ipcMain.handle('settings:choose-recordings-directory', async (event) => {
  if (!trustedWindow(event)) return null;
  const saved = await requestBackend('settings.load').catch(() => ({}));
  const result = await dialog.showOpenDialog(windowRef, {
    title: 'Carpeta de grabaciones', defaultPath: saved.recording_output_dir || app.getPath('videos'),
    properties: ['openDirectory', 'createDirectory'],
  });
  if (result.canceled || !result.filePaths[0]) return null;
  await requestBackend('settings.update', { changes: { recording_output_dir: result.filePaths[0] } });
  return result.filePaths[0];
});
ipcMain.handle('storage:choose-directory', async (event) => {
  if (!trustedWindow(event)) return null;
  const result = await dialog.showOpenDialog(windowRef, {
    title: 'Directorio de datos de Solralol', defaultPath: activeStorageRoot,
    properties: ['openDirectory', 'createDirectory'],
  });
  return result.canceled ? null : (result.filePaths[0] || null);
});
ipcMain.handle('storage:open-directory', async (event) => {
  if (!trustedWindow(event)) return 'Ventana no autorizada';
  const info = await requestBackend('storage.info');
  await fs.mkdir(info.root, { recursive: true });
  return shell.openPath(info.root);
});
ipcMain.handle('settings:open-recordings-directory', async (event) => {
  if (!trustedWindow(event)) return 'Ventana no autorizada';
  const saved = await requestBackend('settings.load');
  const directory = saved.recording_output_dir;
  if (typeof directory !== 'string' || !directory) return 'No hay una carpeta configurada';
  await fs.mkdir(directory, { recursive: true });
  return shell.openPath(directory);
});
ipcMain.handle('settings:open-provider-url', async (event, target) => {
  if (!trustedWindow(event)) return false;
  const urls = new Map([
    ['riot', 'https://developer.riotgames.com/'],
    ['gemini', 'https://aistudio.google.com/apikey'],
  ]);
  if (!urls.has(target)) return false;
  await shell.openExternal(urls.get(target));
  return true;
});
ipcMain.handle('meta:open-source', async (event, rawUrl) => {
  if (!trustedWindow(event) || typeof rawUrl !== 'string' || rawUrl.length > 2048) return false;
  try {
    const url = new URL(rawUrl);
    const allowed = url.protocol === 'https:' && (
      (url.hostname === 'lolalytics.com' && url.pathname.startsWith('/es/lol/tierlist')) ||
      ((url.hostname === 'leagueoflegends.com' || url.hostname.endsWith('.leagueoflegends.com')) && url.pathname.startsWith('/es-es/news/game-updates/'))
    );
    if (!allowed) return false;
    await shell.openExternal(url.href);
    return true;
  } catch { return false; }
});

logDiagnostic(`Electron main loaded (${process.versions.electron || 'unknown'}; ready=${app.isReady()})`);
if (hasSingleInstanceLock) app.on('second-instance', () => {
  if (!windowRef || windowRef.isDestroyed()) return;
  if (windowRef.isMinimized()) windowRef.restore();
  windowRef.show();
  windowRef.focus();
});
app.on('ready', () => logDiagnostic('Electron ready event fired'));
app.on('will-quit', () => { disposeDisplayManagement(); globalShortcut.unregisterAll(); logDiagnostic('Electron will-quit event fired'); });
app.on('quit', (_event, code) => logDiagnostic(`Electron quit (${code})`));
app.whenReady().then(() => {
  if (!hasSingleInstanceLock) return;
  initializeDisplayManagement();
  publishDevStatus('electron', 'starting', { pid: process.pid, detail: 'Electron main initialized' });
  registerRecordingProtocol();
  diagnosticRoot = path.join(activeStorageRoot, 'logs');
  for (const line of startupLogs.splice(0)) {
    fs.mkdir(diagnosticRoot, { recursive: true }).then(() => fs.appendFile(path.join(diagnosticRoot, 'desktop.log'), line, 'utf8')).catch(() => {});
  }
  logDiagnostic(`Electron ready (packaged=${app.isPackaged})`);
  setupDevelopmentWatchers();
  createWindow();
  startBackend().then(() => persistMigrationStartupResult(true)).catch((error) => {
    setBackendLifecycle('error', { message: error.message });
    logDiagnostic(`Backend startup did not become ready: ${error.message}`);
    persistMigrationStartupResult(false, error.message);
  });
  if (!app.isPackaged) logDiagnostic('Solralol dev ready');
})
  .catch((error) => logDiagnostic(`Electron startup failed: ${error.stack || error.message}`));
app.on('before-quit', (event) => {
  if (shutdownCoordinator.complete) return;
  event.preventDefault();
  void shutdownCoordinator.shutdown('before-quit');
});
if (!app.isPackaged) {
  process.on('message', async (message) => {
    if (message?.type === 'dev-restart-backend') {
      if (quitting || backendRestarting) return;
      backendRestarting = true;
      logDiagnostic('Manual backend restart requested');
      setBackendLifecycle('restarting');
      try {
        await stopBackend();
        if (!quitting) await startBackend();
      } catch (error) {
        logDiagnostic(`Manual backend restart failed: ${error.message}`);
        setBackendLifecycle('error', { message: error.message });
      } finally {
        backendRestarting = false;
      }
      return;
    }
    if (message?.type !== 'dev-restart' && message?.type !== 'dev-shutdown') return;
    const shouldRestart = message.type === 'dev-restart';
    if (quitting) return;
    if (shouldRestart) {
      logDiagnostic('Restarting Electron after source change');
      setBackendLifecycle('stopping');
      await stopBackend();
      for (const watcher of developmentWatchers) watcher.close();
      app.quit();
    } else {
      void shutdownCoordinator.shutdown('development-host-close');
    }
  });
}
app.on('window-all-closed', () => {
  logDiagnostic(`[APP] window-all-closed; ${shutdownWindowContext()}`);
  if (windowRef && !windowRef.isDestroyed()) {
    logDiagnostic('[APP] Ignored auxiliary window close while main window is alive');
    return;
  }
  void shutdownCoordinator.shutdown('all-windows-closed');
});
