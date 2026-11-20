const { spawnSync } = require('node:child_process');
const path = require('node:path');
const fs = require('node:fs');

const repoRoot = path.resolve(__dirname, '../..');
const python = process.env.SOLRALOL_PYTHON || path.join(repoRoot, '.venv', 'Scripts', 'python.exe');
const result = spawnSync(python, [
  '-m', 'PyInstaller', '--noconfirm', '--clean',
  '--distpath', path.join(repoRoot, 'backend', 'dist'),
  '--workpath', path.join(repoRoot, 'backend', 'build'),
  path.join(repoRoot, 'backend', 'SolralolBackend.spec'),
], { cwd: repoRoot, stdio: 'inherit', windowsHide: true });
if (result.error) throw result.error;
if (result.status !== 0) process.exit(result.status ?? 1);
const exe = path.join(repoRoot, 'backend', 'dist', 'SolralolBackend.exe');
if (!fs.existsSync(exe)) throw new Error('PyInstaller did not produce SolralolBackend.exe');
