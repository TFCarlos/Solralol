const { contextBridge, ipcRenderer } = require('electron');

const allowedMethods = new Set(['app.bootstrap', 'riot.readiness', 'live.snapshot', 'champions.list', 'champions.analysis', 'champions.analysis.update', 'champions.analysis.update.status', 'champions.analysis.update.cancel', 'draft.snapshot', 'draft.import', 'meta.bootstrap', 'meta.tier', 'meta.notes', 'meta.assets', 'settings.public', 'settings.load', 'settings.update', 'settings.key.save', 'settings.key.clear', 'settings.audio-devices', 'settings.recording-test', 'analysis.settings.load', 'analysis.settings.defaults', 'analysis.settings.save', 'analysis.settings.recalculation.status', 'storage.info', 'storage.preview', 'storage.migrate.start', 'storage.migrate.status', 'storage.migrate.abort', 'recordings.list', 'recordings.thumbnail', 'recordings.review', 'recordings.review.generate', 'recordings.status', 'recordings.start', 'recordings.stop', 'recordings.delete', 'saved_matches.list', 'saved_matches.detail', 'saved_matches.sync', 'saved_matches.analysis.generate', 'saved_matches.delete.preview', 'saved_matches.delete', 'soloq_analyses.list', 'soloq_analyses.register', 'soloq_analyses.detail', 'soloq_analyses.achievements', 'soloq_analyses.delete.preview', 'soloq_analyses.delete', 'soloq_analyses.analysis.generate', 'soloq_analyses.analysis.status', 'soloq_analyses.combat.context', 'soloq_analyses.combat.generate', 'home.dashboard', 'home.counter', 'home.sync', 'home.matches', 'home.match.detail', 'home.clear-history', 'home.assets']);
contextBridge.exposeInMainWorld('solralol', Object.freeze({
  request(method, params = {}) {
    if (!allowedMethods.has(method) || !params || typeof params !== 'object') return Promise.reject(new Error('Invalid backend request'));
    return ipcRenderer.invoke('backend:request', { method, params }).then((result) => {
      if (result && typeof result === 'object' && result.__solralolError) {
        throw new Error(typeof result.__solralolError.message === 'string' ? result.__solralolError.message : 'Backend request failed');
      }
      return result;
    });
  },
  onBackendStatus(callback) {
    const listener = (_event, status) => callback(status);
    ipcRenderer.on('backend:status', listener);
    return () => ipcRenderer.removeListener('backend:status', listener);
  },
  onAnalysisRecalculated(callback) {
    const listener = (_event, payload) => callback(payload);
    ipcRenderer.on('analysis:recalculated', listener);
    return () => ipcRenderer.removeListener('analysis:recalculated', listener);
  },
  onHomeSavedScoresChanged(callback) {
    const listener = () => callback();
    ipcRenderer.on('home:saved-scores-changed', listener);
    return () => ipcRenderer.removeListener('home:saved-scores-changed', listener);
  },
  onAchievementSettingsChanged(callback) {
    const listener = (_event, payload) => callback(payload);
    ipcRenderer.on('analysis:achievements-settings-changed', listener);
    return () => ipcRenderer.removeListener('analysis:achievements-settings-changed', listener);
  },
  getBackendStatus: () => ipcRenderer.invoke('backend:status:get'),
  onWindowState(callback) {
    const listener = (_event, state) => callback(state);
    ipcRenderer.on('window:maximize-state', listener);
    return () => ipcRenderer.removeListener('window:maximize-state', listener);
  },
  publishLiveOverlay(state) {
    if (state && typeof state === 'object') ipcRenderer.send('overlay:publish-live-state', state);
  },
  onLiveOverlayState(callback) {
    const listener = (_event, state) => callback(state);
    ipcRenderer.on('overlay:live-state', listener);
    return () => ipcRenderer.removeListener('overlay:live-state', listener);
  },
  getOverlayEditing: () => ipcRenderer.invoke('overlay:editing:get'),
  setOverlayEditing: (enabled) => ipcRenderer.invoke('overlay:editing:set', enabled),
  onOverlayEditing(callback) {
    const listener = (_event, enabled) => callback(Boolean(enabled));
    ipcRenderer.on('overlay:editing', listener);
    return () => ipcRenderer.removeListener('overlay:editing', listener);
  },
  minimize: () => ipcRenderer.invoke('window:minimize'),
  close: () => ipcRenderer.invoke('window:close'),
  toggleMaximize: () => ipcRenderer.invoke('window:toggle-maximize'),
  getWindowState: () => ipcRenderer.invoke('window:get-state'),
  getDisplays: () => ipcRenderer.invoke('settings:get-displays'),
  chooseRecordingsDirectory: () => ipcRenderer.invoke('settings:choose-recordings-directory'),
  openRecordingsDirectory: () => ipcRenderer.invoke('settings:open-recordings-directory'),
  chooseStorageDirectory: () => ipcRenderer.invoke('storage:choose-directory'),
  openStorageDirectory: () => ipcRenderer.invoke('storage:open-directory'),
  openRecordingReview: (id) => ipcRenderer.invoke('recordings:open-review', id),
  openSoloQAnalysis: (matchId) => ipcRenderer.invoke('soloq:open-analysis', matchId),
  openSettingsUrl: (provider) => ipcRenderer.invoke('settings:open-provider-url', provider),
  openMetaSource: (url) => ipcRenderer.invoke('meta:open-source', url),
}));

