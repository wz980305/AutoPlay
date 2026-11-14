const messages = {
  brand: ['AutoPlay', 'AutoPlay'],
  settings: ['AutoPlay 设置', 'AutoPlay settings'], close: ['关闭', 'Close'], done: ['完成', 'Done'],
  commonTab: ['常用', 'General'], displayTab: ['显示', 'Display'], supportTab: ['连接', 'Connection'], settingsNav: ['设置分类', 'Settings categories'],
  appearance: ['外观', 'Appearance'], frameSettings: ['画质', 'Picture'],
  navigation: ['导航', 'Navigation'], carLocation: ['使用车辆定位', 'Use car location'], datum: ['坐标系', 'Coordinate system'], datumAuto: ['自动', 'Automatic'],
  locationDenied: ['车机浏览器没有允许本页使用位置。', 'The car browser did not allow this page to use location.'],
  locationUnavailable: ['车机浏览器暂时拿不到位置，请稍后再试。', 'The car browser has no position right now. Try again later.'],
  locationReconnecting: ['已开启，正在重新连接 CarPlay。', 'On. Reconnecting CarPlay.'],
  locationFail: ['设置失败，请检查盒子连接后重试。', 'Could not change the setting. Check the box connection and retry.'],
  boxLink: ['AutoPlay 盒子', 'AutoPlay box'],
  playerSettings: ['设置', 'Settings'], performanceMode: ['增强模式', 'Enhanced mode'], language: ['语言', 'Language'],
  waiting: ['等待 iPhone', 'Waiting for iPhone'],
  connecting: ['正在连接盒子', 'Connecting to box'], reconnecting: ['正在重新连接', 'Reconnecting'],
  reconnectingHint: ['暂时无法连接盒子。请检查盒子电源与车机的 AutoPlay 热点连接。', 'Cannot connect to the box. Check its power and the car’s AutoPlay hotspot connection.'],
  waited: ['已等待 ', 'Waited '], secondsUnit: [' 秒', ' s'],
  starting: ['正在准备画面', 'Preparing picture'],
  renegotiating: ['正在调整画面', 'Adjusting picture'],
  // No token: the page asks the box for it when it opens (boot.ts, receiver-access.json) and did not get it. Until
  // 1.4.3 this told the driver to tap a button the box page does not have (1.5.0).
  access: ['未取得盒子的访问许可', 'No access to the box'], accessHint: ['本页打开时没有从盒子取到访问许可。请检查盒子电源与车机的 AutoPlay 热点连接，然后刷新本页。', 'This page did not get its access from the box when it opened. Check the box’s power and the car’s AutoPlay hotspot connection, then reload this page.'],
  fullscreen: ['无边框模式', 'Borderless mode'],
  borderlessOn: ['已开启', 'On'],
  checkingNetwork: ['正在检查网络', 'Checking network'],
  teslaFullscreenOffline: ['暂时无法连接视频网站，不能开启无边框模式。请检查车机网络，当前画面仍可使用。', 'Cannot reach the video site to start borderless mode. Check the car’s internet connection. The current picture still works.'],
  apply: ['应用并重连', 'Apply and reconnect'], applyNow: ['应用', 'Apply'],
  advanced: ['画质与兼容', 'Quality and compatibility'],
  nightMode: ['夜间模式', 'Night mode'], nightSchedule: ['定时 18:30–06:30', '18:30–06:30'], nightSystem: ['跟随系统', 'System'], nightDay: ['始终白天', 'Always day'], nightNight: ['始终夜间', 'Always night'],
  latency: ['解码延迟', 'Decode delay'],
  debugHud: ['显示调试信息', 'Show debug info'],
  compatDisplay: ['兼容显示', 'Compatible display'],
  ui: ['CarPlay 内容大小', 'Content size'],
  fps: ['帧率', 'Frame rate'], codec: ['视频编码', 'Video codec'], codecAuto: ['自动', 'Automatic'], standard: ['标准', 'Standard'], large: ['大', 'Large'], small: ['小', 'Small'], smaller: ['更小', 'Smaller'],
  loading: ['正在读取…', 'Loading…'], applying: ['正在应用…', 'Applying…'], applied: ['已保存，正在重新连接 CarPlay。', 'Saved. Reconnecting CarPlay.'],
  deferred: ['已记下，下次连接 iPhone 时生效，不打断当前画面。', 'Saved for the next connection; the picture is not interrupted now.'],
  nextSession: ['新画质下次连接 iPhone 时生效。', 'The new quality takes effect on the next iPhone connection.'],
  fpsLowered: ['车机解码跟不上 60 帧，已自动改为 30 帧（重新连接一次）。', 'This browser cannot decode 60 fps in time; switched to 30 fps (one reconnect).'],
  adjusting: ['正在调整画面', 'Adjusting picture'],
  recoveringNotice: ['连接中断 · 正在重连 · 触控已暂停', 'Link lost · Reconnecting · Touch paused'],
  loadFail: ['读取失败，请检查盒子连接后重试。', 'Could not load settings. Check the receiver connection and retry.'],
  applyFail: ['应用失败，请检查连接和分辨率范围。', 'Could not apply. Check connection and resolution range.'],
  autoFail: ['暂未完成自动匹配，可在设置中重试。', 'Automatic matching did not complete. Retry in Settings.'],
  diagnostics: ['连接与兼容性', 'Connection and compatibility'], browserCheck: ['浏览器兼容性检测', 'Browser check'],
  decoding: ['解码能力', 'Decoding'], decodingOk: ['可用', 'Available'], decodingInsecure: ['需要 HTTPS', 'Needs HTTPS'],
  decodingMissing: ['不支持', 'Not supported'], picture: ['当前画面', 'Picture'], unsupported: ['此浏览器缺少视频解码能力，请使用支持 WebCodecs 的浏览器。', 'This browser lacks video decoding APIs. Use a browser with WebCodecs support.'],
  insecure: ['当前页面不是安全上下文，请使用已受信任的 HTTPS 地址。', 'This page is not a secure context. Use a trusted HTTPS address.'],
  noStream: ['尚无画面', 'No picture yet'],
  hevcAuto: ['这台车机解不了 H.265，已改用 H.264。', "This car cannot decode H.265; switched to H.264."],
  hevcManual: ['这台车机解不了 H.265。请把「显示 › 画质与兼容 › 视频编码」改为自动或 H.264。', 'This car cannot decode H.265. Set Display › Quality and compatibility › Video codec to Automatic or H.264.'],
  decodeFail: ['画面解码出错，正在重新请求画面。', 'The picture failed to decode; asking for a new one.'], technical: ['详细信息', 'Details'],
  cancel: ['取消', 'Cancel'],
} as const;
export type Key = keyof typeof messages;
/** Storage can be blocked or throw in a car browser (private mode, cleared site data): then zh, remembered for the page. */
function savedLanguage(): 'zh' | 'en' { try { return localStorage.getItem('f50-language') === 'en' ? 'en' : 'zh'; } catch { return 'zh'; } }
export let language: 'zh' | 'en' = savedLanguage();
export function t(key: Key): string { return messages[key][language === 'zh' ? 0 : 1]; }
export function setLanguage(value: string): void {
  language = value === 'en' ? 'en' : 'zh';
  try { localStorage.setItem('f50-language', language); } catch { /* Kept for this page only. */ }
  document.documentElement.lang = language === 'zh' ? 'zh-CN' : 'en';
  document.querySelectorAll<HTMLElement>('[data-i18n]').forEach(e => { e.textContent = t(e.dataset.i18n as Key); });
}
