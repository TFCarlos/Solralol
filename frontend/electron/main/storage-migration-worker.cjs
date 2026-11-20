const { parentPort, workerData } = require('node:worker_threads');
const fs = require('node:fs');
const fsp = require('node:fs/promises');
const path = require('node:path');
const crypto = require('node:crypto');

const config = workerData;
const journalFile = config.journalPath;
const id = config.migrationId;
const stage = `${config.destination}.solralol-stage-${id}`;
let status = {
  migrationId: id, state: 'validating', phase: 'validating', message: 'Verificando archivos',
  source: config.source, destination: config.destination, stage, totalBytes: config.totalBytes || 0,
  currentBytes: 0, verifiedBytes: 0, fileCount: config.fileCount || 0, processedFiles: 0,
  lastProgressAt: Date.now(), currentFile: '',
};
let lastWrite = 0;
let lastLog = 0;
let lastMessage = 0;
let loggedPhase = '';
let publishedPhase = '';
async function logLine(message) {
  if (!config.logPath) return;
  try { await fsp.appendFile(config.logPath, `[${new Date().toISOString()}] ${message}\n`, 'utf8'); } catch {}
}
function publish(phase, message, extra = {}, force = false) {
  status = { ...status, ...extra, phase, state: phase, message, lastProgressAt: Date.now() };
  const now = Date.now();
  if (force || phase !== publishedPhase || now - lastMessage >= 250) {
    parentPort.postMessage({ type: 'progress', value: status });
    lastMessage = now; publishedPhase = phase;
  }
  if (phase !== loggedPhase || now - lastLog >= 10000 || ['complete', 'failed'].includes(phase)) {
    loggedPhase = phase; lastLog = now;
    void logLine(`id=${id} fase=${phase} bytes=${status.currentBytes}/${status.totalBytes} archivos=${status.processedFiles}/${status.fileCount} archivo=${status.currentFile || '-'} mensaje=${message}`);
  }
  if (force || now - lastWrite >= 1000 || ['complete', 'failed', 'recovery_required'].includes(phase)) {
    lastWrite = now;
    writeJsonAtomic(journalFile, status).catch((error) => parentPort.postMessage({ type: 'fatal', message: error.message }));
  }
}
async function writeJsonAtomic(file, value) {
  await fsp.mkdir(path.dirname(file), { recursive: true });
  const temp = `${file}.${id}.${process.pid}.tmp`;
  const handle = await fsp.open(temp, 'w');
  try { await handle.writeFile(`${JSON.stringify(value, null, 2)}\n`, 'utf8'); await handle.sync(); }
  finally { await handle.close(); }
  await renameWithRetry(temp, file);
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
async function* walk(root, relative = '') {
  const entries = await fsp.readdir(path.join(root, relative), { withFileTypes: true });
  for (const entry of entries) {
    if (entry.isSymbolicLink()) throw new Error(`Hay un enlace simbólico que requiere revisión manual: ${entry.name}`);
    const rel = path.join(relative, entry.name);
    if (entry.isDirectory()) yield* walk(root, rel);
    else if (entry.isFile()) yield { root, relative: rel, source: path.join(root, rel) };
  }
}
function sourceSets() {
  const sets = [];
  if (config.includeExistingDestination) sets.push({ root: config.destination, target: stage, ignored: new Set(['.solralol-storage.json']), kind: 'existing' });
  sets.push({ root: config.source, target: stage, ignored: new Set(), kind: 'active' });
  if (config.extraElectronData) sets.push({ root: config.extraElectronData, target: path.join(stage, 'electron'), ignored: new Set(['storage.json']), kind: 'extra' });
  for (const root of config.extraRecordings || []) sets.push({ root, target: path.join(stage, 'recordings', 'videos'), ignored: new Set(), kind: 'extra' });
  return sets;
}
async function digest(file) {
  const hash = crypto.createHash('sha256');
  for await (const chunk of fs.createReadStream(file)) hash.update(chunk);
  return hash.digest('hex');
}
async function copyAndVerify(entry, target) {
  await fsp.mkdir(path.dirname(target), { recursive: true });
  const sourceStat = await fsp.stat(entry.source);
  const existingStage = await fsp.stat(target).catch(() => null);
  if (existingStage?.isFile() && existingStage.size === sourceStat.size && await digest(entry.source) === await digest(target)) {
    try { await fsp.utimes(target, sourceStat.atime, sourceStat.mtime); } catch {}
    try { await fsp.chmod(target, sourceStat.mode); } catch {}
    status.currentBytes += sourceStat.size; status.verifiedBytes += sourceStat.size; status.processedFiles += 1;
    publish('copying', 'Copiando datos', { currentFile: path.basename(entry.source) });
    return { size: sourceStat.size, reused: true };
  }
  const temp = `${target}.${id}.partial`;
  await fsp.rm(temp, { force: true });
  const sourceHash = crypto.createHash('sha256');
  await new Promise((resolve, reject) => {
    const input = fs.createReadStream(entry.source, { highWaterMark: 1024 * 1024 });
    const output = fs.createWriteStream(temp, { flags: 'wx', highWaterMark: 1024 * 1024 });
    input.on('data', (chunk) => { sourceHash.update(chunk); status.currentBytes += chunk.length; publish('copying', 'Copiando datos', { currentFile: path.basename(entry.source) }); });
    input.on('error', reject); output.on('error', reject); output.on('close', resolve); input.pipe(output);
  });
  const handle = await fsp.open(temp, 'r+');
  try { await handle.sync(); } finally { await handle.close(); }
  await renameWithRetry(temp, target);
  try { await fsp.utimes(target, sourceStat.atime, sourceStat.mtime); } catch {}
  try { await fsp.chmod(target, sourceStat.mode); } catch {}
  const targetHash = await digest(target);
  if (sourceHash.digest('hex') !== targetHash || (await fsp.stat(target)).size !== sourceStat.size) throw new Error(`No coincide la verificación de ${path.basename(entry.source)}`);
  status.verifiedBytes += sourceStat.size;
  status.processedFiles += 1;
  publish('copying', 'Copiando datos', { currentFile: path.basename(entry.source) });
  return { size: sourceStat.size, reused: false };
}
async function validateCriticalFiles() {
  const critical = ['settings.json', 'match_history_cache.json'];
  for (const relative of critical) {
    const file = path.join(stage, relative);
    try {
      const parsed = JSON.parse(await fsp.readFile(file, 'utf8'));
      if (!parsed || typeof parsed !== 'object') throw new Error('formato inválido');
    } catch (error) {
      if (error.code === 'ENOENT') continue;
      throw new Error(`No se pudo validar ${relative}: ${error.message}`);
    }
  }
  let sqlite;
  try { sqlite = require('node:sqlite'); } catch { sqlite = null; }
  const databases = [];
  for await (const entry of walk(stage)) if (/\.(?:sqlite|sqlite3|db)$/i.test(entry.relative) && !/-wal$|-shm$/i.test(entry.relative)) databases.push(entry.source);
  if (databases.length && !sqlite?.DatabaseSync) throw new Error('No está disponible la comprobación de integridad de las bases de datos en este equipo.');
  for (const file of databases) {
    const db = new sqlite.DatabaseSync(file, { readOnly: true });
    try { const row = db.prepare('PRAGMA integrity_check').get(); if (Object.values(row || {})[0] !== 'ok') throw new Error(`Integridad incorrecta en ${path.basename(file)}`); }
    finally { db.close(); }
  }
}
function friendlyError(error) {
  if (error?.code === 'ENOSPC') return 'No hay espacio suficiente para completar la copia.';
  if (['ENOENT', 'ENOTDIR'].includes(error?.code)) return 'No se encuentra el origen o el destino. Comprueba que la unidad siga disponible.';
  if (['EACCES', 'EPERM', 'EBUSY', 'ELOCKED'].includes(error?.code)) return 'Un archivo sigue en uso o no se puede escribir en la carpeta de destino.';
  if (error?.message?.includes('carpeta de destino contiene archivos ajenos')) return error.message;
  if (error?.message?.includes('mismo nombre')) return error.message;
  if (error?.message?.includes('enlace simbólico')) return error.message;
  if (error?.message?.includes('validar')) return 'No se pudo validar un archivo de configuración. La carpeta original permanece activa.';
  if (error?.message?.includes('integridad')) return 'La comprobación de integridad de una base de datos no coincide. La carpeta original permanece activa.';
  return 'No se pudo copiar o verificar uno de los archivos. La ubicación original permanece activa.';
}
async function setActiveRoot() {
  const settingsPath = path.join(config.destination, 'settings.json');
  try {
    const settings = JSON.parse(await fsp.readFile(settingsPath, 'utf8'));
    if (typeof settings.recording_output_dir === 'string' && settings.recording_output_dir) {
      settings.recording_output_dir = path.join(config.destination, 'recordings', 'videos');
      await writeJsonAtomic(settingsPath, settings);
    }
  } catch (error) { if (error.code !== 'ENOENT') throw error; }
  await fsp.mkdir(path.dirname(config.pointerPath), { recursive: true });
  const pointer = `${config.pointerPath}.${id}.tmp`;
  const handle = await fsp.open(pointer, 'w');
  try { await handle.writeFile(`${JSON.stringify({ data_root: config.destination }, null, 2)}\n`, 'utf8'); await handle.sync(); }
  finally { await handle.close(); }
  await renameWithRetry(pointer, config.pointerPath);
}
async function run() {
  try {
    publish('validating', 'Preparando archivos', {}, true);
    await fsp.mkdir(stage, { recursive: true });
    const sets = sourceSets();
    const manifest = [];
    for (const set of sets) for await (const entry of walk(set.root)) {
      if (set.ignored.has(path.basename(entry.relative))) continue;
      if (set.kind === 'existing' && entry.relative.startsWith(`.solralol-stage-${id}${path.sep}`)) continue;
      if (set.root === config.extraElectronData && (entry.relative === 'migration.json' || entry.relative.startsWith(`migrations${path.sep}`))) continue;
      const targetRelative = path.relative(set.root, entry.source);
      manifest.push({ ...entry, kind: set.kind, target: path.join(set.target, targetRelative) });
    }
    const targetSources = new Map();
    const uniqueManifest = [];
    for (const item of manifest) {
      const key = path.resolve(item.target).toLowerCase();
      const previous = targetSources.get(key);
      if (!previous) { targetSources.set(key, item); uniqueManifest.push(item); continue; }
      const same = await fsp.stat(previous.source).then((v) => v.size) === await fsp.stat(item.source).then((v) => v.size)
        && await digest(previous.source) === await digest(item.source);
      if (same) continue;
      if (previous.kind === 'existing' && item.kind === 'active') {
        targetSources.set(key, item);
        uniqueManifest[uniqueManifest.indexOf(previous)] = item;
        continue;
      }
      throw new Error(`Dos carpetas contienen archivos distintos con el mismo nombre: ${path.basename(item.target)}`);
    }
    manifest.length = 0; manifest.push(...uniqueManifest);
    status.totalBytes = 0;
    for (const item of manifest) status.totalBytes += (await fsp.stat(item.source)).size;
    status.fileCount = manifest.length;
    const volume = await fsp.statfs(path.dirname(config.destination));
    const freeBytes = Number(volume.bavail) * Number(volume.bsize);
    if (freeBytes < status.totalBytes) throw Object.assign(new Error('No hay espacio suficiente para completar la copia.'), { code: 'ENOSPC' });
    const destStat = await fsp.stat(config.destination).catch(() => null);
    if (destStat?.isDirectory()) {
      const names = await fsp.readdir(config.destination);
      if (names.length && !names.includes('.solralol-storage.json') && !config.includeExistingDestination) throw new Error('La carpeta de destino contiene archivos ajenos a Solralol. Elige una carpeta vacía para protegerlos.');
    } else if (destStat) throw new Error('La ruta de destino ya existe y no es una carpeta.');
    await writeJsonAtomic(path.join(stage, `.solralol-migration-${id}.manifest.json`), manifest.map(({ source, target, root, relative }) => ({ source, target, root, relative })));
    publish('copying', 'Copiando datos', {}, true);
    for (const entry of manifest) {
      await copyAndVerify(entry, entry.target);
    }
    publish('verifying', 'Comprobando integridad', {}, true);
    await validateCriticalFiles();
    const marker = { migrationId: id, verifiedAt: new Date().toISOString(), fileCount: manifest.length, totalBytes: status.totalBytes };
    await writeJsonAtomic(path.join(stage, '.solralol-storage.json'), marker);
    publish('committing', 'Configurando nueva ubicación', {}, true);
    // Preserve a pre-existing target and never replace an unrelated directory.
    const targetExists = await fsp.stat(config.destination).then(() => true, () => false);
    if (targetExists) {
      const names = await fsp.readdir(config.destination).catch(() => []);
      const recognized = names.includes('.solralol-storage.json') || config.destination === config.source;
      if (names.length && !recognized) throw new Error('La carpeta de destino contiene archivos ajenos a Solralol. Elige una carpeta vacía para protegerlos.');
      if (names.length) {
        const old = `${config.destination}.previous-${id}`;
        await renameWithRetry(config.destination, old);
        status.previousDestination = old;
      } else await fsp.rmdir(config.destination);
    }
    await renameWithRetry(stage, config.destination);
    await setActiveRoot();
    publish('complete', 'Migración completada', { currentBytes: status.totalBytes, verifiedBytes: status.totalBytes, processedFiles: status.fileCount, currentFile: '', result: { root: config.destination, fileCount: status.fileCount, migratedBytes: status.totalBytes } }, true);
    parentPort.postMessage({ type: 'complete', value: status });
  } catch (error) {
    await logLine(`id=${id} error fase=${status.phase} ${error.stack || error.message}`);
    const message = friendlyError(error);
    publish('failed', 'No se pudo completar la migración. La ubicación original permanece activa.', { error: message, currentFile: status.currentFile }, true);
    parentPort.postMessage({ type: 'failed', message, value: status });
  }
}
run();
