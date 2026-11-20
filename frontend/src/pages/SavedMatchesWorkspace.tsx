import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { GameImage } from '../components/GameImage';
import { ConfirmModal } from '../components/ConfirmModal';
import { Icon } from '../components/Icon';
import type { DeletionManifest, HomeAssets, HomeMatch, RecordingEntry, RecordingReviewParticipant, SavedMatchDetail, SavedMatchSummary, SavedMatchesList } from '../types/contracts';
import { riotAnalysisActionLabel, riotAnalysisStatusLabel } from '../services/riotReadiness';
import type { RiotReadiness } from '../services/riotReadiness';
import './SavedMatchesPage.css';
import './SavedMatchesWorkspace.css';

const roleLabels: Record<string, string> = { TOP: 'Top', JUNGLE: 'Jungla', MIDDLE: 'Medio', BOTTOM: 'Bot', UTILITY: 'Apoyo' };
function participantRole(player: RecordingReviewParticipant): keyof typeof roleLabels | null {
  const value = String(player.role ?? '').normalize('NFKD').replace(/[\u0300-\u036f]/g, '').toUpperCase().replace(/[^A-Z]/g, '');
  if (['TOP', 'TOPLANE'].includes(value)) return 'TOP';
  if (['JUNGLE', 'JUNGLA', 'JG'].includes(value)) return 'JUNGLE';
  if (['MIDDLE', 'MID', 'MIDLANE', 'MEDIO'].includes(value)) return 'MIDDLE';
  if (['BOTTOM', 'BOT', 'ADC', 'DUOCARRY', 'BOTTOMLANE'].includes(value)) return 'BOTTOM';
  if (['UTILITY', 'SUPPORT', 'SUPP', 'APOYO', 'DUOSUPPORT'].includes(value)) return 'UTILITY';
  return null;
}
const statusLabels: Record<string, string> = { local_only: 'No analizada', pending: 'Pendiente de Riot', downloading: 'Descargando datos', processing: 'Procesando cronología', ready: 'Análisis disponible', partial: 'Datos parciales', error: 'Error de análisis' };
const openSettings = (section = 'cuenta') => window.dispatchEvent(new CustomEvent('solralol:open-settings', {detail:{section}}));
const championAsset = (assets: HomeAssets | undefined, name: string, id?: string | number | null) => {
  const championId = String(id ?? '');
  const canonicalId = assets?.championAliases?.[championId] ?? assets?.championAliases?.[name] ?? name;
  return assets?.champions[championId] ?? assets?.champions[canonicalId] ?? assets?.champions[name] ?? null;
};
const date = (value: string) => { const parsed = new Date(value); return Number.isNaN(parsed.valueOf()) ? 'Fecha no disponible' : new Intl.DateTimeFormat('es-ES', { dateStyle: 'medium', timeStyle: 'short' }).format(parsed); };
const duration = (value?: number) => Number.isFinite(value) && Number(value) > 0 ? `${Math.floor(Number(value) / 60)}:${String(Math.floor(Number(value) % 60)).padStart(2, '0')}` : 'Duración no disponible';

export function SavedMatchesWorkspace({ active, backendReady, initialMatchId, autoAnalyzeInitialMatch = false, onInitialMatchOpened, onAutoAnalysisOpened }: { active: boolean; backendReady: boolean; initialMatchId?: string; autoAnalyzeInitialMatch?: boolean; onInitialMatchOpened?: () => void; onAutoAnalysisOpened?: () => void }) {
  const [data, setData] = useState<SavedMatchesList>();
  const [selectedId, setSelectedId] = useState('');
  const selectedIdRef = useRef('');
  const pendingAutoAnalyzeId = useRef('');
  const historySyncStarted = useRef(false);
  selectedIdRef.current = selectedId;
  const [detail, setDetail] = useState<SavedMatchDetail>();
  const [assets, setAssets] = useState<HomeAssets>();
  const [itemAssets, setItemAssets] = useState<Record<string, string | null>>({});
  const [recordings, setRecordings] = useState<RecordingEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [busyId, setBusyId] = useState('');
  const [error, setError] = useState('');
  const [riotReadiness, setRiotReadiness] = useState<RiotReadiness>('checking');
  const [historyConnection, setHistoryConnection] = useState<'conectado' | 'offline' | 'unknown'>('unknown');
  const [filter, setFilter] = useState('all');
  const [pendingDelete, setPendingDelete] = useState<SavedMatchSummary>();
  const [deleteAnalysisId, setDeleteAnalysisId] = useState('');
  const [manifest, setManifest] = useState<DeletionManifest>();
  const [previewLoading, setPreviewLoading] = useState(false);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState('');

  const refresh = useCallback(async () => {
    if (!backendReady) return;
    try {
      // Inicio y esta pantalla leen la misma API de historial. Cargar páginas
      // desde home.matches evita depender del repositorio de análisis (que puede
      // estar vacío) para descubrir partidas locales ya almacenadas.
      const historyRows: HomeMatch[] = [];
      let offset = 0;
      let totalMatches = 0;
      let analysisCount: number | undefined;
      let hasMore = true;
      while (hasMore && offset < 100_000) {
        const page = await window.solralol.request('home.matches', { offset, limit: 100 });
        if (offset === 0) {
          totalMatches = page.totalMatches;
          analysisCount = page.analysisCount;
        }
        historyRows.push(...page.matches);
        offset += page.matches.length;
        hasMore = page.hasMore && page.matches.length > 0;
      }
      const [media, analysisRegistry] = await Promise.all([
        window.solralol.request('recordings.list'),
        window.solralol.request('soloq_analyses.list').catch(() => undefined),
      ]);
      analysisCount ??= analysisRegistry?.analysisCount;
      const normalizedMatches: SavedMatchSummary[] = historyRows.map(match => {
        const id = String(match.stable_match_id || match.game_id || '');
        const analysis = analysisRegistry?.matches.find(item => item.history_match_id === id || item.match_id === id);
        // Use the backend's single strict readiness decision. The history
        // cache may contain an older ready flag while Riot is still syncing.
        const ready = analysis?.deep_analysis_ready === true;
        return {
          id,
          champion: match.champion_name || 'Campeón no disponible',
          championId: match.champion_id,
          startedAt: match.started_at || '',
          duration: match.duration_seconds,
          mode: match.mode || (match.queue_id == null ? 'Modo desconocido' : `Cola ${match.queue_id}`),
          role: match.lane || '',
          queueId: match.queue_id,
          kills: match.kills,
          deaths: match.deaths,
          assists: match.assists,
          cs: match.cs,
          win: match.result === 'victory' ? true : match.result === 'defeat' ? false : null,
          analysisAvailable: ready,
          analysisState: analysis?.status || match.soloq_analysis_status || 'local_only',
          deepAnalysisReady: ready,
          riotMatchId: match.soloq_analysis_match_id || analysis?.match_id || null,
          analysisMessage: match.soloq_analysis_message || analysis?.status_message || '',
          retainedAnalysis: Boolean(match.soloq_analysis_match_id || analysis),
          historySource: 'home',
        };
      }).filter(match => match.id);
      const next: SavedMatchesList = {
        matches: normalizedMatches,
        count: totalMatches,
        historyCount: totalMatches,
        analysisCount,
        historyCached: normalizedMatches.length > 0,
        historyAvailable: normalizedMatches.length > 0,
        limit: analysisRegistry?.limit ?? 10,
        overLimit: analysisRegistry?.overLimit ?? ((analysisCount ?? 0) > (analysisRegistry?.limit ?? 10)),
      };
      setData(next); setRecordings(media); setError('');
      if (selectedIdRef.current && !next.matches.some(item => item.id === selectedIdRef.current)) { setSelectedId(''); setDetail(undefined); }
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'No se pudieron cargar las partidas locales.'); }
  }, [backendReady]);
  useEffect(() => {
    if (autoAnalyzeInitialMatch && initialMatchId) pendingAutoAnalyzeId.current = initialMatchId;
  }, [autoAnalyzeInitialMatch, initialMatchId]);
  useEffect(() => {
    if (!active || !data || !pendingAutoAnalyzeId.current) return;
    const target = pendingAutoAnalyzeId.current;
    const match = data.matches.find(item => item.id === target || item.riotMatchId === target);
    if (!match?.deepAnalysisReady || match.analysisState !== 'ready' || !match.riotMatchId) return;
    // Consume before opening so a polling refresh cannot create duplicate windows.
    pendingAutoAnalyzeId.current = '';
    void window.solralol.openSoloQAnalysis(match.riotMatchId).then(opened => {
      if (opened) onAutoAnalysisOpened?.();
      else setError('No se pudo abrir la ventana de análisis profundo.');
    }).catch(cause => setError(cause instanceof Error ? cause.message : 'No se pudo abrir la ventana de análisis profundo.'));
  }, [active, data, autoAnalyzeInitialMatch, initialMatchId, onAutoAnalysisOpened]);
  useEffect(() => { if (active) void refresh(); }, [active, refresh]);
  useEffect(() => {
    if (!active || !backendReady) return;
    return window.solralol.onAnalysisRecalculated(() => {
      void refresh();
      const id = detail?.sessionId || selectedIdRef.current;
      if (id) void window.solralol.request('saved_matches.detail', {id}).then(setDetail).catch(() => undefined);
    });
  }, [active, backendReady, detail?.sessionId, refresh]);
  useEffect(() => { if (!active) return; if (!backendReady) { setRiotReadiness('unavailable'); return; } let current = true; setRiotReadiness('checking'); window.solralol.request('riot.readiness').then(value => { if (current) setRiotReadiness(value.state); }).catch(() => { if (current) setRiotReadiness('unavailable'); }); return () => { current = false; }; }, [active, backendReady]);
  useEffect(() => {
    if (!active) { historySyncStarted.current = false; return; }
    if (!backendReady || historySyncStarted.current) return;
    historySyncStarted.current = true;
    void window.solralol.request('home.sync').then(snapshot => { setHistoryConnection(snapshot.connection); return refresh(); }).catch(() => {
      // La lista del repositorio sigue mostrando el historial LCU en caché si el cliente está desconectado.
    });
  }, [active, backendReady, refresh]);
  useEffect(() => {
    if (!active || !backendReady) return;
    const timer = window.setInterval(() => { void refresh(); }, 60_000);
    return () => window.clearInterval(timer);
  }, [active, backendReady, refresh]);
  useEffect(() => {
    if (!active || !backendReady || !data?.matches.some(item => ['pending', 'downloading', 'processing'].includes(item.analysisState))) return;
    const timer = window.setTimeout(() => void refresh(), 2200);
    return () => window.clearTimeout(timer);
  }, [active, backendReady, data, refresh]);
  useEffect(() => {
    if (!initialMatchId || !data?.matches.length) return;
    const match = data.matches.find(item => item.id === initialMatchId || item.riotMatchId === initialMatchId);
    if (match) { void open(match); onInitialMatchOpened?.(); }
  }, [initialMatchId, data?.matches]);
  const championNames = useMemo(() => [...new Set((data?.matches ?? []).map(item => item.champion).filter(Boolean))].slice(0, 20), [data?.matches]);
  const assetChampionRefs = useMemo(() => [...new Set([...(detail?.participants ?? []).map(player => String(player.championId ?? player.champion)), ...(data?.matches ?? []).map(item => String(item.championId ?? item.champion))])].slice(0, 20), [data?.matches, detail?.participants]);
  useEffect(() => {
    if (!assetChampionRefs.length) return;
    let current = true;
    window.solralol.request('home.assets', { champions: assetChampionRefs }).then(value => { if (current) setAssets(value); }).catch(() => undefined);
    return () => { current = false; };
  }, [assetChampionRefs.join('|')]);
  const localItemIds = useMemo(() => [...new Set([...(detail?.localData?.items ?? []), ...(detail?.participants ?? []).flatMap(player => player.items ?? [])].map(String))].filter(id => /^\d{1,8}$/.test(id) && Number(id) > 0).slice(0, 70), [detail]);
  useEffect(() => {
    if (!localItemIds.length) return;
    let current = true;
    for (let index = 0; index < localItemIds.length; index += 20) {
      void window.solralol.request('meta.assets', { items: localItemIds.slice(index, index + 20) })
        .then(result => { if (current) setItemAssets(previous => ({ ...previous, ...result })); }).catch(() => undefined);
    }
    return () => { current = false; };
  }, [localItemIds.join('|')]);
  const matches = useMemo(() => (data?.matches ?? []).filter(item => filter === 'all' || item.champion === filter), [data?.matches, filter]);
  const selected = data?.matches.find(item => item.id === selectedId);
  const recording = recordings.find(item => item.metadata?.session_id === (selected?.sessionId || selectedId) || item.metadata?.match_id === selectedId || item.metadata?.riot_match_id === selectedId);

  const acceptDetail = (value: SavedMatchDetail, matchId = selectedId) => {
    setDetail(value);
    const summary = value.summary;
    if (!summary) return;
    setData(current => current ? { ...current, matches: current.matches.map(item => item.id === matchId ? {
      ...item,
      ...(Object.prototype.hasOwnProperty.call(summary, 'cs') ? { cs: summary.cs } : {}),
      ...(summary.role ? { role: summary.role } : {}),
      ...(summary.kills != null ? { kills: summary.kills } : {}),
      ...(summary.deaths != null ? { deaths: summary.deaths } : {}),
      ...(summary.assists != null ? { assists: summary.assists } : {}),
    } : item) } : current);
  };

  const open = async (match: SavedMatchSummary) => {
    setSelectedId(match.id); setLoading(true); setError('');
    try {
      try { acceptDetail(await window.solralol.request('saved_matches.detail', { id: match.id }), match.id); }
      catch {
        const local = await window.solralol.request('home.match.detail', { matchId: match.id });
        const localRows = local.participants?.filter(player => player.is_local) ?? [];
        const localTeamId = localRows.length === 1 ? localRows[0].team_id : undefined;
        const teamIds = new Set((local.participants ?? []).map(player => player.team_id).filter(value => value != null).map(String));
        const teamAssignmentKnown = localTeamId != null && teamIds.size >= 2 && (local.participants ?? []).every(player => player.team_id != null);
        setDetail({
          available: Boolean(local.participants?.length), champion: local.champion_name || match.champion,
          gameMode: local.mode || match.mode, duration: Number(local.duration_seconds || 0), gameTimeOffset: 0,
          teamAssignmentKnown, participants: (local.participants || []).map((player, index) => ({
            participantId: String(player.participant_id ?? index + 1), champion: player.champion_name || 'Campeón no disponible',
            championId: player.champion_id, team: String(player.team_id ?? ''),
            side: teamAssignmentKnown ? (String(player.team_id) === String(localTeamId) ? 'allied' : 'enemy') : player.is_local ? 'allied' : 'unknown', local: Boolean(player.is_local),
            role: player.lane || '', items: player.items || [], kills: player.kills, deaths: player.deaths, assists: player.assists, cs: player.cs, win: player.win,
          })),
          teams: {}, events: [], markers: [], analysis: null, analysisState: 'local_only', analysisSource: 'Historial local',
          result: local.result === 'victory' ? true : local.result === 'defeat' ? false : null,
          summary: { ...match, cs: local.cs ?? match.cs, role: local.lane || match.role }, sessionId: '', matchAnalysis: null,
          localData: { items: (local.items || []).map(item => Number(item)).filter(Number.isFinite), queue_id: Number(local.queue_id), source: 'historial local' },
        });
        acceptDetail({
          available: Boolean(local.participants?.length), champion: local.champion_name || match.champion,
          gameMode: local.mode || match.mode, duration: Number(local.duration_seconds || 0), gameTimeOffset: 0,
          teamAssignmentKnown, result: local.result === 'victory' ? true : local.result === 'defeat' ? false : null,
          participants: (local.participants || []).map((player, index) => ({
            participantId: String(player.participant_id ?? index + 1), champion: player.champion_name || 'Campeón no disponible',
            championId: player.champion_id, team: String(player.team_id ?? ''),
            side: teamAssignmentKnown ? (String(player.team_id) === String(localTeamId) ? 'allied' : 'enemy') : player.is_local ? 'allied' : 'unknown', local: Boolean(player.is_local),
            role: player.lane || '', items: player.items || [], kills: player.kills, deaths: player.deaths, assists: player.assists, cs: player.cs, win: player.win,
          })),
          teams: {}, events: [], markers: [], analysis: null, analysisState: 'local_only', analysisSource: 'Historial local',
          summary: { ...match, cs: local.cs ?? match.cs, role: local.lane || match.role }, sessionId: '', matchAnalysis: null,
        }, match.id);
      }
    }
    catch (cause) { setDetail(undefined); setError(cause instanceof Error ? cause.message : 'No se pudo cargar la ficha local.'); }
    finally { setLoading(false); }
  };
  const sync = async (match: SavedMatchSummary) => {
    if (busyId) return;
    setBusyId(match.id); setError('');
    try {
      const result = await window.solralol.request('saved_matches.sync', { id: match.id });
      setData(current => current ? { ...current, matches: current.matches.map(item => item.id === match.id ? { ...item, analysisState: result.status, analysisMessage: result.status_message ?? '', riotMatchId: result.match_id ?? result.id, deepAnalysisReady: false, analysisAvailable: false } : item) } : current);
      await refresh();
      if (selectedId === match.id) setDetail(await window.solralol.request('saved_matches.detail', { id: match.id }));
    } catch (cause) { await refresh(); if (selectedId === match.id) { try { setDetail(await window.solralol.request('saved_matches.detail', { id: match.id })); } catch { /* La ficha local sigue visible. */ } } setError(cause instanceof Error ? cause.message : 'No se pudieron sincronizar los datos de Riot. La ficha local se conserva.'); }
    finally { setBusyId(''); }
  };
  const syncEligible = Boolean(selected && Number(selected.queueId) === 420 && /^[A-Za-z0-9_-]{3,160}$/.test(selected.id) && detail?.participants?.some(player => player.local) && (data?.analysisCount ?? 0) < (data?.limit ?? 10));
  const unavailableReason = data && (data.analysisCount ?? 0) >= data.limit ? 'Límite de análisis alcanzado' : 'No se puede analizar esta partida';
  const analysisStatus = selected ? riotAnalysisStatusLabel(riotReadiness, selected.analysisState, Boolean(selected.deepAnalysisReady), selected.analysisMessage, syncEligible, unavailableReason) : '';
  const syncButtonLabel = selected ? riotAnalysisActionLabel(riotReadiness, selected.analysisState, Boolean(selected.deepAnalysisReady), syncEligible, unavailableReason) : 'Analizar';
  const participantRows = useMemo(() => {
    if (!detail?.teamAssignmentKnown) return [];
    // Filtering is stable: each side keeps the order in the LCU participant array.
    const allied = detail.participants.filter(player => player.side === 'allied');
    const enemy = detail.participants.filter(player => player.side === 'enemy');
    return Array.from({ length: Math.max(allied.length, enemy.length) }, (_, index) => ({ allied: allied[index], enemy: enemy[index] }));
  }, [detail]);
  const renderParticipant = (player?: RecordingReviewParticipant) => player ? <article className={`saved-match-player ${player.local ? 'local' : ''}`} key={player.participantId ?? `${player.champion}-${player.role}`}>
    <GameImage src={championAsset(assets, player.champion, player.championId)} alt={player.champion} className="saved-match-player-icon" fallback={player.champion.slice(0, 1)}/>
    <span><b title={player.champion}>{player.champion}{player.local ? ' · Tú' : ''}</b><small>{participantRole(player) ? `${roleLabels[participantRole(player)!]} · ` : ''}KDA {player.kills ?? '?'}/{player.deaths ?? '?'}/{player.assists ?? '?'} · {player.cs == null ? '— CS' : `${player.cs} CS`}</small></span>
  </article> : <div className="saved-local-player-empty" aria-hidden="true"/>;
  const handleAnalysisAction = () => { if (selected?.deepAnalysisReady) void openAnalysis(selected); else if (['missing', 'invalid', 'forbidden'].includes(riotReadiness)) openSettings(); else if (['unavailable', 'rate_limited'].includes(riotReadiness)) { setRiotReadiness('checking'); void window.solralol.request('riot.readiness').then(value => setRiotReadiness(value.state)).catch(() => setRiotReadiness('unavailable')); } else if (riotReadiness === 'ready' && selected && syncEligible) { pendingAutoAnalyzeId.current = selected.id; void sync(selected); } };
  const openAnalysis = async (match: SavedMatchSummary) => {
    if (!match.deepAnalysisReady || match.analysisState !== 'ready' || !match.riotMatchId) return;
    const opened = await window.solralol.openSoloQAnalysis(match.riotMatchId);
    if (!opened) setError('No se pudo abrir la ventana de análisis profundo.');
  };
  const openRecording = async () => { if (recording?.id) await window.solralol.openRecordingReview(recording.id); };
  const showDeletePreview = async (match: SavedMatchSummary) => {
    setPendingDelete(match); setDeleteAnalysisId(match.retainedAnalysis ? (match.riotMatchId || '') : ''); setManifest(undefined); setDeleteError(''); setPreviewLoading(true);
    try { setManifest(match.retainedAnalysis && match.riotMatchId
      ? await window.solralol.request('soloq_analyses.delete.preview', { matchId: match.riotMatchId })
      : await window.solralol.request('saved_matches.delete.preview', { id: match.id })); }
    catch (cause) { setDeleteError(cause instanceof Error ? cause.message : 'No se pudo calcular el inventario.'); }
    finally { setPreviewLoading(false); }
  };
  const deleteMatch = async () => {
    if (!pendingDelete || !manifest || deleteBusy) return;
    setDeleteBusy(true); setDeleteError('');
    try {
      if (deleteAnalysisId) await window.solralol.request('soloq_analyses.delete', { matchId: deleteAnalysisId, manifestId: manifest.manifestId });
      else await window.solralol.request('saved_matches.delete', { id: pendingDelete.id, manifestId: manifest.manifestId });
      setData(current => current ? { ...current, matches: deleteAnalysisId
        ? current.matches.map(item => item.id === pendingDelete.id ? { ...item, analysisState: 'local_only', analysisMessage: '', analysisAvailable: false, deepAnalysisReady: false, riotMatchId: null, retainedAnalysis: false } : item)
        : current.matches.filter(item => item.id !== pendingDelete.id),
        count: deleteAnalysisId ? current.count : Math.max(0, current.count - 1),
        analysisCount: current.analysisCount == null ? undefined : Math.max(0, current.analysisCount - (deleteAnalysisId ? 1 : 0)) } : current);
      if (selectedId === pendingDelete.id) { setDetail(undefined); }
      setRecordings(current => current.filter(item => item.metadata?.session_id !== (pendingDelete.sessionId || pendingDelete.id) && item.metadata?.match_id !== pendingDelete.id && item.metadata?.riot_match_id !== pendingDelete.id));
      setPendingDelete(undefined); setDeleteAnalysisId('');
    } catch (cause) { setDeleteError(cause instanceof Error ? cause.message : 'No se pudo completar la eliminación. Actualiza la vista previa.'); }
    finally { setDeleteBusy(false); }
  };

  if (!active) return null;
  return <section className="saved-matches-page saved-local-workspace">
    <header className="saved-matches-header"><div><div className="eyebrow">HISTORIAL LOCAL LCU · ANÁLISIS PROFUNDO DE RIOT</div><h1>Partidas guardadas</h1><p>Consulta tu historial local y sincroniza con Riot solo las partidas que quieras analizar.</p></div><div className="saved-match-capacity"><b>{data?.analysisCount == null ? '—' : data.analysisCount} / {data?.limit ?? 10}</b><span>análisis guardados</span><small>{data?.historyCount ?? data?.matches.length ?? 0} partidas en el historial LCU</small><button type="button" onClick={() => void refresh()} disabled={!backendReady}>Actualizar</button></div></header>
    {error && <div className="saved-match-error" role="alert">{error}{error.includes('historial local') && <button type="button" onClick={() => openSettings('almacenamiento')}>Abrir Almacenamiento</button>}<button type="button" onClick={() => setError('')}>Cerrar</button></div>}
    {!backendReady && <div className="saved-match-notice">El backend local está desconectado. Se conservarán los datos cargados hasta que vuelva a conectar.</div>}
    {historyConnection === 'offline' && data?.historyCached && <div className="saved-match-notice">League Client no está conectado. Se muestra el historial LCU guardado en caché.</div>}
    <div className="saved-match-filters saved-local-filter"><span>Historial de partidas · {matches.length} visibles</span><select aria-label="Filtrar campeón" value={filter} onChange={event => setFilter(event.target.value)}><option value="all">Todos los campeones</option>{championNames.map(name => <option value={name} key={name}>{name}</option>)}</select></div>
    <div className="saved-match-layout saved-local-layout">
      <div className="saved-match-library"><div className="saved-match-list">
      {!data && <div className="saved-match-empty">Cargando historial local…</div>}
      {data && !matches.length && <div className="saved-match-empty">{data.historyAvailable ? 'No hay partidas que coincidan con este filtro.' : data.historyCached ? 'No hay partidas en el historial local almacenado.' : 'No hay historial local disponible. Conecta League Client para consultar tus partidas.'}</div>}
      {matches.map(match => {
        const linked = recordings.find(item => item.metadata?.session_id === (match.sessionId || match.id) || item.metadata?.match_id === match.id || item.metadata?.riot_match_id === match.id);
        const eligible = Number(match.queueId) === 420;
        return <article key={match.id} className={`saved-match-card ${match.win === true ? 'victory' : match.win === false ? 'defeat' : ''} ${selectedId === match.id ? 'selected' : ''}`}>
          <button className="saved-match-select" type="button" aria-label={`Ver detalles de ${match.champion}, ${match.win === true ? 'victoria' : match.win === false ? 'derrota' : 'resultado no disponible'}`} onClick={() => void open(match)}><GameImage src={championAsset(assets, match.champion, match.championId)} alt={match.champion} className="saved-match-champion" fallback={match.champion.slice(0, 1)}/><div className="saved-match-main"><div className="saved-match-title"><b>{match.champion}</b><strong>{match.win === true ? 'Victoria' : match.win === false ? 'Derrota' : 'Resultado no disponible'}</strong></div><span>{match.mode} · {(roleLabels[match.role.toUpperCase()] ?? match.role) || 'Posición no disponible'} · {match.kills ?? '?'}/{match.deaths ?? '?'}/{match.assists ?? '?'}</span><small className="saved-match-meta">{date(match.startedAt)} · {duration(match.duration)} · <em className={`saved-match-state ${match.analysisState}`}>{statusLabels[match.analysisState] ?? 'No analizada'}</em></small>{match.analysisState === 'error' && match.analysisMessage && <small className="saved-match-message" title={match.analysisMessage}>{match.analysisMessage}</small>}</div></button>
          <div className="saved-local-actions">{match.deepAnalysisReady && match.riotMatchId ? <button type="button" title="Abrir análisis" aria-label="Abrir análisis" onClick={(event) => { event.stopPropagation(); void openAnalysis(match); }}><Icon name="external-link" className="saved-match-action-icon"/></button> : eligible ? <button type="button" title={riotAnalysisActionLabel(riotReadiness, match.analysisState, Boolean(match.deepAnalysisReady))} aria-label={riotAnalysisActionLabel(riotReadiness, match.analysisState, Boolean(match.deepAnalysisReady))} disabled={!backendReady || Boolean(busyId) || ['pending', 'downloading', 'processing'].includes(match.analysisState)} onClick={(event) => { event.stopPropagation(); if (['missing', 'invalid', 'forbidden'].includes(riotReadiness)) openSettings(); else void open(match); }}><Icon name={['missing', 'invalid', 'forbidden'].includes(riotReadiness) ? 'settings' : 'chart'} className="saved-match-action-icon"/></button> : null}{linked?.id && <button type="button" title="Ver grabación" aria-label="Ver grabación" onClick={(event) => { event.stopPropagation(); void window.solralol.openRecordingReview(linked.id); }}><Icon name="video" className="saved-match-action-icon"/></button>}{match.retainedAnalysis && <button type="button" className="saved-match-delete" title="Eliminar análisis" aria-label={`Eliminar análisis de ${match.champion}`} onClick={(event) => { event.stopPropagation(); void showDeletePreview(match); }}><Icon name="close" className="saved-match-action-icon"/></button>}</div>
        </article>;
      })}
    </div></div>
    <aside className="saved-match-detail saved-local-detail">
      {!selected && <div className="saved-match-empty">Selecciona una partida para consultar su ficha local.</div>}
      {loading && <div className="saved-match-empty">Cargando datos locales...</div>}
      {detail && selected && !loading && <>
        <div className="saved-match-detail-head"><div><div className="eyebrow">FICHA LCU LOCAL</div><h2>{selected.champion}</h2><p>{selected.mode} · {date(selected.startedAt)} · {duration(selected.duration)}</p></div></div>
        <div className="saved-match-detail-stats">
          <div><small>RESULTADO</small><b>{selected.win === true ? 'Victoria' : selected.win === false ? 'Derrota' : 'No disponible'}</b></div>
          <div><small>KDA</small><b>{selected.kills ?? '?'} / {selected.deaths ?? '?'} / {selected.assists ?? '?'}</b></div>
          <div><small>POSICIÓN</small><b>{(roleLabels[selected.role.toUpperCase()] ?? selected.role) || 'No disponible'}</b></div>
          <div><small>Farm</small><b>{selected.cs ?? '—'}</b></div>
        </div>
        <div className="saved-local-explanation"><b>Resumen local</b><p>Estos datos proceden de la sesión local de League. El análisis profundo requiere sincronizar una partida verificable con Riot.</p></div>
        {detail.participants?.length > 0 && <section className="saved-local-roster"><h3>Participantes</h3>
          {detail.teamAssignmentKnown ? <>
            <div className="saved-local-versus-head"><b>Tu equipo</b><span>VS.</span><b>Equipo rival</b></div>
            <div className="saved-local-versus">{participantRows.map((row, index) => <div className="saved-local-versus-row" key={`${row.allied?.sourceIndex ?? row.allied?.participantId ?? 'a'}-${row.enemy?.sourceIndex ?? row.enemy?.participantId ?? index}`}>
              {renderParticipant(row.allied)}{renderParticipant(row.enemy)}
            </div>)}</div>
          </> : <>
            <div className="saved-local-unconfirmed-head">Comparación incompleta · equipos no confirmados</div>
            <div className="saved-local-unconfirmed">{detail.participants.map(player => renderParticipant(player))}</div>
            <p className="saved-local-incomplete">No hay datos suficientes para confirmar qué participantes pertenecen a cada equipo. Se muestran sin asignar.</p>
          </>}
        </section>}
        {detail.localData?.items?.length ? <section className="saved-local-roster saved-local-build"><h3>Objetos de la partida</h3><div>{detail.localData.items.filter(id => id > 0).map((id, index) => <GameImage key={`${id}-${index}`} src={itemAssets[`item:${id}`] ?? null} alt={`Objeto ${id}`} title={`Objeto ${id}`} className="saved-local-item" fallback="?"/>)}</div></section> : null}
        {Number(selected.queueId) === 420 && <div className={`saved-local-sync-note ${selected.analysisState === 'error' ? 'failed' : ''}`}><b>{analysisStatus}</b><span>{riotReadiness === 'ready' && selected.analysisState === 'error' && selected.analysisMessage ? selected.analysisMessage : selected.deepAnalysisReady ? 'La API de Riot está verificada y el análisis está disponible.' : 'Los datos locales de esta partida siguen disponibles.'}</span></div>}
        <div className="saved-local-detail-actions">
          {Number(selected.queueId) === 420 && <button type="button" disabled={!backendReady || Boolean(busyId) || ['pending', 'downloading', 'processing'].includes(selected.analysisState) || riotReadiness === 'checking' || (riotReadiness === 'ready' && !selected.deepAnalysisReady && !syncEligible)} onClick={handleAnalysisAction}>{busyId === selected.id ? 'Descargando datos' : syncButtonLabel}</button>}
          {recording?.id && <button type="button" onClick={() => void openRecording()}>Ver grabación</button>}
        </div>
      </>}
    </aside>
    </div>
    {pendingDelete && <ConfirmModal title="Eliminar partida guardada" description="¿Eliminar esta partida guardada y sus datos asociados? Esta acción no se puede deshacer." manifest={manifest} championImage={championAsset(assets, pendingDelete.champion, pendingDelete.championId)} loading={previewLoading} busy={deleteBusy} error={deleteError} onRetry={() => void showDeletePreview(pendingDelete)} onCancel={() => { if (!deleteBusy) { setPendingDelete(undefined); setManifest(undefined); setDeleteError(''); } }} onConfirm={() => void deleteMatch()}/>}
  </section>;
}
