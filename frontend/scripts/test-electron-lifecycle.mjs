import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const source = await readFile(new URL('../electron/main/index.cjs', import.meta.url), 'utf8');
const readyCall = source.indexOf('app.whenReady().then(() => {');
assert.notEqual(readyCall, -1, 'main startup must use the central ready lifecycle');
assert.doesNotMatch(source.slice(0, source.indexOf('\n', 0)), /\bscreen\s*,/, 'screen must not be eagerly destructured');

const initializeStart = source.indexOf('function initializeDisplayManagement()');
const initializeEnd = source.indexOf('\nfunction disposeDisplayManagement()', initializeStart);
assert.ok(initializeStart >= 0 && initializeEnd > initializeStart, 'display setup must be an explicit initializer');
const initializer = source.slice(initializeStart, initializeEnd);
assert.match(initializer, /if \(screenListenersRegistered\) return/);
assert.match(initializer, /screen = require\('electron'\)\.screen/);
assert.equal((initializer.match(/screen\.on\(/g) ?? []).length, 3, 'register each display listener exactly once');
const startupEnd = source.indexOf(".catch((error) => logDiagnostic(`Electron startup failed", readyCall);
const startupBody = source.slice(readyCall, startupEnd);
assert.ok(startupBody.indexOf('initializeDisplayManagement()') >= 0, 'initialize display management from app.whenReady');
assert.ok(startupBody.indexOf('initializeDisplayManagement()') < startupBody.indexOf('createWindow()'), 'initialize displays before creating any windows');

const disposerStart = source.indexOf('function disposeDisplayManagement()');
const disposerEnd = source.indexOf('\nfunction liveOverlayPayload(', disposerStart);
const disposer = source.slice(disposerStart, disposerEnd);
assert.equal((disposer.match(/screen\.removeListener\(/g) ?? []).length, 3, 'remove each display listener at shutdown');
assert.match(source, /app\.on\('will-quit',[^\n]*disposeDisplayManagement\(\)/, 'dispose display listeners during final shutdown');
const overlaySyncStart = source.indexOf('function syncLiveOverlays(');
const overlaySyncEnd = source.indexOf("\nipcMain.on('overlay:publish-live-state'", overlaySyncStart);
assert.ok(overlaySyncStart >= 0 && overlaySyncEnd > overlaySyncStart);
const overlaySync = source.slice(overlaySyncStart, overlaySyncEnd);
assert.match(overlaySync, /overlay\.hide\(\)/, 'visibility transitions hide existing windows');
assert.match(overlaySync, /overlay\.showInactive\(\)/, 'restoring visibility reuses existing windows');
assert.doesNotMatch(overlaySync, /overlay\.(?:close|destroy)\(/, 'visibility transitions cannot close overlays');
assert.match(overlaySync, /Synchronization failed panel=/, 'one overlay error cannot abort sibling updates');
assert.match(source, /if \(windowRef && !windowRef\.isDestroyed\(\)\) \{\s*logDiagnostic\('\[APP\] Ignored auxiliary window close/, 'auxiliary close cannot trigger application shutdown');
assert.match(source, /if \(liveOverlayWindows\.get\(panel\) === overlay\)/, 'closed overlay cannot delete a replacement from the registry');
console.log('Electron screen access is ready-gated, single-registration, and shutdown-cleaned.');
