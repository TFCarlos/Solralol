'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const { spawn } = require('node:child_process');
const { ApplicationShutdownCoordinator } = require('../frontend/electron/main/shutdown-coordinator.cjs');
const { stopOwnedChild } = require('../frontend/electron/main/owned-child-shutdown.cjs');

test('repeated close requests share one graceful shutdown and exit only afterward', async () => {
  const order = [];
  let releaseChildren;
  const childrenStopped = new Promise((resolve) => { releaseChildren = resolve; });
  const manager = new ApplicationShutdownCoordinator({
    log: (message) => order.push(message),
    stopIntake: () => order.push('intake'),
    closeWindows: () => order.push('windows'),
    stopChildren: async () => { order.push('children-start'); await childrenStopped; order.push('children-end'); },
    finish: () => order.push('quit'),
  });

  const first = manager.shutdown('main-window-close');
  const second = manager.shutdown('repeated-close');
  assert.equal(first, second);
  await Promise.resolve();
  assert.equal(order.filter((entry) => entry === 'intake').length, 1);
  assert.equal(order.includes('quit'), false);
  releaseChildren();
  await first;

  assert.deepEqual(order.filter((entry) => ['intake', 'windows', 'children-start', 'children-end', 'quit'].includes(entry)),
    ['intake', 'windows', 'children-start', 'children-end', 'quit']);
  assert.equal(manager.complete, true);
});

test('a failed subsystem does not prevent remaining cleanup or final exit', async () => {
  const order = [];
  const manager = new ApplicationShutdownCoordinator({
    log: (message) => order.push(message),
    stopIntake: () => { throw new Error('watcher failure'); },
    closeWindows: () => order.push('windows'),
    stopChildren: async () => order.push('children'),
    finish: () => order.push('quit'),
  });

  await manager.shutdown();
  assert.ok(order.some((entry) => String(entry).includes('watcher failure')));
  assert.ok(order.includes('windows'));
  assert.ok(order.includes('children'));
  assert.equal(order.at(-1), 'quit');
});

test('shutdown stops the process handle it owns and leaves an unrelated child running', async () => {
  const owned = spawn(process.execPath, ['-e', 'process.stdin.on("end", () => process.exit(0)); setInterval(() => {}, 1000)'], { windowsHide: true, stdio: ['pipe', 'ignore', 'ignore'] });
  const unrelated = spawn(process.execPath, ['-e', 'setInterval(() => {}, 1000)'], { windowsHide: true, stdio: 'ignore' });
  try {
    await new Promise((resolve) => setTimeout(resolve, 150));
    const manager = new ApplicationShutdownCoordinator({
      log: () => {},
      stopIntake: () => {},
      closeWindows: () => {},
      stopChildren: () => stopOwnedChild(owned, { timeoutMs: 1000, forceStop: (child) => child.kill('SIGKILL') }),
      finish: () => {},
    });
    await manager.shutdown('owned-process-test');
    assert.ok(owned.exitCode !== null || owned.signalCode !== null);
    assert.equal(unrelated.exitCode, null);
  } finally {
    if (owned.exitCode === null) owned.kill();
    if (unrelated.exitCode === null) unrelated.kill();
  }
});

test('unresponsive owned child escalates after the grace timeout', async () => {
  const child = new EventEmitter();
  child.exitCode = null;
  child.signalCode = null;
  child.pid = 4321;
  child.stdin = { writable: true, end() {} };
  let escalated = 0;

  await stopOwnedChild(child, {
    timeoutMs: 10,
    onTimeout: (processHandle) => assert.equal(processHandle, child),
    forceStop: (processHandle) => {
      assert.equal(processHandle, child);
      escalated += 1;
      processHandle.exitCode = 1;
      processHandle.emit('close', 1, null);
    },
  });
  assert.equal(escalated, 1);
  assert.equal(child.exitCode, 1);
});
