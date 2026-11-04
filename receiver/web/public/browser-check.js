/* ES5 classic script: independent of the modern player bundle, so an old car browser still gets a readable answer.
   Driver view first (viewer audit V10): one headline, the missing things in plain words, what to do in this car (a
   Tesla), and the technical list behind a disclosure. Bilingual: zh unless this browser's saved language is en. */
(function(w,d){
 'use strict';
 var lang='zh';try{if(w.localStorage&&w.localStorage.getItem('f50-language')==='en')lang='en';}catch(e){}
 var T={
  checking:['正在检测车机浏览器…','Checking this car browser…'],
  checkingNote:['如果此提示一直不变，请确认 JavaScript 已启用，或刷新页面。','If this never changes, make sure JavaScript is on, or reload the page.'],
  passTitle:['浏览器检测通过','Browser check passed'],passNote:['正在加载播放器…','Loading the player…'],
  failTitle:['这台车机的浏览器无法显示 CarPlay 画面','This car browser cannot show the CarPlay picture'],
  failNote:['缺少：','Missing: '],
  advice:['特斯拉：在「控制 › 软件」更新车辆软件后再试；旧版本的浏览器不能解码视频。地址必须是盒子的 https:// 名称（证书受信任）。','Tesla: update the car software (Controls › Software) and try again; older browsers cannot decode video. Open the box by its https:// name (trusted certificate).'],
  details:['技术详情','Technical details'],ok:['通过：','OK: '],missing:['缺少：','Missing: '],limited:['受限：','Limited: '],
  loading:['正在加载播放器…','Loading the player…'],unavailable:['无法显示画面','Cannot show the picture'],enter:['进入 CarPlay','Enter CarPlay'],
  ready:['播放器已启动。检测通过不代表已连接 iPhone；第一次声音播放前需轻点屏幕。','The player is running. A passed check does not mean the iPhone is connected; tap the screen once before the first sound.'],
  appFailed:['播放器未正常启动','The player did not start'],
  appFailedNote:['脚本加载或初始化失败。请刷新页面；仍不行则更新车辆软件。','The script failed to load or start. Reload the page; if that fails, update the car software.'],
  agent:['浏览器上报：','Browser reports: '],
  secure:['不是安全连接（证书未受信任，或用了 http://）','not a secure connection (certificate not trusted, or http://)'],
  old:['浏览器太旧','browser too old'],video:['视频解码（H.264 / WebCodecs）','video decoding (H.264 / WebCodecs)']
 };
 function t(k){return T[k][lang==='zh'?0:1];}
 var panel=d.getElementById('browser-check'), list=d.getElementById('browser-check-list'), title=d.getElementById('browser-check-title'), note=d.getElementById('browser-check-note'),
     advice=d.getElementById('browser-check-advice'), button=d.getElementById('browser-check-continue'), summary=d.getElementById('browser-check-details-title');
 var failures=0,pending=0,timer,plain={},api=w.F50BrowserCheck={done:false,allowed:false,ready:false};
 title.textContent=t('checking');note.textContent=t('checkingNote');if(summary)summary.textContent=t('details');button.textContent=t('checking');
 /* name: the technical row; plainKey: what a driver reads when a required one is missing (one line per cause, no repeats). */
 function add(name,ok,required,detail,plainKey){var row=d.createElement('li');row.style.marginBottom='.4em';row.style.color=ok?'#b5edc9':required?'#ffb7ad':'#ffe3a1';
  row.appendChild(d.createTextNode((ok?t('ok'):required?t('missing'):t('limited'))+name+'。'+detail));list.appendChild(row);
  if(!ok&&required){failures++;if(plainKey)plain[plainKey]=true;}}
 function plainWords(){var keys=['secure','video','old'],out=[];for(var i=0;i<keys.length;i++)if(plain[keys[i]])out.push(t(keys[i]));return out.join(lang==='zh'?'；':'; ');}
 function finish(){if(api.done||pending)return;api.done=true;api.allowed=failures===0;
  if(!api.allowed){panel.style.display='block';title.textContent=t('failTitle');note.textContent=t('failNote')+plainWords();if(advice)advice.textContent=t('advice');button.textContent=t('unavailable');return;}
  title.textContent=t('passTitle');note.textContent=t('passNote');button.textContent=t('loading');timer=w.setTimeout(function(){if(!api.ready)api.appFailed();},12000);}
 api.appReady=function(){api.ready=true;w.clearTimeout(timer);button.disabled=false;button.textContent=t('enter');note.textContent=t('ready');if(api.allowed)panel.style.display='none';};
 api.appFailed=function(){w.clearTimeout(timer);panel.style.display='block';title.textContent=t('appFailed');note.textContent=t('appFailedNote');if(advice)advice.textContent=t('advice');button.disabled=true;};
 api.show=function(){panel.style.display='block';};button.onclick=function(){if(api.allowed&&api.ready)panel.style.display='none';};
 d.getElementById('browser-check-agent').textContent=t('agent')+w.navigator.userAgent;
 var zh=lang==='zh';
 add(zh?'HTTPS 安全上下文':'HTTPS secure context',w.isSecureContext===true,true,zh?'视频解码需要安全上下文。':'Video decoding needs a secure context.','secure');
 add('WebSocket',typeof w.WebSocket==='function',true,zh?'接收画面与发送触控。':'Receives the picture, sends touches.','old');
 add(zh?'JavaScript 模块':'JavaScript modules','noModule' in d.createElement('script'),true,zh?'播放器的脚本格式。':'The player script format.','old');
 add('Canvas',!!d.createElement('canvas').getContext('2d'),true,zh?'绘制画面。':'Draws the picture.','old');
 add('Pointer Events',!!w.PointerEvent,true,zh?'画面内触控。':'Touch on the picture.','old');
 add(zh?'设置弹窗':'Settings dialog',!!d.createElement('dialog').showModal,true,zh?'打开设置需要。':'Needed to open Settings.','old');
 add(zh?'WebCodecs 视频解码':'WebCodecs video decoding',!!w.VideoDecoder,true,zh?'缺少 VideoDecoder 无法显示画面。':'Without VideoDecoder there is no picture.','video');
 if(w.VideoDecoder&&typeof w.VideoDecoder.isConfigSupported==='function'){
  pending++;var completed=false;
  function result(ok,detail){if(completed)return;completed=true;add(zh?'H.264 解码探测':'H.264 decode probe',ok,true,detail,'video');pending--;finish();}
  w.setTimeout(function(){result(false,zh?'检测超时。':'The probe timed out.');},5000);
  try{w.VideoDecoder.isConfigSupported({codec:'avc1.42E01F',codedWidth:1280,codedHeight:720}).then(function(r){result(!!r.supported,zh?'720p 基础配置。':'720p baseline profile.');},function(){result(false,zh?'浏览器拒绝检测。':'The browser refused the probe.');});}catch(e){result(false,zh?'浏览器无法检测该配置。':'The browser could not probe it.');}
 }else if(w.VideoDecoder)add(zh?'H.264 解码探测':'H.264 decode probe',false,true,zh?'缺少 isConfigSupported。':'No isConfigSupported.','video');
 finish();
}(window,document));
