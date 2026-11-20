const { spawn } = require('node:child_process');
const path = require('node:path');
const fs = require('node:fs');
const electronPath = require('electron');
const electronEnv = { ...process.env };
delete electronEnv.ELECTRON_RUN_AS_NODE;
const electronArgs = [];
if (process.env.SOLRALOL_ELECTRON_INSPECT_PORT) {
  electronArgs.push(`--inspect=${process.env.SOLRALOL_ELECTRON_INSPECT_PORT}`);
}
electronArgs.push('.');
const cwd = path.resolve(__dirname, '..');
let child;
let restarting = false;
let shuttingDown = false;
let migrationWaiting = false;
let migrationJournalPath;
let migrationPoll;

function launch() {
  child = spawn(electronPath, electronArgs, {
    cwd,
    stdio: ['inherit', 'inherit', 'inherit', 'ipc'],
    windowsHide: false,
    env: electronEnv,
  });
  child.on('message', (message) => {
    if (message?.type === 'solralol-status' && process.connected) process.send(message);
    if (message?.type === 'solralol-storage-migration-started') {
      migrationWaiting = true;
      migrationJournalPath = message.journalPath;
      if (process.connected) process.send({ type: 'solralol-storage-migration-started', migrationId: message.migrationId });
    }
    if (message?.type === 'solralol-storage-restart' && child && !restarting && !shuttingDown) {
      if (typeof message.root === 'string' && message.root.trim()) {
        electronEnv.SOLRALOL_DATA_DIR = message.root;
        process.env.SOLRALOL_DATA_DIR = message.root;
      }
      restarting = true;
      if (process.connected) process.send({
        type: 'solralol-status', component: 'electron', state: 'restarting',
        details: { detail: 'Aplicando la nueva ubicación de almacenamiento' },
      });
      child.send({ type: 'dev-restart' });
    }
  });
  if (process.connected) process.send({ type: 'solralol-status', component: 'electron', state: 'starting', details: { pid: child.pid, detail: 'Electron process spawned' } });
  child.on('error', (error) => { console.error('Could not start Electron:', error.message); process.exitCode = 1; });
  child.on('exit', (code, signal) => {
    if (restarting && !shuttingDown) {
      restarting = false;
      launch();
      return;
    }
    if (migrationWaiting && !shuttingDown) {
      if (process.connected) process.send({ type: 'solralol-status', component: 'electron', state: 'stopped', details: { detail: 'Asistente independiente en ejecución' } });
      pollMigrationJournal();
      return;
    }
    if (signal) process.kill(process.pid, signal);
    else process.exit(code ?? 1);
  });
}

function pollMigrationJournal() {
  clearTimeout(migrationPoll);
  if (shuttingDown || !migrationWaiting || !migrationJournalPath) return;
  let journal;
  try { journal = JSON.parse(fs.readFileSync(migrationJournalPath, 'utf8')); } catch {}
  if (journal?.state === 'launching_destination' || journal?.state === 'launching_source') {
    const root = journal.launchRoot || (journal.state === 'launching_destination' ? journal.destination : journal.source);
    if (typeof root === 'string') {
      electronEnv.SOLRALOL_DATA_DIR = root;
      process.env.SOLRALOL_DATA_DIR = root;
      electronEnv.SOLRALOL_MIGRATION_ID = journal.migrationId;
      process.env.SOLRALOL_MIGRATION_ID = journal.migrationId;
    }
    migrationWaiting = false;
    restarting = false;
    if (process.connected) process.send({ type: 'solralol-storage-migration-finished', state: journal.state, root });
    launch();
    return;
  }
  migrationPoll = setTimeout(pollMigrationJournal, 700);
  migrationPoll.unref();
}

process.on('message', (message) => {
  if (message?.type === 'restart-backend' && child && !restarting && !shuttingDown) {
    if (migrationWaiting) return;
    child.send({ type: 'dev-restart-backend' });
  } else
  if (message?.type === 'restart' && child && !restarting && !shuttingDown) {
    if (migrationWaiting) return;
    restarting = true;
    if (process.connected) process.send({ type: 'solralol-status', component: 'electron', state: 'restarting', details: { detail: 'Electron source changed; relaunching' } });
    child.send({ type: 'dev-restart' });
  } else if (message?.type === 'shutdown' && child && !shuttingDown) {
    shuttingDown = true;
    child.send({ type: 'dev-shutdown' });
  }
});
process.on('SIGINT', () => {
  if (child && !shuttingDown) { shuttingDown = true; child.send({ type: 'dev-shutdown' }); }
});
process.on('SIGTERM', () => {
  if (child && !shuttingDown) { shuttingDown = true; child.send({ type: 'dev-shutdown' }); }
});

launch();
