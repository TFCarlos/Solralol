import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { createServer } from 'vite';
import { mkdtemp, readFile, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawn } from 'node:child_process';
import electron from 'electron';

const vite = await createServer({
  configFile: fileURLToPath(new URL('../vite.config.ts', import.meta.url)),
  server: { middlewareMode: true, hmr: false },
  appType: 'custom',
});

try {
  const { TimelineList } = await vite.ssrLoadModule('/src/pages/LiveMatchPage.tsx');
  const event = {
    EventID: 221,
    EventName: 'ChampionKill',
    EventTime: 754.2,
    // Reproduce a stale normalized snapshot where actor identity was replaced
    // with the victim, while the explicit actor type still says TURRET.
    KillerActorType: ' TURRET ',
    KillerActorName: 'Briar',
    KillerChampion: 'Briar',
    VictimActorType: 'champion',
    VictimActorName: 'Briar',
    VictimChampion: 'Briar',
    // The server snapshot lacks a localized description, so the renderer has
    // to trust the actor type instead of guessing from description text.
  };
  const portrait = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLbtAAAAABJRU5ErkJggg==';
  const externalAssets = process.env.SOLRALOL_TEST_ASSETS ? JSON.parse(await readFile(process.env.SOLRALOL_TEST_ASSETS, 'utf8')) : {};
  const assets = { 'champion:Briar': portrait, 'champion:Lux': portrait, 'champion:Ahri': portrait, 'item:3100': portrait, ...externalAssets };
  const markup = renderToStaticMarkup(createElement(TimelineList, {
    events: [event], localTeam: 'ORDER', assets,
  }));

  assert.match(markup, /data-event-type="CHAMPION_KILL"/);
  assert.match(markup, /data-actor-type="TURRET"/);
  assert.match(markup, /data-actor-name="Torre"/);
  assert.match(markup, /data-victim-champion="Briar"/);
  assert.match(markup, /role="group" aria-label="12:34 Torre/);
  assert.ok(markup.includes(`aria-label="12:34 Torre \u2192 Briar. Briar muri\u00f3 por una torre"`));
  assert.match(markup, /class="live-objective-mark live-mark-tower"[^>]*title="Torre"/);
  assert.match(markup, /<svg viewBox="0 0 24 24"/);
  assert.match(markup, /<i aria-hidden="true"><\/i>/, 'neutral gray timeline dot remains separate');
  assert.ok(markup.includes(`class="live-event-arrow" aria-hidden="true">\u2192</span>`));
  assert.match(markup, /<time>12:34<\/time>/);
  assert.ok(markup.includes('<b>Briar muri\u00f3 por una torre</b>'));
  assert.match(markup, /<img class="live-event-champion"[^>]*alt="Briar"/);
  assert.equal((markup.match(/alt="Briar"/g) ?? []).length, 1, 'Briar must appear only as the victim portrait');
  assert.doesNotMatch(markup, /-31:|image-fallback/);

  const invalidTimeMarkup = renderToStaticMarkup(createElement(TimelineList, {
    events: [{ ...event, EventID: 222, EventTime: -31.5 }], localTeam: 'ORDER', assets,
  }));
  assert.match(invalidTimeMarkup, /<time>--:--<\/time>/, 'invalid timestamps use a safe value');
  assert.doesNotMatch(invalidTimeMarkup, /-31:/);
  const unknownMarkup = renderToStaticMarkup(createElement(TimelineList, {
    events:[{...event, KillerActorType:'unknown', EventDescription:'Briar muri\u00f3 por una torre'}], localTeam:'ORDER', assets,
  }));
  assert.doesNotMatch(unknownMarkup, /live-mark-tower|data-actor-type="TURRET"/);
  assert.ok(unknownMarkup.includes('Briar muri\u00f3 por una causa no identificada'));
  const { RunePage } = await vite.ssrLoadModule('/src/pages/DraftPage.tsx');
  const runeMarkup = renderToStaticMarkup(createElement(RunePage, {
    page:{primary_tree:'Precision', keystone:'Conqueror', keystone_id:8010,
      slots:['Triumph','Legend: Haste','Last Stand'], slot_ids:[9111,9105,8299]},
    assets:{'rune:8010':portrait,'rune:9111':portrait,'rune:9105':portrait,'rune:8299':portrait,...externalAssets},
  }));
  assert.match(runeMarkup, /<img[^>]*alt="Legend: Haste"/);
  assert.doesNotMatch(runeMarkup, /image-fallback/);
  const layoutEvents = [event,
    { EventName:'ChampionKill', EventTime:787, KillerActorType:'minion', VictimChampion:'Lux' },
    { EventName:'ChampionKill', EventTime:790, KillerActorType:'unknown', VictimChampion:'Briar' },
    { EventName:'ChampionKill', EventTime:791, KillerActorType:'champion', KillerChampion:'Ahri', VictimChampion:'Briar', KillerTeam:'ORDER' },
    { EventName:'TurretKilled', EventTime:850, KillerActorType:'minion', ObjectiveKind:'tower', EventDescription:'Los s\u00fabditos destruyeron una torre' },
    { EventName:'InhibRespawned', EventTime:544, ObjectiveKind:'inhibitor', EventDescription:'Inhibidor de top reaparecido' },
    { EventName:'CompletedItemAcquired', EventTime:640, KillerChampion:'Briar', ItemId:'3100', ItemName:'Perdici\u00f3n del Liche' },
  ];
  const respawnMarkup = renderToStaticMarkup(createElement(TimelineList, {events:[layoutEvents[5]], localTeam:'ORDER', assets}));
  assert.match(respawnMarkup, /live-mark-inhibitor/);
  assert.doesNotMatch(respawnMarkup, /live-mark-environment|live-event-arrow/);
  const layoutMarkup = renderToStaticMarkup(createElement(TimelineList, { events:layoutEvents, localTeam:'ORDER', assets }));
  const directory = await mkdtemp(join(tmpdir(), 'solralol-timeline-'));
  try {
    const html = join(directory, 'timeline.html');
    const css = await readFile(new URL('../src/styles.css', import.meta.url), 'utf8');
    await writeFile(html, `<!doctype html><meta charset="UTF-8"><style>${css}</style><style>body{min-width:0;padding:20px}.live-timeline{box-sizing:border-box}</style><section class="live-card live-timeline">${layoutMarkup}</section>${runeMarkup}`);
    const env = {...process.env};
    delete env.ELECTRON_RUN_AS_NODE;
    await new Promise((resolve, reject) => {
      const child = spawn(electron, [fileURLToPath(new URL('./check-live-timeline-layout.cjs', import.meta.url)), html, ...(process.env.SOLRALOL_TEST_SCREENSHOT ? [process.env.SOLRALOL_TEST_SCREENSHOT] : [])], { env, windowsHide:true, stdio:'inherit' });
      const timeout = setTimeout(() => { child.kill(); reject(new Error('Chromium timeline check timed out')); }, 20000);
      child.on('error', error => { clearTimeout(timeout); reject(error); });
      child.on('exit', code => { clearTimeout(timeout); code === 0 ? resolve() : reject(new Error(`Chromium timeline check failed (${code})`)); });
    });
  } finally { await rm(directory, {recursive:true, force:true}); }
  process.stdout.write('Rendered turret death timeline regression passed.\n');
} finally {
  await vite.close();
}
