/* ES5 classic script: independent of the modern player bundle, so an old car browser still gets a readable answer.
   Driver view first (viewer audit V10): one headline, the missing things in plain words, what to do in this car (a
   Tesla). Since 1.5.4 in the settings panel's look: a title bar, one row per check with its result as the value, the
   reason only under a check that failed, and the browser's own report only when something failed (until then the
   list sat behind a "技术详情" disclosure, and a passed check still spoke of tapping before the first sound, which the
   page has not played since 1.3.0). Bilingual: zh unless this browser's saved language is en. */
(function(w,d){
 'use strict';
 var lang='zh';try{if(w.localStorage&&w.localStorage.getItem('f50-language')==='en')lang='en';}catch(e){}
 var T={
  checking:['正在检测车机浏览器…','Checking this car browser…'],
  checkingNote:['一直停在这里时，请刷新页面。','If this stays, reload the page.'],
  passTitle:['浏览器检测通过','Browser check passed'],passNote:['正在加载播放器…','Loading the player…'],
  failTitle:['这台车机的浏览器无法显示 CarPlay 画面','This car browser cannot show the CarPlay picture'],
  failNote:['缺少：','Missing: '],
  advice:['请在「控制 › 软件」更新车辆软件后再试。','Update the car software (Controls › Software) and try again.'],
  ok:['通过','OK'],missing:['缺少','Missing'],limited:['受限','Limited'],done:['完成','Done'],
  appFailed:['播放器未正常启动','The player did not start'],
  appFailedNote:['请刷新页面；仍不行就更新车辆软件。','Reload the page; if that fails, update the car software.'],
  agent:['浏览器上报：','Browser reports: '],
  secure:['不是安全连接（证书未受信任，或用了 http://）','not a secure connection (certificate not trusted, or http://)'],
  old:['浏览器太旧','browser too old'],video:['视频解码（H.264 / WebCodecs）','video decoding (H.264 / WebCodecs)']
 };
 function t(k){return T[k][lang==='zh'?0:1];}
 var panel=d.getElementById('browser-check'), list=d.getElementById('browser-check-list'), title=d.getElementById('browser-check-title'), note=d.getElementById('browser-check-note'),
     advice=d.getElementById('browser-check-advice'), button=d.getElementById('browser-check-continue'), agent=d.getElementById('browser-check-agent');
 var failures=0,pending=0,timer,plain={},api=w.F50BrowserCheck={done:false,allowed:false,ready:false};
 title.textContent=t('checking');note.textContent=t('checkingNote');button.textContent=t('done');button.hidden=true;
 /* name: the technical row; plainKey: what a driver reads when a required one is missing (one line per cause, no repeats). */
 function add(name,ok,required,detail,plainKey){var kind=ok?'ok':required?'missing':'limited',row=d.createElement('li'),label=d.createElement('b'),value=d.createElement('span');
  row.className=kind;label.appendChild(d.createTextNode(name));
  if(!ok){var why=d.createElement('small');why.appendChild(d.createTextNode(detail));label.appendChild(why);}
  value.appendChild(d.createTextNode(t(kind)));row.appendChild(label);row.appendChild(value);list.appendChild(row);
  if(!ok&&required){failures++;if(plainKey)plain[plainKey]=true;}}
 function report(){if(agent)agent.textContent=t('agent')+w.navigator.userAgent;}
 function plainWords(){var keys=['secure','video','old'],out=[];for(var i=0;i<keys.length;i++)if(plain[keys[i]])out.push(t(keys[i]));return out.join(lang==='zh'?'；':'; ');}
 function finish(){if(api.done||pending)return;api.done=true;api.allowed=failures===0;
  if(!api.allowed){panel.style.display='block';title.textContent=t('failTitle');note.textContent=t('failNote')+plainWords();if(advice)advice.textContent=t('advice');report();return;}
  title.textContent=t('passTitle');note.textContent=t('passNote');timer=w.setTimeout(function(){if(!api.ready)api.appFailed();},12000);}
 api.appReady=function(){api.ready=true;w.clearTimeout(timer);button.disabled=false;button.hidden=false;note.textContent='';if(api.allowed)panel.style.display='none';};
 api.appFailed=function(){w.clearTimeout(timer);panel.style.display='block';title.textContent=t('appFailed');note.textContent=t('appFailedNote');if(advice)advice.textContent=t('advice');report();button.disabled=true;button.hidden=true;};
 api.show=function(){panel.style.display='block';};button.onclick=function(){if(api.allowed&&api.ready)panel.style.display='none';};
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
