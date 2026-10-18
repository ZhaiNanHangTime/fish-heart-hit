'use strict';
const $=id=>document.getElementById(id), preview=$('preview');
const FRAMES={ghost:'幽灵',fish:'原版咸鱼',idle:'冷静',alert_low:'好奇',alert_mid:'专注',tense:'紧张',high:'慌张',charge:'蓄力',burst:'突刺',recover:'收招'};
const fields=['skin','fishScale','fishWidth','fxWarmth','fxKick','viewWidth','viewHeight','traceLayout','traceSeconds','hudWidth','hudHeight'];
let originalSize=false,lastPanelRequest=0,selectedTool='/monitor?noiframe=1',hudEditBusy=false,toastTimer=null,runtimeSession=null,previewState=null;
let previewTarget=location.hash==='#hud-size'?'hud':'obs';
let draft={},saved={},dirty=new Set(),snapshot={},ready=false,mode='live',forcedFrame=null,token=null,ramp=null,hudBusy=false,ending=false,connected=false,lastSeen=0,saving=false;
let recordingBusy=false;
function updateRecording(){
 const r=snapshot.recording,available=connected&&!ending&&!!snapshot.runtime?.available&&!!r?.available&&!recordingBusy;
 const game=r?.activity==='game',labels={unmarked:'未标注',game:'游戏记录中',non_game:'非游戏记录中'};
 $('recordingStart').disabled=!available||game;
 $('recordingEnd').disabled=!available||r?.activity==='non_game';
 $('recordingUnknown').disabled=!available||r?.activity==='unmarked';
 $('gameName').disabled=!available||game;
 $('recordingEnd').textContent=game?'结束游戏记录':'标为非游戏';
 $('recordingState').textContent=!connected?'状态未知':r?.error||(!r?.available?'未开启CSV记录':labels[r.activity]||'未标注');
 $('recordingState').classList.toggle('recording-on',!!game);
 const seconds=Math.max(0,Math.floor(Date.now()/1000-(r?.started_at||Date.now()/1000)));
 $('recordingDetail').textContent=r?.active?`${game?(r.game||'未填写游戏名')+' · ':''}${Math.floor(seconds/60)}分${seconds%60}秒 · ${r.samples} 个有效心率样本`:'通过一键入口启动服务后，可在这里标记游戏时段。';
 $('recordingFile').textContent=r?.file?'当前文件：'+r.file:'';
}
async function markRecording(activity){
 recordingBusy=true;updateRecording();
 try{
  snapshot.recording=await control('recording',{activity,game:activity==='game'?$('gameName').value:'',expected_segment:snapshot.recording?.segment_id});
  status(activity==='game'?'已开始游戏记录；结束游戏时请点“结束游戏记录”。':activity==='non_game'?'已切换为非游戏记录，游戏文件已独立保存。':'后续记录改为未标注；已保存的标签不变。','success');
 }catch(e){status(e.message,'error')}
 finally{recordingBusy=false;updateRecording()}
}
$('recordingStart').addEventListener('click',()=>markRecording('game'));
$('recordingEnd').addEventListener('click',()=>markRecording('non_game'));
$('recordingUnknown').addEventListener('click',()=>markRecording('unmarked'));
function status(text,type=''){
 $('saveStatus').textContent=text;$('saveStatus').className='status '+type;
 $('feedback').textContent=text;$('feedback').className='feedback '+type;$('feedback').hidden=false;
 clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('feedback').hidden=true,type==='error'?10000:4500);
}
function renderAvailability(){
 const blocked=saving||!connected||ending||!dirty.size;
 for(const id of ['save','applyHudSize','applyPreview'])$(id).disabled=blocked;
 updateRuntime(snapshot.runtime);
 updateRecording();
}

function renderSettings(){
 document.querySelectorAll('[data-skin]').forEach(el=>el.setAttribute('aria-pressed',String(el.dataset.skin===draft.skin)));
 document.querySelectorAll('[data-layout]').forEach(el=>el.setAttribute('aria-pressed',String(el.dataset.layout===(draft.traceLayout||'overlay'))));
 document.querySelectorAll('[data-fish-width]').forEach(el=>el.setAttribute('aria-pressed',String(Number(el.dataset.fishWidth)===(draft.fishWidth??1.5))));
 $('fishScale').value=Math.round((draft.fishScale??1)*100);$('fishScaleText').textContent=$('fishScale').value+'%';
 $('fishWidth').value=Math.round((draft.fishWidth??1.5)*100);$('fishWidthText').textContent=$('fishWidth').value+'%';
 $('traceSeconds').value=String(draft.traceSeconds??180);
 $('xianyuEffects').hidden=draft.skin!=='xianyu';$('poseControls').hidden=draft.skin!=='xianyu';
 $('warmth').checked=draft.fxWarmth!==false;$('kick').checked=draft.fxKick!==false;
 $('resolution').value=(draft.viewWidth||520)+','+(draft.viewHeight||170);
 for(const key of ['hudWidth','hudHeight']){
  $(key).value=draft[key]??(key==='hudWidth'?240:104);
  $(key+'Text').textContent=$(key).value+' px';
 }
 $('hudSize').textContent=(saved.hudWidth||240)+' × '+(saved.hudHeight||104);
 $('applyHudSize').disabled=saving||!connected||!dirty.size;
 $('applyPreview').disabled=saving||!connected||!dirty.size;
 $('hudSizeNote').textContent=dirty.size?'当前画面尚未应用；点击“应用当前画面”同时保存尺寸与外观。':'当前画面已应用；皮肤、角色大小及布局共享，输出宽高分别设置。';
 document.querySelectorAll('[data-preview-target]').forEach(el=>el.setAttribute('aria-pressed',String(el.dataset.previewTarget===previewTarget)));
 $('obsSize').textContent=(draft.viewWidth||520)+' × '+(draft.viewHeight||170);
 $('obsUrl').textContent=location.origin+'/';$('copy').disabled=false;
 $('save').disabled=saving||!dirty.size||!connected;$('save').textContent=dirty.size?'应用到直播':'已同步';
 $('draftNote').hidden=!dirty.size;
 const [w,h]=previewSize();
 preview.style.width=w+'px';preview.style.aspectRatio=w+'/'+h;
 fitPreview();
 renderAvailability();
}
function fitPreview(){
 const [w,h]=previewSize();
 const scale=originalSize?1:Math.min(1,Math.max(120,$('screen').clientWidth-26)/w);
 $('screen').classList.toggle('original-size',originalSize);
 $('previewZoom').textContent=originalSize?'缩略适应窗口':'原始尺寸 1:1';
 $('previewZoom').setAttribute('aria-pressed',String(originalSize));
 $('previewDimensions').textContent=w+' × '+h+' px · 预览 '+Math.round(scale*100)+'%'+(dirty.size?' · 未应用草稿':' · 已应用');
 preview.style.width=w+'px';preview.style.height=h+'px';preview.style.transform='scale('+scale+')';
 $('previewStage').style.width=(w*scale)+'px';$('previewStage').style.height=(h*scale)+'px';
 preview.title=(previewTarget==='hud'?'桌面悬浮窗':'OBS')+'预览 '+w+' × '+h+(scale<1?'（缩略显示）':'');
}
function previewSize(){return previewTarget==='hud'?[draft.hudWidth||240,draft.hudHeight||104]:[draft.viewWidth||520,draft.viewHeight||170]}
function setPreviewTarget(target){if(previewTarget===target)return;previewTarget=target;setMode(mode);renderSettings();}
function change(key,value){if(key==='skin')forcedFrame=null;draft[key]=value;if(saved[key]===value)dirty.delete(key);else dirty.add(key);renderSettings();transmit();status(dirty.size?'预览已更新，点击“应用到直播”后同步到悬浮窗和OBS。':'与直播设置一致');}
function transmit(extra={}){
 if(!ready)return;
 preview.contentWindow.postMessage({type:'params',params:draft},location.origin);
 if(mode==='demo') preview.contentWindow.postMessage({type:'fish-demo-control',bpm:Number($('bpm').value),base:snapshot.base??70,frame:forcedFrame,fishScale:draft.fishScale,effects:{warmth:draft.fxWarmth,kick:draft.fxKick},...extra},location.origin);
}
function stopRamp(){if(ramp)clearInterval(ramp);ramp=null;$('ramp').textContent='自动演示';}
function openTool(path){
 selectedTool=path;$('toolframe').hidden=false;
 if($('toolframe').getAttribute('src')!==path){$('toolStatus').textContent='正在打开工具…';$('toolframe').src=path;}
 document.querySelectorAll('[data-tool]').forEach(el=>el.setAttribute('aria-pressed',String(el.dataset.tool===path)));
}
function setMode(next){
 if(!['live','demo','more'].includes(next))next='live';
 if(mode!==next){forcedFrame=null;stopRamp();document.querySelectorAll('[data-frame]').forEach(x=>x.setAttribute('aria-pressed','false'));}
 mode=next;
 const source=(next==='demo'?'/?demo=1&controlled=1&bg=1':'/?preview=1&bg=1')+(previewTarget==='hud'?'&hudPreview=1':'');
 if(preview.getAttribute('src')!==source){ready=false;previewState=null;$('showBpm').textContent='—';$('showFrame').textContent='加载中…';$('showHeat').textContent='—';$('fitNotice').textContent='正在加载预览…';preview.src=source;}
 $('previewKind').textContent=(previewTarget==='hud'?'桌面 · ':'OBS · ')+(next==='demo'?'模拟预览':'真实心率');
 $('simulation').hidden=next!=='demo';$('tools').hidden=next!=='more';$('outputControls').hidden=next!=='live';
 $('recordingPanel').hidden=next!=='live';
 $('appearance').hidden=next==='more';$('baselinePanel').hidden=next==='more';
 $('workspace').hidden=false;document.querySelector('main').dataset.view=next;
 requestAnimationFrame(fitPreview);
 $('workspace').setAttribute('aria-labelledby','tab-'+next);
 $('modeDescription').textContent={live:'直播总控：使用手表真实心率，调整外观后应用到直播。',demo:'试效果：模拟心率与姿态，仅在预览中演示，不改变正式直播。',more:'更多工具：历史与数据、高级参数、行为验收，在这里直接打开。'}[next];
 $('previewNote').textContent=next==='demo'?'这里的心率、姿态和突刺仅用于试效果，不会发送到正式直播。':'画面使用真实心率；外观调整可先预览，应用后再同步到正式直播。';
 document.querySelectorAll('[data-mode]').forEach(el=>{const active=el.dataset.mode===next;el.setAttribute('aria-selected',String(active));el.tabIndex=active?0:-1;});
 if(next==='more')openTool(selectedTool);
 else if($('toolframe').hasAttribute('src')){$('toolframe').removeAttribute('src');$('toolframe').hidden=true;}
}
function navigateMode(next){
 setMode(next);history.replaceState(null,'',next==='demo'?'#effects':next==='more'?'#tools':'#live');
 const panel=next==='demo'?$('simulation'):next==='more'?$('tools'):$('workspace');
 if(panel.getBoundingClientRect().top>innerHeight*.65)panel.scrollIntoView({block:'start'});
 status({live:'已切换到直播总控',demo:'已打开模拟效果，请使用右侧或下方的演示控件',more:'已打开更多工具：默认显示历史与数据'}[next]);
}

function updateRuntime(rt){
 const available=!!rt?.available && connected && !rt?.stopping;
 $('hud').disabled=!available||hudBusy||ending;
 $('hudEdit').disabled=!available||ending||hudEditBusy;
 $('hudEdit').textContent=rt?.hud_editing?'完成边界调整':'显示悬浮窗边界 / 拖角调整';
 $('hud').textContent=rt?.hud?'关闭悬浮窗':'显示悬浮窗';$('hud').dataset.visible=String(!!rt?.hud);
 $('hudStatus').textContent=!connected?(ending?'本次运行已结束':'连接中断，状态未知'):rt?.error||(rt?.hud?'已开启 · 右键“大小与外观”回到总控，预览与悬浮窗共用尺寸':'默认关闭，需要时再打开');
 $('shutdown').disabled=!available||ending;
}
async function readResponse(response){
 const raw=await response.text();let data;
 try{data=JSON.parse(raw)}catch(_){throw Error(response.ok?'服务返回了无效内容，请刷新总控重试':'操作失败（HTTP '+response.status+'），请稍后重试')}
 if(!response.ok)throw Error(data.error||data.message||'操作失败（HTTP '+response.status+'）');
 return data;
}
async function control(path,body={},retried=false){
 try{
  if(!token){const r=await fetch('/control',{cache:'no-store'});token=(await readResponse(r)).token;if(!token)throw Error('总控尚未就绪，请使用一键入口启动');}
  const r=await fetch('/control/'+path,{method:'POST',headers:{'Content-Type':'application/json','X-Control-Token':token},body:JSON.stringify(body)});
  if(r.status===403&&!retried){token=null;return control(path,body,true)}
  return await readResponse(r);
 }catch(e){if(e instanceof TypeError)throw Error('服务连接失败，请确认一键入口仍在运行');throw e;}
}

preview.addEventListener('load',()=>{ready=true;transmit()});
document.querySelectorAll('[data-skin]').forEach(el=>el.addEventListener('click',()=>change('skin',el.dataset.skin)));
document.querySelectorAll('[data-layout]').forEach(el=>el.addEventListener('click',()=>change('traceLayout',el.dataset.layout)));
$('traceSeconds').addEventListener('change',()=>change('traceSeconds',Number($('traceSeconds').value)));
document.querySelectorAll('[data-preview-target]').forEach(el=>el.addEventListener('click',()=>setPreviewTarget(el.dataset.previewTarget)));
for(const key of ['hudWidth','hudHeight'])$(key).addEventListener('input',()=>{const value=Number($(key).value);setPreviewTarget('hud');change(key,value)});
document.querySelectorAll('[data-hud-size]').forEach(el=>el.addEventListener('click',()=>{
 setPreviewTarget('hud');const [w,h]=el.dataset.hudSize.split(',').map(Number);change('hudWidth',w);change('hudHeight',h);
}));
$('previewZoom').addEventListener('click',()=>{originalSize=!originalSize;fitPreview()});
$('hudEdit').addEventListener('click',async()=>{
 hudEditBusy=true;updateRuntime(snapshot.runtime);
 try{snapshot.runtime=await control('hud-edit',{editing:!snapshot.runtime?.hud_editing});if(snapshot.runtime.error)throw Error(snapshot.runtime.error);status(snapshot.runtime.hud_editing?'悬浮窗边界已显示，可拖动右下角':'已完成边界调整');}
 catch(e){status(e.message,'error')}
 finally{hudEditBusy=false;updateRuntime(snapshot.runtime)}
});
$('fishScale').addEventListener('input',()=>change('fishScale',Number($('fishScale').value)/100));
$('fishWidth').addEventListener('input',()=>change('fishWidth',Number($('fishWidth').value)/100));
document.querySelectorAll('[data-fish-width]').forEach(button=>button.addEventListener('click',()=>change('fishWidth',Number(button.dataset.fishWidth))));
$('warmth').addEventListener('change',()=>change('fxWarmth',$('warmth').checked));
$('kick').addEventListener('change',()=>change('fxKick',$('kick').checked));
$('resolution').addEventListener('change',()=>{const [w,h]=$('resolution').value.split(',').map(Number);change('viewWidth',w);change('viewHeight',h)});
async function saveChanges(keys=null){
 if(saving)return;
 const body=Object.fromEntries([...dirty].filter(k=>!keys||keys.includes(k)).map(k=>[k,draft[k]]));if(!Object.keys(body).length)return;
 saving=true;renderSettings();status('正在应用…');
 try{
  const r=await fetch('/params',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}),data=await readResponse(r);
  for(const [k,v] of Object.entries(body))if(draft[k]===v)dirty.delete(k);
  saved=data;for(const k of fields)if(!dirty.has(k))draft[k]=data[k];
  renderSettings();transmit();status(keys?'悬浮窗尺寸已应用。':'已应用到直播设置。','success');
 }catch(e){status(e instanceof TypeError?'保存失败，服务连接中断；当前草稿仍保留。':e.message,'error')}
 finally{saving=false;renderSettings()}
}
$('save').addEventListener('click',()=>saveChanges());
$('applyHudSize').addEventListener('click',()=>saveChanges());
$('applyPreview').addEventListener('click',()=>saveChanges());
$('discard').addEventListener('click',()=>{draft={...saved};dirty.clear();renderSettings();transmit();status('已恢复到当前直播设置')});
$('copy').addEventListener('click',async()=>{
 try{await navigator.clipboard.writeText(location.origin+'/');$('copy').textContent='已复制';setTimeout(()=>$('copy').textContent='复制地址',2000)}
 catch(_){status('请选中下方地址手动复制','error')}
});
$('hud').addEventListener('click',async()=>{
 hudBusy=true;updateRuntime(snapshot.runtime);
 try{const result=await control('hud',{visible:$('hud').dataset.visible!=='true'});snapshot.runtime=result;updateRuntime(result);if(result.error)status(result.error,'error')}
 catch(e){status(e.message,'error')}
 finally{hudBusy=false;updateRuntime(snapshot.runtime)}
});
$('shutdown').addEventListener('click',async()=>{
 ending=true;renderAvailability();
 try{await control('shutdown');$('service').textContent='本次运行已结束';$('sessionEnded').hidden=false;status('服务和由总控打开的悬浮窗正在退出。再次双击启动文件即可恢复。');}
 catch(e){ending=false;status(e.message,'error');renderAvailability()}
});
$('calibrate').addEventListener('click',async()=>{
 $('calibrate').disabled=true;$('baseNote').dataset.manual='true';setTimeout(()=>delete $('baseNote').dataset.manual,8000);
 try{const r=await fetch('/calibrate',{method:'POST'}),data=await readResponse(r);$('baseNote').textContent=data.message||'校准完成';status($('baseNote').textContent,'success');}
 catch(e){$('baseNote').textContent=e instanceof TypeError?'服务连接失败，请重新打开总控':e.message;status($('baseNote').textContent,'error');}
 finally{$('calibrate').disabled=false}
});
document.querySelectorAll('[data-mode]').forEach(el=>el.addEventListener('click',()=>navigateMode(el.dataset.mode)));
document.querySelector('nav').addEventListener('keydown',ev=>{
 const tabs=[...document.querySelectorAll('[data-mode]')],index=tabs.indexOf(document.activeElement);
 if(index<0||!['ArrowLeft','ArrowRight','Home','End'].includes(ev.key))return;
 ev.preventDefault();const next=ev.key==='Home'?0:ev.key==='End'?tabs.length-1:(index+(ev.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;
 tabs[next].focus();navigateMode(tabs[next].dataset.mode);
});

$('bpm').addEventListener('input',()=>{document.querySelectorAll('[data-frame]').forEach(x=>x.setAttribute('aria-pressed','false'));forcedFrame=null;stopRamp();$('bpmText').textContent=$('bpm').value+' BPM';transmit()});
document.querySelectorAll('[data-frame]').forEach(el=>el.addEventListener('click',()=>{forcedFrame=el.dataset.frame;document.querySelectorAll('[data-frame]').forEach(x=>x.setAttribute('aria-pressed',String(x===el)));transmit()}));
$('autoFrame').addEventListener('click',()=>{forcedFrame=null;document.querySelectorAll('[data-frame]').forEach(x=>x.setAttribute('aria-pressed','false'));transmit()});
$('burst').addEventListener('click',()=>{document.querySelectorAll('[data-frame]').forEach(x=>x.setAttribute('aria-pressed','false'));forcedFrame=null;transmit({burst:true})});
$('ramp').addEventListener('click',()=>{
 if(ramp){stopRamp();return;}forcedFrame=null;document.querySelectorAll('[data-frame]').forEach(x=>x.setAttribute('aria-pressed','false'));const start=performance.now();$('ramp').textContent='停止演示';
 ramp=setInterval(()=>{const t=(performance.now()-start)/1000;if(t>12){stopRamp();return}const b=snapshot.base??70;$('bpm').value=Math.round(b+(t<8?t*3:(12-t)*6));$('bpmText').textContent=$('bpm').value+' BPM';transmit()},120);
});
document.querySelectorAll('[data-tool]').forEach(el=>el.addEventListener('click',()=>openTool(el.dataset.tool)));
$('toolframe').addEventListener('load',()=>{if($('toolframe').hasAttribute('src'))$('toolStatus').textContent='工具已打开，可直接操作';});
function focusHudSizing(){
 setMode('live');setPreviewTarget('hud');$('hudSizing').scrollIntoView({block:'center',behavior:'smooth'});
}
window.addEventListener('hashchange',()=>{
 if(location.hash==='#hud-size')focusHudSizing();
 else setMode(location.hash==='#effects'?'demo':location.hash==='#tools'?'more':'live');
});
window.addEventListener('resize',fitPreview);
window.addEventListener('message',ev=>{
 if(ev.origin!==location.origin||ev.source!==preview.contentWindow)return;
 const d=ev.data;if(!d||!['fish-demo-state','fish-preview-state'].includes(d.type))return;
 if((mode==='demo')!==(d.type==='fish-demo-state')||(d.layout&&d.layout.target!==previewTarget))return;
 previewState=d;
 if(d.layout){$('fitNotice').textContent=d.layout.fitted?'当前空间不足，已限制角色显示范围；继续放大或拉宽请增加窗口宽高。':'尺寸和布局已统一；素材宽窄按你选择的比例显示。'}
 $('showBpm').textContent=(d.bpm??'—');$('showFrame').textContent=FRAMES[d.frame]||d.frame||'—';$('showHeat').textContent=Math.round((d.intensity||0)*100)+'%';
 if(d.assetError)status(d.assetError,'error');
});
HRLive.subscribe(s=>{
 if(s.stream_online===false){connected=false;$('service').textContent=ending?'本次运行已结束':'服务连接中断';renderAvailability();return;}
 snapshot=s;lastSeen=performance.now();connected=true;
 if(s.runtime?.session_id){
  if(runtimeSession&&runtimeSession!==s.runtime.session_id){ending=false;token=null;lastPanelRequest=0;$('sessionEnded').hidden=true;}
  runtimeSession=s.runtime.session_id;
 }
 if(s.runtime?.stopping){ending=true;$('sessionEnded').hidden=false;}
 $('service').textContent=ending?'正在结束':s.synthetic?'自检预览 · 合成数据':'总控已就绪';$('device').textContent=s.synthetic?'合成自检数据':s.connected&&s.bpm!=null?'心率设备已连接':'正在等待心率广播';$('devicePill').className='pill'+(s.connected&&s.bpm!=null?'':' off');
 $('base').textContent=s.base==null?'预热中':s.base.toFixed(1);$('p25').textContent=s.baseline?.p25??'—';$('delta').textContent=s.baseline?.delta??'—';
 if(!$('baseNote').dataset.manual)$('baseNote').textContent=s.baseline?.warning|| (s.base==null?'请保持平静，收集至少一分钟心率。':'基准持续慢跟随，避免长时间锁高。');
 $('configVersion').textContent='配置已连接';
 if(s.params){if(!Object.keys(saved).length)status('与直播设置一致');saved={...s.params};for(const [k,v] of Object.entries(s.params))if(!dirty.has(k))draft[k]=v;renderSettings();transmit();}
 updateRuntime(s.runtime);
 if(s.runtime?.panel?.id&&s.runtime.panel.id>lastPanelRequest){lastPanelRequest=s.runtime.panel.id;if(s.runtime.panel.target==='hud-size')focusHudSizing();else document.querySelector('[data-mode="demo"]').click();}
});
setInterval(()=>{if(lastSeen&&performance.now()-lastSeen>6000){connected=false;$('service').textContent=ending?'本次运行已结束':'服务连接中断';renderAvailability();}},1000);
const side=$('workspace').lastElementChild;
side.firstElementChild.after($('outputControls'));
side.prepend($('tools'));side.prepend($('simulation'));
setMode(location.hash==='#effects'?'demo':location.hash==='#tools'?'more':'live');
if(location.hash==='#hud-size')setTimeout(focusHudSizing,100);

