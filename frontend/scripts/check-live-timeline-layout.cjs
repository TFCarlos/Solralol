const { app, BrowserWindow } = require('electron');
const assert = require('node:assert/strict');
const fs = require('node:fs');

app.disableHardwareAcceleration();
app.whenReady().then(async () => {
  const window = new BrowserWindow({ show: false, width: 1000, height: 900,
    webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false } });
  try {
    await window.loadFile(process.argv[2]);
    for (const width of [280, 310, 420, 760]) {
      const rows = await window.webContents.executeJavaScript(`(async () => {
        document.querySelector('.live-timeline').style.width = '${width}px';
        await Promise.all([...document.images].map(image => image.decode().catch(() => {})));
        await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
        const box = element => { const r = element.getBoundingClientRect(); return { left:r.left, right:r.right, top:r.top, bottom:r.bottom, width:r.width, height:r.height }; };
        return [...document.querySelectorAll('.live-event')].map(row => ({
          label:row.getAttribute('aria-label'), type:row.dataset.actorType,
          row:box(row), availableWidth:row.parentElement.clientWidth - parseFloat(getComputedStyle(row.parentElement).paddingRight), time:box(row.querySelector('time')),
          dot:box(row.querySelector(':scope > i')), dotColor:getComputedStyle(row.querySelector(':scope > i')).backgroundColor,
          actors:box(row.querySelector('.live-event-actors')), description:box(row.querySelector('.live-event-detail')),
          textTransform:getComputedStyle(row.querySelector('b')).textTransform,
          icons:[...row.querySelectorAll('.live-event-actors > span, .live-event-actors > img')].map(icon => ({
            box:box(icon), visible:getComputedStyle(icon).visibility, label:icon.getAttribute('title'),
            svg:!!icon.querySelector('svg path,svg circle'), loaded:icon.tagName !== 'IMG' || icon.naturalWidth > 0
          }))
        }));
      })()`);
      assert.ok(rows.length >= 6);
      for (const row of rows) {
        assert.ok(row.row.width >= row.availableWidth - 1, `${width}px: shrunken event row: ${row.label} (${row.row.width}px)`);
        assert.ok(row.time.right <= row.dot.left + 1, `${width}px: timestamp overlaps dot: ${row.label}`);
        assert.ok(row.dot.right <= row.actors.left + 1, `${width}px: dot overlaps actor: ${row.label}`);
        assert.ok(row.actors.right <= row.description.left + 1, `${width}px: actor overlaps description: ${row.label}`);
        const center = box => (box.top + box.bottom) / 2;
        assert.ok(Math.abs(center(row.time) - center(row.actors)) <= 1, `${width}px: timestamp is vertically misaligned`);
        assert.ok(Math.abs(center(row.dot) - center(row.actors)) <= 1, `${width}px: dot is vertically misaligned`);
        assert.equal(row.textTransform, 'none');
        for (const icon of row.icons) {
          assert.ok(icon.box.left >= row.row.left && icon.box.right <= row.row.right + 1, `${width}px: icon outside row: ${row.label}`);
          assert.ok(icon.box.top >= row.row.top - 1 && icon.box.bottom <= row.row.bottom + 1, `${width}px: icon clipped vertically`);
          assert.equal(icon.visible, 'visible');
          assert.equal(icon.loaded, true, `${width}px: champion portrait failed to load`);
        }
        if (['TURRET', 'MINION', 'UNKNOWN'].includes(row.type)) assert.equal(row.dotColor, 'rgb(127, 130, 126)');
        if (row.type === 'CHAMPION') assert.equal(row.dotColor, 'rgb(121, 185, 146)');
        if (row.type === 'TURRET') assert.ok(row.icons.some(icon => icon.label === 'Torre' && icon.svg));
      }
      const runes = await window.webContents.executeJavaScript(`({
        count:document.querySelectorAll('.draft-rune-icons img').length,
        loaded:[...document.querySelectorAll('.draft-rune-icons img')].every(image=>image.complete&&image.naturalWidth>0),
        fallback:!!document.querySelector('.draft-rune-icons .image-fallback')
      })`);
      assert.equal(runes.count, 4);
      assert.equal(runes.loaded, true);
      assert.equal(runes.fallback, false);
    }
    if (process.argv[3]) fs.writeFileSync(process.argv[3], (await window.webContents.capturePage()).toPNG());
    process.stdout.write('Chromium timeline layout passed at 280, 310, 420 and 760 px.\n');
  } finally { window.destroy(); }
  app.exit(0);
}).catch(error => { console.error(error); app.exit(1); });
