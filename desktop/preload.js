// 렌더러(HUD 페이지)에 window.jarvisDesktop 만 연다. Node 와 ipcRenderer 자체는 넘기지 않는다.
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('jarvisDesktop', {
  platform: process.platform,
  getSettings: () => ipcRenderer.invoke('desktop:get-settings'),
  setSettings: (next) => ipcRenderer.invoke('desktop:set-settings', next),
  restartBackend: () => ipcRenderer.invoke('desktop:restart-backend'),
  onHotkey: (callback) => {
    ipcRenderer.on('desktop:hotkey', () => callback());
  },
});
