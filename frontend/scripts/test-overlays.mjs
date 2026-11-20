import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';
import {createElement} from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {createServer} from 'vite';

const vite=await createServer({configFile:fileURLToPath(new URL('../vite.config.ts',import.meta.url)),server:{middlewareMode:true,hmr:false},appType:'custom'});
try {
  const {OverlayContent,overlayPreview}=await vite.ssrLoadModule('/src/pages/LiveOverlayPanel.tsx');
  const panels=['gold','alerts','purchase','recall','ability'];
  for(const panel of panels){
    const html=renderToStaticMarkup(createElement(OverlayContent,{panel,snapshot:overlayPreview,assets:{}}));
    assert.ok(html.length>40,`${panel} preview is populated without a game`);
  }
  const ability=renderToStaticMarkup(createElement(OverlayContent,{panel:'ability',snapshot:overlayPreview}));
  assert.match(ability,/aria-label="Subir Q"/);
  assert.equal((ability.match(/class="active"/g)??[]).length,1);
  const calibrated=renderToStaticMarkup(createElement(OverlayContent,{panel:'ability',snapshot:overlayPreview,slotSpacing:72}));
  assert.match(calibrated,/gap:29px/);
  const recall=renderToStaticMarkup(createElement(OverlayContent,{panel:'recall',snapshot:overlayPreview}));
  assert.match(recall,/Darius/);
  assert.match(recall,/MUERTO|02:34/);
  assert.ok(recall.indexOf('TOP') < recall.indexOf('JUNGLE'));
  const quiet=renderToStaticMarkup(createElement(OverlayContent,{panel:'alerts',snapshot:{overlay:{alerts:[]}}}));
  assert.equal(quiet,'');
  const notices=renderToStaticMarkup(createElement(OverlayContent,{panel:'alerts',snapshot:overlayPreview,assets:{'champion:Ahri':'data:image/png;base64,AA==','item:6655':'data:image/png;base64,AA=='}}));
  assert.equal((notices.match(/class="overlay-notification(?: |")/g)??[]).length,3);
  assert.match(notices,/class="overlay-notification-portrait"/);
  assert.match(notices,/class="overlay-notification-item"/);
  assert.match(notices,/Inhibidor de MID/);
  const tick=renderToStaticMarkup(createElement(OverlayContent,{panel:'alerts',snapshot:overlayPreview,elapsed:1}));
  assert.match(tick,/Aparece en 9 s/);
  const purchaseCards=renderToStaticMarkup(createElement(OverlayContent,{panel:'purchase',snapshot:overlayPreview,assets:{'item:6655':'main','item:3802':'component','item:3157':'hourglass','item:3089':'hat','item:1058':'rod'}}));
  assert.equal((purchaseCards.match(/overlay-next-item/g)??[]).length,3);
  assert.equal((purchaseCards.match(/class="overlay-item-caption"/g)??[]).length,3);
  const longName={...overlayPreview,recommendations:[{id:'9999',name:'Objeto legendario de nombre especialmente largo',synergy_score:78,nextPurchase:{status:'save',id:'1058'}}]};
  const longCard=renderToStaticMarkup(createElement(OverlayContent,{panel:'purchase',snapshot:longName}));
  assert.match(longCard,/Objeto legendario de nombre especialmente largo<\/b><small>SINERGIA 78 pts/);
  assert.match(purchaseCards,/Siguiente compra: Capítulo perdido/);
  const noPurchase={...overlayPreview,recommendations:[]};
  const purchase=renderToStaticMarkup(createElement(OverlayContent,{panel:'purchase',snapshot:noPurchase}));
  assert.match(purchase,/Sin recomendaciones verificadas/);
  assert.doesNotMatch(purchase,/Tormenta de Luden/);
  console.log('Five isolated overlay previews, purchase path indicators, and unavailable purchase state passed.');
} finally {await vite.close();}
