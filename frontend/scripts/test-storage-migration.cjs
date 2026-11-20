const assert = require('node:assert/strict');
const fs = require('node:fs');
const fsp = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { Worker } = require('node:worker_threads');
const { randomUUID, createHash } = require('node:crypto');

const workerFile = path.resolve(__dirname, '../electron/main/storage-migration-worker.cjs');
const gib = 1024 * 1024 * 1024;
const runLarge = process.argv.includes('--large');

async function runWorker(config) {
  return new Promise((resolve, reject) => {
    const worker = new Worker(workerFile, { workerData: config });
    worker.on('message', (message) => {
      if (message.type === 'complete') resolve(message.value);
      if (message.type === 'failed') reject(new Error(message.message));
      if (message.type === 'fatal') reject(new Error(message.message));
    });
    worker.on('error', reject);
    worker.on('exit', (code) => { if (code && code !== 0) reject(new Error(`worker exit ${code}`)); });
  });
}

async function interruptAtVerification(config) {
  const worker = new Worker(workerFile, { workerData: config });
  await new Promise((resolve, reject) => {
    worker.on('message', (message) => {
      if (message.type === 'progress' && message.value?.phase === 'verifying') {
        worker.terminate().then(resolve, reject);
      }
      if (message.type === 'failed') reject(new Error(message.message));
    });
    worker.on('error', reject);
  });
}

async function sha256(file) {
  const hash = createHash('sha256');
  for await (const chunk of fs.createReadStream(file)) hash.update(chunk);
  return hash.digest('hex');
}

async function main() {
  const root = await fsp.mkdtemp(path.join(os.tmpdir(), 'solralol-offline-migration-'));
  const source = path.join(root, 'origen con espacios');
  const destination = path.join(root, 'destino con espacios');
  const pointerPath = path.join(root, 'bootstrap', 'storage.json');
  const journalPath = path.join(root, 'bootstrap', 'migration.json');
  const id = randomUUID();
  try {
    await fsp.mkdir(path.join(source, 'recordings', 'videos'), { recursive: true });
    await fsp.writeFile(path.join(source, 'settings.json'), JSON.stringify({ recording_output_dir: path.join(source, 'recordings', 'videos') }));
    await fsp.writeFile(path.join(source, 'match_history_cache.json'), JSON.stringify({ matches: Array.from({ length: 168 }, (_, i) => `EUW1_${i}`) }));
    for (let i = 0; i < 3000; i++) await fsp.writeFile(path.join(source, `cache-${i}.json`), `{"n":${i}}`);
    const video = path.join(source, 'recordings', 'videos', 'partida.mp4');
    const videoSize = runLarge ? 1024 * 1024 * 1024 + 64 * 1024 * 1024 : 24 * 1024 * 1024;
    const videoHandle = await fsp.open(video, 'w');
    try { await videoHandle.truncate(videoSize); } finally { await videoHandle.close(); }
    await fsp.mkdir(path.dirname(pointerPath), { recursive: true });
    await fsp.writeFile(pointerPath, JSON.stringify({ data_root: source }));
    const result = await runWorker({ migrationId: id, source, destination, pointerPath, journalPath,
      extraRecordings: [], extraElectronData: null, includeExistingDestination: false,
      totalBytes: videoSize, fileCount: 3002 });
    assert.equal(result.state, 'complete');
    assert.equal(JSON.parse(await fsp.readFile(pointerPath, 'utf8')).data_root, destination);
    assert.equal((await fsp.stat(video)).size, videoSize, 'se conserva el origen');
    assert.equal((await fsp.stat(path.join(destination, 'recordings', 'videos', 'partida.mp4'))).size, videoSize);
    assert.equal(await sha256(video), await sha256(path.join(destination, 'recordings', 'videos', 'partida.mp4')));
    assert.equal(JSON.parse(await fsp.readFile(path.join(destination, 'match_history_cache.json'), 'utf8')).matches.length, 168);
    assert.equal(JSON.parse(await fsp.readFile(path.join(destination, 'settings.json'), 'utf8')).recording_output_dir,
      path.join(destination, 'recordings', 'videos'));
    console.log(`PASS: ${result.fileCount} archivos, ${result.totalBytes} bytes, origen intacto, hash MP4 y puntero confirmado.`);
  } finally {
    await fsp.rm(root, { recursive: true, force: true });
  }

  const recoveryRoot = await fsp.mkdtemp(path.join(os.tmpdir(), 'solralol-migration-recovery-'));
  const source2 = path.join(recoveryRoot, 'source');
  const destination2 = path.join(recoveryRoot, 'destination');
  const pointer2 = path.join(recoveryRoot, 'bootstrap', 'storage.json');
  const journal2 = path.join(recoveryRoot, 'bootstrap', 'migration.json');
  const retryId = 'resume-safe-fixture';
  try {
    await fsp.mkdir(source2, { recursive: true });
    await fsp.mkdir(destination2, { recursive: true });
    await fsp.writeFile(path.join(source2, 'cache.json'), '{"valid":true}');
    await fsp.writeFile(path.join(destination2, 'unrelated.txt'), 'preserve this');
    await fsp.mkdir(path.dirname(pointer2), { recursive: true });
    await fsp.writeFile(pointer2, JSON.stringify({ data_root: source2 }));
    await assert.rejects(runWorker({ migrationId: retryId, source: source2, destination: destination2, pointerPath: pointer2,
      journalPath: journal2, extraRecordings: [], extraElectronData: null, includeExistingDestination: false }), /carpeta de destino contiene archivos ajenos/);
    assert.equal(JSON.parse(await fsp.readFile(pointer2, 'utf8')).data_root, source2);
    assert.equal(await fsp.readFile(path.join(destination2, 'unrelated.txt'), 'utf8'), 'preserve this');
    const stage = `${destination2}.solralol-stage-${retryId}`;
    await fsp.mkdir(stage, { recursive: true });
    await fsp.copyFile(path.join(source2, 'cache.json'), path.join(stage, 'cache.json'));
    await fsp.rm(path.join(destination2, 'unrelated.txt'));
    await fsp.rmdir(destination2);
    const resumed = await runWorker({ migrationId: retryId, source: source2, destination: destination2, pointerPath: pointer2,
      journalPath: journal2, extraRecordings: [], extraElectronData: null, includeExistingDestination: false });
    assert.equal(resumed.state, 'complete');
    assert.equal(await fsp.readFile(path.join(source2, 'cache.json'), 'utf8'), await fsp.readFile(path.join(destination2, 'cache.json'), 'utf8'));
    assert.equal(JSON.parse(await fsp.readFile(pointer2, 'utf8')).data_root, destination2);
    console.log('PASS: destino ajeno preservado; reintento reutiliza una copia parcial verificada y conmuta el puntero al final.');
  } finally {
    await fsp.rm(recoveryRoot, { recursive: true, force: true });
  }

  const interruptedRoot = await fsp.mkdtemp(path.join(os.tmpdir(), 'solralol-migration-interrupted-'));
  const source3 = path.join(interruptedRoot, 'source');
  const destination3 = path.join(interruptedRoot, 'destination');
  const pointer3 = path.join(interruptedRoot, 'bootstrap', 'storage.json');
  const journal3 = path.join(interruptedRoot, 'bootstrap', 'migration.json');
  const interruptedId = 'interrupted-before-commit';
  try {
    await fsp.mkdir(source3, { recursive: true });
    const large = await fsp.open(path.join(source3, 'recording.mp4'), 'w');
    try { await large.truncate(96 * 1024 * 1024); } finally { await large.close(); }
    await fsp.mkdir(path.dirname(pointer3), { recursive: true });
    await fsp.writeFile(pointer3, JSON.stringify({ data_root: source3 }));
    const config = { migrationId: interruptedId, source: source3, destination: destination3, pointerPath: pointer3,
      journalPath: journal3, extraRecordings: [], extraElectronData: null, includeExistingDestination: false };
    await interruptAtVerification(config);
    assert.equal(JSON.parse(await fsp.readFile(pointer3, 'utf8')).data_root, source3, 'el puntero no cambia antes de verificar');
    assert.equal((await fsp.stat(path.join(source3, 'recording.mp4'))).size, 96 * 1024 * 1024, 'el origen permanece intacto tras la interrupción');
    const resumed = await runWorker(config);
    assert.equal(resumed.state, 'complete');
    assert.equal((await fsp.stat(path.join(destination3, 'recording.mp4'))).size, 96 * 1024 * 1024);
    assert.equal(JSON.parse(await fsp.readFile(pointer3, 'utf8')).data_root, destination3);
    console.log('PASS: interrupción antes del commit conserva el origen y permite reanudar mediante verificación.');
  } finally {
    await fsp.rm(interruptedRoot, { recursive: true, force: true });
  }
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
