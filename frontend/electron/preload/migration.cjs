const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('migrationAssistant', {
  ready: () => ipcRenderer.send('migration:ready'),
  action: (action) => ipcRenderer.invoke('migration:action', action),
  onStatus: (callback) => {
    const listener = (_event, value) => callback(value);
    ipcRenderer.on('migration:status', listener);
    return () => ipcRenderer.removeListener('migration:status', listener);
  },
});
