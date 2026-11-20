import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { GameImage } from '../components/GameImage';
import { ConfirmModal } from '../components/ConfirmModal';
import type { DeletionManifest, HomeAssets, SavedMatchDetail, SavedMatchesList, SavedMatchSummary, SoloQAnalysisDetail, SoloQAnalysisList, SoloQAnalysisSummary } from '../types/contracts';
import { SoloQAnalysisCenter } from './SoloQAnalysisCenter';
import './SavedMatchesPage.css';

type Props = { active: boolean; backendReady: boolean; initialMatchId?: string; onInitialMatchOpened?: () => void };
type PendingDelete = { kind: 'legacy'; match: SavedMatchSummary } | { kind: 'soloq'; match: SoloQAnalysisSummary };
const roleNames: Record<string, string> = { TOP: 'Top', JUNGLE: 'Jungla', MIDDLE: 'Medio', BOTTOM: 'Bot', UTILITY: 'Apoyo' };
const fmtDuration = (value?: number) => { const n = Number(value); return Number.isFinite(n) && n > 0 ? `${Math.floor(n / 60)}:${String(Math.floor(n % 60)).padStart(2, '0')}` : 'Duración no disponible'; };
const fmtDate = (value?: string) => { const date = new Date(value ?? ''); return Number.isNaN(date.valueOf()) ? 'Fecha no disponible' : new Intl.DateTimeFormat('es-ES', { dateStyle: 'medium', timeStyle: 'short' }).format(date); };

export function SavedMatchesPage({ active, backendReady, initialMatchId, onInitialMatchOpened }: Props) {
  const [data, setData] = useState<SavedMatchesList>();
  const [selectedId, setSelectedId] = useState('');
  const [detail, setDetail] = useState<SavedMatchDetail>();
  const [loading, setLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState('');
  const [assets, setAssets] = useState<HomeAssets>();
  const [itemAssets, setItemAssets] = useState<Record<string, string | null>>({});
  const [sort, setSort] = useState<'recent' | 'oldest'>('recent');
  const [resultFilter, setResultFilter] = useState<'all' | 'win' | 'loss'>('all');
  const [championFilter, setChampionFilter] = useState('all');
  const [modeFilter, setModeFilter] = useState('all');
  const [soloqData, setSoloqData] = useState<SoloQAnalysisList>();
  const [soloqDetail, setSoloqDetail] = useState<SoloQAnalysisDetail>();
  const [soloqLoading, setSoloqLoading] = useState(false);
  const [soloqError, setSoloqError] = useState('');
  const [pendingDelete, setPendingDelete] = useState<PendingDelete>();
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState('');
  const [deleteManifest, setDeleteManifest] = useState<DeletionManifest>();
  const [previewLoading, setPreviewLoading] = useState(false);
  const previewSequence = useRef(0);
  const initialOpened = useRef('');
  const selectedIdRef = useRef(selectedId);
  selectedIdRef.current = selectedId;

  const refresh = useCallback(async () => {
    if (!backendReady) return;
    setError('');
    try {
      const next = await window.solralol.request('saved_matches.list');
      setData(next);
      if (selectedIdRef.current && !next.matches.some(match => match.id === selectedIdRef.current)) { setSelectedId(''); setDetail(undefined); }
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'No se pudieron leer las partidas guardadas.'); }
  }, [backendReady]);
  useEffect(() => { if (active && backendReady) void refresh(); }, [active, backendReady, refresh]);
  const refreshSoloq = useCallback(async () => {
    if (!backendReady) return;
    try { setSoloqData(await window.solralol.request('soloq_analyses.list')); setSoloqError(''); }
    catch (cause) { setSoloqError(cause instanceof Error ? cause.message : 'No se pudo cargar el espacio de análisis SoloQ.'); }
  }, [backendReady]);
  useEffect(() => { if (active && backendReady) void refreshSoloq(); }, [active, backendReady, refreshSoloq]);
  useEffect(() => {
    if (!active || !soloqData?.matches.some(match => ['pending', 'downloading', 'processing'].includes(match.status))) return;
    const timer = window.setTimeout(() => void refreshSoloq(), 2200);
    return () => window.clearTimeout(timer);
  }, [active, soloqData, refreshSoloq]);
  useEffect(() => {
    if (!active || !backendReady || !initialMatchId || initialOpened.current === initialMatchId) return;
    const riotMatch = soloqData?.matches.find(item => item.id === initialMatchId);
    if (riotMatch) {
      initialOpened.current = initialMatchId;
      setSoloqLoading(true);
      window.solralol.request('soloq_analyses.detail', { matchId: initialMatchId }).then(setSoloqDetail).catch(cause => setSoloqError(cause instanceof Error ? cause.message : 'No se pudo abrir el análisis.')).finally(() => setSoloqLoading(false));
      onInitialMatchOpened?.();
      return;
    }
    const match = data?.matches.find(item => item.id === initialMatchId);
    if (match) { initialOpened.current = initialMatchId; void open(match); onInitialMatchOpened?.(); }
  }, [active, backendReady, initialMatchId, data?.matches, soloqData?.matches]);
  const sorted = useMemo(() => [...(data?.matches ?? [])].filter(match => (resultFilter === 'all' || (resultFilter === 'win' ? match.win === true : match.win === false)) && (championFilter === 'all' || match.champion === championFilter) && (modeFilter === 'all' || match.mode === modeFilter)).sort((a, b) => (Date.parse(a.startedAt) - Date.parse(b.startedAt)) * (sort === 'recent' ? -1 : 1)), [data?.matches, resultFilter, sort, championFilter, modeFilter]);
  const champKeys = useMemo(() => [...new Set([...(data?.matches ?? []).map(match => match.champion), ...(detail?.participants ?? []).map(player => player.champion), ...(soloqData?.matches ?? []).map(match => match.champion ?? ''), ...(soloqDetail?.participants ?? []).map(player => player.champion)].filter(Boolean))].slice(0, 20), [data?.matches, detail?.participants, soloqData?.matches, soloqDetail?.participants]);
  useEffect(() => {
    if (!backendReady || !champKeys.length) { setAssets(undefined); return; }
    let current = true;
    window.solralol.request('home.assets', { champions: champKeys }).then(next => { if (current) setAssets(next); }).catch(() => { if (current) setAssets(undefined); });
    return () => { current = false; };
  }, [backendReady, champKeys.join('|')]);
  const itemIds = useMemo(() => [...new Set([...(detail?.participants ?? []).flatMap(player => player.items ?? []), ...(soloqDetail?.participants ?? []).flatMap(player => player.items ?? [])].map(String))].filter(id => /^\d{1,8}$/.test(id) && Number(id) > 0).slice(0, 70), [detail?.participants, soloqDetail?.participants]);
  useEffect(() => {
    if (!backendReady || !itemIds.length) { setItemAssets({}); return; }
    let current = true;
    const batches: string[][] = [];
    for (let index = 0; index < itemIds.length; index += 20) batches.push(itemIds.slice(index, index + 20));
    for (const items of batches) void window.solralol.request('meta.assets', { items })
      .then(result => { if (current) setItemAssets(previous => ({ ...previous, ...result })); })
      .catch(() => undefined);
    return () => { current = false; };
  }, [backendReady, itemIds.join('|')]);
  const open = async (match: SavedMatchSummary) => {
    setSelectedId(match.id); setLoading(true); setError('');
    try { setDetail(await window.solralol.request('saved_matches.detail', { id: match.id })); }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'No se pudieron cargar los detalles.'); }
    finally { setLoading(false); }
  };
  const openSoloq = async (match: SoloQAnalysisSummary) => {
    setSoloqLoading(true); setSoloqError(''); setSoloqDetail(undefined);
    try {
      const next = await window.solralol.request('soloq_analyses.detail', { matchId: match.id });
      setSoloqDetail(next);
      const localScore = next.participants.find(player => player.local)?.battleScore ?? null;
      setSoloqData(current => current ? { ...current, matches: current.matches.map(item => item.id === next.id ? { ...item, battleScore: localScore, battleScoreVersion: localScore == null ? null : next.battle_score?.version ?? null } : item) } : current);
    }
    catch (cause) { setSoloqError(cause instanceof Error ? cause.message : 'No se pudieron cargar los datos de Riot.'); }
    finally { setSoloqLoading(false); }
  };
  const removeSoloq = async (match: SoloQAnalysisSummary) => { await openDeletePreview({ kind: 'soloq', match }); };
  const retrySoloq = async (match: SoloQAnalysisDetail) => {
    try {
      const next = await window.solralol.request('soloq_analyses.register', { matchId: match.history_match_id ?? match.id });
      setSoloqDetail(current => current ? { ...current, status: next.status, status_message: next.status_message } : current);
      await refreshSoloq();
    } catch (cause) { setSoloqError(cause instanceof Error ? cause.message : 'No se pudo reintentar la descarga.'); }
  };
  const remove = async (match: SavedMatchSummary) => { await openDeletePreview({ kind: 'legacy', match }); };
  const openDeletePreview = async (target: PendingDelete) => {
    const sequence = ++previewSequence.current;
    setPendingDelete(target); setDeleteManifest(undefined); setDeleteError(''); setPreviewLoading(true);
    try {
      const manifest = target.kind === 'soloq'
        ? await window.solralol.request('soloq_analyses.delete.preview', { matchId: target.match.id })
        : await window.solralol.request('saved_matches.delete.preview', { id: target.match.id });
      if (previewSequence.current === sequence) setDeleteManifest(manifest);
    } catch (cause) { if (previewSequence.current === sequence) setDeleteError(cause instanceof Error ? cause.message : 'No se pudo calcular el inventario.'); }
    finally { if (previewSequence.current === sequence) setPreviewLoading(false); }
  };
  const confirmDelete = async () => {
    if (!pendingDelete || deleteBusy) return;
    setDeleteBusy(true); setDeleteError('');
    try {
      if (pendingDelete.kind === 'soloq') {
        if (!deleteManifest) throw new Error('Calcula de nuevo la vista previa antes de eliminar.');
        await window.solralol.request('soloq_analyses.delete', { matchId: pendingDelete.match.id, manifestId: deleteManifest.manifestId });
        setSoloqData(current => current ? { ...current, matches: current.matches.filter(item => item.id !== pendingDelete.match.id), count: Math.max(0, current.count - 1), analysisCount: Math.max(0, current.analysisCount - 1) } : current);
        if (soloqDetail?.id === pendingDelete.match.id) setSoloqDetail(undefined);
        await refreshSoloq();
      } else {
        if (!deleteManifest) throw new Error('Calcula de nuevo la vista previa antes de eliminar.');
        await window.solralol.request('saved_matches.delete', { id: pendingDelete.match.id, manifestId: deleteManifest.manifestId });
        setData(current => current ? { ...current, matches: current.matches.filter(item => item.id !== pendingDelete.match.id), count: Math.max(0, current.count - 1) } : current);
        if (selectedIdRef.current === pendingDelete.match.id) { setSelectedId(''); setDetail(undefined); }
        await refresh();
      }
      setPendingDelete(undefined);
    } catch (cause) { setDeleteError(cause instanceof Error ? cause.message : 'No se pudo completar la eliminación.'); }
    finally { setDeleteBusy(false); }
  };
  const analyze = async (force: boolean) => {
    if (!selectedId || generating) return;
    setGenerating(true); setError('');
    try { const next = await window.solralol.request('saved_matches.analysis.generate', { id: selectedId, force }); setDetail(next); await refresh(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'No se pudo generar el análisis.'); }
    finally { setGenerating(false); }
  };

  if (!active) return null;
  const detailAnalysis = detail?.analysis;
  const legacyRecord = detail?.matchAnalysis as Record<string, unknown> | null | undefined;
  const legacyAnalysis = legacyRecord?.analysis && typeof legacyRecord.analysis === 'object' ? legacyRecord.analysis as Record<string, unknown> : undefined;
  const insights = Array.isArray(detailAnalysis?.insights) ? detailAnalysis.insights : [];
  const summary = detailAnalysis?.summary ?? {};
  return <section className="saved-matches-page">
    <header className="saved-matches-header"><div><div className="eyebrow">BIBLIOTECA LOCAL · ANÁLISIS DE PARTIDAS</div><h1>Partidas guardadas</h1><p>Partidas completas registradas por Solralol al terminar la sesión.</p></div><div className="saved-match-capacity"><b>{data?.count ?? '—'} / {data?.limit ?? 10}</b><span>partidas guardadas</span><button type="button" onClick={() => void refresh()} disabled={!backendReady}>Actualizar</button></div></header>
    {!backendReady && <div className="saved-match-notice">Backend local desconectado. Se conservarán los datos cargados y se actualizarán al reconectar.</div>}
    {error && <div className="saved-match-error" role="alert">{error}<button onClick={() => setError('')}>Cerrar</button></div>}
    {data?.overLimit && <div className="saved-match-notice">El repositorio heredado contiene más de diez partidas. Se muestran todas y no se eliminará ninguna automáticamente.</div>}
    <SoloQAnalysisCenter list={soloqData} detail={soloqDetail} loading={soloqLoading} error={soloqError} assets={assets} itemAssets={itemAssets} onRefresh={() => void refreshSoloq()} onOpen={match => void openSoloq(match)} onUpdateDetail={setSoloqDetail} onRetry={match => void retrySoloq(match)} onDelete={match => removeSoloq(match)} />
    <div className={`saved-match-layout ${detail ? 'has-detail' : ''}`}>
      <div className="saved-match-library"><div className="saved-match-filters"><span>{data ? `${sorted.length} de ${data.count} partidas` : 'Cargando biblioteca'}</span><select aria-label="Filtrar campeón" value={championFilter} onChange={event => setChampionFilter(event.target.value)}><option value="all">Todos los campeones</option>{[...new Set((data?.matches ?? []).map(match => match.champion))].map(name => <option key={name} value={name}>{name}</option>)}</select><select aria-label="Filtrar modo" value={modeFilter} onChange={event => setModeFilter(event.target.value)}><option value="all">Todos los modos</option>{[...new Set((data?.matches ?? []).map(match => match.mode).filter(Boolean))].map(mode => <option key={mode} value={mode}>{mode}</option>)}</select><select aria-label="Filtrar resultado" value={resultFilter} onChange={event => setResultFilter(event.target.value as typeof resultFilter)}><option value="all">Todos los resultados</option><option value="win">Victorias</option><option value="loss">Derrotas</option></select><select aria-label="Ordenar partidas" value={sort} onChange={event => setSort(event.target.value as typeof sort)}><option value="recent">Más recientes</option><option value="oldest">Más antiguas</option></select></div>
        {!data && !error && <div className="saved-match-empty">{backendReady ? 'Cargando partidas guardadas…' : 'Conectando con el repositorio local…'}</div>}
        {data && sorted.length === 0 && <div className="saved-match-empty">{data.count ? 'No hay partidas con este filtro.' : 'Aún no hay partidas guardadas. Las partidas aparecerán aquí al terminar una sesión con Solralol abierto.'}</div>}
        <div className="saved-match-list">{sorted.map(match => <article key={match.id} className={`saved-match-card ${match.win === true ? 'victory' : match.win === false ? 'defeat' : ''} ${selectedId === match.id ? 'selected' : ''}`}>
          <button className="saved-match-select" type="button" onClick={() => void open(match)} aria-label={`Abrir partida de ${match.champion}`}>
            <GameImage src={assets?.champions[match.champion] ?? null} alt={match.champion} className="saved-match-champion" fallback={match.champion.slice(0, 1)} />
            <div className="saved-match-main"><div className="saved-match-title"><b>{match.champion}</b><strong>{match.win === true ? 'Victoria' : match.win === false ? 'Derrota' : 'Resultado no disponible'}</strong></div><span>{match.mode} · {roleNames[match.role.toUpperCase()] ?? 'Posición no disponible'} · {match.kills ?? '—'}/{match.deaths ?? '—'}/{match.assists ?? '—'}</span><small>{fmtDate(match.startedAt)} · {fmtDuration(match.duration)}</small><em>{match.analysisAvailable ? 'Análisis con IA disponible' : 'Sin análisis guardado'}</em></div>
          </button><button className="saved-match-delete" type="button" aria-label={`Eliminar partida de ${match.champion}`} onClick={() => void remove(match)}>×</button>
        </article>)}</div>
      </div>
      <aside className="saved-match-detail">
        {!selectedId && <div className="saved-match-empty">Selecciona una partida para ver sus estadísticas y análisis.</div>}
        {loading && <div className="saved-match-empty">Cargando detalles…</div>}
        {detail && !loading && <>
          <div className="saved-match-detail-head"><div><div className="eyebrow">DETALLE DE PARTIDA</div><h2>{detail.summary.champion}</h2><p>{detail.summary.mode} · {fmtDate(detail.summary.startedAt)} · {fmtDuration(detail.summary.duration)}</p></div><button aria-label="Cerrar detalle" onClick={() => { setDetail(undefined); setSelectedId(''); }}>×</button></div>
          <div className="saved-match-detail-stats"><div><small>RESULTADO</small><b>{detail.result === true ? 'Victoria' : detail.result === false ? 'Derrota' : 'No disponible'}</b></div><div><small>K / D / A</small><b>{detail.summary.kills ?? '—'} / {detail.summary.deaths ?? '—'} / {detail.summary.assists ?? '—'}</b></div><div><small>CS</small><b>{detail.summary.cs ?? '—'}</b></div></div>
          {detail.participants?.length > 0 ? <div className="saved-match-teams">{(['allied', 'enemy'] as const).map(side => <section key={side}><h3>{side === 'allied' ? 'Tu equipo' : 'Equipo rival'}</h3>{detail.participants.filter(item => item.side === side).map((item, index) => <div key={item.participantId ?? index} className={`saved-match-player ${item.local ? 'local' : ''}`}><GameImage src={assets?.champions[item.champion] ?? null} alt={item.champion} className="saved-match-player-icon" fallback={item.champion.slice(0, 1)} /><b>{item.champion}{item.local ? ' · Tú' : ''}</b><span>{item.kills ?? '—'}/{item.deaths ?? '—'}/{item.assists ?? '—'} · {item.cs ?? '—'} CS{item.gold != null ? ` · ${Math.round(item.gold).toLocaleString('es-ES')} oro` : ''}{item.vision != null ? ` · ${item.vision} visión` : ''}{item.championDamageDealt != null ? ` · ${Math.round(item.championDamageDealt).toLocaleString('es-ES')} daño a campeones` : ''}{item.championDamageReceivedCoverage === 'partial' ? ` · ${Math.round(item.championDamageReceived ?? 0).toLocaleString('es-ES')} daño recibido de campeones (parcial)` : ' · daño recibido de campeones no disponible'}</span>{item.runes && <small>Runas: {[item.runes.keystone, item.runes.primaryRuneTree, item.runes.secondaryRuneTree].filter(Boolean).map(String).join(' · ') || 'Datos disponibles'}</small>}{item.summonerSpells && <small>Hechizos: {Object.values(item.summonerSpells as Record<string, unknown>).map(String).join(' · ')}</small>}{Boolean(item.items?.length) && <div className="saved-match-items">{item.items?.filter(id => Number(id) > 0).map((id, itemIndex) => <GameImage key={`${id}-${itemIndex}`} src={itemAssets[`item:${id}`] ?? null} alt={`Objeto ${id}`} title={`Objeto ${id}`} className="saved-match-item-icon" fallback="·" />)}</div>}</div>)}</section>)}</div> : <p className="saved-match-empty">El registro local no conserva un marcador completo para esta partida.</p>}
          <section className="saved-match-analysis"><div className="saved-match-analysis-head"><h3>Análisis con IA</h3><button disabled={generating || !detail.available} onClick={() => void analyze(Boolean(legacyAnalysis))}>{generating ? 'Generando…' : legacyAnalysis ? 'Regenerar análisis' : 'Generar análisis'}</button></div>
            {legacyAnalysis ? <><p>{String((legacyAnalysis.summary as Record<string, unknown> | undefined)?.short_summary ?? (legacyAnalysis.summary as Record<string, unknown> | undefined)?.key_takeaway ?? 'Análisis generado a partir de los datos guardados de la partida.')}</p><div className="saved-match-insights">{Object.entries(legacyAnalysis).filter(([key, value]) => key !== 'summary' && value && (typeof value === 'object' || typeof value === 'string')).map(([key, value]) => <article key={key}><small>{key.replaceAll('_', ' ')}</small><div>{typeof value === 'string' ? value : Array.isArray(value) ? value.map(String).join(' · ') : Object.entries(value as Record<string, unknown>).map(([label, text]) => `${label.replaceAll('_', ' ')}: ${Array.isArray(text) ? text.join(' · ') : String(text ?? '')}`).join('\n')}</div></article>)}</div></> : detail.analysis ? <><p>{String(summary.overall_assessment ?? 'Informe generado a partir de la telemetría local de la partida.')}</p><div className="saved-match-insights">{insights.map((value, index) => { const insight = value as Record<string, unknown>; return <article key={String(insight.id ?? index)}><small>{String(insight.category ?? 'Revisión').replaceAll('_', ' ')}</small><b>{String(insight.title ?? 'Momento de partida')}</b><p>{String(insight.description ?? insight.what_happened ?? '')}</p>{typeof insight.learning === 'string' && <span>Aprendizaje: {insight.learning}</span>}</article>; })}</div></> : <p>{detail.available ? 'El análisis usa telemetría local; no analiza fotogramas del vídeo.' : 'No hay telemetría suficiente para generar un análisis de esta partida.'}</p>}
          </section>
        </>}
      </aside>
    </div>
    {pendingDelete && <ConfirmModal title="Eliminar partida guardada" description={'¿Eliminar esta partida guardada? También se eliminarán su grabación, los datos de Riot almacenados localmente y sus análisis guardados. Esta acción no se puede deshacer.'} manifest={deleteManifest} championImage={assets?.champions[pendingDelete.match.champion ?? ''] ?? null} loading={previewLoading} busy={deleteBusy} error={deleteError} onRetry={() => void openDeletePreview(pendingDelete)} onCancel={() => { if (!deleteBusy) { previewSequence.current++; setPendingDelete(undefined); setDeleteManifest(undefined); setDeleteError(''); } }} onConfirm={() => void confirmDelete()} />}
  </section>;
}
