const messages = {
  brand: ['AutoPlay', 'AutoPlay'],
  settings: ['AutoPlay 设置', 'AutoPlay settings'], close: ['关闭', 'Close'], done: ['完成', 'Done'],
  commonTab: ['常用', 'General'], displayTab: ['显示', 'Display'], supportTab: ['连接', 'Connection'], settingsNav: ['设置分类', 'Settings categories'],
  appearance: ['外观', 'Appearance'], frameSettings: ['画质', 'Picture'],
  navigation: ['导航', 'Navigation'], carLocation: ['使用车辆定位', 'Use car location'], datum: ['坐标系', 'Coordinate system'], datumAuto: ['自动', 'Automatic'],
  locationDenied: ['车机浏览器没有允许本页使用位置。', 'The car browser did not allow this page to use location.'],
  locationUnavailable: ['暂时拿不到车辆位置。', 'No position from the car right now.'],
  locationReconnecting: ['已开启，正在重新连接 CarPlay。', 'On. Reconnecting CarPlay.'],
  locationFail: ['设置失败，请检查盒子连接后重试。', 'Could not change the setting. Check the box connection and retry.'],
  boxLink: ['AutoPlay 盒子', 'AutoPlay box'],
  playerSettings: ['设置', 'Settings'], performanceMode: ['增强模式', 'Enhanced mode'], language: ['语言', 'Language'],
  waiting: ['等待 iPhone', 'Waiting for iPhone'],
  connecting: ['正在连接盒子', 'Connecting to box'], reconnecting: ['正在重新连接', 'Reconnecting'],
  reconnectingHint: ['连不上盒子，请检查盒子电源和 AutoPlay 热点。', 'Can’t reach the box. Check its power and the AutoPlay hotspot.'],
  waited: ['已等待 ', 'Waited '], secondsUnit: [' 秒', ' s'],
  starting: ['正在准备画面', 'Preparing picture'],
  renegotiating: ['正在调整画面', 'Adjusting picture'],
  // No token: the page asks the box for it when it opens (boot.ts, receiver-access.json) and did not get it. Until
  // 1.4.3 this told the driver to tap a button the box page does not have (1.5.0).
  access: ['未取得盒子的访问许可', 'No access to the box'], accessHint: ['请检查盒子电源和 AutoPlay 热点，然后刷新本页。', 'Check the box’s power and the AutoPlay hotspot, then reload this page.'],
  fullscreen: ['无边框模式', 'Borderless mode'],
  borderlessOn: ['已开启', 'On'],
  checkingNetwork: ['正在检查网络', 'Checking network'],
  teslaFullscreenOffline: ['车机连不上视频网站，暂时开不了无边框模式。', 'The car can’t reach the video site, so borderless mode is unavailable for now.'],
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
  fpsLowered: ['车机解码跟不上 60 帧，已改为 30 帧。', 'This car can’t decode 60 fps in time; switched to 30 fps.'],
  adjusting: ['正在调整画面', 'Adjusting picture'],
  recoveringNotice: ['连接中断 · 正在重连 · 触控已暂停', 'Link lost · Reconnecting · Touch paused'],
  loadFail: ['读取失败，请检查盒子连接后重试。', 'Could not load settings. Check the receiver connection and retry.'],
  applyFail: ['没有应用成功，请重试。', 'Couldn’t apply. Try again.'],
  autoFail: ['暂未完成自动匹配，可在设置中重试。', 'Automatic matching did not complete. Retry in Settings.'],
  diagnostics: ['连接与兼容性', 'Connection and compatibility'], browserCheck: ['浏览器兼容性检测', 'Browser check'],
  decoding: ['解码能力', 'Decoding'], decodingOk: ['可用', 'Available'], decodingInsecure: ['需要 HTTPS', 'Needs HTTPS'],
  decodingMissing: ['不支持', 'Not supported'], picture: ['当前画面', 'Picture'], unsupported: ['这台车机的浏览器不能解码视频，请更新车辆软件。', 'This car’s browser can’t decode video. Update the car software.'],
  insecure: ['不是安全连接，请用盒子的 https:// 地址打开本页。', 'Not a secure connection. Open this page at the box’s https:// address.'],
  noStream: ['尚无画面', 'No picture yet'],
  hevcAuto: ['这台车机解不了 H.265，已改用 H.264。', "This car cannot decode H.265; switched to H.264."],
  hevcManual: ['这台车机解不了 H.265，请在「显示 › 画质与兼容」把视频编码改为自动。', 'This car can’t decode H.265. Set the video codec to Automatic in Display › Quality and compatibility.'],
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
