import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { Lane, MetaAssetsRequest, MetaBootstrap, MetaChampionRow, MetaNoteNode, MetaPatchNotes, MetaRegion, MetaRole, MetaTierResult } from '../types/contracts';

type Props = { active: boolean; backendReady: boolean; onOpenAnalysis: (champion: string, role: Lane) => void };
type MetaTab = 'tier' | 'notes';
type SortKey = 'position' | 'win_rate' | 'pick_rate' | 'ban_rate' | 'sample_size';

const TIERS = ['S+', 'S', 'S-', 'A+', 'A', 'A-', 'B+', 'B', 'B-', 'C+', 'C', 'C-', 'D+', 'D', 'D-'];
const TIER_COLORS: Record<string, string> = { S: '#d6b66d', A: '#78b79b', B: '#829bb6', C: '#c99a68', D: '#bf7468' };
const ROLE_LABELS: Record<MetaRole, string> = { top: 'Top', jungle: 'Jungla', mid: 'Medio', adc: 'Bot', support: 'Apoyo' };
const REGION_LABELS: Record<MetaRegion, string> = { all: 'Mundo', euw: 'Europa Oeste (EUW)', na: 'Norteamérica (NA)', kr: 'Corea (KR)' };
const SORT_LABELS: Record<SortKey, string> = { position: 'Posición LoLalytics', win_rate: 'Win rate', pick_rate: 'Pick rate', ban_rate: 'Ban rate', sample_size: 'Partidas analizadas' };

export function MetaPage({ active, backendReady, onOpenAnalysis }: Props) {
  const [tab, setTab] = useState<MetaTab>('tier');
  const [bootstrap, setBootstrap] = useState<MetaBootstrap>();
  const [role, setRole] = useState<MetaRole>('top');
  const [region, setRegion] = useState<MetaRegion>('euw');
  const [sort, setSort] = useState<SortKey>('position');
  const [expandedTiers, setExpandedTiers] = useState<Record<string, boolean>>({});
  const [query, setQuery] = useState('');
  const [tierCache, setTierCache] = useState<Record<string, MetaTierResult>>({});
  const [tierLoading, setTierLoading] = useState(false);
  const [tierError, setTierError] = useState('');
  const [notes, setNotes] = useState<MetaPatchNotes>();
  const [notesLoading, setNotesLoading] = useState(false);
  const [notesError, setNotesError] = useState('');
  const [assets, setAssets] = useState<Record<string, string | null>>({});
  const [selectedImage, setSelectedImage] = useState<{ url: string; alt: string }>();
  const assetsRef = useRef(assets);
  assetsRef.current = assets;
  const [selectedChampion, setSelectedChampion] = useState<MetaChampionRow>();
  const tierRequest = useRef(0);
  const notesRequest = useRef(0);
  const assetRequests = useRef(new Set<string>());
  const initialized = useRef(false);
  const key = `${role}|${region}`;
  const tier = tierCache[key];

  useEffect(() => {
    if (!selectedImage) return;
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === 'Escape') setSelectedImage(undefined); };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [selectedImage]);

  useEffect(() => {
    if (!active || !backendReady || initialized.current) return;
    let current = true;
    window.solralol.request('meta.bootstrap').then((result) => {
      if (!current) return;
      setBootstrap(result);
      setRegion(result.region);
      initialized.current = true;
    }).catch((error: Error) => { if (current) setTierError(error.message); });
    return () => { current = false; };
  }, [active, backendReady]);

  useEffect(() => {
    if (!active || !backendReady || !initialized.current) return;
    const cached = tierCache[key];
    if (cached) { setTierLoading(false); return; }
    let current = true;
    const requestId = ++tierRequest.current;
    setTierLoading(true);
    setTierError('');
    window.solralol.request('meta.tier', { role, region }).then((result) => {
      if (!current || requestId !== tierRequest.current) return;
      setTierCache((previous) => ({ ...previous, [key]: result }));
    }).catch((error: Error) => {
      if (current && requestId === tierRequest.current) setTierError(error.message || 'No se pudo consultar el ranking.');
    }).finally(() => { if (current && requestId === tierRequest.current) setTierLoading(false); });
    return () => { current = false; };
  }, [active, backendReady, initialized.current, key, role, region, tierCache]);

  const loadNotes = useCallback((force = false) => {
    const requestId = ++notesRequest.current;
    setNotesLoading(true);
    setNotesError('');
    window.solralol.request('meta.notes', { force }).then((result) => {
      if (requestId === notesRequest.current) setNotes(result);
    }).catch((error: Error) => {
      if (requestId === notesRequest.current) setNotesError(error.message || 'No se pudieron cargar las notas oficiales.');
    }).finally(() => { if (requestId === notesRequest.current) setNotesLoading(false); });
  }, []);

  useEffect(() => {
    if (!active || !backendReady) return;
    loadNotes(false);
    const timer = window.setInterval(() => loadNotes(false), 6 * 60 * 60 * 1000);
    return () => { window.clearInterval(timer); notesRequest.current += 1; };
  }, [active, backendReady, loadNotes]);

  const ensureAsset = useCallback((assetKey: string) => {
    if (Object.prototype.hasOwnProperty.call(assetsRef.current, assetKey) || assetRequests.current.has(assetKey)) return;
    const request: MetaAssetsRequest = {};
    if (assetKey.startsWith('champion:')) request.champions = [assetKey.slice('champion:'.length)];
    else if (assetKey.startsWith('item:')) request.items = [assetKey.slice('item:'.length)];
    else if (assetKey.startsWith('ability:')) {
      const [champion, slot] = assetKey.slice('ability:'.length).split('|');
      if (!champion || !['passive', 'q', 'w', 'e', 'r'].includes(slot)) return;
      request.abilities = [{ champion, slot: slot as 'passive' | 'q' | 'w' | 'e' | 'r' }];
    } else return;
    assetRequests.current.add(assetKey);
    window.solralol.request('meta.assets', request).then((result) => {
      setAssets((previous) => ({ ...previous, ...result }));
    }).catch(() => {
      setAssets((previous) => ({ ...previous, [assetKey]: null }));
    }).finally(() => assetRequests.current.delete(assetKey));
  }, []);

  const rows = useMemo(() => {
    const source = tier?.champions ?? [];
    const normalized = query.trim().toLocaleLowerCase('es');
    return source.filter((champion) => !normalized || `${champion.name} ${champion.source_name ?? ''} ${champion.champion_id}`.toLocaleLowerCase('es').includes(normalized));
  }, [tier, query]);
  const topChampion = sort === 'position' && !query.trim() ? rows.find((champion) => champion.position === 1) : undefined;
  const tiers = useMemo(() => [...new Set(rows.map((champion) => champion.tier))].sort((a, b) => (TIERS.indexOf(a) < 0 ? 99 : TIERS.indexOf(a)) - (TIERS.indexOf(b) < 0 ? 99 : TIERS.indexOf(b))), [rows]);

  const refreshTier = () => {
    if (!backendReady) return;
    const requestId = ++tierRequest.current;
    setTierLoading(true);
    setTierError('');
    window.solralol.request('meta.tier', { role, region, force: true }).then((result) => {
      if (requestId === tierRequest.current) setTierCache((previous) => ({ ...previous, [key]: result }));
    }).catch((error: Error) => { if (requestId === tierRequest.current) setTierError(error.message || 'No se pudo actualizar la clasificación.'); })
      .finally(() => { if (requestId === tierRequest.current) setTierLoading(false); });
  };

  return <section className="meta-page" aria-label="Meta y notas">
    <header className="meta-page-header">
      <div><span className="eyebrow">ESTADÍSTICAS COMPETITIVAS Y ACTUALIZACIONES OFICIALES</span><h1>Meta y notas</h1><p>Explora el rendimiento de campeones y los cambios publicados por Riot.</p></div>
      <div className="meta-context"><span>RANGO <b>Esmeralda+</b></span><span>COLA <b>Solo/Dúo</b></span></div>
    </header>
    <nav className="meta-tabs" aria-label="Secciones de Meta">
      <button type="button" className={tab === 'tier' ? 'selected' : ''} aria-current={tab === 'tier' ? 'page' : undefined} onClick={() => setTab('tier')}>Tier list</button>
      <button type="button" className={tab === 'notes' ? 'selected' : ''} aria-current={tab === 'notes' ? 'page' : undefined} onClick={() => setTab('notes')}>Notas del parche</button>
    </nav>

    {tab === 'tier' ? <div className="meta-tier-view">
      <div className="meta-filters">
        <div className="meta-role-filter" role="group" aria-label="Filtrar por posición">{(bootstrap?.roles ?? Object.entries(ROLE_LABELS).map(([id, label]) => ({ id, label }))).map((item) => <button type="button" key={item.id} className={role === item.id ? 'selected' : ''} aria-pressed={role === item.id} onClick={() => setRole(item.id as MetaRole)}>{item.label}</button>)}</div>
        <label className="meta-control"><span>Región</span><select value={region} onChange={(event) => setRegion(event.target.value as MetaRegion)}>{(bootstrap?.regions ?? Object.entries(REGION_LABELS).map(([id, label]) => ({ id, label }))).map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>
        <label className="meta-control meta-search"><span>Buscar campeón</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Nombre de campeón" /></label>
        <label className="meta-control"><span>Ordenar por</span><select value={sort} onChange={(event) => setSort(event.target.value as SortKey)}>{Object.entries(SORT_LABELS).map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select></label>
        <button type="button" className="meta-source-link" onClick={() => void window.solralol.openMetaSource('https://lolalytics.com/es/lol/tierlist/')}>Fuente LoLalytics ↗</button>
        <button type="button" className="meta-refresh" disabled={tierLoading || !backendReady} onClick={refreshTier}>{tierLoading ? 'Actualizando…' : 'Actualizar datos'}</button>
      </div>
      <div className="meta-data-status" role="status">
        <span className={`meta-status-dot ${tier?.stale ? 'stale' : tier ? 'ready' : ''}`} />
        {tier ? <><b>{tier.complete === false ? 'Datos parciales · identidad pendiente' : tier.stale ? 'Caché desactualizada' : tier.cached ? 'Caché local' : 'Datos actualizados'}</b><span>LoLalytics · parche {tier.patch} · {ROLE_LABELS[role]} · {REGION_LABELS[region]}</span><small>{tier.champions.length} de {tier.source_count} campeones identificados · {formatDate(tier.retrieved_at)}</small></> : <><b>{tierLoading ? 'Consultando clasificación…' : backendReady ? 'Sin datos para estos filtros' : 'Backend desconectado'}</b><span>{tierLoading ? 'Se reutiliza la caché local o se consulta LoLalytics.' : 'No se muestran posiciones inventadas.'}</span></>}
      </div>
      {tierError && <div className="meta-alert" role="alert"><span>{tierError}</span><button type="button" onClick={refreshTier}>Reintentar</button></div>}
      {tier?.stale && tier.cache_error && <div className="meta-alert warning" role="status"><span>No se pudo actualizar LoLalytics; se conserva el último conjunto válido. {tier.cache_error}</span></div>}
      {tier?.complete === false && <div className="meta-alert warning" role="status"><span>No se pudo resolver {tier.unresolved?.map((entry) => `${entry.source_name} (#${entry.position})`).join(', ') || 'una identidad de campeón'}. Se conserva el puesto original de cada fila; el ranking puede estar incompleto.</span></div>}
      {!tier && tierLoading ? <div className="meta-loading"><i className="spinner"/>Cargando clasificación Emerald+ de {ROLE_LABELS[role]}…</div> : rows.length ? <div className="meta-ranking-content">
        {topChampion && <FeaturedChampion row={topChampion} assets={assets} ensureAsset={ensureAsset} onSelect={setSelectedChampion} />}
        {tiers.map((tierName) => {
          const tierRows = rows.filter((champion) => champion.tier === tierName && champion.champion_id !== topChampion?.champion_id).sort((a, b) => compareRows(a, b, sort));
          if (!tierRows.length) return null;
          return <details className="meta-tier-group" key={tierName} open={expandedTiers[tierName] ?? true} onToggle={(event) => { const open = event.currentTarget.open; setExpandedTiers((previous) => previous[tierName] === open ? previous : { ...previous, [tierName]: open }); }}>
            <summary style={{ '--tier-accent': TIER_COLORS[tierName[0]] ?? '#c6a261' } as React.CSSProperties}><span className="meta-tier-badge">{tierName}</span><b>{tierRows.length} campeones</b><span className="meta-tier-line"/><small>LoLalytics</small></summary>
            <div className="meta-champion-grid">{tierRows.map((row) => <ChampionCard key={`${row.champion_id}-${row.position}`} row={row} assets={assets} ensureAsset={ensureAsset} onSelect={setSelectedChampion} />)}</div>
          </details>;
        })}
      </div> : <div className="meta-empty"><strong>{tier ? `Sin resultados para «${query.trim()}»` : 'No hay datos de ranking disponibles'}</strong><span>{tier ? 'Prueba otro nombre o limpia la búsqueda.' : 'Comprueba la conexión e inténtalo de nuevo.'}</span></div>}
    </div> : <div className="meta-notes-view">
      <div className="meta-notes-toolbar"><div><span className="eyebrow">FUENTE OFICIAL · LEAGUE OF LEGENDS</span><strong>{notes ? `Parche ${notes.version} · ${formatDate(notes.published)}` : 'Notas del parche'}</strong>{notes?.cached && <small>Contenido en caché local</small>}</div><button type="button" className="meta-refresh" disabled={notesLoading || !backendReady} onClick={() => loadNotes(true)}>{notesLoading ? 'Comprobando…' : 'Actualizar notas'}</button></div>
      {notesError && <div className="meta-alert" role="alert"><span>{notesError}</span><button type="button" onClick={() => loadNotes(false)}>Reintentar</button></div>}
      {!notes && notesLoading ? <div className="meta-loading"><i className="spinner"/>Buscando la última publicación oficial…</div> : notes ? <>
        <article className="meta-patch-hero">
          {notes.hero_image && <button type="button" className="meta-hero-image-trigger" aria-label="Ampliar imagen del parche" onClick={() => setSelectedImage({ url: notes.hero_image!, alt: 'Imagen del parche' })}><img src={notes.hero_image} alt="" /></button>}
          <div><span className="meta-patch-version">PARCHE {notes.version}</span><h2>{notes.title}</h2><p>{notes.published ? `Publicado el ${formatDate(notes.published)}` : 'Notas oficiales de League of Legends'}{notes.game_version ? ` · Datos del juego ${notes.game_version}` : ''}</p><button type="button" className="meta-source-link" onClick={() => void window.solralol.openMetaSource(notes.url)}>Abrir publicación oficial ↗</button></div>
        </article>
        {notes.stale && <div className="meta-alert warning" role="status"><span>No fue posible consultar la publicación actual; se muestra la última copia guardada.</span></div>}
        <div className="meta-note-sections">{notes.sections.map((node, index) => <NoteNode key={`${node.title}-${index}`} node={node} level={0} assets={assets} ensureAsset={ensureAsset} onOpenImage={(url, alt) => setSelectedImage({ url, alt })} />)}</div>
        <div className="meta-notes-foot">Revisado {formatDate(notes.checked_at)} · Secciones en el orden de publicación oficial</div>
      </> : <div className="meta-empty"><strong>No se pudieron cargar las notas oficiales</strong><span>Se conservará y mostrará una copia local válida cuando esté disponible.</span></div>}
    </div>}

    {selectedChampion && <div className="meta-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setSelectedChampion(undefined); }}><section className="meta-champion-modal" role="dialog" aria-modal="true" aria-labelledby="meta-champion-modal-title">
      <button type="button" className="meta-modal-close" aria-label="Cerrar" onClick={() => setSelectedChampion(undefined)}>×</button>
      <div className="meta-modal-heading"><MetaIcon assetKey={`champion:${selectedChampion.champion_id}`} assets={assets} ensureAsset={ensureAsset} fallback={selectedChampion.name.slice(0, 1)} /><div><span className="eyebrow">{ROLE_LABELS[selectedChampion.role]} · ESMERALDA+ · {REGION_LABELS[selectedChampion.region]}</span><h2 id="meta-champion-modal-title">{selectedChampion.name}</h2><small>Tier {selectedChampion.tier} · puesto #{selectedChampion.position}</small></div></div>
      <div className="meta-modal-stats">{[['Win rate', selectedChampion.win_rate], ['Pick rate', selectedChampion.pick_rate], ['Ban rate', selectedChampion.ban_rate]].map(([label, value]) => <div key={label as string}><small>{label}</small><b>{Number(value).toFixed(2)}%</b></div>)}<div><small>Partidas</small><b>{selectedChampion.sample_size?.toLocaleString('es-ES') ?? '—'}</b></div></div>
      <button type="button" className="meta-refresh" onClick={() => { setSelectedChampion(undefined); onOpenAnalysis(selectedChampion.champion_id, selectedChampion.role); }}>Abrir análisis local</button>
    </section></div>}
    {selectedImage && <div className="meta-image-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setSelectedImage(undefined); }}><section className="meta-image-dialog" role="dialog" aria-modal="true" aria-label={selectedImage.alt}><button type="button" aria-label="Cerrar imagen" onClick={() => setSelectedImage(undefined)}>×</button><img src={selectedImage.url} alt={selectedImage.alt} /></section></div>}
  </section>;
}

function compareRows(a: MetaChampionRow, b: MetaChampionRow, sort: SortKey) {
  if (sort === 'position') return a.position - b.position;
  const aValue = a[sort], bValue = b[sort];
  if (aValue == null && bValue != null) return 1;
  if (bValue == null && aValue != null) return -1;
  return Number(bValue ?? 0) - Number(aValue ?? 0) || a.position - b.position;
}

function FeaturedChampion({ row, assets, ensureAsset, onSelect }: { row: MetaChampionRow; assets: Record<string, string | null>; ensureAsset: (key: string) => void; onSelect: (row: MetaChampionRow) => void }) {
  return <button type="button" className="meta-featured-champion" onClick={() => onSelect(row)}>
    <span className="meta-featured-rank">#1</span><MetaIcon assetKey={`champion:${row.champion_id}`} assets={assets} ensureAsset={ensureAsset} fallback={row.name.slice(0, 1)} />
    <span className="meta-featured-name"><small>MEJOR POSICIÓN · TIER {row.tier}</small><b>{row.name}</b><i>{ROLE_LABELS[row.role]} · {row.sample_size?.toLocaleString('es-ES') ?? 'Muestra n/d'} partidas</i></span>
    <span className="meta-featured-stat"><small>WIN RATE</small><b>{row.win_rate.toFixed(2)}%</b></span><span className="meta-featured-stat"><small>PICK RATE</small><b>{row.pick_rate.toFixed(2)}%</b></span>
  </button>;
}

function ChampionCard({ row, assets, ensureAsset, onSelect }: { row: MetaChampionRow; assets: Record<string, string | null>; ensureAsset: (key: string) => void; onSelect: (row: MetaChampionRow) => void }) {
  const accent = TIER_COLORS[row.tier[0]] ?? '#c6a261';
  return <button type="button" className="meta-champion-card" style={{ '--tier-accent': accent } as React.CSSProperties} onClick={() => onSelect(row)} title={`Ver estadísticas de ${row.name}`}>
    <span className="meta-position">#{row.position}</span><MetaIcon assetKey={`champion:${row.champion_id}`} assets={assets} ensureAsset={ensureAsset} fallback={row.name.slice(0, 1)} />
    <span className="meta-champion-copy"><b>{row.name}</b><small>{row.sample_size == null ? 'Muestra no disponible' : `${row.sample_size.toLocaleString('es-ES')} partidas`}</small></span><span className="meta-tier-small">{row.tier}</span>
    <span className="meta-champion-metrics"><span><small>WR</small><b>{row.win_rate.toFixed(2)}%</b></span><span><small>PICK</small><b>{row.pick_rate.toFixed(2)}%</b></span><span><small>BAN</small><b>{row.ban_rate.toFixed(2)}%</b></span></span>
  </button>;
}

function MetaIcon({ assetKey, assets, ensureAsset, fallback }: { assetKey: string; assets: Record<string, string | null>; ensureAsset: (key: string) => void; fallback: string }) {
  const ref = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    const node = ref.current;
    if (!node || Object.prototype.hasOwnProperty.call(assets, assetKey)) return;
    if (!('IntersectionObserver' in window)) { ensureAsset(assetKey); return; }
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) { ensureAsset(assetKey); observer.disconnect(); }
    }, { rootMargin: '160px' });
    observer.observe(node);
    return () => observer.disconnect();
  }, [assetKey, assets, ensureAsset]);
  const source = assets[assetKey];
  return <span ref={ref} className="meta-icon-frame">{source ? <img src={source} alt="" loading="lazy" /> : <i>{fallback}</i>}</span>;
}

function NoteNode({ node, level, assets, ensureAsset, onOpenImage }: { node: MetaNoteNode; level: number; assets: Record<string, string | null>; ensureAsset: (key: string) => void; onOpenImage: (url: string, alt: string) => void }) {
  const detailsRef = useRef<HTMLDetailsElement>(null);
  const children = Array.isArray(node.children) ? node.children : [];
  const kind = node.kind;
  const identityKey = kind === 'champion' && node.champion_id ? `champion:${node.champion_id}` : kind === 'item' && node.item_id ? `item:${node.item_id}` : kind === 'detail' && node.champion_id && node.ability_slot ? `ability:${node.champion_id}|${node.ability_slot}` : undefined;
  const safeTitle = node.title || 'Contenido del parche';
  useEffect(() => { if (level === 0 && normalize(safeTitle) === 'campeones' && detailsRef.current) detailsRef.current.open = true; }, []);
  return <details ref={detailsRef} className={`meta-note-node level-${Math.min(level, 3)} ${kind === 'champion' ? 'champion' : ''} ${kind === 'item' ? 'item' : ''}`}>
    <summary>
      {identityKey && <MetaIcon assetKey={identityKey} assets={assets} ensureAsset={ensureAsset} fallback={kind === 'detail' ? node.ability_slot?.toUpperCase() ?? '•' : safeTitle.slice(0, 1)} />}
      <span className="meta-note-title">{safeTitle}</span>
      {node.change_type && <ChangeBadge value={node.change_type} />}
      {children.length > 0 && <small className="meta-note-child-count">{children.length}</small>}
    </summary>
    <div className="meta-note-body">
      {node.blocks?.map((block, index) => block.type === 'image' ? safeMediaUrl(block.url) ? <button type="button" className="meta-note-media-trigger" key={index} onClick={() => onOpenImage(block.url!, block.alt || 'Imagen de las notas')}><img className="meta-note-media" src={block.url} alt={block.alt || 'Imagen de las notas'} loading="lazy" /></button> : null : block.text ? <div className={`meta-note-text ${block.type === 'change' ? 'change' : ''}`} key={index}>{block.change_type && <ChangeBadge value={block.change_type} />}<p>{block.text}</p></div> : null)}
      {children.map((child, index) => <NoteNode key={`${child.title}-${index}`} node={child} level={level + 1} assets={assets} ensureAsset={ensureAsset} onOpenImage={onOpenImage} />)}
    </div>
  </details>;
}

function ChangeBadge({ value }: { value: string }) {
  const change = value.toLocaleLowerCase();
  const category = change.includes('buff') || change.includes('mejora') ? 'buff' : change.includes('nerf') || change.includes('debil') ? 'nerf' : 'adjustment';
  const label = category === 'buff' ? 'Mejora' : category === 'nerf' ? 'Debilitación' : 'Ajuste';
  return <span className={`meta-change-badge ${category}`}>{label}</span>;
}

function safeMediaUrl(raw?: string) {
  if (!raw) return false;
  try {
    const url = new URL(raw);
    return url.protocol === 'https:' && ['leagueoflegends.com', 'riotgames.com', 'contentstack.io'].some((domain) => url.hostname === domain || url.hostname.endsWith(`.${domain}`));
  } catch { return false; }
}

function normalize(value: string) { return value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase(); }
function formatDate(value?: string | null) {
  if (!value) return 'fecha no disponible';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? 'fecha no disponible' : new Intl.DateTimeFormat('es-ES', { dateStyle: 'medium' }).format(parsed);
}
