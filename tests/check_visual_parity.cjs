const {chromium}=require('playwright'),fs=require('fs'),crypto=require('crypto'),assert=require('node:assert/strict');
(async()=>{
 const evidence=process.env.EVIDENCE_DIR||'work/control-evidence';
 const cases=JSON.parse(fs.readFileSync(evidence+'/native-visual-parity.json'));
 const browser=await chromium.launch({headless:false,channel:'chrome'});
 const page=await browser.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
 try{
  for(const item of cases){
   await page.setViewportSize({width:item.width,height:item.height});
   const q=new URLSearchParams({demo:1,controlled:1,hudPreview:1,skin:'xianyu',fishScale:item.scale,fishWidth:item.fishWidth||1,traceLayout:item.traceLayout,fxWarmth:false,fxKick:false});
   await page.goto('http://127.0.0.1:18766/?'+q);
   await page.waitForFunction(()=>visualLayout&&Object.values(scaledSpriteSet.images).length===8&&Object.values(scaledSpriteSet.images).every(i=>i.complete&&i.naturalWidth>0));
   assert.deepEqual(await page.evaluate(()=>visualLayout),item.layout);
   const rgba=await page.evaluate(name=>{
    demoForcedFrame=name;ctx.clearRect(0,0,W,H);
    const v=visualLayout;drawXianyu(...v.fish_origin,v.unit,{beat:0,sleeping:false,flush:0,burst:0,bpm:72,rect:v.sprite_rect});
    const [x,y,w,h]=v.sprite_rect;return Array.from(ctx.getImageData(x,y,w,h).data);
   },item.frame);
   assert.equal(crypto.createHash('sha256').update(Buffer.from(rgba)).digest('hex'),item.rgba_sha256,JSON.stringify(item));
  }
  await page.setViewportSize({width:1340,height:1000});
  await page.goto('http://127.0.0.1:18766/console#hud-size');await page.bringToFront();
  await page.waitForFunction(()=>document.getElementById('hudWidth').value!=='');
  await page.locator('[data-skin="xianyu"]').click();
  await page.locator('#hudWidth').fill('640');await page.locator('#hudWidth').dispatchEvent('input');
  await page.locator('#hudHeight').fill('280');await page.locator('#hudHeight').dispatchEvent('input');
  await page.locator('#fishScale').fill('250');await page.locator('#fishScale').dispatchEvent('input');
  await page.frameLocator('#preview').locator('body').evaluate(()=>new Promise(resolve=>{
    const check=()=>visualLayout?.width===640&&visualLayout?.height===280?resolve():setTimeout(check,20);check();
  }));
  const original=await page.frameLocator('#preview').locator('body').evaluate(()=>visualLayout);
  const before=await (await page.request.get('http://127.0.0.1:18766/params')).json();
  await page.locator('#fishWidth').fill('75');await page.locator('#fishWidth').dispatchEvent('input');
  await page.waitForTimeout(400);
  const narrowed=await page.frameLocator('#preview').locator('body').evaluate(()=>visualLayout);
  assert(narrowed.sprite_rect[2]<original.sprite_rect[2]);assert.equal(narrowed.sprite_rect[3],original.sprite_rect[3]);
  assert.deepEqual(narrowed.digit_origin,original.digit_origin);
  assert.equal((await (await page.request.get('http://127.0.0.1:18766/params')).json()).fishWidth,before.fishWidth);
  await page.locator('#applyPreview').click();
  await page.waitForFunction(()=>document.getElementById('applyPreview').disabled);
  assert.equal((await (await page.request.get('http://127.0.0.1:18766/params')).json()).fishWidth,.75);
  const mirror=await browser.newPage();await mirror.goto('http://127.0.0.1:18766/');await mirror.waitForFunction(()=>P.fishWidth===.75);
  await mirror.close();await page.bringToFront();
  await page.screenshot({path:evidence+'/fish-width-75.png',fullPage:true});
  await page.locator('[data-fish-width="1"]').click();assert.equal(await page.locator('#fishWidth').inputValue(),'100');
  await page.locator('#applyPreview').click();await page.waitForFunction(()=>document.getElementById('applyPreview').disabled);
  await page.waitForTimeout(500);
  await page.screenshot({path:evidence+'/visual-size-console.png',fullPage:true});
  assert.match(await page.locator('#previewDimensions').textContent(),/640 × 280 px/);
  await page.locator('#previewZoom').click();assert.match(await page.locator('#previewDimensions').textContent(),/100%/);
  await page.locator('#previewZoom').click();
  await page.locator('#hudEdit').click();await page.waitForFunction(()=>document.getElementById('hudEdit').textContent==='完成边界调整');
  await page.locator('#hudEdit').click();await page.waitForFunction(()=>document.getElementById('hudEdit').textContent.includes('显示悬浮窗边界'));
  await page.locator('[data-mode="more"]').click();assert(await page.locator('#preview').isVisible());
  assert.deepEqual(errors,[]);
  const result={cases:cases.length,layout:'exactly identical',native_image_vs_browser_canvas:'all RGBA SHA256 match',fish_width_preview_save_reset_and_obs_sync:true,fish_width_keeps_height_and_digits:true,preview_zoom_and_dimensions:true,visual_native_border_controls:true,advanced_settings_keep_preview_visible:true,page_errors:errors};
  fs.writeFileSync(evidence+'/visual-parity-results.json',JSON.stringify(result,null,2)+'\n');console.log(JSON.stringify(result));
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
