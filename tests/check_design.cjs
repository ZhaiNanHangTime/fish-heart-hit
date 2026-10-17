const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('fs');
(async()=>{
 const base='http://127.0.0.1:18766',out=process.env.EVIDENCE_DIR||'work/design-evidence';fs.mkdirSync(out,{recursive:true});
 const browser=await chromium.launch({headless:false,channel:'chrome'}),page=await browser.newPage({viewport:{width:1440,height:1050}});
 const errors=[],requests=[],checks=[];page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>requests.push(r.url()));
 try{
  await page.request.post(base+'/__test',{data:{bpm:72,base:72,new_session:true}});
  await page.request.post(base+'/params',{data:{skin:'xianyu',fishScale:1.35,fishWidth:1.5,hudWidth:381,hudHeight:95}});
  await page.goto(base+'/console');await page.bringToFront();await page.waitForFunction(()=>connected&&previewState?.frame==='idle');
  assert.equal((await page.request.get(base+'/studio-theme.css')).status(),200);
  assert.equal(await page.locator('body').evaluate(e=>getComputedStyle(e).backgroundColor),'rgb(227, 229, 218)');
  assert.equal(await page.locator('[data-fish-width="1.5"]').getAttribute('aria-pressed'),'true');
  const normalColor=await page.locator('#shutdown').evaluate(e=>getComputedStyle(e).color);
  function luminance(c){const a=c.match(/\d+/g).slice(0,3).map(x=>{const v=Number(x)/255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4});return .2126*a[0]+.7152*a[1]+.0722*a[2]}
  const ratios=await page.evaluate(()=>{
   const s=getComputedStyle(document.body),h=getComputedStyle(document.querySelector('header'));
   return {bodyText:s.color,bodyBg:s.backgroundColor,headerBg:h.backgroundColor};
  });
  const contrast=(a,b)=>(Math.max(luminance(a),luminance(b))+.05)/(Math.min(luminance(a),luminance(b))+.05);
  assert(contrast(ratios.bodyText,ratios.bodyBg)>=4.5);assert(contrast(normalColor,ratios.headerBg)>=4.5);
  checks.push('new theme is served; saved 150% preset is visibly selected; body text and end-session text meet 4.5:1 contrast');
  await page.waitForTimeout(4600);await page.screenshot({path:out+'/design-live.png'});
  for(const width of [380,390,768,1024,1440]){
   await page.setViewportSize({width,height:900});await page.evaluate(()=>scrollTo(0,0));await page.waitForTimeout(100);
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'horizontal overflow at '+width);
   for(const mode of ['live','demo','more']){
    await page.locator('[data-mode='+mode+']').scrollIntoViewIfNeeded();await page.locator('[data-mode='+mode+']').click();
    assert(await page.locator('[data-mode='+mode+']').getAttribute('aria-selected')==='true');
    const id=mode==='live'?'workspace':mode==='demo'?'simulation':'tools';
    assert(await page.locator('#'+id).isVisible());assert((await page.locator('#'+id).boundingBox()).y<550);
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'mode overflow at '+width+' '+mode);
   }
  }
  checks.push('380, 390, 768, 1024, 1440px: no horizontal overflow; all three tabs expose the requested controls');
  await page.locator('[data-mode=demo]').click();await page.locator('#poseControls').evaluate(e=>e.open=true);
  await page.locator('[data-frame=recover]').click();await page.waitForFunction(()=>previewState?.frame==='recover');
  await page.waitForTimeout(4600);await page.evaluate(()=>scrollTo(0,0));await page.screenshot({path:out+'/design-demo.png'});
  await page.locator('[data-mode=more]').click();
  for(const tool of ['/monitor?noiframe=1','/tune','/test']){
   await page.locator('[data-tool="'+tool+'"]').click();await page.frameLocator('#toolframe').locator('body.studio-tool').waitFor();
   const frame=page.frames().find(f=>f.url().endsWith(tool));assert(frame);
   assert.equal(await frame.locator('body').evaluate(e=>getComputedStyle(e).backgroundColor),'rgb(38, 50, 44)');
   assert(await frame.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'tool horizontal overflow: '+tool);
  }
  checks.push('history, advanced parameters and behavior tools all load the shared pine theme, with no horizontal overflow at desktop embedded width');
  await page.locator('[data-tool="/monitor?noiframe=1"]').click();await page.frameLocator('#toolframe').locator('body.studio-tool').waitFor();
  await page.waitForTimeout(4600);await page.evaluate(()=>scrollTo(0,0));await page.screenshot({path:out+'/design-tools.png'});
  await page.locator('[data-mode=live]').click();await page.setViewportSize({width:390,height:844});await page.evaluate(()=>scrollTo(0,0));
  await page.waitForTimeout(4600);await page.screenshot({path:out+'/design-mobile.png',fullPage:true});
  await page.emulateMedia({reducedMotion:'reduce'});
  assert.equal(await page.locator('[data-mode=live]').evaluate(e=>getComputedStyle(e).transitionDuration),'0s');
  await page.locator('[data-mode=live]').focus();await page.keyboard.press('ArrowRight');
  assert.notEqual(await page.locator('[data-mode=demo]').evaluate(e=>getComputedStyle(e).outlineStyle),'none');
  assert(requests.every(url=>url.startsWith(base)||url==='about:blank'),'unexpected external runtime resource');assert.deepEqual(errors,[]);
  checks.push('reduced motion, visible keyboard focus, no external runtime resources, no page errors');
  const report={environment:'visible Chrome; isolated synthetic service; no actual heart-rate or private configuration',checks,page_errors:errors,contrast_ratios:{body:contrast(ratios.bodyText,ratios.bodyBg),end_session:contrast(normalColor,ratios.headerBg)},viewports:[380,390,768,1024,1440]};
  fs.writeFileSync(out+'/design-results.json',JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify(report,null,2));
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
