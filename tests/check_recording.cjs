const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('fs');
(async()=>{
 const base=process.env.FISH_TEST_BASE||'http://127.0.0.1:18768',out=process.env.EVIDENCE_DIR||'test-evidence/recording';
 fs.mkdirSync(out,{recursive:true});
 const browser=await chromium.launch({channel:'chrome',headless:false});
 const context=await browser.newContext({viewport:{width:1360,height:1000}}),page=await context.newPage(),other=await context.newPage();
 const errors=[],checks=[];for(const p of [page,other])p.on('pageerror',e=>errors.push(e.message));
 try{
  const initial=await(await page.request.get(base+'/control/recording')).json();
  if(initial.activity!=='unmarked'){
   const ctl=await(await page.request.get(base+'/control')).json();
   await page.request.post(base+'/control/recording',{headers:{'X-Control-Token':ctl.token},data:{activity:'unmarked',expected_segment:initial.segment_id}});
  }
  await page.goto(base+'/console');await page.bringToFront();await page.locator('#recordingStart').waitFor({state:'visible'});
  await page.waitForFunction(()=>!document.getElementById('recordingStart').disabled);
  assert.equal(await page.locator('#recordingState').innerText(),'未标注');
  const before=await (await page.request.get(base+'/params')).json();
  await other.goto(base+'/console');
  await page.locator('#gameName').fill('<img src=x onerror=alert(1)> 游戏A');
  await page.locator('#recordingStart').click();
  await page.waitForFunction(()=>document.getElementById('recordingState').textContent==='游戏记录中');
  await other.waitForFunction(()=>document.getElementById('recordingState').textContent==='游戏记录中');
  assert(await page.locator('#recordingStart').isDisabled());
  for(let i=0;i<12;i++)await page.request.post(base+'/__test',{data:{bpm:80+i,connected:true}});
  await page.screenshot({path:out+'/game-recording-desktop.png',fullPage:true});
  const gameState=await(await page.request.get(base+'/control/recording')).json();
  await page.reload();await page.waitForFunction(()=>document.getElementById('recordingState').textContent==='游戏记录中');
  assert.equal((await(await page.request.get(base+'/control/recording')).json()).segment_id,gameState.segment_id);
  checks.push('actual start button; SSE state shared by two consoles; reload preserves the same active segment; game name rendered as text');
  await page.locator('#recordingEnd').click();await page.waitForFunction(()=>document.getElementById('recordingState').textContent==='非游戏记录中');
  const list=await(await page.request.get(base+'/logs?activity=game')).json();const gameItem=list.find(it=>it.name===gameState.file);assert(gameItem&&gameItem.samples>=12);
  assert.deepEqual(await(await page.request.get(base+'/params')).json(),before);
  const monitor=await context.newPage();monitor.on('pageerror',e=>errors.push(e.message));
  await monitor.goto(base+'/monitor?noiframe=1');await monitor.locator('summary').filter({hasText:'历史记录'}).click();
  await monitor.locator('#logActivity').selectOption('game');await monitor.waitForFunction(count=>document.querySelectorAll('#logs tr.pick').length===count,list.length);
  assert((await monitor.locator('#logs').innerText()).includes(gameItem.game));assert.equal(await monitor.locator('#logs img').count(),0);
  await monitor.locator(`#logs tr.pick[data-name="${gameState.file}"]`).click();await monitor.waitForFunction(()=>document.getElementById('replayNote').textContent.includes('样本 /'));
  checks.push('actual end button saves game data separately; history filter selects game-only files; replay works; parameters unchanged; hostile name does not execute');
  await monitor.close();await page.bringToFront();
  await page.route('**/control/recording',route=>route.request().method()==='POST'?route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:'合成检查：磁盘空间不足'})}):route.continue());
  await page.locator('#recordingStart').click();await page.waitForFunction(()=>document.getElementById('feedback').textContent.includes('磁盘空间不足'));
  assert.equal(await page.locator('#recordingState').innerText(),'非游戏记录中');assert(await page.locator('#recordingStart').isEnabled());await page.unroute('**/control/recording');
  checks.push('failed write is visible and leaves current label unchanged with retry available');
  await page.setViewportSize({width:390,height:900});await page.screenshot({path:out+'/game-recording-mobile.png',fullPage:true});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await page.locator('#recordingStart').click();await page.waitForFunction(()=>document.getElementById('recordingState').textContent==='游戏记录中');
  await page.locator('#recordingUnknown').click();await page.waitForFunction(()=>document.getElementById('recordingState').textContent==='未标注');
  await page.request.post(base+'/__test',{data:{silent:true,disconnect_streams:true}});
  await page.waitForFunction(()=>document.getElementById('recordingState').textContent==='状态未知');
  assert(await page.locator('#recordingStart').isDisabled());assert(await page.locator('#recordingEnd').isDisabled());
  checks.push('390px controls work without overflow; explicitly return to unmarked; stream loss disables mutations and shows unknown state');
  assert.deepEqual(errors,[]);
  const result={environment:'visible Chrome; isolated synthetic service with temporary CSVs; no personal data or real BLE',checks,page_errors:errors};
  fs.writeFileSync(out+'/browser-results.json',JSON.stringify(result,null,2)+'\n');console.log(JSON.stringify(result,null,2));
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
