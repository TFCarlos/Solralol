import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ChampionSelector } from '../components/ChampionSelector';
import { GameImage } from '../components/GameImage';
import type { Champion, HomeAssets, RecordingEntry, RecordingStatus } from '../types/contracts';

type PlaybackStatus = 'idle' | 'loading' | 'ready' | 'error';
type LibraryState = 'idle' | 'loading' | 'loaded' | 'error';
type ThumbnailResult = { state: 'ready' | 'deferred' | 'unavailable'; data: string | null };
const inactive: RecordingStatus = { state: 'inactive', message: '', error: '', elapsedSeconds: 0, recordingName: null };
const positionLabels: Record<string, string> = { top: 'Top', jungle: 'Jungla', mid: 'Medio', adc: 'Bot', support: 'Apoyo' };
const positionAliases: Record<string, string> = { top: 'top', jungle: 'jungle', jungla: 'jungle', middle: 'mid', mid: 'mid', medio: 'mid', bottom: 'adc', bot: 'adc', adc: 'adc', utility: 'support', support: 'support', apoyo: 'support' };
function positionKey(value: string) { return positionAliases[value.trim().toLocaleLowerCase('es')] ?? value.trim().toLocaleLowerCase('es'); }
let thumbnailRequestQueue: Promise<unknown> = Promise.resolve();
function requestThumbnail(id: string): Promise<ThumbnailResult> {
  const request = thumbnailRequestQueue.then(() => window.solralol.request('recordings.thumbnail', { id }));
  thumbnailRequestQueue = request.catch(() => undefined);
  return request;
}

function formatTime(value: number) {
  if (!Number.isFinite(value) || value < 0) return '00:00';
  const seconds = Math.floor(value);
  return `${Math.floor(seconds / 3600).toString().padStart(2, '0')}:${Math.floor(seconds % 3600 / 60).toString().padStart(2, '0')}:${(seconds % 60).toString().padStart(2, '0')}`;
}
function localDay(timestamp: number) {
  if (!timestamp) return '';
  const date = new Date(timestamp * 1000);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}
function formatBytes(bytes: number) {
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 MB';
  const gb = bytes / (1024 ** 3);
  return gb >= 1 ? `${gb.toLocaleString('es-ES', { maximumFractionDigits: 1 })} GB` : `${(bytes / (1024 ** 2)).toLocaleString('es-ES', { maximumFractionDigits: 0 })} MB`;
}
function dayHeading(day: string) {
  if (!day) return 'Fecha no disponible';
  const today = new Date();
  const yesterday = new Date(); yesterday.setDate(today.getDate() - 1);
  if (day === localDay(today.getTime() / 1000)) return 'Hoy';
  if (day === localDay(yesterday.getTime() / 1000)) return 'Ayer';
  const [year, month, date] = day.split('-').map(Number);
  return new Date(year, month - 1, date).toLocaleDateString('es-ES', { day: 'numeric', month: 'long', year: 'numeric' });
}
function recordingDay(row: RecordingEntry) { return row.created_at > 0 ? localDay(row.created_at) : ''; }
const requestHomeAssets = window.solralol.request as unknown as (method: 'home.assets', params: { champions: string[] }) => Promise<HomeAssets>;

function RecordingThumbnail({ id, title, playedAt, duration, playbackUrl, retryKey, active, previewing, liveRecording }: { id: string; title: string; playedAt: string; duration: string; playbackUrl: string | null; retryKey: number; active: boolean; previewing: boolean; liveRecording: boolean }) {
  const rootRef = useRef<HTMLDivElement>(null);
  const [data, setData] = useState('');
  const [state, setState] = useState<'idle' | 'loading' | 'deferred' | 'unavailable'>('idle');
  const [previewStarted, setPreviewStarted] = useState(false);
  const [previewReady, setPreviewReady] = useState(false);
  const [inViewport, setInViewport] = useState(true);
  const previewRef = useRef<HTMLVideoElement>(null);
  useEffect(() => {
    if (!active || data || liveRecording) return;
    const root = rootRef.current;
    if (!root) return;
    let disposed = false;
    let observer: IntersectionObserver | undefined;
    const request = () => {
      if (disposed) return;
      setState('loading');
      void requestThumbnail(id).then((result) => {
        if (disposed) return;
        if (result.state === 'ready' && result.data) { setData(`data:image/jpeg;base64,${result.data}`); setState('idle'); }
        else setState(result.state === 'deferred' ? 'deferred' : 'unavailable');
      }).catch(() => { if (!disposed) setState('unavailable'); });
    };
    if ('IntersectionObserver' in window) {
      observer = new IntersectionObserver((entries) => {
        if (entries.some((entry) => entry.isIntersecting)) { observer?.disconnect(); request(); }
      }, { rootMargin: '240px' });
      observer.observe(root);
    } else request();
    return () => { disposed = true; observer?.disconnect(); };
  }, [active, data, id, liveRecording, retryKey]);
  useEffect(() => {
    const root = rootRef.current;
    if (!root || !('IntersectionObserver' in window)) return;
    const observer = new IntersectionObserver((entries) => setInViewport(entries.some((entry) => entry.isIntersecting)), { threshold: 0.01 });
    observer.observe(root);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    if (!previewing || !active || !playbackUrl || !inViewport) { setPreviewStarted(false); setPreviewReady(false); return; }
    let disposed = false;
    const timer = window.setTimeout(() => { if (!disposed) setPreviewStarted(true); }, 380);
    return () => {
      disposed = true;
      window.clearTimeout(timer);
      const video = previewRef.current;
      video?.pause();
      video?.removeAttribute('src');
      video?.load();
      setPreviewStarted(false);
      setPreviewReady(false);
    };
  }, [active, inViewport, playbackUrl, previewing]);
  useEffect(() => {
    const video = previewRef.current;
    if (!video || !previewStarted) return;
    video.muted = true;
    video.playsInline = true;
    void video.play().catch(() => {});
  }, [previewStarted]);
  return <div className="recording-card-thumb" ref={rootRef}>
    {data && !liveRecording ? <img src={data} alt={`Primer fotograma de ${title}`} loading="lazy" decoding="async"/> : <div className={`recording-thumb-placeholder ${liveRecording ? 'recording-live-preview' : ''}`}><span>{liveRecording ? '●' : '▶'}</span><small>{liveRecording ? 'Captura en curso' : state === 'deferred' ? 'Miniatura pendiente' : state === 'unavailable' ? 'Vista previa no disponible' : 'Preparando vista previa'}</small></div>}
    {previewStarted && playbackUrl && <video ref={previewRef} className={`recording-hover-preview ${previewReady ? 'ready' : ''}`} src={playbackUrl} muted playsInline preload="metadata" onCanPlay={() => { setPreviewReady(true); void previewRef.current?.play().catch(() => {}); }} onEnded={() => { if (previewRef.current) previewRef.current.currentTime = 0; void previewRef.current?.play().catch(() => {}); }}/ >}
    <span className="recording-card-overlay">{playedAt && <small>{playedAt}</small>}<b>{duration || 'Duración no disponible'}</b></span>
  </div>;
}

export function RecordingsPage({ active, backendReady, onOpenSettings }: { active: boolean; backendReady: boolean; onOpenSettings: () => void }) {
  const [rows, setRows] = useState<RecordingEntry[]>([]);
  const [status, setStatus] = useState<RecordingStatus>(inactive);
  const [champions, setChampions] = useState<Champion[]>([]);
  const [championIcons, setChampionIcons] = useState<Record<string, string | null>>({});
  const [selected, setSelected] = useState('');
  const [playerOpen, setPlayerOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [libraryState, setLibraryState] = useState<LibraryState>('idle');
  const [backendDisconnected, setBackendDisconnected] = useState(false);
  const [error, setError] = useState('');
  const [query, setQuery] = useState('');
  const [championFilter, setChampionFilter] = useState('');
  const [positionFilter, setPositionFilter] = useState('all');
  const [dateFilter, setDateFilter] = useState('any');
  const [customDate, setCustomDate] = useState('');
  const [deleteName, setDeleteName] = useState('');
  const [busy, setBusy] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [playbackStatus, setPlaybackStatus] = useState<PlaybackStatus>('idle');
  const [playing, setPlaying] = useState(false);
  const [volume, setVolume] = useState(1);
  const [rate, setRate] = useState(1);
  const [muted, setMuted] = useState(false);
  const [thumbnailRetryKey, setThumbnailRetryKey] = useState(0);
  const [hoveredPreview, setHoveredPreview] = useState('');
  const videoRef = useRef<HTMLVideoElement>(null);
  const selectedRef = useRef(selected); selectedRef.current = selected;
  const statusRef = useRef(status); statusRef.current = status;
  const selectedRow = rows.find((row) => row.id === selected) ?? null;

  const refresh = useCallback(async (showLoading = false) => {
    if (!backendReady) { setBackendDisconnected(true); return; }
    if (showLoading) { setLoading(true); setLibraryState('loading'); }
    try {
      const [recordings, nextStatus] = await Promise.all([
        window.solralol.request('recordings.list'), window.solralol.request('recordings.status'),
      ]);
      setRows(recordings); setStatus(nextStatus);
      setSelected((old) => recordings.some((row) => row.id === old) ? old : '');
      setThumbnailRetryKey((value) => value + 1);
      setLibraryState('loaded'); setBackendDisconnected(false); setError('');
    } catch (e) {
      const message = (e as Error).message || '';
      setLibraryState('error');
      if (/backend unavailable|backend request timed out|backend desconectado/i.test(message)) setBackendDisconnected(true);
      setError(/carpeta de grabaciones/i.test(message) ? message : 'No se pudo actualizar la biblioteca. La lista anterior se conserva; inténtalo de nuevo.');
    } finally { if (showLoading) setLoading(false); }
  }, [backendReady]);

  useEffect(() => { if (active) void refresh(true); }, [active, refresh]);
  useEffect(() => {
    if (!active || !backendReady) return;
    let disposed = false;
    const timer = window.setInterval(() => {
      window.solralol.request('recordings.status').then((next) => {
        if (disposed) return;
        const prior = statusRef.current.state;
        const priorName = statusRef.current.recordingName;
        setStatus(next); setBackendDisconnected(false);
        if (next.recordingName !== priorName) void refresh(false);
        if (next.state === 'completed' && prior !== 'completed') { void refresh(false); setThumbnailRetryKey((value) => value + 1); }
      }).catch(() => { if (!disposed) { setBackendDisconnected(true); setError('El backend local se ha desconectado. Se conserva la biblioteca ya cargada.'); } });
    }, 2500);
    return () => { disposed = true; window.clearInterval(timer); };
  }, [active, backendReady, refresh]);
  useEffect(() => {
    if (!active) return;
    let disposed = false;
    void window.solralol.request('champions.list').then((value) => { if (!disposed) setChampions(value); }).catch(() => {});
    return () => { disposed = true; };
  }, [active]);
  useEffect(() => {
    if (!active || !rows.length) return;
    const names = [...new Set(rows.flatMap((row) => [row.champion, row.opponent_champion].filter((name): name is string => Boolean(name))))];
    let disposed = false;
    const batches = Array.from({ length: Math.ceil(names.length / 20) }, (_, index) => names.slice(index * 20, index * 20 + 20));
    void Promise.all(batches.map((batch) => requestHomeAssets('home.assets', { champions: batch }))).then((assets) => {
      if (!disposed) setChampionIcons((current) => Object.assign({}, current, ...assets.map((item) => item.champions)));
    }).catch(() => {});
    return () => { disposed = true; };
  }, [active, rows]);
  useEffect(() => { if (!active && videoRef.current) videoRef.current.pause(); }, [active]);
  useEffect(() => {
    setPlaybackStatus('idle'); setCurrentTime(0); setDuration(0); setPlaying(false);
  }, [selected]);
  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    video.volume = volume; video.playbackRate = rate; video.muted = muted;
  }, [volume, rate, muted, selected, playerOpen]);

  const visibleRows = useMemo(() => {
    const now = new Date();
    const today = localDay(now.getTime() / 1000);
    const yesterdayDate = new Date(); yesterdayDate.setDate(now.getDate() - 1);
    const yesterday = localDay(yesterdayDate.getTime() / 1000);
    const selectedChampion = champions.find((item) => item.id === championFilter);
    const cutoff = dateFilter === '7' ? new Date(now.getFullYear(), now.getMonth(), now.getDate() - 6).getTime() / 1000 : 0;
    return rows.filter((row) => {
      const searchFields = `${row.title} ${row.champion} ${row.opponent_champion ?? ''} ${row.game_mode} ${row.date_label}`.toLocaleLowerCase('es');
      const day = recordingDay(row);
      const dateMatches = dateFilter === 'any' || dateFilter === 'today' && day === today || dateFilter === 'yesterday' && day === yesterday
        || dateFilter === '7' && !!row.created_at && row.created_at >= cutoff
        || dateFilter === 'custom' && day === customDate;
      return searchFields.includes(query.trim().toLocaleLowerCase('es'))
        && (!championFilter || [championFilter, selectedChampion?.name ?? ''].some((name) => name && row.champion.toLocaleLowerCase('es') === name.toLocaleLowerCase('es')))
        && (positionFilter === 'all' || positionKey(row.position ?? '') === positionFilter)
        && dateMatches;
    }).sort((a, b) => b.created_at - a.created_at || a.name.localeCompare(b.name));
  }, [rows, query, championFilter, champions, positionFilter, dateFilter, customDate]);
  const groups = useMemo(() => {
    const grouped = new Map<string, RecordingEntry[]>();
    for (const row of visibleRows) { const day = recordingDay(row); grouped.set(day, [...(grouped.get(day) ?? []), row]); }
    return [...grouped.entries()].sort(([a], [b]) => !a ? 1 : !b ? -1 : b.localeCompare(a));
  }, [visibleRows]);
  const totalBytes = useMemo(() => rows.reduce((sum, row) => sum + (row.size_bytes || 0), 0), [rows]);
  const filtersActive = !!(query || championFilter || positionFilter !== 'all' || dateFilter !== 'any');

  const startStop = async () => {
    setBusy(true); setError('');
    try {
      const recording = ['recording', 'preparing', 'stopping', 'finalizing'].includes(status.state);
      setStatus(await window.solralol.request(recording ? 'recordings.stop' : 'recordings.start'));
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };
  const remove = async () => {
    if (!deleteName) return;
    setBusy(true);
    try {
      if (selectedRow?.name === deleteName) { videoRef.current?.pause(); videoRef.current?.removeAttribute('src'); videoRef.current?.load(); setPlayerOpen(false); setSelected(''); }
      const result = await window.solralol.request('recordings.delete', { name: deleteName });
      if (!result.deleted) throw new Error(result.message);
      setDeleteName(''); await refresh(false);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };
  const togglePlayback = () => {
    const video = videoRef.current;
    if (!video || !playerOpen) return;
    if (video.paused) void video.play().catch((e) => {
      console.error('[Grabaciones] No se pudo iniciar la reproducción', { recordingId: selected, message: (e as Error).message });
      setError('No se pudo iniciar la reproducción. Vuelve a seleccionar el vídeo para reintentar.');
    }); else video.pause();
  };
  const seekBy = (amount: number) => { const video = videoRef.current; if (video && Number.isFinite(video.duration)) video.currentTime = Math.max(0, Math.min(video.duration, video.currentTime + amount)); };
  const fullscreen = () => { const video = videoRef.current; if (!video) return; if (document.fullscreenElement) void document.exitFullscreen(); else void video.requestFullscreen(); };
  const clearFilters = () => { setQuery(''); setChampionFilter(''); setPositionFilter('all'); setDateFilter('any'); setCustomDate(''); };

  useEffect(() => {
    if (!active || !playerOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target?.closest('input,select,textarea,button,[contenteditable="true"]')) return;
      if (event.code === 'Space' && selectedRow) { event.preventDefault(); togglePlayback(); }
      else if (event.key === 'ArrowLeft') seekBy(-10);
      else if (event.key === 'ArrowRight') seekBy(10);
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [active, playerOpen, selectedRow]);

  return <div className="recordings-page">
    <div className="recordings-toolbar">
      <div className="recordings-title"><span className="eyebrow">BIBLIOTECA LOCAL · CAPTURA DXGI</span><h1>Grabaciones</h1></div>
      <div className="recordings-summary"><b>{rows.length}</b> {rows.length === 1 ? 'grabación' : 'grabaciones'} <span>·</span> {formatBytes(totalBytes)} ocupados</div>
      <div className={`recording-state ${status.state}`}><i/><span>{status.state === 'recording' ? `Grabando · ${formatTime(status.elapsedSeconds)}` : status.state === 'preparing' ? 'Preparando captura' : status.state === 'stopping' || status.state === 'finalizing' ? 'Finalizando vídeo' : status.state === 'failed' ? 'Error de grabación' : status.state === 'completed' ? 'Última grabación finalizada' : 'En espera'}</span><button className={status.state === 'recording' ? 'stop' : ''} disabled={busy || ['preparing','stopping','finalizing'].includes(status.state)} onClick={() => void startStop()}>{status.state === 'recording' ? 'Detener' : 'Grabar ahora'}</button></div>
    </div>
    {status.message && <div className="recording-info">{status.state === 'failed' && status.error ? status.error : status.message}{status.state !== 'failed' && status.error && <span> &middot; {status.error}</span>}</div>}
    {error && <div className="recording-error" role="alert">{error}<button onClick={() => setError('')} aria-label="Cerrar error">×</button></div>}
    {!backendReady && <div className="recording-empty"><strong>Backend local desconectado</strong><span>La biblioteca volverá a estar disponible cuando se conecte el backend.</span></div>}
    {backendReady && <>
      <section className="recording-gallery panel" hidden={playerOpen} aria-label="Biblioteca de grabaciones">
        <div className="recording-gallery-tools">
          <label className="recording-query"><span>⌕</span><input aria-label="Buscar en grabaciones" placeholder="Buscar por campeón o modo" value={query} onChange={(event) => setQuery(event.target.value)}/></label>
          <div className="recording-champion-filter"><ChampionSelector label="Campeón" placeholder="Todos los campeones" champions={champions} value={championFilter} getIcon={(id) => championIcons[id] ?? undefined} onChange={setChampionFilter} onOpen={(ids) => { const missing = ids.filter((id) => !(id in championIcons)); if (missing.length) void requestHomeAssets('home.assets', { champions: missing.slice(0, 20) }).then((assets) => setChampionIcons((current) => ({ ...current, ...assets.champions }))).catch(() => {}); }}/></div>
          <div className="recording-position-filter" role="group" aria-label="Filtrar por posición">{[['all','Todas'],['top','Top'],['jungle','Jungla'],['mid','Medio'],['adc','Bot'],['support','Apoyo']].map(([id,label]) => <button key={id} className={positionFilter === id ? 'selected' : ''} onClick={() => setPositionFilter(id)}>{label}</button>)}</div>
          <select className="recording-date-filter" aria-label="Filtrar por fecha" value={dateFilter} onChange={(event) => setDateFilter(event.target.value)}><option value="any">Todas las fechas</option><option value="today">Hoy</option><option value="yesterday">Ayer</option><option value="7">Últimos 7 días</option><option value="custom">Fecha concreta</option></select>
          {dateFilter === 'custom' && <input className="recording-date-input" type="date" aria-label="Elegir fecha" value={customDate} onChange={(event) => setCustomDate(event.target.value)}/>}
          <span className="recording-result-count">{visibleRows.length} {visibleRows.length === 1 ? 'resultado' : 'resultados'}</span>
          {filtersActive && <button className="recording-clear-filters" onClick={clearFilters}>Limpiar filtros</button>}
          <div className="recording-library-actions"><button onClick={() => void refresh(true)} disabled={loading}>{loading ? 'Actualizando…' : 'Actualizar'}</button><button onClick={() => void window.solralol.openRecordingsDirectory().then((message) => message && setError(message)).catch((e:Error)=>setError(e.message))}>Abrir carpeta</button><button onClick={onOpenSettings}>Ajustes</button></div>
        </div>
        {loading && libraryState === 'loading' && <div className="recording-gallery-loading">Cargando biblioteca…</div>}
        {!loading && !visibleRows.length && <div className="recording-empty"><strong>{libraryState === 'error' || backendDisconnected ? 'No se pudo confirmar la biblioteca' : rows.length ? 'Sin coincidencias' : 'Todavía no hay grabaciones'}</strong><span>{rows.length ? 'Prueba con otros filtros.' : 'Las partidas guardadas aparecerán aquí.'}</span>{libraryState === 'error' && <button className="secondary-button" onClick={() => void refresh(true)}>Reintentar</button>}{!rows.length && libraryState === 'loaded' && <button className="secondary-button" onClick={onOpenSettings}>Configurar grabaciones</button>}</div>}
        <div className="recording-day-groups">{groups.map(([day, items]) => <section className="recording-day-group" key={day || 'unknown'}><h2>{dayHeading(day)} <small>· {items.length} {items.length === 1 ? 'partida' : 'partidas'}</small></h2><div className="recording-card-grid">{items.map((row) => {
          const kda = row.kda ?? row.saved_match?.kda;
          const liveState = ['preparing','recording','stopping','finalizing'].includes(status.state);
          const isLiveRecording = row.active === true || (row.name === status.recordingName && liveState);
          const champion = isLiveRecording ? status.currentChampion || row.champion : row.champion;
          const gameMode = isLiveRecording ? status.currentGameMode || row.game_mode : row.game_mode;
          const role = isLiveRecording ? status.currentRole || row.position || '' : row.position || '';
          const liveDuration = isLiveRecording ? formatTime(status.elapsedSeconds) : row.duration_label;
          const liveSize = isLiveRecording && status.fileSizeBytes !== undefined ? formatBytes(status.fileSizeBytes) : row.size_label;
          const position = role ? positionLabels[positionKey(role)] ?? role : '';
          const playedAt = row.created_at ? new Date(row.created_at * 1000).toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' }) : '';
          return <article className={`recording-card ${isLiveRecording ? 'recording-card-live' : ''} ${hoveredPreview === row.id ? 'previewing' : ''}`} key={row.id || row.name} onMouseEnter={() => setHoveredPreview(row.id)} onMouseLeave={() => setHoveredPreview((current) => current === row.id ? '' : current)}>
            <button className="recording-card-open" disabled={!row.available || isLiveRecording} onClick={() => { void window.solralol.openRecordingReview(row.id).then((opened) => { if (!opened) setError('No se pudo abrir el repaso de esta grabación. Actualiza la biblioteca y vuelve a intentarlo.'); }).catch((e: Error) => setError(e.message)); }} aria-label={`Abrir repaso de ${row.title}`}>
              <RecordingThumbnail id={row.id} title={row.title} playedAt={playedAt} duration={liveDuration} playbackUrl={row.playbackUrl} retryKey={thumbnailRetryKey} active={active && !playerOpen} previewing={hoveredPreview === row.id && !isLiveRecording} liveRecording={isLiveRecording}/>
              <span className="recording-card-copy"><span className="recording-card-titleline"><GameImage src={championIcons[champion]} alt={champion || 'Campeón no disponible'} fallback={champion ? champion.slice(0,1) : '?'} className="recording-champion-portrait"/><b>{row.title}</b></span>
                <span className="recording-card-match">{row.opponent_champion ? <><GameImage src={championIcons[row.opponent_champion]} alt={row.opponent_champion} fallback={row.opponent_champion.slice(0,1)} className="recording-opponent-portrait"/><span>Contra {row.opponent_champion}{row.opponent_position ? ` · ${positionLabels[positionKey(row.opponent_position)] ?? row.opponent_position}` : ''}</span></> : <span className="recording-missing">Rival no disponible</span>}</span>
                <span className="recording-card-meta"><span>{position || 'Posición no disponible'}</span><span>{kda ? `${kda.join(' / ')} KDA` : 'KDA no disponible'}</span><span>{gameMode || 'Modo no disponible'}</span></span>
              </span>
            </button>
            <div className="recording-card-management"><span className={`recording-validity ${isLiveRecording ? 'recording-live-badge' : row.complete ? 'valid' : ''}`}>{isLiveRecording ? <><i/> {status.state === 'preparing' ? 'Preparando' : status.state === 'finalizing' || status.state === 'stopping' ? 'Finalizando' : 'Grabando ahora'}</> : row.complete ? 'Finalizada' : 'Incompleta'} · {liveDuration} · {liveSize}</span><button className="recording-delete" disabled={isLiveRecording} onClick={() => setDeleteName(row.name)} aria-label={`Eliminar ${row.title}`} title={isLiveRecording ? 'No se puede eliminar mientras graba' : 'Eliminar grabación'}>×</button></div>
          </article>;
        })}</div></section>)}</div>
      </section>
      <section className="recording-playback-view panel" hidden={!playerOpen} aria-label="Reproductor de grabaciones">
        <div className="recording-playback-heading"><button className="recording-back-button" onClick={() => { videoRef.current?.pause(); setPlayerOpen(false); }}>← Volver a la biblioteca</button><div><span className="eyebrow">REPRODUCCIÓN LOCAL</span><h2>{selectedRow?.title ?? 'Grabación'}</h2><p>{selectedRow ? `${selectedRow.date_label} · ${selectedRow.game_mode || 'Modo no disponible'} · ${selectedRow.position ? positionLabels[positionKey(selectedRow.position)] ?? selectedRow.position : 'Posición no disponible'}` : ''}</p></div><button className="recording-delete" onClick={() => selectedRow && setDeleteName(selectedRow.name)} disabled={!selectedRow} aria-label="Eliminar grabación">×</button></div>
        <div className="recording-video-wrap">{playerOpen && selectedRow?.playbackUrl ? <video key={selectedRow.id} ref={videoRef} src={selectedRow.playbackUrl} preload="metadata" playsInline onLoadStart={()=>setPlaybackStatus('loading')} onPlay={()=>setPlaying(true)} onPause={()=>setPlaying(false)} onTimeUpdate={(event)=>setCurrentTime(event.currentTarget.currentTime)} onLoadedMetadata={(event)=>{setDuration(event.currentTarget.duration);setCurrentTime(event.currentTarget.currentTime)}} onCanPlay={()=>setPlaybackStatus('ready')} onDurationChange={(event)=>setDuration(event.currentTarget.duration)} onError={(event)=>{const video=event.currentTarget;const code=video.error?.code;console.error('[Grabaciones] Error de reproducción',{recordingId:selected,mediaErrorCode:code,mediaErrorMessage:video.error?.message});setPlaybackStatus('error');setError(code===MediaError.MEDIA_ERR_DECODE?'Chromium no pudo decodificar el vídeo.':code===MediaError.MEDIA_ERR_SRC_NOT_SUPPORTED?'Formato no compatible o MP4 incompleto.':'No se pudo abrir la grabación. Comprueba que el archivo siga disponible.');}} onClick={togglePlayback}/> : <div className="recording-video-empty"><span>▶</span><b>Selecciona una grabación disponible</b></div>}</div>
        <div className="recording-player-info"><div><span className="eyebrow">DATOS DE PARTIDA</span><p>{selectedRow?.champion || 'Campeón no disponible'} · {selectedRow?.opponent_champion ? `Contra ${selectedRow.opponent_champion}` : 'Rival no disponible'} · {selectedRow?.position ? positionLabels[positionKey(selectedRow.position)] ?? selectedRow.position : 'Posición no disponible'} · {selectedRow?.game_mode || 'Modo no disponible'}{selectedRow?.kda ? ` · ${selectedRow.kda.join(' / ')}` : ''}</p></div><span className={`recording-validity ${playbackStatus === 'ready' ? 'valid' : ''}`}>{playbackStatus === 'ready' ? 'Reproducción disponible' : playbackStatus === 'loading' ? 'Abriendo archivo…' : playbackStatus === 'error' ? 'Error de reproducción' : 'Reproductor local'}</span></div>
        <div className="recording-timeline"><span>{formatTime(currentTime)}</span><input aria-label="Posición de reproducción" type="range" min="0" max={duration || 0} step="0.1" value={Math.min(currentTime,duration || currentTime)} onChange={(event)=>{const video=videoRef.current;if(video)video.currentTime=Number(event.target.value)}} disabled={!duration}/><span>{formatTime(duration)}</span></div>
        <div className="recording-controls"><button onClick={()=>seekBy(-10)} disabled={!selectedRow} title="Retroceder 10 segundos">−10</button><button className="recording-play" onClick={togglePlayback} disabled={!selectedRow} aria-label="Reproducir o pausar">{playing ? 'Ⅱ' : '▶'}</button><button onClick={()=>seekBy(10)} disabled={!selectedRow} title="Avanzar 10 segundos">+10</button><button onClick={()=>setMuted((value)=>!value)} disabled={!selectedRow} title={muted?'Activar sonido':'Silenciar'} aria-label={muted?'Activar sonido':'Silenciar'}>{muted?'Silenciado':'Sonido'}</button><label className="recording-volume">Volumen<input aria-label="Volumen" type="range" min="0" max="1" step="0.05" value={volume} onChange={(event)=>setVolume(Number(event.target.value))}/></label><select aria-label="Velocidad de reproducción" value={rate} onChange={(event)=>setRate(Number(event.target.value))}><option value="0.5">0,5×</option><option value="0.75">0,75×</option><option value="1">1×</option><option value="1.25">1,25×</option><option value="1.5">1,5×</option><option value="2">2×</option></select><button onClick={fullscreen} disabled={!selectedRow} title="Pantalla completa">⛶</button></div>
        {selectedRow && (selectedRow.markers?.length ?? 0) > 0 && <div className="recording-markers"><span className="eyebrow">MOMENTOS DE LA PARTIDA</span><div>{(selectedRow.markers ?? []).slice(0,80).map((marker,index)=><button key={`${marker.time}-${index}`} title={marker.detail || marker.label || 'Evento'} onClick={()=>{const video=videoRef.current;if(video)video.currentTime=marker.time}}>{formatTime(marker.time)} · {marker.label || marker.kind || 'Evento'}</button>)}</div></div>}
      </section>
    </>}
    {deleteName && <div className="recording-confirm-backdrop" role="presentation" onMouseDown={(event)=>{if(event.target===event.currentTarget)setDeleteName('')}}><div className="recording-confirm" role="dialog" aria-modal="true" aria-labelledby="recording-delete-title"><span className="eyebrow">ELIMINAR ARCHIVO</span><h2 id="recording-delete-title">¿Eliminar esta grabación?</h2><p>Se eliminarán el vídeo, sus metadatos y la miniatura asociada.</p><div><button className="secondary-button" disabled={busy} onClick={()=>setDeleteName('')}>Cancelar</button><button className="recording-confirm-delete" disabled={busy} onClick={()=>void remove()}>{busy?'Eliminando…':'Eliminar grabación'}</button></div></div></div>}
  </div>;
}
