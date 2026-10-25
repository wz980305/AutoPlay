const messages = {
  settings: ['盒子设置', 'Box settings'], close: ['关闭', 'Close'], done: ['完成', 'Done'],
  boxLink: ['添加 iPhone · 网络设置', 'Add iPhone · Network'], boxLinkHint: ['配对新手机、选择热点', 'Pair a phone, choose the hotspot'],
  boxLinkHintLive: ['离开画面，配对手机、更换热点', 'Leaves the picture to pair phones or change the hotspot'],
  playerSettings: ['画面与声音', 'Display and sound'], performanceMode: ['性能模式', 'Performance mode'], performanceModeHint: ['开：先按最高分辨率放大再缩回窗口，更清楚但更吃解码；关（默认）：按窗口实际尺寸，更省电、发热更少', 'On: upsize then shrink into the window, sharper but heavier; off (default): the window own size, cooler'], language: ['语言', 'Language'],
  waiting: ['正在等待 iPhone', 'Waiting for iPhone'], waitingHint: ['已添加的 iPhone 打开蓝牙和 Wi-Fi 后会自动连接。第一次使用，请先添加 iPhone。', 'An added iPhone connects by itself with Bluetooth and Wi-Fi on. First time here? Add your iPhone.'],
  connecting: ['正在连接盒子…', 'Connecting to the box…'], reconnecting: ['连接中断，正在自动重连…', 'Link lost. Reconnecting automatically…'],
  reconnectingHint: ['盒子没有响应。请确认盒子已通电、车机已连上 AutoPlay 热点。', 'The box is not answering. Check that it is powered and the car is on the AutoPlay hotspot.'],
  waited: ['已等待 ', 'waiting '], secondsUnit: [' 秒', ' s'],
  starting: ['已连接，正在等待画面…', 'Connected. Waiting for the picture…'], startingHint: ['iPhone 已连接，画面马上出现。', 'iPhone connected; the picture is about to appear.'],
  renegotiating: ['正在按新的窗口大小重新连接 CarPlay…', 'Reconnecting CarPlay for the new window size…'], renegotiatingHint: ['约 5 秒，画面会短暂中断。', 'About 5 seconds; the picture pauses briefly.'],
  live: ['已连接', 'Connected'],
  access: ['需要首次登录链接', 'First-time access link required'], accessHint: ['请使用私有访问资料中的完整链接打开一次，此浏览器会记住登录。', 'Open the complete link from your private access file once. This browser will remember it.'],
  sound: ['轻点屏幕任意位置开启声音（导航播报、Siri）', 'Tap anywhere on the screen to turn on sound (navigation prompts, Siri)'], volume: ['播报音量', 'Prompt volume'],
  display: ['画面', 'Display'], fullscreen: ['无边框模式', 'Borderless mode'], fullscreenRowHint: ['经视频网站跳转约 5 秒后回到本页，去掉地址栏；期间无画面', 'Hops through a video site (~5 s) and comes back without the address bar; no picture meanwhile'],
  borderlessOn: ['已是无边框模式', 'Borderless mode is on'], borderlessOnHint: ['退出：浏览器返回', 'Exit: the browser back button'],
  checkingNetwork: ['正在检查网络…', 'Checking the network…'], checkingNetworkHint: ['跳转需要车辆自己能上网', 'The hop needs the car own internet'],
  teslaFullscreenOffline: ['无边框模式要经视频网站跳转，车辆现在上不了网（盒子没有 SIM 或车辆无流量）。画面照常可用。', 'Borderless mode hops through a video site and the car is offline (no SIM in the box, no data in the car). The picture keeps working.'],
  autoHint: ['分辨率跟随窗口：窗口多大就用多大，切到没见过的窗口会重连一次。帧率、界面大小和编码在这里改。', 'The resolution follows the window: a new window size reconnects CarPlay once. Frame rate, UI size and codec are set here.'],
  apply: ['应用并重连', 'Apply and reconnect'],
  advanced: ['高级', 'Advanced'], advancedHint: ['性能模式、帧率、编码、界面大小、兼容显示、调试', 'Performance mode, frame rate, codec, UI size, compatible display, debug'],
  volumeHint: ['仅此页面的声音：导航播报、提示音。音乐和通话走车机蓝牙。', 'This page sound only: navigation prompts and alerts. Music and calls are on the car Bluetooth.'],
  nightMode: ['夜间模式', 'Night mode'], nightSchedule: ['自动（18:30–06:30 为夜间）', 'Auto (night 18:30–06:30)'], nightSystem: ['跟随车机浏览器深色模式', 'Follow car browser dark mode'], nightDay: ['始终白天', 'Always day'], nightNight: ['始终夜间', 'Always night'],
  nightNow: ['当前请求：', 'Requested now: '], nightOn: ['夜间', 'night'], nightOff: ['白天', 'day'], browserDark: ['车机浏览器报告深色模式', 'Car browser reports dark mode'], browserLight: ['车机浏览器报告浅色模式', 'Car browser reports light mode'],
  latency: ['解码延迟', 'Decode delay'],
  debugHud: ['画面上显示调试信息', 'Debug info over the picture'], debugHudHint: ['帧率、分辨率、码率、声音，右下角', 'Frame rate, size, bitrate, sound; bottom right'],
  allow2560: ['允许 2560 分辨率', 'Allow 2560 px'], allow2560Hint: ['默认最长边 1920；只有解码快的车机才会用到', 'Long side 1920 by default; only a fast-decoding car ever uses it'],
  compatDisplay: ['兼容显示', 'Compatible display'], compatDisplayHint: ['有声音但画面黑屏时打开（老车机浏览器默认打开）；切换后页面会刷新', 'Turn on if there is sound but no picture (on by default in older car browsers); the page reloads'],
  ui: ['界面大小', 'UI size'], fps: ['帧率', 'Frame rate'], codec: ['视频编码', 'Video codec'], codecAuto: ['自动', 'Automatic'], standard: ['标准', 'Standard'], large: ['大', 'Large'], small: ['小', 'Small'], smaller: ['更小', 'Smaller'],
  loading: ['正在读取…', 'Loading…'], applying: ['正在应用…', 'Applying…'], applied: ['已保存，正在重新连接 CarPlay。', 'Saved. Reconnecting CarPlay.'],
  deferred: ['已记下，下次连接 iPhone 时生效，不打断当前画面。', 'Saved for the next connection; the picture is not interrupted now.'],
  nextSession: ['新画质下次连接生效', 'new quality on next connection'],
  fpsLowered: ['车机解码跟不上 60 帧，已自动改为 30 帧（重新连接一次）。', 'This browser cannot decode 60 fps in time; switched to 30 fps (one reconnect).'],
  adjusting: ['正在按新的窗口大小重新连接 · 约 5 秒', 'Reconnecting for the new window size · ~5 s'],
  recoveringNotice: ['连接中断 · 正在重连 · 触控已暂停', 'Link lost · Reconnecting · Touch paused'],
  loadFail: ['读取失败，请检查盒子连接后重试。', 'Could not load settings. Check the receiver connection and retry.'],
  applyFail: ['应用失败，请检查连接和分辨率范围。', 'Could not apply. Check connection and resolution range.'],
  autoFail: ['暂未完成自动匹配，可在设置中重试。', 'Automatic matching did not complete. Retry in Settings.'],
  diagnostics: ['连接与兼容性', 'Connection and compatibility'], browserCheck: ['浏览器兼容性检测', 'Browser check'],
  fallback: ['备用控制', 'Fallback controls'], fallbackHint: ['触控失灵时用；上一曲、播放、下一曲是车机自己的按键', 'When touch fails; previous, play and next are the car own keys'],
  home: ['主屏幕', 'Home'], back: ['返回', 'Back'], refresh: ['刷新画面', 'Refresh video'],
  compatible: ['基础解码能力可用', 'Basic decoding APIs available'], unsupported: ['此浏览器缺少视频或音频解码能力，请使用支持 WebCodecs 的浏览器。', 'This browser lacks video or audio decoding APIs. Use a browser with WebCodecs support.'],
  insecure: ['当前页面不是安全上下文，请使用已受信任的 HTTPS 地址。', 'This page is not a secure context. Use a trusted HTTPS address.'],
  noStream: ['尚无音视频流', 'No media stream yet'], playing: ['音频正在播放', 'Audio playing'], paused: ['等待音频', 'Waiting for audio'],
  error: ['播放遇到问题', 'Playback problem'], technical: ['详细信息', 'Details'],
  savedHere: ['语言、音量与分辨率偏好保存在此浏览器。CarPlay 内部语言跟随 iPhone。', 'Language, volume and display preferences are saved in this browser. CarPlay itself follows the iPhone language.'],
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
