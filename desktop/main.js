// Electron 메인 프로세스: 창 하나, 트레이 상주, 전역 단축키, 마이크와 알림 권한, 백엔드 확인.
const path = require('node:path');
const {
  app, BrowserWindow, Tray, Menu, nativeImage, globalShortcut, ipcMain, session, shell, systemPreferences,
} = require('electron');

const { DesktopSettings } = require('./desktop_settings');
const { BackendProbe } = require('./backend_probe');

// 앱 아이콘은 HUD 리액터에 가운데 글자만 AGENT. 트레이는 메뉴 막대에 맞게 둥근 사각형 없이 리액터만
const ICON = path.join(__dirname, 'icons', 'icon.png');
const TRAY_ICON = path.join(__dirname, 'icons', 'tray.png');
const LOADING = path.join(__dirname, 'loading.html');
// 백엔드가 없으면 이 간격으로 다시 본다. 앱은 백엔드를 띄우지 않는다(docker compose 나 Ion 의 몫). 뜨면 알아서 붙는다
const RETRY_MS = 5000;
// 렌더러가 요청할 수 있는 권한. 그 밖은 모두 거절한다
const ALLOWED_PERMISSIONS = new Set(['media', 'notifications', 'clipboard-sanitized-write']);
// 기본 제목 표시줄을 숨기고 HUD 헤더(높이 52px, 배경 #02060c)가 그 자리를 맡는다.
// macOS 는 신호등 버튼을 헤더 세로 가운데에, 그 밖은 창 버튼을 헤더 색으로 덧그린다
const HEADER_H = 52;
const TITLE_BAR = process.platform === 'darwin'
  ? { titleBarStyle: 'hiddenInset', trafficLightPosition: { x: 16, y: 18 } }
  : { titleBarStyle: 'hidden', titleBarOverlay: { color: '#02060c', symbolColor: '#5fc8e2', height: HEADER_H } };

// 시험과 여러 설치를 나눌 때 앱 데이터 폴더를 바꾼다. 비우면 OS 기본 위치
if (process.env.JARVIS_DESKTOP_DATA) app.setPath('userData', path.resolve(process.env.JARVIS_DESKTOP_DATA));
const settingsStore = new DesktopSettings(path.join(app.getPath('userData'), 'settings.json'));
let settings = settingsStore.load();
let win = null;
let tray = null;
let quitting = false;
let connectSeq = 0;  // 주소가 바뀌면 지난 재시도 루프를 버린다

function isBackendUrl(target) {
  try { return new URL(target).origin === settings.backendUrl; } catch { return false; }
}

function showLoading(error) {
  if (!win) return;
  win.loadFile(LOADING, error ? { query: { error } } : undefined);
}

async function connectBackend() {
  const seq = ++connectSeq;
  showLoading();
  const probe = new BackendProbe({ url: settings.backendUrl });
  while (win && seq === connectSeq) {
    if (await probe.alive()) {
      if (win && seq === connectSeq) win.loadURL(settings.backendUrl);
      return;
    }
    showLoading(`백엔드(${settings.backendUrl})가 응답하지 않습니다. docker compose --profile web up -d 로 띄우면 자동으로 연결합니다.`);
    await new Promise((resolve) => setTimeout(resolve, RETRY_MS));
  }
}

function showWindow() {
  if (!win) return;
  if (win.isMinimized()) win.restore();
  win.show();
  win.focus();
}

function guardPermissions() {
  const ses = session.defaultSession;
  ses.setPermissionRequestHandler((wc, permission, callback, details) => {
    const fromBackend = isBackendUrl(details.requestingUrl || wc.getURL());
    const audioOnly = permission !== 'media' || (details.mediaTypes || []).every((t) => t === 'audio');
    callback(fromBackend && ALLOWED_PERMISSIONS.has(permission) && audioOnly);
  });
  ses.setPermissionCheckHandler((_wc, permission, origin) => ALLOWED_PERMISSIONS.has(permission) && isBackendUrl(origin));
}

function createWindow() {
  win = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 380,
    minHeight: 560,
    backgroundColor: '#02060c',
    title: 'Jarvis',
    icon: ICON,
    show: false,
    ...TITLE_BAR,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  win.once('ready-to-show', () => win.show());
  // 백엔드 밖으로는 창 안에서 이동하지 않는다. http(s) 링크만 기본 브라우저로 연다
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:\/\//.test(url) && !isBackendUrl(url)) shell.openExternal(url);
    return { action: 'deny' };
  });
  win.webContents.on('will-navigate', (event, url) => {
    if (!isBackendUrl(url) && !url.startsWith('file://')) event.preventDefault();
  });
  // 백엔드가 재시작되면 페이지 로드가 끊긴다. 다시 연결한다
  win.webContents.on('did-fail-load', (_e, code, _desc, url, isMainFrame) => {
    if (isMainFrame && code !== -3 && isBackendUrl(url)) connectBackend();
  });
  // 닫기는 트레이로 숨기기. 백그라운드 알림(🔔, 리마인더)을 받으려면 ws 가 열려 있어야 한다
  win.on('close', (event) => {
    if (quitting) return;
    event.preventDefault();
    win.hide();
  });
  win.on('closed', () => { win = null; });
}

function triggerListen() {
  showWindow();
  win?.webContents.send('desktop:hotkey');
}

function applyHotkey() {
  globalShortcut.unregisterAll();
  if (!settings.hotkey) return true;
  try { return globalShortcut.register(settings.hotkey, triggerListen); } catch { return false; }
}

function applyLoginItem() {
  if (process.platform === 'darwin' || process.platform === 'win32') {
    app.setLoginItemSettings({ openAtLogin: settings.autoLaunch, openAsHidden: true });
  }
}

function createTray() {
  const source = nativeImage.createFromPath(TRAY_ICON);
  const image = source.resize({ width: 18, height: 18 });
  image.addRepresentation({ scaleFactor: 2, width: 36, height: 36, buffer: source.resize({ width: 36, height: 36 }).toPNG() });
  tray = new Tray(image);
  tray.setToolTip('Jarvis');
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: '열기', click: showWindow },
    { label: '듣기 시작', click: triggerListen },
    { type: 'separator' },
    { label: '종료', click: () => { quitting = true; app.quit(); } },
  ]));
  tray.on('click', showWindow);
}

function registerIpc() {
  ipcMain.handle('desktop:get-settings', () => settings);
  ipcMain.handle('desktop:set-settings', (_event, next) => {
    const prevUrl = settings.backendUrl;
    const result = settingsStore.save(next || {});
    if (!result.ok) return result;
    settings = result.settings;
    applyLoginItem();
    if (!applyHotkey()) return { ok: false, error: `단축키를 등록하지 못했습니다: ${settings.hotkey}`, settings };
    if (settings.backendUrl !== prevUrl) connectBackend();
    return { ok: true, settings };
  });
}

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', showWindow);
  app.whenReady().then(async () => {
    if (process.platform === 'darwin') {
      // 패키징 전 macOS 는 창 icon 을 무시하고 Electron 기본 아이콘을 Dock 에 띄운다. 번들은 Info.plist 의 아이콘을 쓴다
      if (!app.isPackaged) app.dock?.setIcon(ICON);
      // 처음 한 번 macOS 가 마이크 권한을 묻는다. 거절하면 HUD 가 마이크 오류를 보여 준다
      await systemPreferences.askForMediaAccess('microphone').catch(() => false);
    }
    guardPermissions();
    registerIpc();
    createWindow();
    createTray();
    applyHotkey();
    applyLoginItem();
    await connectBackend();
  });
  app.on('activate', showWindow);
  app.on('before-quit', () => { quitting = true; });
  app.on('will-quit', () => globalShortcut.unregisterAll());
  // 창을 닫아도 트레이에 남는다. 종료는 트레이 메뉴나 Cmd+Q
  app.on('window-all-closed', () => {});
}
