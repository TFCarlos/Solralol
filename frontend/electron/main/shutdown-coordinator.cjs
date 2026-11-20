'use strict';

/**
 * Owns the desktop application's one shutdown sequence. Callers may request
 * shutdown repeatedly; intake is stopped once, child services are awaited,
 * and Electron is allowed to quit only after cleanup finishes.
 */
class ApplicationShutdownCoordinator {
  constructor({ log, stopIntake, closeWindows, stopChildren, finish }) {
    this.log = log;
    this.stopIntake = stopIntake;
    this.closeWindows = closeWindows;
    this.stopChildren = stopChildren;
    this.finish = finish;
    this.promise = null;
    this.complete = false;
  }

  shutdown(reason = 'application-exit') {
    if (this.promise) return this.promise;
    this.log(`[Shutdown] Application close requested (source=${reason})`);
    this.promise = Promise.resolve().then(() => this.run(reason));
    return this.promise;
  }

  async run(reason) {
    for (const [label, action] of [
      ['Preventing new background operations', this.stopIntake],
      ['Closing overlays and auxiliary windows', this.closeWindows],
    ]) {
      try {
        action();
        this.log(`[Shutdown] ${label}`);
      } catch (error) {
        this.log(`[Shutdown] ${label} failed: ${error?.message || error}`);
      }
    }

    try {
      await this.stopChildren();
      this.log('[Shutdown] Owned backend and recording processes stopped');
    } catch (error) {
      this.log(`[Shutdown] Child cleanup failed: ${error?.message || error}`);
    } finally {
      this.complete = true;
      this.log('[Shutdown] All shutdown steps completed');
      this.finish(reason);
    }
  }
}

module.exports = { ApplicationShutdownCoordinator };
