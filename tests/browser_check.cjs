const {chromium}=require('playwright');
const fs=require('fs');
const assert=require('node:assert/strict');
const crypto=require('crypto');
(async()=>{
 const browser=await chromium.launch({headless:false,channel:'chrome',args:['--disable-background-timer-throttling','--disable-renderer-backgrounding']});
 const context=await browser.newContext({viewport:{width:1340,height:1000},deviceScaleFactor:1});
 const evidence=process.env.EVIDENCE_DIR||'test-evidence';fs.mkdirSync(evidence,{recursive:true});
 const errors=[]; const checks=[];
 const page=await context.newPage();
 page.on('pageerror',e=>errors.push(e.message));
 page.on('console',m=>{if(m.type()==='error'&&m.text().includes('心率快照'))errors.push(m.text())});
 await page.addInitScript(()=>{
   window.rafCounts={};const raf=window.requestAnimationFrame;
   window.requestAnimationFrame=function(fn){window.rafCounts[fn.name]=(window.rafCounts[fn.name]||0)+1;return raf.call(this,fn)};
 });
 const base='http://127.0.0.1:18766';
 const initialControl=await (await page.request.get(base+'/control')).json();
 await page.request.post(base+'/control/hud',{headers:{'X-Control-Token':initialControl.token},data:{visible:false}});
 await page.request.post(base+'/__test',{data:{bpm:72,base:72}});
 await page.setViewportSize({width:520,height:170});
 await page.goto(base+'/?test=1&skin=xianyu&bg=1');
 await page.bringToFront();
 await page.waitForTimeout(400);
 assert.equal(await page.evaluate(()=>document.visibilityState),'visible');
 assert.deepEqual(await page.evaluate(()=>XIANYU_STAGES),['idle','alert_low','alert_mid','tense','high','charge']);
 const frames=await page.evaluate(()=>{
   const names=[];xianyuStageIndex=0;
   for(const n of [0,6,10,14,18,22])names.push(xianyuStage(n));
   return names;
 });
 assert.deepEqual(frames,['idle','alert_low','alert_mid','tense','high','charge']);
 const oscillations=await page.evaluate(()=>{xianyuStageIndex=2;return Array.from({length:100},(_,i)=>xianyuStage(8+(i%2?1:-1)))});
 assert.equal(new Set(oscillations).size,1);
 checks.push('six absolute stages; +/-1 bpm jitter does not toggle at the 8 bpm boundary');
 await page.waitForFunction(()=>Object.keys(XIANYU_IMAGES).length===8&&Object.values(XIANYU_IMAGES).every(v=>v.complete&&v.naturalWidth>0));
 const loaded=await page.evaluate(()=>Object.entries(XIANYU_IMAGES).map(([k,v])=>[k,v.complete&&v.naturalWidth>0]));
 assert(loaded.length===8&&loaded.every(x=>x[1]));
 const raf=await page.evaluate(()=>rafCounts);
 assert(raf.testTick>3);assert(!raf.frame);
 checks.push('all eight material PNGs load; test mode schedules testTick only');
 await page.evaluate(()=>{TEST_HR=82;TEST_BASE=72;lockedBase=72});
 await page.waitForTimeout(250);
 assert.equal(await page.evaluate(()=>algo.anchors.B),72);
 assert.equal(await page.evaluate(()=>lastXianyuFrame),'alert_mid');
 await page.evaluate(()=>{TEST_BASE=65;lockedBase=65});
 await page.waitForTimeout(100);
 assert.equal(await page.evaluate(()=>algo.anchors.B),65);
 await page.evaluate(()=>{TEST_HR=null});
 await page.waitForTimeout(100);
 assert.equal(await page.evaluate(()=>state.connected),false);
 checks.push('test baseline override survives frame(); clearing BPM makes test channel offline');
 // Live URL override must beat both startup and later saved values.
 await page.goto(base+'/?skin=xianyu&fishScale=0.9&fxKick=false&bg=1');
 await page.waitForTimeout(300);
 await page.request.post(base+'/params',{data:{skin:'ghost',fishScale:1.2,fxKick:true,fxWarmth:false}});
 await page.waitForTimeout(300);
 const override=await page.evaluate(()=>({skin:P.skin,scale:P.fishScale,kick:XIANYU_FX.kick,warmth:XIANYU_FX.warmth}));
 assert.deepEqual(override,{skin:'xianyu',scale:.9,kick:false,warmth:false});
 checks.push('URL skin/number/boolean overrides survive SSE configuration updates');
 await page.goto(base+'/?bg=1');
 await page.waitForTimeout(200);
 await page.request.post(base+'/params',{data:{skin:'xianyu',fishScale:1,fxKick:true,fxWarmth:true}});
 await page.waitForTimeout(300);
 assert.equal(await page.evaluate(()=>P.skin),'xianyu');
 await page.request.post(base+'/__test',{data:{bpm:96}});
 await page.waitForTimeout(1300);
 assert.equal(await page.evaluate(()=>lastXianyuFrame),'charge');
 await page.screenshot({path:evidence+'/live-overlay.png'});
 await page.evaluate(()=>{algo.burst=1});
 await page.screenshot({path:evidence+'/burst-overlay.png'});
 checks.push('live overlay follows server skin and params without reload');
 // Fixed size and a fixed virtual anchor across all eight states and heartbeat phases.
 await page.goto(base+'/?demo=1&controlled=1&skin=xianyu&bg=1&fxKick=false');
 await page.waitForFunction(()=>Object.keys(XIANYU_SPRITES).length===8);
 await page.waitForFunction(()=>state.connected&&state.bpm!==null);
 const geometry=await page.evaluate(()=>{
   const rows=[];
   for(const f of [...XIANYU_STAGES,'burst','recover']){
     demoForcedFrame=f;
     for(const beat of [0,.12,.25,.5,.9]){
       drawXianyu(36,15,5,{beat,sleeping:false,flush:.8,burst:0,bpm:82});
       rows.push({...lastSpriteGeometry,canvas:[XIANYU_SPRITES[f].width,XIANYU_SPRITES[f].height]});
     }
   }
   return rows;
 });
 assert.equal(new Set(geometry.map(r=>r.width+','+r.height)).size,1);
 assert.equal(new Set(geometry.map(r=>r.x+','+r.y)).size,1);
 assert(geometry.every(r=>r.bob===0&&r.canvas[0]===576&&r.canvas[1]===384));
 checks.push('8 poses x 5 heartbeat phases: identical geometry, kick=false has zero bob and zero scale modulation');
 const spriteMeta=await (await page.request.get(base+'/assets/skins/xianyu/frames.json')).json();
 assert.equal(spriteMeta.baked_effects,true);
 for(const [name,def] of Object.entries(spriteMeta.frames)){
  const bytes=await (await page.request.get(base+'/assets/skins/xianyu/'+name+'.png')).body();
  assert.equal(crypto.createHash('sha256').update(bytes).digest('hex'),def.sha256);
 }
 assert(await page.evaluate(()=>Object.keys(XIANYU_SPRITES).every(name=>{
  const raw=document.createElement('canvas');raw.width=576;raw.height=384;
  const c=raw.getContext('2d');c.drawImage(XIANYU_IMAGES[name],0,0);
  const a=c.getImageData(0,0,576,384).data,b=XIANYU_SPRITES[name].getContext('2d').getImageData(0,0,576,384).data;
  return a.every((value,i)=>value===b[i]);
 })));
 async function countExtraWater(skin){
  await page.evaluate(skin=>{P.skin=skin},skin);
  await page.waitForFunction(skin=>visualLayout?.skin===skin&&visualAppliedKey===visualLayoutKey,skin);
  return await page.evaluate(async skin=>{
  const original=px;let water=0;P.skin=skin;algo.burst=.9;algo.lastBurstAt=performance.now()/1000;
  px=(...args)=>{if(args[4]==='#bfe9ff')water++;return original(...args)};
  try{await new Promise(requestAnimationFrame);return water}finally{px=original}
 },skin)}
 assert.equal(await countExtraWater('xianyu'),0);
 assert(await countExtraWater('fish')>=6);
 await page.evaluate(()=>{P.skin='xianyu';XIANYU_FX.warmth=false;algo.burst=0});
 for(const name of Object.keys(spriteMeta.frames)){
  await page.evaluate(name=>{demoForcedFrame=name;algo.burst=0},name);
  await page.waitForFunction(name=>lastXianyuFrame===name,name);
  await page.screenshot({path:evidence+'/state-'+name+'.png'});
 }
 checks.push('new eight states match input PNG hashes; normalized pixels are unchanged, embedded splash/trail is not duplicated, original fish effects remain, eight visible state screenshots');
 await page.setViewportSize({width:1280,height:1000});
 await page.goto(base+'/console');
 await page.waitForFunction(()=>document.getElementById('showBpm').textContent==='96');
 assert.equal(await page.locator('#saveStatus').textContent(),'与直播设置一致');
 assert.equal(await page.locator('[data-mode]').count(),3);
 assert.equal(await page.locator('[data-frame]').count(),8);
 // Layout choice is a preview draft until saved, then reaches the live OBS page and survives reload.
 assert.equal(await page.locator('[data-layout]').count(),2);
 const mirror=await context.newPage();await mirror.setViewportSize({width:520,height:170});
 mirror.on('pageerror',e=>errors.push(e.message));
 await mirror.goto(base+'/?skin=xianyu&bg=1');
 await mirror.waitForFunction(()=>P.traceLayout==='overlay');
 await page.bringToFront();
 await page.locator('[data-layout="lower"]').click();
 await page.waitForTimeout(200);
 assert.equal((await (await page.request.get(base+'/params')).json()).traceLayout,'overlay');
 assert.equal(await mirror.evaluate(()=>P.traceLayout),'overlay');
 assert.equal(await page.frameLocator('#preview').locator('body').evaluate(()=>P.traceLayout),'lower');
 await page.locator('#save').click();
 await mirror.waitForFunction(()=>P.traceLayout==='lower');
 await page.reload();await page.waitForFunction(()=>document.querySelector('[data-layout="lower"]').getAttribute('aria-pressed')==='true');
 async function inspectLayout(target){
  await target.waitForFunction(()=>visualLayout&&visualLayout.traceLayout===P.traceLayout);
  return await target.evaluate(async()=>{
   const originals={trace:drawTrace,character:drawCharacter,text:pixelText};
   const result={order:[],height:H};
   drawTrace=(samples,y,amp)=>{result.traceY=y;result.amp=amp;result.order.push('trace');return originals.trace(samples,y,amp)};
   drawCharacter=(...args)=>{result.characterY=args[1];result.order.push('character');return originals.character(...args)};
   pixelText=(...args)=>{result.digitY=args[1];result.order.push('digits');return originals.text(...args)};
   try{await new Promise(requestAnimationFrame);return result}
   finally{drawTrace=originals.trace;drawCharacter=originals.character;pixelText=originals.text}
  });
 }
 await mirror.bringToFront();const lower=await inspectLayout(mirror);
 assert(Math.abs(lower.traceY/lower.height-.78)<1e-9);assert(Math.abs(lower.amp/lower.height-.15)<1e-9);
 assert(lower.order.indexOf('trace')<lower.order.indexOf('character'));assert(lower.order.indexOf('trace')<lower.order.indexOf('digits'));
 await mirror.evaluate(()=>{history.samples=Array.from({length:91},(_,t)=>[t,82+8*Math.sin(t/8)])});
 await mirror.screenshot({path:evidence+'/layout-lower.png'});
 await page.bringToFront();await page.locator('[data-layout="overlay"]').click();await page.locator('#save').click();
 await mirror.waitForFunction(()=>P.traceLayout==='overlay');
 await mirror.bringToFront();const overlay=await inspectLayout(mirror);
 assert(Math.abs(overlay.traceY/overlay.height-.5)<1e-9);assert(Math.abs(overlay.amp/overlay.height-.44)<1e-9);
 assert(overlay.digitY>lower.digitY&&overlay.characterY>lower.characterY);
 assert(overlay.order.indexOf('trace')<overlay.order.indexOf('character'));assert(overlay.order.indexOf('trace')<overlay.order.indexOf('digits'));
 await mirror.evaluate(()=>{history.samples=Array.from({length:91},(_,t)=>[t,82+8*Math.sin(t/8)])});
 await mirror.screenshot({path:evidence+'/layout-overlay.png'});
 await mirror.goto(base+'/?traceLayout=lower&skin=xianyu&bg=1');
 await mirror.waitForFunction(()=>P.traceLayout==='lower');
 assert.equal((await (await page.request.get(base+'/params')).json()).traceLayout,'overlay');
 await mirror.close();await page.bringToFront();
 checks.push('both trace layouts: draft isolation, apply broadcasts to live OBS page, saved choice survives reload, URL override, real canvas geometry and background draw order');
 // Applying the visible desktop draft saves its appearance and size together.
 const beforeHud=await (await page.request.get(base+'/params')).json();
 await page.locator('[data-preview-target="obs"]').click();
 await page.locator('#hudWidth').fill('220');await page.locator('#hudWidth').dispatchEvent('input');
 await page.locator('#hudHeight').fill('120');await page.locator('#hudHeight').dispatchEvent('input');
 await page.waitForTimeout(300);
 assert.equal(await page.locator('#hudWidth').inputValue(),'220');
 assert.equal(await page.locator('[data-preview-target="hud"]').getAttribute('aria-pressed'),'true');
 assert.deepEqual(await page.frameLocator('#preview').locator('body').evaluate(()=>({w:W,h:H,hud:HUD_PREVIEW})),{w:220,h:120,hud:true});
 assert.equal((await (await page.request.get(base+'/params')).json()).hudWidth,beforeHud.hudWidth);
 await page.locator('[data-skin="ghost"]').click();
 await page.locator('#applyHudSize').click();await page.waitForTimeout(250);
 let hudSaved=await (await page.request.get(base+'/params')).json();
 assert.equal(hudSaved.hudWidth,220);assert.equal(hudSaved.hudHeight,120);assert.equal(hudSaved.skin,'ghost');
 assert.equal(hudSaved.viewWidth,beforeHud.viewWidth);assert.equal(hudSaved.viewHeight,beforeHud.viewHeight);
 assert.equal(await page.locator('#save').isEnabled(),false);
 await page.locator('[data-skin="xianyu"]').click();await page.locator('#save').click();await page.waitForTimeout(200);
 await page.locator('#discard').click();
 await page.reload();await page.waitForFunction(()=>document.getElementById('hudWidth').value==='220');
 await page.request.post(base+'/params',{data:{hudWidth:211,hudHeight:119}});
 await page.waitForFunction(()=>document.getElementById('hudWidth').value==='211'&&document.getElementById('hudHeight').value==='119');
 assert.equal(await page.locator('#hudWidthText').textContent(),'211 px');
 await page.locator('[data-preview-target="hud"]').click();await page.waitForTimeout(300);
 await page.screenshot({path:evidence+'/hud-size-controls.png',fullPage:true});
 await page.locator('#preview').screenshot({path:evidence+'/hud-preview.png'});
 await page.locator('[data-preview-target="obs"]').click();await page.waitForTimeout(250);
 const obsViewport=await page.frameLocator('#preview').locator('body').evaluate(()=>({w:W,h:H,hud:HUD_PREVIEW}));
 assert.equal(obsViewport.w,520);assert(Math.abs(obsViewport.h-170)<1);assert.equal(obsViewport.hud,false);
 await page.locator('[data-hud-size="240,104"]').click();
 assert.equal(await page.locator('#hudWidth').inputValue(),'240');assert.equal(await page.locator('#hudHeight').inputValue(),'104');
 await page.locator('#applyHudSize').click();await page.waitForTimeout(250);
 await page.locator('[data-preview-target="obs"]').click();
 checks.push('interactive HUD controls: desktop preview, independent width/height, one apply saves the visible skin and size draft together, OBS dimensions remain separate, presets, reload and external updates');
 // Large shared character size reaches an unpinned OBS page and stays within its own viewport.
 const obs=await context.newPage();await obs.setViewportSize({width:800,height:320});
 await obs.goto(base+'/?bg=1');await obs.bringToFront();
 await page.locator('[data-skin="xianyu"]').click();
 await page.locator('#fishScale').fill('400');await page.locator('#fishScale').dispatchEvent('input');
 await page.locator('#save').click();
 await obs.waitForFunction(()=>P.fishScale===4&&P.skin==='xianyu'&&visualLayout?.requested_scale===4&&visualLayout.skin==='xianyu'&&visualAppliedKey===visualLayoutKey&&Object.keys(scaledSpriteSet.images).length===8&&Object.values(scaledSpriteSet.images).every(i=>i.complete&&i.naturalWidth>0));
 const large=await obs.evaluate(()=>{
   const calls=[];const original=ctx.drawImage;
   ctx.drawImage=function(...args){if(args.length>=5)calls.push(args.slice(-4));return original.apply(this,args)};
   return new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>{ctx.drawImage=original;resolve(calls)})));
 });
 assert(large.length>0);
 assert(large.every(([x,y,w,h])=>x>=0&&y>=0&&x+w<=800&&y+h<=320),JSON.stringify(large));
 assert(large.some(([, ,w,h])=>h>150));
 await obs.screenshot({path:evidence+'/large-shared-obs.png'});
 // A change initiated outside the console (the same partial POST as the native HUD menu).
 await page.request.post(base+'/params',{data:{skin:'fish',fishScale:2}});
 await obs.waitForFunction(()=>P.skin==='fish'&&P.fishScale===2);
 await page.waitForFunction(()=>document.querySelector('[data-skin="fish"]').getAttribute('aria-pressed')==='true'&&document.getElementById('fishScale').value==='200');
 await page.request.post(base+'/params',{data:{skin:'xianyu',fishScale:1}});
 await page.waitForFunction(()=>document.getElementById('fishScale').value==='100');
 await obs.close();await page.bringToFront();
 checks.push('50–400% controls; 400% sprite fits a visible OBS canvas without clipping; HUD-style partial skin/scale POST broadcasts to OBS and console');
 await page.locator('[data-skin="ghost"]').click();
 await page.waitForTimeout(1300);
 assert.equal((await (await page.request.get(base+'/params')).json()).skin,'xianyu');
 assert.equal(await page.frameLocator('#preview').locator('body').evaluate(()=>P.skin),'ghost');
 await page.locator('#fishScale').fill('110');
 await page.locator('#fishScale').dispatchEvent('input');
 await page.locator('#save').click();
 await page.waitForTimeout(250);
 assert.match(await page.locator('#saveStatus').textContent(),/已应用/);
 let saved=await (await page.request.get(base+'/params')).json();assert.equal(saved.fishScale,1.1);assert.equal(saved.skin,'ghost');
 // Applying a request may not discard a newer edit made while that request is pending.
 await page.route('**/params',async route=>{if(route.request().method()==='POST')await new Promise(r=>setTimeout(r,250));await route.continue()});
 await page.locator('#fishScale').fill('115');await page.locator('#fishScale').dispatchEvent('input');
 await page.locator('#save').click();
 await page.locator('#fishScale').fill('120');await page.locator('#fishScale').dispatchEvent('input');
 await page.waitForTimeout(650);
 assert.equal(await page.locator('#fishScale').inputValue(),'120');assert.equal(await page.locator('#save').isEnabled(),true);
 await page.locator('#save').click();await page.waitForTimeout(650);await page.unroute('**/params');
 await page.locator('#hud').click();await page.waitForTimeout(100);assert.equal(await page.locator('#hud').textContent(),'关闭悬浮窗');
 await page.locator('#hud').click();await page.waitForTimeout(100);assert.equal(await page.locator('#hud').textContent(),'显示悬浮窗');
 await page.screenshot({path:evidence+'/console.png',fullPage:true});
 await page.locator('[data-mode="demo"]').click();
 await page.locator('#bpm').fill('140');await page.locator('#bpm').dispatchEvent('input');
 await page.locator('#burst').click();await page.waitForTimeout(400);
 assert.equal((await (await page.request.get(base+'/hr')).json()).bpm,96);
 assert.equal((await (await page.request.get(base+'/params')).json()).fishScale,1.2);
 await page.screenshot({path:evidence+'/effects-integrated.png',fullPage:true});
 await page.locator('[data-mode="more"]').click();
 for(const tool of ['/monitor?noiframe=1','/tune','/test']){
   await page.locator('[data-tool="'+tool+'"]').click();await page.waitForTimeout(450);
   assert(await page.frameLocator('#toolframe').locator('body').count());
 }
 await page.locator('[data-mode="live"]').click();assert.equal(await page.locator('[data-mode="live"]').getAttribute('aria-selected'),'true');
 await page.goto(base+'/effects');await page.waitForTimeout(500);
 assert(page.url().endsWith('/console#effects'));
 assert.equal(await page.locator('#simulation').isVisible(),true);
 await page.locator('[data-skin="xianyu"]').click();
 await page.locator('#save').click();await page.waitForTimeout(250);
 await page.locator('#poseControls').evaluate(el=>el.open=true);
 await page.locator('[data-frame="charge"]').click();await page.waitForTimeout(200);
 await page.screenshot({path:evidence+'/xianyu-total-control.png',fullPage:true});
 // Screenshots are captured by the browser at the real production viewport above.
 await page.setViewportSize({width:390,height:844});await page.waitForTimeout(250);
 assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
 await page.screenshot({path:evidence+'/mobile.png',fullPage:true});
 checks.push('single control: live vs draft isolation, persistence, edits during save, HUD control, three tools, effects redirect, mobile layout');
 // Every page really executes; collect its errors and inspect a visible state.
 for(const route of ['/monitor','/tune','/effects','/test','/plain']){
   await page.goto(base+route);await page.waitForTimeout(450);
 }
 assert.deepEqual(errors,[]);
 checks.push('no uncaught JS errors across all pages and nested preview/test frames');
 fs.writeFileSync(evidence+'/browser-results.json',JSON.stringify({engine:browser.version(),visibility:'visible',checks,errors},null,2));
 console.log(JSON.stringify({checks,errors},null,2));
 await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
