const {chromium}=require('playwright'),fs=require('fs'),assert=require('node:assert/strict');
(async()=>{
 const base=process.env.FISH_TEST_BASE||'http://127.0.0.1:18769',out=process.env.EVIDENCE_DIR||'test-evidence/trace';
 const native=JSON.parse(fs.readFileSync(out+'/native-trace.json','utf8'));
 const browser=await chromium.launch({headless:false,channel:'chrome'}),page=await browser.newPage();
 const errors=[];let oldClippedPixels=0;page.on('pageerror',e=>errors.push(e.message));
 try{
  for(const c of native.cases){
   await page.setViewportSize({width:c.width,height:c.height});
   await page.goto(base+'/?preview=1&hudPreview=1&bg=1&skin=xianyu&traceLayout='+c.traceLayout);
   await page.waitForFunction(()=>visualLayout);
   const actual=await page.evaluate(({samples,c})=>{
    canvas.style.width=c.width+'px';canvas.style.height=c.height+'px';fitCanvas();
    P.traceSeconds=c.seconds;P.traceLayout=c.traceLayout;history.samples=samples;state.trace=c.series;
    const fallback=traceSeries(samples,c.seconds),shared=currentTrace(samples);
    const cy=H*(c.traceLayout==='lower'?.78:.5),amp=H*(c.traceLayout==='lower'?.15:.44),paths=[];
    const methods={moveTo:ctx.moveTo,lineTo:ctx.lineTo,stroke:ctx.stroke};let path=[];
    ctx.moveTo=function(x,y){path=[x,y];return methods.moveTo.call(this,x,y)};
    ctx.lineTo=function(x,y){path.push(x,y);return methods.lineTo.call(this,x,y)};
    ctx.stroke=function(){paths.push({coords:[...path],width:this.lineWidth,join:this.lineJoin});return methods.stroke.call(this)};
    try{drawTrace(samples,cy,amp)}finally{Object.assign(ctx,methods)}
    const [x,y]=paths[1].coords.slice(-2),d=Math.max(2,Math.round(H*.028));
    function outside(coords,join){
     const pad=50,off=document.createElement('canvas');off.width=c.width+pad*2;off.height=c.height+pad*2;
     const brush=off.getContext('2d');brush.translate(pad,pad);brush.lineJoin=join;brush.lineCap='butt';
     brush.lineWidth=Math.max(3,Math.round(c.height*.055));brush.strokeStyle='#f00';brush.beginPath();brush.moveTo(coords[0],coords[1]);
     for(let i=2;i<coords.length;i+=2)brush.lineTo(coords[i],coords[i+1]);brush.stroke();
     const [ex,ey]=coords.slice(-2);brush.fillRect(ex-d,ey-d,d*2,d*2);
     const pixels=brush.getImageData(0,0,off.width,off.height).data;let count=0;
     for(let row=0;row<off.height;row++)for(let col=0;col<off.width;col++)
      if((col<pad||col>=pad+c.width||row<pad||row>=pad+c.height)&&pixels[(row*off.width+col)*4+3])count++;
     return count;
    }
    const oldCoords=c.series.points.flatMap(([x,y])=>[1+x*(W-2),cy-y*amp]);
    return {fallback,uses_shared:shared===state.trace,paths,dot:[x-d,y-d,x+d,y+d],clipped_before:outside(oldCoords,'miter'),clipped_after:outside(paths[1].coords,'bevel')};
   },{samples:native.samples,c});
   assert.deepEqual(actual.fallback,c.series);assert(actual.uses_shared);
   assert.deepEqual(actual.paths[0].coords,c.coords);assert.deepEqual(actual.paths[1].coords,c.coords);
   assert.equal(actual.paths[0].width,c.shadow_stroke);assert.equal(actual.paths[1].width,c.stroke);assert.deepEqual(actual.dot,c.dot);
   assert.equal(actual.paths[1].join,'bevel');assert.equal(actual.clipped_after,0);oldClippedPixels+=actual.clipped_before;
  }
  await page.setViewportSize({width:1340,height:1000});await page.goto(base+'/console');await page.bringToFront();
  await page.waitForFunction(()=>connected);
  const saved=await(await page.request.get(base+'/params')).json();
  await page.locator('[data-preview-target="hud"]').click();await page.locator('#traceSeconds').selectOption('600');
  const preview=page.frameLocator('#preview').locator('body');
  await preview.evaluate(()=>new Promise(resolve=>{const check=()=>P.traceSeconds===600?resolve():setTimeout(check,20);check()}));
  assert.equal((await(await page.request.get(base+'/params')).json()).traceSeconds,saved.traceSeconds);
  await page.locator('#applyPreview').click();await page.waitForFunction(()=>document.getElementById('applyPreview').disabled);
  assert.equal((await(await page.request.get(base+'/params')).json()).traceSeconds,600);
  const obs=await browser.newPage();await obs.goto(base+'/');await obs.waitForFunction(()=>P.traceSeconds===600);
  assert.equal(await obs.evaluate(()=>state.trace.seconds),600);await obs.close();await page.bringToFront();
  await page.screenshot({path:out+'/shared-trace-control.png',fullPage:true});
  // Visible synthetic trace, with the exact same points that the real Tk rendered.
  await page.setViewportSize({width:640,height:280});await page.goto(base+'/?preview=1&hudPreview=1&bg=1&skin=xianyu');await page.waitForFunction(()=>visualLayout);
  await page.evaluate(c=>{state.trace=c.series;P.traceSeconds=c.seconds;history.samples=[];},native.cases.find(c=>c.width===640&&c.seconds===180&&c.traceLayout==='overlay'));
  await page.waitForTimeout(150);await page.screenshot({path:out+'/three-minute-trend.png'});
  assert.deepEqual(errors,[]);
  assert(oldClippedPixels>0);
  const result={environment:'visible Chrome + actual Tk; isolated synthetic data, no real BLE',cases:native.cases.length,normalized_series_and_preview_fallback:'exact match',actual_native_and_browser_curve_coordinates:'exact match',stroke_width_and_endpoint_dot:'exact match',clipped_pixels_before_fix:oldClippedPixels,clipped_pixels_after_fix:0,draft_isolated_until_apply:true,saved_window_reaches_OBS:true,page_errors:errors};
  fs.writeFileSync(out+'/browser-trace.json',JSON.stringify(result,null,2)+'\n');console.log(JSON.stringify(result,null,2));
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
