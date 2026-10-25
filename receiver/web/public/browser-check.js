/* ES5 classic script: independent of the modern player bundle. */
(function(w,d){
 'use strict';
 var panel=d.getElementById('browser-check'), list=d.getElementById('browser-check-list'), title=d.getElementById('browser-check-title'), note=d.getElementById('browser-check-note'), button=d.getElementById('browser-check-continue');
 var failures=0,pending=0,timer,api=w.F50BrowserCheck={done:false,allowed:false,ready:false};
 function add(name,ok,required,detail){var row=d.createElement('li');row.style.marginBottom='10px';row.style.color=ok?'#b5edc9':required?'#ffb7ad':'#ffe3a1';row.appendChild(d.createTextNode((ok?'通过：':required?'缺少：':'受限：')+name+'。'+detail));list.appendChild(row);if(!ok&&required)failures++;}
 function finish(){if(api.done||pending)return;api.done=true;api.allowed=failures===0;title.textContent=api.allowed?'浏览器基础检测通过':'此浏览器暂不能使用标准 CarPlay 模式';note.textContent=api.allowed?'正在加载播放器；实际画面、声音仍需连接后验证。':'缺失能力会造成黑屏或操作异常。请使用较新的浏览器；实验兼容模式仍在研究，当前未启用。';button.textContent=api.allowed?'正在加载播放器…':'标准模式不可用';if(api.allowed)timer=w.setTimeout(function(){if(!api.ready)api.appFailed();},12000);}
 api.appReady=function(){api.ready=true;w.clearTimeout(timer);button.disabled=false;button.textContent='进入 CarPlay';note.textContent='播放器已启动。检测通过不代表已连接 iPhone；首次声音播放可能需要点击。';w.setTimeout(function(){if(api.allowed)panel.style.display='none';},2500);};
 api.appFailed=function(){w.clearTimeout(timer);panel.style.display='block';title.textContent='播放器未正常启动';note.textContent='可能是现代 JavaScript 不兼容、脚本加载失败或初始化失败。请刷新或更新浏览器。';button.disabled=true;};
 api.show=function(){panel.style.display='block';};button.onclick=function(){if(api.allowed&&api.ready)panel.style.display='none';};
 d.getElementById('browser-check-agent').textContent='浏览器上报：'+w.navigator.userAgent;
 add('HTTPS 安全上下文',w.isSecureContext===true,true,'视频解码需要安全上下文；证书页面必须能正常访问。');
 add('WebSocket',typeof w.WebSocket==='function',true,'接收画面与发送触控。');
 add('JavaScript 模块','noModule' in d.createElement('script'),true,'播放器还会验证现代脚本是否成功启动。');
 add('Canvas',!!d.createElement('canvas').getContext('2d'),true,'绘制画面。');
 add('Web Audio',!!w.AudioContext,true,'当前播放器初始化及辅助音轨需要。');
 add('Pointer Events',!!w.PointerEvent,true,'画面内触控需要。');
 add('设置弹窗',!!d.createElement('dialog').showModal,true,'打开设置需要。');
 add('WebCodecs 视频解码',!!w.VideoDecoder,true,'缺少 VideoDecoder 无法显示标准模式画面。');
 add('实验候选：MSE H.264 播放',!!w.MediaSource&&typeof w.MediaSource.isTypeSupported==='function'&&w.MediaSource.isTypeSupported('video/mp4; codecs="avc1.42E01F"'),false,'仅调查兼容路线，不代表兼容模式已经实现。');
 add('AAC 原生音乐播放',!!w.MediaSource&&w.MediaSource.isTypeSupported('audio/mp4; codecs="mp4a.40.2"'),false,'不支持时可能降级或没有声音，系统媒体控制也可能不可用。');
 add('辅助音频解码',!!w.AudioDecoder,false,'缺少 AudioDecoder 时部分音轨不可用。');
 add('全屏',!!d.documentElement.requestFullscreen,false,'不支持时仍可在窗口内显示。');
 add('系统媒体控制',!!w.navigator.mediaSession,false,'影响系统媒体卡片；方向盘按键仍需车机实测。');
 if(w.VideoDecoder&&typeof w.VideoDecoder.isConfigSupported==='function'){
  pending++;var completed=false;
  function result(ok,detail){if(completed)return;completed=true;add('H.264 解码探测',ok,true,detail);pending--;finish();}
  w.setTimeout(function(){result(false,'检测超时，无法确认支持。');},5000);
  try{w.VideoDecoder.isConfigSupported({codec:'avc1.42E01F',codedWidth:1280,codedHeight:720}).then(function(r){result(!!r.supported,'检测 720p 基础配置；手机实际编码与分辨率仍需连接后验证。');},function(){result(false,'浏览器拒绝检测请求。');});}catch(e){result(false,'浏览器无法检测该配置。');}
 }else if(w.VideoDecoder)add('H.264 解码探测',false,true,'缺少 isConfigSupported。');
 finish();
}(window,document));
