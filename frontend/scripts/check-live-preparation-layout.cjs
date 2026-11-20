const {app,BrowserWindow}=require('electron');
const assert=require('node:assert/strict');
if(process.env.SOLRALOL_TEST_USER_DATA)app.setPath('userData',process.env.SOLRALOL_TEST_USER_DATA);
app.disableHardwareAcceleration();
app.whenReady().then(async()=>{
  const window=new BrowserWindow({show:false,width:1600,height:1000,webPreferences:{sandbox:true,contextIsolation:true,nodeIntegration:false}});
  try {
    await window.loadURL(process.argv[2]);
    window.webContents.debugger.attach('1.3');
    await window.webContents.debugger.sendCommand('Emulation.setEmulatedMedia',{features:[{name:'prefers-reduced-motion',value:'no-preference'}]});
    const execute=script=>window.webContents.executeJavaScript(script);
    await execute(`new Promise((resolve,reject)=>{const deadline=Date.now()+10000;const check=()=>{if(document.querySelectorAll('.live-recommendation').length===3)return resolve();if(Date.now()>deadline)return reject(new Error(document.body.innerText));setTimeout(check,50);};check();})`);
    for(const width of [1920,1600,1280,1024,800]){
      window.setContentSize(width,1000);
      for(const collapsed of [false,true]){
        const result=await execute(`(async()=>{
          document.querySelector('.app-shell').classList.toggle('sidebar-collapsed',${collapsed});
          await Promise.all([...document.images].map(image=>image.decode().catch(()=>{})));
          await new Promise(resolve=>setTimeout(resolve,300));
          const box=e=>{const r=e.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,height:r.height};};
          const page=document.querySelector('.live-page');
          const overflows=[...page.querySelectorAll('*')].filter(e=>getComputedStyle(e).position!=='absolute'&&e.getBoundingClientRect().right>page.getBoundingClientRect().right+1).map(e=>e.className);
          return {hero:!!document.querySelector('.live-hero'),status:document.querySelector('.topbar .live-nav-status')?.textContent,recommendations:document.querySelectorAll('.live-recommendation').length,skillCells:document.querySelectorAll('.live-skill-grid [role=cell]').length,timers:document.querySelectorAll('.live-enemy-timer').length,critical:document.querySelectorAll('.live-enemy-timer.critical').length,animation:getComputedStyle(document.querySelector('.live-enemy-timer.critical img')).animationName,teams:document.querySelectorAll('.live-team').length,players:document.querySelectorAll('.live-row').length,upperItems:document.querySelectorAll('.live-row-main .live-row-item-icon').length,lowerItems:document.querySelectorAll('.live-row-bottom .live-row-item-icon').length,overflows,documentOverflow:document.documentElement.scrollWidth>innerWidth+1,advice:box(document.querySelector('.live-preparation')),comparison:box(document.querySelector('.live-teams')),timeline:box(document.querySelector('.live-timeline')),page:box(page),groups:[...document.querySelectorAll('.live-row-bottom')].map(row=>({utility:box(row.querySelector('.live-row-utility')),items:box(row.querySelector('.live-row-items'))}))};
        })()`);
        assert.equal(result.hero,false);assert.ok(result.status.includes('En partida'));
        assert.equal(result.recommendations,3);assert.equal(result.skillCells,72);assert.equal(result.timers,5);assert.equal(result.critical,1);
        const reducedMotion=await execute(`matchMedia('(prefers-reduced-motion: reduce)').matches`);
        assert.equal(result.animation,reducedMotion?'none':'enemy-shop-pulse');
        assert.equal(result.teams,2);assert.equal(result.players,10);assert.equal(result.upperItems,0);assert.equal(result.lowerItems,60);
        assert.equal(result.documentOverflow,false,`${width}px overflow`);assert.deepEqual(result.overflows,[],`${width}px elements outside page`);
        const header=await execute(`(()=>{const label=document.querySelector('.topbar-label').getBoundingClientRect(),status=document.querySelector('.live-nav-status').getBoundingClientRect(),controls=document.querySelector('.window-controls').getBoundingClientRect();return {gap:status.left-label.right,clearance:controls.left-status.right};})()`);
        assert.ok(header.gap>=0&&header.gap<=24,'status must remain beside breadcrumb');assert.ok(header.clearance>=0,'status overlaps window controls');
        assert.ok(result.comparison.top>=result.advice.bottom-1);
        for(const group of result.groups)assert.ok(group.utility.right<=group.items.left+1,`${width}px utility overlaps six items`);
        if(result.timeline.left>result.advice.right){assert.ok(Math.abs(result.timeline.top-result.advice.top)<1);assert.ok(result.timeline.bottom>=result.comparison.bottom-1);}
      }
    }
    const update=await execute(`(async()=>{
      window.originalCard=document.querySelector('.live-recommendation');
      window.liveTestFixture.snapshot.localStats.currentGold=1500;
      window.liveTestFixture.snapshot.enemyShopTimers[2]={...window.liveTestFixture.snapshot.enemyShopTimers[2],elapsedSeconds:0,state:'normal',lastInferredShopAt:842};
      window.liveTestSend();await new Promise(resolve=>setTimeout(resolve,50));
      return {sameCard:window.originalCard===document.querySelector('.live-recommendation'),critical:document.querySelectorAll('.live-enemy-timer.critical').length,clock:document.querySelectorAll('.live-enemy-timer time')[2].textContent};
    })()`);
    assert.equal(update.sameCard,true);assert.equal(update.critical,0);assert.equal(update.clock,'00:00');
    const clockOnly=await execute(`(async()=>{window.liveTestFixture.snapshot.gameTime+=10;window.liveTestFixture.snapshot.enemyShopTimers[0].elapsedSeconds+=10;window.liveTestSend();await new Promise(resolve=>setTimeout(resolve,50));return {timer:document.querySelector('.live-enemy-timer time').textContent,cs:[...document.querySelectorAll('.live-metric')].find(metric=>metric.textContent.includes('CS / min')).querySelector('b').textContent,clock:document.querySelector('.live-nav-status').textContent};})()`);
    assert.equal(clockOnly.timer,'01:25');assert.equal(clockOnly.cs,'8.9');assert.ok(clockOnly.clock.includes('14:12'));
    const death=await execute(`(async()=>{window.liveTestFixture.snapshot.enemyShopTimers[0].state='dead';window.liveTestSend();await new Promise(resolve=>setTimeout(resolve,50));const row=document.querySelector('.live-enemy-timer');return {text:row.querySelector('time').textContent,paused:row.classList.contains('paused'),animation:getComputedStyle(row.querySelector('img')).animationName};})()`);
    assert.equal(death.text,'Muerto');assert.equal(death.paused,true);assert.equal(death.animation,'none');
    const reborn=await execute(`(async()=>{window.liveTestFixture.snapshot.enemyShopTimers[0].state='normal';window.liveTestFixture.snapshot.enemyShopTimers[0].origin='respawn_observed';window.liveTestFixture.snapshot.enemyShopTimers[0].elapsedSeconds=0;window.liveTestSend();await new Promise(resolve=>setTimeout(resolve,50));return document.querySelector('.live-enemy-timer time').textContent;})()`);
    assert.equal(reborn,'00:00');
    const scroll=await execute(`(async()=>{window.liveTestFixture.snapshot.events=Array.from({length:120},(_,index)=>({EventID:index,EventName:'ChampionKill',EventTime:index+10,KillerActorType:'champion',KillerChampion:'Ahri',VictimChampion:'Garen'}));window.liveTestSend();await new Promise(resolve=>setTimeout(resolve,50));const list=document.querySelector('.live-event-list');list.scrollTop=300;return {count:list.querySelectorAll('.live-event').length,scrollable:list.scrollHeight>list.clientHeight,scrolled:list.scrollTop>0};})()`);
    assert.equal(scroll.count,100);assert.ok(scroll.scrollable&&scroll.scrolled,'timeline must scroll independently');
    await window.webContents.debugger.sendCommand('Emulation.setEmulatedMedia',{features:[{name:'prefers-reduced-motion',value:'reduce'}]});
    await execute(`window.liveTestFixture.snapshot.enemyShopTimers[2].state='critical';window.liveTestSend()`);
    await execute(`new Promise(resolve=>setTimeout(resolve,50))`);
    assert.equal(await execute(`getComputedStyle(document.querySelector('.live-enemy-timer.critical img')).animationName`),'none');
    if(process.env.SOLRALOL_TEST_SCREENSHOT){
      window.setContentSize(1600,1000);
      await execute(`document.querySelector('.app-shell').classList.remove('sidebar-collapsed');document.querySelector('.content').scrollTop=0;new Promise(resolve=>setTimeout(resolve,350))`);
      require('node:fs').writeFileSync(process.env.SOLRALOL_TEST_SCREENSHOT,(await window.webContents.capturePage()).toPNG());
    }
    console.log('Live preparation Chromium checks passed: 5 widths × expanded/collapsed sidebar, 72 skill cells, 5 timers, six-item rows, pulse reset and retained recommendation widgets.');
  } finally {window.destroy();}
  app.exit(0);
}).catch(error=>{console.error(error);app.exit(1);});
