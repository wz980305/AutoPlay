const messages = {
  settings: ['设置', 'Settings'], close: ['关闭', 'Close'], language: ['语言', 'Language'],
  waiting: ['正在等待 iPhone', 'Waiting for iPhone'], waitingHint: ['手机开启蓝牙并连接盒子 Wi-Fi，已配对手机会自动重连。', 'Enable Bluetooth and join the receiver Wi-Fi. Paired phones reconnect automatically.'],
  connecting: ['正在连接盒子…', 'Connecting to receiver…'], reconnecting: ['连接中断，正在自动重连…', 'Disconnected. Reconnecting automatically…'],
  starting: ['已连接，正在等待画面…', 'Connected. Waiting for video…'], live: ['已连接', 'Connected'],
  access: ['需要首次登录链接', 'First-time access link required'], accessHint: ['请使用私有访问资料中的完整链接打开一次，此浏览器会记住登录。', 'Open the complete link from your private access file once. This browser will remember it.'],
  sound: ['轻点启用声音', 'Tap to enable sound'], volume: ['音量', 'Volume'],
  display: ['画面', 'Display'], fullscreen: ['全屏', 'Fullscreen'], exitFullscreen: ['退出全屏', 'Exit fullscreen'], fullscreenFail: ['此浏览器不允许全屏，画面仍会自动适配窗口。', 'Fullscreen unavailable. The picture still fits this window.'],
  auto: ['自动匹配屏幕比例', 'Match screen aspect ratio automatically'], autoHint: ['仅此显示端启用。比例变化时重新协商画面，最多 1920 像素长边；可能短暂重连。', 'Enable on one display only. Aspect changes renegotiate video, up to 1920 pixels on the long edge, and may briefly reconnect.'],
  width: ['宽度', 'Width'], height: ['高度', 'Height'], apply: ['应用并重连', 'Apply and reconnect'],
  ui: ['界面大小', 'UI size'], fps: ['帧率', 'Frame rate'], standard: ['标准', 'Standard'], large: ['大', 'Large'], small: ['小', 'Small'],
  loading: ['正在读取…', 'Loading…'], applying: ['正在应用…', 'Applying…'], applied: ['已保存，正在重新连接 CarPlay。', 'Saved. Reconnecting CarPlay.'],
  loadFail: ['读取失败，请检查盒子连接后重试。', 'Could not load settings. Check the receiver connection and retry.'],
  applyFail: ['应用失败，请检查连接和分辨率范围。', 'Could not apply. Check connection and resolution range.'],
  range: ['宽高需为 480–3840 之间的偶数。', 'Width and height must be even numbers between 480 and 3840.'],
  autoFail: ['暂未完成自动匹配，可在设置中重试。', 'Automatic matching did not complete. Retry in Settings.'],
  diagnostics: ['连接与兼容性', 'Connection and compatibility'], advanced: ['备用控制', 'Fallback controls'],
  home: ['主屏幕', 'Home'], back: ['返回', 'Back'], previous: ['上一曲', 'Previous track'], play: ['播放 / 暂停', 'Play / pause'], next: ['下一曲', 'Next track'], refresh: ['刷新画面', 'Refresh video'],
  mic: ['麦克风', 'Microphone'], micHint: ['Siri 与通话需要浏览器允许麦克风；尚未完成车机验证。', 'Siri and calls require browser microphone permission; not yet verified on the car.'],
  compatible: ['基础解码能力可用', 'Basic decoding APIs available'], unsupported: ['此浏览器缺少视频或音频解码能力，请使用支持 WebCodecs 的浏览器。', 'This browser lacks video or audio decoding APIs. Use a browser with WebCodecs support.'],
  insecure: ['当前页面不是安全上下文，请使用已受信任的 HTTPS 地址。', 'This page is not a secure context. Use a trusted HTTPS address.'],
  mediaYes: ['系统媒体控制接口可用，方向盘按键需车机实测。', 'System media API available. Steering-wheel keys require a test in the car.'],
  mediaNo: ['浏览器不提供系统媒体控制接口。', 'This browser does not expose system media controls.'],
  noStream: ['尚无音视频流', 'No media stream yet'], playing: ['音频正在播放', 'Audio playing'], paused: ['等待音频', 'Waiting for audio'],
  error: ['播放遇到问题', 'Playback problem'], technical: ['详细信息', 'Details'],
  savedHere: ['语言、音量与自动匹配偏好保存在此浏览器。CarPlay 内部语言跟随 iPhone。', 'Language, volume and auto-fit preferences are saved in this browser. CarPlay itself follows the iPhone language.'],
  privacy: ['首次登录后无需再次进入设置；自动播放被浏览器拦截时，只需轻点画面一次。', 'No need to reopen settings after setup. If autoplay is blocked, tap the screen once.'],
} as const;
export type Key = keyof typeof messages;
export let language: 'zh' | 'en' = localStorage.getItem('f50-language') === 'en' ? 'en' : 'zh';
export function t(key: Key): string { return messages[key][language === 'zh' ? 0 : 1]; }
export function setLanguage(value: string): void {
  language = value === 'en' ? 'en' : 'zh';
  localStorage.setItem('f50-language', language);
  document.documentElement.lang = language === 'zh' ? 'zh-CN' : 'en';
  document.querySelectorAll<HTMLElement>('[data-i18n]').forEach(e => { e.textContent = t(e.dataset.i18n as Key); });
}
