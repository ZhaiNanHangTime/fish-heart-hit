/* The backend scans this computer's adapter. Device names are untrusted text. */
'use strict';
(()=>{
 const byId=id=>document.getElementById(id),panel=byId('bluetoothPanel');
 let state=null,busy=false,polling=false,first=true,lastRevision=-1,lastBody='',actionError='',epoch=0;
 const labels={idle:'尚未连接',connecting:'正在连接',waiting:'已连接，等待心率',connected:'心率已接入',retrying:'断开后重连中',unsupported:'不支持标准心率广播'};
 function button(text,action,id){const el=document.createElement('button');el.type='button';el.textContent=text;el.dataset.bleAction=action;if(id)el.dataset.deviceId=id;return el;}
 function render(){
  const live=typeof connected!=='undefined'&&connected&&!ending&&state?.available!==false;
  for(const el of panel.querySelectorAll('button'))el.disabled=!live||busy;
  byId('bleScan').disabled=!live||busy||!!state?.scanning;
  byId('bleStopScan').hidden=!state?.scanning;
  byId('bleDisconnect').disabled=!live||busy||!state?.selected_id||state?.state==='idle';
  if(!state)return;
  byId('bleSummary').textContent=state.available===false?'需要新版服务':state.scanning?'正在搜索附近设备…':labels[state.state]||'连接心率设备';
  byId('bleScan').textContent=state.scanning?'扫描中…':'扫描附近设备';
  const note=actionError||state.error||state.scan_error||state.storage_error||
   (state.state==='waiting'?'蓝牙已连接，尚未收到心率。请检查手表的心率广播是否开启。':
   state.state==='connected'?'已接入真实心率。下次启动会优先重连这台设备。':
   state.scanning?'正在扫描广播，通常约8秒。可以继续使用当前已连接的心率设备。':
   state.scanned_at?'扫描结束。未声明心率服务的设备也可以尝试连接验证。':'开启电脑蓝牙和手表的心率广播，然后扫描并选择自己的设备。');
  byId('bleNote').textContent=note;byId('bleNote').classList.toggle('error',!!(actionError||state.error||state.scan_error||state.storage_error));
  const bodyKey=JSON.stringify([state.devices,state.state,state.selected_id]);
  if(lastRevision!==state.revision||lastBody!==bodyKey){
   lastRevision=state.revision;lastBody=bodyKey;
   const list=byId('bleDevices');list.replaceChildren();
   for(const row of state.devices||[]){
    const item=document.createElement('div');item.className='ble-device';item.dataset.deviceId=row.id;
    const info=document.createElement('div'),name=document.createElement('strong'),meta=document.createElement('small');
    name.textContent=row.name;
    meta.textContent=[row.heart_rate?'声明心率服务':'连接时验证心率服务',row.rssi!=null?'信号 '+row.rssi+' dBm':row.remembered?'已记住，等待广播':'未在本轮发现','标识末尾 '+row.suffix].join(' · ');
    info.append(name,meta);item.append(info);
    const actions=document.createElement('div');actions.className='ble-actions';
    const active=row.selected&&['connecting','retrying','connected','waiting'].includes(state.state);
    if(active){const tag=document.createElement('span');tag.className='ble-current';tag.textContent=labels[state.state];actions.append(tag)}
    else actions.append(button('连接','connect',row.id));
    if(row.remembered)actions.append(button('忘记','forget',row.id));
    item.append(actions);list.append(item);
   }
   byId('bleEmpty').hidden=!!state.devices?.length;
  }
  for(const el of panel.querySelectorAll('[data-ble-action]'))el.disabled=!live||busy;
  byId('bleScan').disabled=!live||busy||!!state.scanning;
  byId('bleDisconnect').disabled=!live||busy||!state.selected_id||state.state==='idle';
 }
 async function refresh(){
  if(polling||busy)return;polling=true;const requestEpoch=epoch;
  try{
   const response=await fetch('/control/devices',{cache:'no-store'});
   if(requestEpoch!==epoch)return;
   if(response.status===503){state={available:false,error:'此服务尚未启用蓝牙管理，请通过新版一键入口重启。',devices:[]};render();return;}
   const result=await readResponse(response);if(requestEpoch!==epoch)return;state=result;
   if(first){first=false;if(state.state==='idle'&&!state.selected_id)panel.open=true;}
   render();
  }catch(e){if(panel.open)byId('bleNote').textContent='设备状态读取失败，请检查服务连接后重试。';}
  finally{polling=false;}
 }
 panel.addEventListener('click',async event=>{
  const el=event.target.closest('[data-ble-action]');if(!el||el.disabled||busy)return;
  busy=true;epoch++;actionError='';render();byId('bleNote').textContent='正在处理设备操作…';
  try{state=await control('devices',{action:el.dataset.bleAction,...(el.dataset.deviceId?{id:el.dataset.deviceId}:{})});render();}
  catch(e){actionError=e.message;status(e.message,'error');}
  finally{busy=false;render();}
 });
 function openDevices(){panel.open=true;panel.scrollIntoView({block:'start',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});refresh();}
 byId('devicePill').addEventListener('click',()=>{if(panel.open)panel.open=false;else openDevices();});
 panel.addEventListener('toggle',()=>{byId('devicePill').setAttribute('aria-expanded',String(panel.open));if(panel.open)refresh();});
 window.addEventListener('hashchange',()=>{if(location.hash==='#devices')openDevices();});
 setInterval(()=>{render();if(!document.hidden)refresh();},1200);
 document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});
 refresh();if(location.hash==='#devices')openDevices();
})();
