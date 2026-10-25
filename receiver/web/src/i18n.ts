const messages = {
  settings: ['盒子设置', 'Box settings'], close: ['关闭', 'Close'], done: ['完成', 'Done'],
  boxLink: ['添加 iPhone · 网络设置', 'Add iPhone · Network'], boxLinkHint: ['配对新手机、选择热点', 'Pair a phone, choose the hotspot'],
  boxLinkHintLive: ['离开画面，配对手机、更换热点', 'Leaves the picture to pair phones or change the hotspot'],
  playerSettings: ['画面与声音', 'Display and sound'], displaySettings: ['画面参数', 'Display settings'], performanceMode: ['性能模式', 'Performance mode'], performanceModeHint: ['开：先按最高分辨率放大再缩回窗口，更清楚但更吃解码；关：按窗口实际尺寸（最小宽度 720），清晰度可能下降', 'On: upsize then shrink into the window, sharper but heavier; off: the window own size (min width 720), clarity may drop'], customSize: ['自定义分辨率', 'Custom resolution'], customSizeHint: ['关闭时跟随窗口', 'Off: follow the window'], language: ['语言', 'Language'],
  waiting: ['正在等待 iPhone', 'Waiting for iPhone'], waitingHint: ['已添加的 iPhone 打开蓝牙和 Wi-Fi 后会自动连接。第一次使用，请先添加 iPhone。', 'An added iPhone connects by itself with Bluetooth and Wi-Fi on. First time here? Add your iPhone.'],
  connecting: ['正在连接盒子…', 'Connecting to receiver…'], reconnecting: ['连接中断，正在自动重连…', 'Disconnected. Reconnecting automatically…'],
  starting: ['已连接，正在等待画面…', 'Connected. Waiting for video…'], live: ['已连接', 'Connected'],
  access: ['需要首次登录链接', 'First-time access link required'], accessHint: ['请使用私有访问资料中的完整链接打开一次，此浏览器会记住登录。', 'Open the complete link from your private access file once. This browser will remember it.'],
  sound: ['轻点启用声音', 'Tap to enable sound'], volume: ['音量', 'Volume'],
  display: ['画面', 'Display'], fullscreen: ['全屏', 'Fullscreen'], exitFullscreen: ['退出全屏', 'Exit fullscreen'], fullscreenHint: ['已全屏。退出全屏：点 CarPlay 主屏幕上的「盒子设置」图标，再点「退出全屏」。', 'Fullscreen on. To exit, tap the Box settings icon on the CarPlay home screen, then Exit fullscreen.'], fullscreenFail: ['此浏览器不允许全屏，画面仍会自动适配窗口。', 'Fullscreen unavailable. The picture still fits this window.'], tapFullscreen: ['轻点画面恢复全屏', 'Tap the picture to go back to fullscreen'],
  teslaFullscreenOffline: ['全屏要经腾讯视频跳转，特斯拉现在上不了网。画面照常可用。', 'Fullscreen goes through a video site and the car is offline. The picture keeps working.'],
  autoHint: ['关闭时跟随窗口：窗口多大就用多大，切到没见过的窗口会重连一次；打开后可自己填宽度、高度。只在一个显示端开启。', 'Off: follow the window; a new window size reconnects CarPlay once. On: set the width and height yourself. Turn it on for one display only.'],
  width: ['宽度', 'Width'], height: ['高度', 'Height'], apply: ['应用并重连', 'Apply and reconnect'],
  nightMode: ['夜间模式', 'Night mode'], nightSchedule: ['自动（18:30–06:30 为夜间）', 'Auto (night 18:30–06:30)'], nightSystem: ['跟随车机浏览器深色模式', 'Follow car browser dark mode'], nightDay: ['始终白天', 'Always day'], nightNight: ['始终夜间', 'Always night'],
  nightNow: ['当前请求：', 'Requested now: '], nightOn: ['夜间', 'night'], nightOff: ['白天', 'day'], browserDark: ['车机浏览器报告深色模式', 'Car browser reports dark mode'], browserLight: ['车机浏览器报告浅色模式', 'Car browser reports light mode'],
  latency: ['解码延迟', 'Decode delay'],
  fullscreenButton: ['画面上的全屏按钮', 'Fullscreen button on the picture'], fullscreenButtonHint: ['挡住 CarPlay 里的按钮时换个位置或不显示；全屏仍可在本页顶部点', 'Move or hide it if it covers a CarPlay button; fullscreen stays at the top of this page'],
  cornerTop: ['右上角', 'Top right'], cornerBottom: ['右下角', 'Bottom right'], cornerOff: ['不显示', 'Hidden'],
  debugHud: ['画面上显示调试信息', 'Debug info over the picture'], debugHudHint: ['帧率、分辨率、码率、声音，右下角', 'Frame rate, size, bitrate, sound; bottom right'],
  compatDisplay: ['兼容显示', 'Compatible display'], compatDisplayHint: ['有声音但画面黑屏时打开（老车机浏览器默认打开）；切换后页面会刷新', 'Turn on if there is sound but no picture (on by default in older car browsers); the page reloads'],
  ui: ['界面大小', 'UI size'], fps: ['帧率', 'Frame rate'], codec: ['视频编码', 'Video codec'], codecAuto: ['自动', 'Automatic'], standard: ['标准', 'Standard'], large: ['大', 'Large'], small: ['小', 'Small'], smaller: ['更小', 'Smaller'],
  loading: ['正在读取…', 'Loading…'], applying: ['正在应用…', 'Applying…'], applied: ['已保存，正在重新连接 CarPlay。', 'Saved. Reconnecting CarPlay.'],
  deferred: ['已记下，下次连接 iPhone 时生效，不打断当前画面。', 'Saved for the next connection; the picture is not interrupted now.'],
  nextSession: ['新画质下次连接生效', 'new quality on next connection'],
  fpsLowered: ['车机解码跟不上 60 帧，已自动改为 30 帧（重新连接一次）。', 'This browser cannot decode 60 fps in time; switched to 30 fps (one reconnect).'],
  adjusting: ['正在按新画面重新连接 iPhone…', 'Reconnecting the iPhone for the new picture size…'],
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
  savedHere: ['语言、音量与分辨率偏好保存在此浏览器。CarPlay 内部语言跟随 iPhone。', 'Language, volume and display preferences are saved in this browser. CarPlay itself follows the iPhone language.'],
  privacy: ['首次登录后无需再次进入设置；自动播放被浏览器拦截时，只需轻点画面一次。', 'No need to reopen settings after setup. If autoplay is blocked, tap the screen once.'],
  follow: ['关注作者 · 一只小黑狗', 'Follow the author'],
  followDouyin: ['抖音扫一扫', 'Scan in Douyin'], followXiaohongshu: ['小红书扫一扫', 'Scan in Xiaohongshu'],
  followHint: ['DashPlay 的更新和教程会发在这里；主页有讨论群，有任何问题欢迎在群里讨论。', 'DashPlay updates and how-tos are posted here; the profile links to a discussion group for any questions.'],
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
