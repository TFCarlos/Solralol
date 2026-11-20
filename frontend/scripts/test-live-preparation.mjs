import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { spawn } from 'node:child_process';
import { createServer } from 'vite';
import electron from 'electron';
import {mkdtemp,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';

const pixel='data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLbtAAAAABJRU5ErkJggg==';
const html='<!doctype html><html><head><meta charset="UTF-8"></head><body><div id="root"></div><script type="module" src="/@id/__x00__live-preparation-test"></script></body></html>';
const entry=`
import React from 'react';
import {createRoot} from 'react-dom/client';
import {LiveMatchPage} from '/src/pages/LiveMatchPage.tsx';
import {WindowTitleBar} from '/src/components/WindowTitleBar.tsx';
import {LiveMatchStatus} from '/src/components/LiveMatchStatus.tsx';
import {liveFixture} from '/src/pages/liveFixtures.ts';
import '/src/styles.css';import '/src/live-preparation.css';
window.solralol={getWindowState:async()=>({maximized:false}),onWindowState:()=>()=>{},request:async(method,params)=>method==='home.assets'?{championAliases:Object.fromEntries(params.champions.map(c=>[c,c])),champions:Object.fromEntries(params.champions.map(c=>[c,${JSON.stringify(pixel)}]))}:Object.fromEntries(Object.entries(params).flatMap(([kind,values])=>values.map(id=>[kind.slice(0,-1)+':'+id,${JSON.stringify(pixel)}])))};
window.liveTestFixture=liveFixture();
window.liveTestFixture.snapshot.players.forEach(p=>{p.items=[3006,3031,3153,3071,3026,6333].map(itemID=>({itemID,displayName:'Objeto de prueba'}));p.runes={keystone:{id:8010,displayName:'Conqueror'},primaryRuneTree:{id:8000,displayName:'Precision'},secondaryRuneTree:{id:8400,displayName:'Resolve'}};});
window.liveTestSend=()=>window.dispatchEvent(new CustomEvent('solralol:live-update',{detail:structuredClone(window.liveTestFixture)}));
createRoot(document.getElementById('root')).render(React.createElement('div',{className:'app-shell'},React.createElement('aside',{className:'rail'}),React.createElement('main',{className:'main-area'},React.createElement(WindowTitleBar,{label:'Partida en vivo'},React.createElement(LiveMatchStatus)),React.createElement('div',{className:'content'},React.createElement(LiveMatchPage,{active:true,backendReady:true,onOpenSaved:()=>{}})))));
setTimeout(window.liveTestSend,100);
`;
const directory=await mkdtemp(join(tmpdir(),'solralol-live-preparation-'));
const vite=await createServer({configFile:fileURLToPath(new URL('../vite.config.ts',import.meta.url)),cacheDir:join(directory,'vite'),optimizeDeps:{include:['react','react-dom/client','react/jsx-dev-runtime']},server:{host:'127.0.0.1',port:0,open:false},plugins:[{name:'live-preparation-test',resolveId(id){if(id==='\0live-preparation-test'||id==='live-preparation-test')return '\0live-preparation-test';},load(id){if(id==='\0live-preparation-test')return entry;},configureServer(server){server.middlewares.use('/__live-preparation-test',async(req,res)=>{res.setHeader('Content-Type','text/html');res.end(await server.transformIndexHtml('/__live-preparation-test',html));});}}]});
try {
  const {livePresentationKey}=await vite.ssrLoadModule('/src/pages/LiveMatchPage.tsx');
  const {liveFixture}=await vite.ssrLoadModule('/src/pages/liveFixtures.ts');
  const original=liveFixture(), clockOnly=structuredClone(original);
  clockOnly.lastUpdated='2026-10-25T00:00:00Z';clockOnly.snapshot.gameTime+=10;
  clockOnly.snapshot.enemyShopTimers.forEach(row=>row.elapsedSeconds+=10);
  assert.equal(livePresentationKey(original),livePresentationKey(clockOnly),'time-only updates must not rerender the whole Live page');
  clockOnly.snapshot.localStats.currentGold+=100;
  assert.notEqual(livePresentationKey(original),livePresentationKey(clockOnly),'material player changes must update the page');
  await vite.listen();
  const address=vite.httpServer.address();assert.ok(address&&typeof address==='object');
  const env={...process.env,SOLRALOL_TEST_USER_DATA:join(directory,'electron')};delete env.ELECTRON_RUN_AS_NODE;
  await new Promise((resolve,reject)=>{
    const child=spawn(electron,[fileURLToPath(new URL('./check-live-preparation-layout.cjs',import.meta.url)),`http://127.0.0.1:${address.port}/__live-preparation-test`],{env,windowsHide:true,stdio:'inherit'});
    const timeout=setTimeout(()=>{child.kill();reject(new Error('Live preparation Chromium test timed out'));},45000);
    child.on('error',error=>{clearTimeout(timeout);reject(error);});
    child.on('exit',code=>{clearTimeout(timeout);code===0?resolve():reject(new Error(`Chromium check failed (${code})`));});
  });
} finally { await vite.close();await rm(directory,{recursive:true,force:true}); }
