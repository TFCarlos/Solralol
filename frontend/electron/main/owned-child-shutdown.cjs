'use strict';

/**
 * End only the child process represented by the supplied owned handle.
 * Escalation is delegated to the caller so Windows can target that PID's tree.
 */
function stopOwnedChild(child, { timeoutMs, forceStop, onTimeout = () => {} }) {
  if (!child || child.exitCode !== null || child.signalCode !== null) return Promise.resolve();
  return new Promise((resolve) => {
    let settled = false;
    const finish = () => {
      if (settled) return;
      settled = true;
      clearTimeout(forceTimer);
      child.removeListener('close', finish);
      resolve();
    };
    child.once('close', finish);
    const forceTimer = setTimeout(() => {
      try { onTimeout(child); } catch {}
      try { forceStop(child); } catch {}
    }, timeoutMs);
    try {
      if (child.stdin?.writable) child.stdin.end();
      else if (child.exitCode !== null || child.signalCode !== null) finish();
    } catch {
      // Keep waiting for the close event; the bounded force path still owns
      // this exact process handle if it does not exit by the deadline.
    }
  });
}

module.exports = { stopOwnedChild };
