const messages = {
  brand: ['AutoPlay', 'AutoPlay'],
  settings: ['AutoPlay 设置', 'AutoPlay settings'], close: ['关闭', 'Close'], done: ['完成', 'Done'],
  commonTab: ['常用', 'General'], displayTab: ['显示', 'Display'], supportTab: ['连接', 'Connection'], settingsNav: ['设置分类', 'Settings categories'],
  appearance: ['外观', 'Appearance'], frameSettings: ['画质', 'Picture'],
  navigation: ['导航', 'Navigation'], carLocation: ['使用车辆定位', 'Use car location'], datum: ['坐标系', 'Coordinate system'], datumAuto: ['自动', 'Automatic'],
  locationDenied: ['车机浏览器未允许本页使用位置。', 'The car browser did not allow this page to use location.'],
  locationUnavailable: ['暂时无法获取车辆位置。', 'No position from the car right now.'],
  locationReconnecting: ['已开启，正在重新连接 CarPlay。', 'On. Reconnecting CarPlay.'],
  locationFail: ['设置失败，请检查盒子连接后重试。', 'Could not change the setting. Check the box connection and retry.'],
  boxLink: ['AutoPlay 盒子', 'AutoPlay box'],
  playerSettings: ['AutoPlay 设置', 'AutoPlay settings'], performanceMode: ['增强模式', 'Enhanced mode'], language: ['语言', 'Language'],
  waiting: ['等待 iPhone', 'Waiting for iPhone'],
  connecting: ['正在连接盒子', 'Connecting to box'], reconnecting: ['正在重新连接', 'Reconnecting'],
  reconnectingHint: ['无法连接盒子，请检查盒子电源和 AutoPlay 热点。', 'Can’t reach the box. Check its power and the AutoPlay hotspot.'],
  waited: ['已等待 ', 'Waited '], secondsUnit: [' 秒', ' s'],
  starting: ['正在准备画面', 'Preparing picture'],
  renegotiating: ['正在调整画面', 'Adjusting picture'],
  // No token: the page asks the box for it when it opens (boot.ts, receiver-access.json) and did not get it. Until
  // 1.4.3 this told the driver to tap a button the box page does not have (1.5.0).
  access: ['未取得盒子的访问许可', 'No access to the box'], accessHint: ['请检查盒子电源和 AutoPlay 热点，然后刷新本页。', 'Check the box’s power and the AutoPlay hotspot, then reload this page.'],
  fullscreen: ['无边框模式', 'Borderless mode'],
  borderlessOn: ['已开启', 'On'],
  checkingNetwork: ['正在检查网络', 'Checking network'],
  teslaFullscreenOffline: ['无法连接视频网站，暂时无法开启无边框模式', 'Can’t reach the video site; borderless mode is unavailable for now'],
  apply: ['应用并重连', 'Apply and reconnect'], applyNow: ['应用', 'Apply'],
  advanced: ['画质与兼容', 'Quality and compatibility'],
  nightMode: ['夜间模式', 'Night mode'], nightSchedule: ['定时 18:30–06:30', '18:30–06:30'], nightSystem: ['跟随系统', 'System'], nightDay: ['始终白天', 'Always day'], nightNight: ['始终夜间', 'Always night'],
  latency: ['解码延迟', 'Decode delay'],
  debugHud: ['显示调试信息', 'Show debug info'],
  compatDisplay: ['兼容显示', 'Compatible display'],
  ui: ['CarPlay 内容大小', 'Content size'],
  fps: ['帧率', 'Frame rate'], codec: ['视频编码', 'Video codec'], codecAuto: ['自动', 'Automatic'], standard: ['标准', 'Standard'], large: ['大', 'Large'], small: ['小', 'Small'], smaller: ['更小', 'Smaller'],
  loading: ['正在读取…', 'Loading…'], applying: ['正在应用…', 'Applying…'], applied: ['已保存，正在重新连接 CarPlay。', 'Saved. Reconnecting CarPlay.'],
  deferred: ['下次连接 iPhone 时生效。', 'Takes effect at the next connection.'],
  nextSession: ['新画质下次连接 iPhone 时生效。', 'The new quality takes effect on the next iPhone connection.'],
  fpsLowered: ['车机无法流畅解码 60 帧，已改为 30 帧', 'This car can’t decode 60 fps smoothly; switched to 30 fps'],
  adjusting: ['正在调整画面', 'Adjusting picture'],
  recoveringNotice: ['正在重新连接，触控已暂停', 'Reconnecting; touch is paused'],
  loadFail: ['读取失败，请检查盒子连接后重试。', 'Could not load settings. Check the receiver connection and retry.'],
  applyFail: ['应用失败，请重试。', 'Couldn’t apply. Try again.'],
  autoFail: ['无法自动调整画面尺寸', 'Couldn’t adjust the picture size'],
  diagnostics: ['连接与兼容性', 'Connection and compatibility'], browserCheck: ['浏览器兼容性检测', 'Browser check'],
  decoding: ['解码能力', 'Decoding'], decodingOk: ['可用', 'Available'], decodingInsecure: ['需要 HTTPS', 'Needs HTTPS'],
  decodingMissing: ['不支持', 'Not supported'], picture: ['当前画面', 'Picture'], unsupported: ['请更新车辆软件。', 'Update the car software.'],
  insecure: ['请用盒子的 https:// 地址打开本页。', 'Open this page at the box’s https:// address.'],
  noStream: ['尚无画面', 'No picture yet'],
  hevcAuto: ['此车机不支持 H.265 解码，已改用 H.264', 'This car doesn’t support H.265 decoding; switched to H.264'],
  hevcManual: ['请将视频编码改为「自动」。', 'Set the video codec to Automatic.'],
  goToSetting: ['前往设置', 'Open Setting'],
  ok: ['好', 'OK'], hevcTitle: ['此车机不支持 H.265 解码', 'This car doesn’t support H.265 decoding'],
  unsupportedTitle: ['此浏览器不支持视频解码', 'This browser doesn’t support video decoding'], insecureTitle: ['不是安全连接', 'Not a secure connection'],
  decodeFail: ['画面解码出错，正在重新获取', 'Decoding failed; asking for a new picture'],
  cancel: ['取消', 'Cancel'],
} as const;
export type Key = keyof typeof messages;
/** The language chosen in 「语言」; until one is chosen, the car browser's own (1.5.4, Apple's settings guidance: detect
 *  what can be detected - it was 简体中文 for every car). Chinese for a zh browser or one that names none, else English.
 *  Storage can be blocked or throw in a car browser (private mode, cleared site data): then the browser's, for the page. */
export function defaultLanguage(asked: string): 'zh' | 'en' { return !asked || asked.toLowerCase().startsWith('zh') ? 'zh' : 'en'; }
function savedLanguage(): 'zh' | 'en' {
  try { const saved = localStorage.getItem('f50-language'); if (saved === 'en' || saved === 'zh') return saved; } catch { /* the browser's */ }
  try { return defaultLanguage(navigator.languages?.[0] ?? navigator.language ?? ''); } catch { return 'zh'; }
}
export let language: 'zh' | 'en' = savedLanguage();
export function t(key: Key): string { return messages[key][language === 'zh' ? 0 : 1]; }
export function setLanguage(value: string): void {
  language = value === 'en' ? 'en' : 'zh';
  try { localStorage.setItem('f50-language', language); } catch { /* Kept for this page only. */ }
  document.documentElement.lang = language === 'zh' ? 'zh-CN' : 'en';
  document.querySelectorAll<HTMLElement>('[data-i18n]').forEach(e => { e.textContent = t(e.dataset.i18n as Key); });
  // Buttons that are a symbol alone (1.5.4: the panel's close) carry their name for a screen reader.
  document.querySelectorAll<HTMLElement>('[data-i18n-label]').forEach(e => { e.setAttribute('aria-label', t(e.dataset.i18nLabel as Key)); });
}
