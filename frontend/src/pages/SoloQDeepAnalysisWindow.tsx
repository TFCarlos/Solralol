import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import type { CSSProperties, KeyboardEvent as ReactKeyboardEvent, PointerEvent as ReactPointerEvent, ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { GameImage } from '../components/GameImage';
import { Icon } from '../components/Icon';
import { WindowTitleBar } from '../components/WindowTitleBar';
import { AiMatchReport } from './AiMatchReport';
import { battleScoreAt, displayedBattleScoreAt, resampleAndSmoothBattleScore } from '../utils/battleScoreTimeline';
import { battleScoreColor, formatBattleScore } from '../utils/battleScore';
import type { HomeAssets, ImprovementFinding, MatchAchievement, MetaAssetsRequest, SoloQAnalysisDetail, SoloQEvent, SoloQFrame, SoloQParticipant } from '../types/contracts';
import './SoloQDeepAnalysisWindow.css';

const colors = ['#d5b567', '#69c79c', '#df7b70', '#72a8dc', '#c28bdd', '#e29b57', '#66c9cf', '#d77da3', '#a9c46a', '#9a9eee'];
const metricDefinitions = [
  ['Oro por campeón', 'gold', 'Oro'], ['EXP por campeón', 'xp', 'XP'], ['CS por campeón', 'cs', 'CS'],
  ['BattleScore', 'battleScore', 'BattleScore'], ['Visión', 'vision', 'Visión'], ['Daño infligido', 'championDamageDealt', 'Daño'],
  ['Daño recibido', 'allSourceDamageReceived', 'Daño'], ['Daño útil recibido', 'usefulDamageReceived', 'Daño'],
] as const;
type MetricKey = typeof metricDefinitions[number][1];
type Inspection = { time: number; metric: MetricKey; source?: 'teams' | 'players'; cursor?: { x: number; y: number } } | null;
type Series = { label: string; color: string; points: Array<{ x: number; y: number }> };
type PlacedTimelineEvent = { x: number; ratio: number; lane: number; event: SoloQEvent; kind: 'kill' | 'death' | 'assist' | 'purchase' | 'sale' | 'objective' };
type TimelineFilters = Record<PlacedTimelineEvent['kind'], boolean>;
const initialTimelineFilters: TimelineFilters = { kill: true, death: true, assist: true, purchase: true, sale: true, objective: true };

const fmt = (value: number | null | undefined) => value == null || !Number.isFinite(value) ? '—' : Math.round(value).toLocaleString('es-ES');
const numericId = (value: unknown): string | null => typeof value === 'number' && Number.isInteger(value) && value > 0 ? String(value) : typeof value === 'string' && /^\d{1,10}$/.test(value) && Number(value) > 0 ? value : null;
function participantRuneIds(runes: unknown): string[] {
  if (!runes || typeof runes !== 'object' || Array.isArray(runes)) return [];
  const styles = (runes as Record<string, unknown>).styles;
  if (!Array.isArray(styles)) return [];
  const ids: string[] = [];
  styles.forEach(style => {
    if (!style || typeof style !== 'object' || Array.isArray(style)) return;
    const value = style as Record<string, unknown>;
    if (Array.isArray(value.selections)) value.selections.forEach(selection => {
      if (selection && typeof selection === 'object' && !Array.isArray(selection)) {
        const perk = numericId((selection as Record<string, unknown>).perk);
        if (perk) ids.push(perk);
      }
    });
  });
  return [...new Set(ids)];
}
function finalFrameValue(frames: SoloQFrame[], participantId: number, key: 'allSourceDamageReceived'): number | null {
  let latest: SoloQFrame | undefined;
  for (const frame of frames) {
    const value = frame[key];
    if (frame.participantId !== participantId || value == null || !Number.isFinite(value)) continue;
    if (!latest || frame.timestamp > latest.timestamp) latest = frame;
  }
  const result = latest?.[key];
  return result == null ? null : result;
}
const spellIdsFor = (player: SoloQParticipant) => (player.summonerSpells ?? []).map(numericId).filter((id): id is string => Boolean(id));
const clock = (ms: number) => `${Math.floor(ms / 60000)}:${String(Math.floor(ms / 1000) % 60).padStart(2, '0')}`;
const minuteLabel = (ms: number) => `${Math.floor(ms / 60000)}m`;
const activeTitle = (players: SoloQParticipant[]) => players.length > 3 ? `${players.length} campeones seleccionados` : players.map(player => player.champion).join(' vs. ') || 'Sin campeones seleccionados';

export function SoloQDeepAnalysisWindow({ matchId }: { matchId: string }) {
  const [detail, setDetail] = useState<SoloQAnalysisDetail>();
  const [assets, setAssets] = useState<HomeAssets>();
  const [itemAssets, setItemAssets] = useState<Record<string, string | null>>({});
  const [selected, setSelected] = useState<number[]>([]);
  const [timelineFilters, setTimelineFilters] = useState<TimelineFilters>(initialTimelineFilters);
  const [inspection, setInspection] = useState<Inspection>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [aiBusy, setAiBusy] = useState(false);
  const [aiPolling, setAiPolling] = useState(false);
  const [aiError, setAiError] = useState('');
  const [activeView, setActiveView] = useState<'analysis' | 'report'>('analysis');

  useEffect(() => {
    let active = true;
    window.solralol.request('soloq_analyses.detail', { matchId }).then(value => {
      if (!active) return;
      if (!value.timeline_available || !value.local_identity_resolved || !value.participants?.length || !value.frames?.length) throw new Error('Esta partida no tiene una cronología completa de Riot para mostrar el análisis profundo.');
      setDetail(value);
      const local = value.participants.find(player => player.local);
      setSelected(local ? [local.participantId] : []);
    }).catch(cause => { if (active) setError(cause instanceof Error ? cause.message : 'No se pudo cargar el análisis de Riot.'); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [matchId]);

  useEffect(() => {
    let live = true;
    const unsubscribe = window.solralol.onAchievementSettingsChanged(() => {
      window.solralol.request('soloq_analyses.achievements', { matchId }).then(value => {
        if (live) setDetail(current => current ? {...current, ...value} : current);
      }).catch(() => undefined);
    });
    return () => { live = false; unsubscribe(); };
  }, [matchId]);

  useEffect(() => {
    let live = true;
    const unsubscribe = window.solralol.onAnalysisRecalculated(() => {
      window.solralol.request('soloq_analyses.detail', { matchId }).then(value => {
        if (live && value.battle_score?.configurationHash) setDetail(value);
      }).catch(() => undefined);
    });
    return () => { live = false; unsubscribe(); };
  }, [matchId]);

  useEffect(() => {
    if (!aiPolling) return;
    let live = true;
    let timer: number | undefined;
    const poll = async () => {
      try {
        const status = await window.solralol.request('soloq_analyses.analysis.status', { matchId });
        if (!live) return;
        setDetail(current => current ? { ...current, ...status, ai_analysis: status.ai_analysis ?? current.ai_analysis } : current);
        if (status.ai_generation_status === 'generating') {
          timer = window.setTimeout(() => void poll(), 1200);
          return;
        }
        if (status.ai_generation_status === 'error' || status.ai_generation_status === 'idle') {
          setAiError(status.ai_status_message || 'No se pudo completar el análisis. Puedes volver a intentarlo.');
        }
        setAiPolling(false);
        setAiBusy(false);
      } catch (cause) {
        if (!live) return;
        setAiError(cause instanceof Error ? cause.message : 'No se pudo consultar el estado de la generación.');
        setAiPolling(false);
        setAiBusy(false);
      }
    };
    timer = window.setTimeout(() => void poll(), 1000);
    return () => { live = false; if (timer !== undefined) window.clearTimeout(timer); };
  }, [aiPolling, matchId]);

  const participantIds = useMemo(() => detail?.participants.map(item => item.champion) ?? [], [detail?.participants]);
  useEffect(() => {
    if (!participantIds.length) return;
    let active = true;
    window.solralol.request('home.assets', { champions: [...new Set(participantIds)].slice(0, 20) }).then(value => { if (active) setAssets(value); }).catch(() => undefined);
    return () => { active = false; };
  }, [participantIds.join('|')]);
  const aiAnalysis = detail?.ai_analysis?.analysis as Record<string, unknown> | undefined;
  const suggestedItemIds = useMemo(() => {
    const ids: unknown[] = [];
    for (const key of ['item_alternatives', 'item_reviews', 'situational_item_suggestions']) {
      const rows = aiAnalysis?.[key];
      if (Array.isArray(rows)) for (const row of rows) if (row && typeof row === 'object') {
        const item = row as Record<string, unknown>;
        ids.push(item.item_id, item.replace_or_delay_item_id, item.component_id);
      }
    }
    return ids.map(numericId).filter((id): id is string => Boolean(id));
  }, [detail?.ai_analysis]);
  const itemIds = useMemo(() => [...new Set([
    ...(detail?.participants ?? []).flatMap(player => player.items ?? []),
    ...(detail?.events ?? []).flatMap(event => event.itemId ? [event.itemId] : []),
    ...suggestedItemIds,
  ].map(String))].filter(value => /^\d{1,8}$/.test(value) && Number(value) > 0).slice(0, 200), [detail?.participants, detail?.events, suggestedItemIds]);
  const runeIds = useMemo(() => {
    const runes = [...new Set((detail?.participants ?? []).flatMap(player => participantRuneIds(player.runes)))].slice(0, 100);
    const runeEvaluation = aiAnalysis?.rune_evaluation;
    const runeAlternative = runeEvaluation && typeof runeEvaluation === 'object' && !Array.isArray(runeEvaluation) ? (runeEvaluation as Record<string, unknown>).alternative : null;
    const alternativeId = runeAlternative && typeof runeAlternative === 'object' && !Array.isArray(runeAlternative) ? numericId((runeAlternative as Record<string, unknown>).id) : null;
    if (alternativeId && !runes.includes(alternativeId)) runes.push(alternativeId);
    return runes;
  }, [detail?.participants, detail?.ai_analysis]);
  const spellIds = useMemo(() => [...new Set((detail?.participants ?? []).flatMap(spellIdsFor))].slice(0, 20), [detail?.participants]);
  useEffect(() => {
    let active = true;
    const patch = detail?.patch;
    const batches: MetaAssetsRequest[] = Array.from({ length: Math.ceil(itemIds.length / 20) }, (_, index) =>
      ({ items: itemIds.slice(index * 20, index * 20 + 20), patch }));
    for (let index = 0; index < runeIds.length; index += 10) {
      batches.push({ runes: runeIds.slice(index, index + 10), patch });
    }
    if (spellIds.length) batches.push({ spells: spellIds, patch });
    const load = async () => {
      while (active) {
        const batch = batches.shift();
        if (!batch) return;
        try {
          const result = await window.solralol.request('meta.assets', batch);
          if (active) setItemAssets(previous => ({ ...previous, ...result }));
        } catch { /* Another batch can still provide its icons. */ }
      }
    };
    const workers = Math.min(3, batches.length);
    for (let index = 0; index < workers; index++) void load();
    return () => { active = false; };
  }, [itemIds.join('|'), runeIds.join('|'), spellIds.join('|'), detail?.patch]);

  const openAI = async (force: boolean) => {
    if (aiBusy) return;
    setAiBusy(true); setAiError('');
    try {
      const result = await window.solralol.request('soloq_analyses.analysis.generate', { matchId, force });
      setDetail(result);
      if (result.ai_generation_status === 'generating') setAiPolling(true);
      else setAiBusy(false);
    } catch (cause) {
      setAiError(cause instanceof Error ? cause.message : 'No se pudo generar el análisis con IA.');
      setAiBusy(false);
    }
  };

  const handleViewTabKeyDown = (event: ReactKeyboardEvent<HTMLButtonElement>) => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const next = event.key === 'Home' ? 'analysis' : event.key === 'End' ? 'report' : activeView === 'analysis' ? 'report' : 'analysis';
    setActiveView(next);
    document.getElementById(`deep-view-tab-${next}`)?.focus();
  };

  const chartPlayers = useMemo(() => selected.map(id => detail?.participants.find(item => item.participantId === id)).filter((item): item is SoloQParticipant => Boolean(item)), [detail?.participants, selected]);
  const paletteIndices = useMemo(() => new Map((detail?.participants ?? []).map((player, index) => [player.participantId, index])), [detail?.participants]);

  if (loading) return <main className="deep-analysis-window"><WindowTitleBar label="Análisis de partida"/><div className="deep-state">Cargando datos sincronizados de Riot…</div></main>;
  if (!detail) return <main className="deep-analysis-window"><WindowTitleBar label="Análisis de partida"/><div className="deep-state deep-error">{error || 'No hay datos profundos disponibles para esta partida.'}</div></main>;

  const participants = detail.participants;
  const paletteIndex = paletteIndices;
  const duration = Math.max(1, Number(detail.duration ?? 0) * 1000);
  const toggle = (id: number) => setSelected(current => current.includes(id) ? current.filter(value => value !== id) : participants.length >= 10 && current.length >= 10 ? current : [...current, id]);
  const allies = participants.filter(item => item.side === 'allied');
  const enemies = participants.filter(item => item.side === 'enemy');
  const goldTeams = teamGold(detail.frames, participants);
  const activePlayers = chartPlayers;
  const battleScoreTeams = teamBattleScore(
    participants,
    duration,
    detail.battle_score?.visualization?.sample_interval_ms ?? 30_000,
    detail.battle_score?.visualization?.smoothing_intensity ?? 0.20,
  );
  const objectiveEvents = detail.events.filter(isObjectiveEvent);
  const participantEventsByPlayer = new Map(activePlayers.map(player => [player.participantId, detail.events.filter(event => event.type !== 'TURRET_PLATE_DESTROYED' && event.participantIds.includes(player.participantId) && timelineFilters[timelineEventKind(event, player.participantId)])]));
  const visibleParticipantEventCount = [...participantEventsByPlayer.values()].reduce((sum, events) => sum + events.length, 0);
  const local = participants.find(item => item.local);
  const inspectionMetric = metricDefinitions.find(([, key]) => key === inspection?.metric);
  const inspectionPlayerValues = inspection && inspection.source !== 'teams' ? activePlayers.map(player => {
    if (inspection.metric !== 'battleScore') return { player, value: metricValueAt(inspection.metric, player, detail.frames, detail.events, inspection.time), rawValue: null };
    const canonical = player.battleScoreSeries ?? [];
    const displayed = resampleAndSmoothBattleScore(canonical, duration, player.battleScore,
      detail.battle_score?.visualization?.sample_interval_ms ?? 30_000,
      1 - (detail.battle_score?.visualization?.smoothing_intensity ?? 0.20));
    return { player, value: displayedBattleScoreAt(displayed, inspection.time), rawValue: battleScoreAt(canonical, inspection.time) };
  }) : [];
  const inspectedTeams = inspection?.metric === 'battleScore' ? battleScoreTeams : goldTeams;
  const inspectionTeamValues = inspection?.source === 'teams' ? inspectedTeams.map(series => ({ series, value: inspection.metric === 'battleScore' ? displayedBattleScoreAt(series.points, inspection.time) : seriesValueAt(series, inspection.time) })) : [];
  const tooltipWidth = Math.min(340, Math.max(260, window.innerWidth - 24));
  const tooltipRows = inspection?.source === 'teams' ? 2 : activePlayers.length;
  const tooltipHeight = Math.min(window.innerHeight - 16, 56 + tooltipRows * (inspection?.metric === 'battleScore' ? 38 : 25));
  const tooltipLeft = inspection?.cursor ? Math.max(8, Math.min(inspection.cursor.x + 14, window.innerWidth - tooltipWidth - 8)) : 0;
  const tooltipTop = inspection?.cursor ? Math.max(8, Math.min(inspection.cursor.y + 14, window.innerHeight - tooltipHeight - 8)) : 0;
  const maxMinute = Math.ceil(duration / 60000);
  const rulerTicks = Array.from({ length: Math.floor(maxMinute / 2) + 1 }, (_, index) => index * 2 * 60000).filter(value => value <= duration);
  if (rulerTicks[rulerTicks.length - 1] !== duration) rulerTicks.push(duration);
  const timelineWidth = Math.max(1132, Math.ceil(duration / 60000 * 50));
  // The timeline CSS uses a 150px identity column and a 12px gap; percentages
  // are calculated against the exact remaining track width.
  const timelineTrackWidth = timelineWidth - 162;

  return <main className="deep-analysis-window">
    <WindowTitleBar label="Análisis profundo">
    <nav className="deep-view-tabs" role="tablist" aria-label="Vistas del análisis profundo">
      <button id="deep-view-tab-analysis" type="button" role="tab" aria-selected={activeView === 'analysis'} aria-controls="deep-view-panel-analysis" tabIndex={activeView === 'analysis' ? 0 : -1} className={activeView === 'analysis' ? 'active' : ''} onClick={() => setActiveView('analysis')} onKeyDown={handleViewTabKeyDown}><Icon name="chart"/><span>Análisis</span></button>
      <button id="deep-view-tab-report" type="button" role="tab" aria-selected={activeView === 'report'} aria-controls="deep-view-panel-report" tabIndex={activeView === 'report' ? 0 : -1} className={activeView === 'report' ? 'active' : ''} onClick={() => setActiveView('report')} onKeyDown={handleViewTabKeyDown}><Icon name="sparkles"/><span>Informe de partida</span></button>
    </nav>
    </WindowTitleBar>
    <div id="deep-view-panel-analysis" role="tabpanel" aria-labelledby="deep-view-tab-analysis" className="deep-analysis-scroll deep-view-panel" hidden={activeView !== 'analysis'}>
      <header className="deep-match-header"><div><span className="eyebrow">ANÁLISIS PROFUNDO · DATOS DE RIOT</span><h1>{detail.champion ?? local?.champion ?? 'Partida SoloQ'} <span className={detail.win === true ? 'win' : detail.win === false ? 'loss' : ''}>{detail.win === true ? 'Victoria' : detail.win === false ? 'Derrota' : 'Resultado no disponible'}</span></h1><p>{detail.mode ?? 'Modo desconocido'} · {detail.role || 'Posición no disponible'} · {detail.startedAt ? new Intl.DateTimeFormat('es-ES', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(detail.startedAt)) : 'Fecha no disponible'} · {clock(duration)} · {detail.patch ?? 'Parche no disponible'} · {local?.side === 'allied' ? 'Equipo azul' : local?.side === 'enemy' ? 'Equipo rojo' : 'Equipo no resuelto'}</p></div><div className="deep-kda"><b>{detail.kills ?? '—'} / {detail.deaths ?? '—'} / {detail.assists ?? '—'}</b><small>K / D / A</small></div></header>

      <section className="deep-panel deep-medals"><header><div><span className="eyebrow">RECONOCIMIENTOS</span><h2>Logros de partida</h2></div><small>Evaluados con datos disponibles de Riot</small></header><h3 className="deep-achievement-category-title">Logros positivos</h3><div className="deep-medal-grid">{(detail.achievements?.items ?? []).map(medal => <AchievementCard key={medal.id} medal={medal}/>)}</div>{!(detail.achievements?.items.length) && <p className="deep-medal-empty">No hay logros positivos visibles. Puedes cambiar el filtro en Ajustes → Análisis.</p>}{detail.improvement_opportunities?.enabled !== false && <div className="deep-improvements"><h3 className="deep-achievement-category-title">Oportunidades de mejora</h3>{detail.improvement_opportunities?.items.length ? <div className="deep-medal-grid">{detail.improvement_opportunities.items.map(finding=><ImprovementCard key={finding.achievement_id} finding={finding}/>)}</div> : <p className="deep-improvement-empty">No se detectaron oportunidades verificables con la telemetría disponible. Esto no implica que la partida fuera perfecta.</p>}</div>}</section>

      <section className="deep-panel deep-performance-panel"><header><div><span className="eyebrow">RENDIMIENTO</span><h2>Progresión de ambos equipos</h2></div></header><div className="deep-performance-charts"><article><h3>Oro acumulado por equipo</h3><LineChart label="Evolución de oro por equipo" metric="gold" series={goldTeams} duration={duration} inspection={inspection} onInspect={setInspection}/></article><article><h3>BattleScore medio por equipo</h3><LineChart label="BattleScore medio por equipo" metric="battleScore" series={battleScoreTeams} duration={duration} inspection={inspection} onInspect={setInspection}/></article></div></section>

      <section className="deep-panel"><header><div><span className="eyebrow">PARTICIPANTES</span><h2>Selecciona entre 1 y 10 campeones</h2></div><small>{activeTitle(activePlayers)}</small></header><div className="deep-rosters"><Roster title="Equipo rival" players={enemies} selected={selected} assets={assets} toggle={toggle} paletteIndex={paletteIndex}/><Roster title="Tu equipo" players={allies} selected={selected} assets={assets} toggle={toggle} paletteIndex={paletteIndex}/></div></section>

      {selected.length > 0 ? <section className="deep-panel"><header><div><span className="eyebrow">COMPARATIVA</span><h2>{activeTitle(activePlayers)}</h2></div><small>Inspección sincronizada · {activePlayers.length} participantes</small></header>
        <div className="deep-chart-grid" onPointerLeave={() => setInspection(null)}>{metricDefinitions.map(([label, metric]) => <article className="deep-chart-card" key={metric}><h3>{label}</h3>{metric === 'vision' ? <VisionBarChart active={activePlayers} assets={assets} paletteIndex={paletteIndex}/> : <ParticipantChart label={label} metric={metric} active={activePlayers} frames={detail.frames} events={detail.events} duration={duration} intervalMs={detail.battle_score?.visualization?.sample_interval_ms ?? 30_000} smoothingIntensity={detail.battle_score?.visualization?.smoothing_intensity ?? 0.20} paletteIndex={paletteIndex} inspection={inspection} onInspect={setInspection}/>}</article>)}</div>
      </section> : <div className="deep-state">Selecciona al menos un retrato para comparar su evolución durante la partida.</div>}

      <section className="deep-panel deep-chronology"><header><div><span className="eyebrow">CRONOLOGÍA</span><h2>Eventos de la partida</h2></div><small>{visibleParticipantEventCount} eventos visibles</small></header>
        <div className="deep-event-filters" aria-label="Filtros de eventos">{([['kill', 'Asesinato'], ['death', 'Muerte'], ['assist', 'Asistencia'], ['purchase', 'Compra'], ['sale', 'Venta'], ['objective', 'Objetivo']] as const).map(([kind, label]) => <button type="button" key={kind} className={timelineFilters[kind] ? 'active' : ''} aria-pressed={timelineFilters[kind]} onClick={() => setTimelineFilters(current => ({ ...current, [kind]: !current[kind] }))}>{label}</button>)}</div>
        <div className="deep-timeline-scroll"><div className="deep-timeline" style={{ minWidth: `${timelineWidth}px` }}>
          <div className="deep-timeline-ruler"><span className="deep-ruler-spacer">TIEMPO</span><div className="deep-ruler-track">{rulerTicks.map((tick, index) => <span key={`${tick}-${index}`} style={{ left: `${tick / duration * 100}%` }}>{tick === duration ? clock(tick) : minuteLabel(tick)}</span>)}</div></div>
          <div className="deep-timeline-lane deep-objective-lane"><div className="deep-lane-player objective-label"><span className="deep-objective-mark">◇</span><b>Objetivos</b></div><div className="deep-lane-track objective-track">{rulerTicks.map(tick => <i key={`objective-tick-${tick}`} className="deep-track-tick" style={{ left: `${tick / duration * 100}%` }}/>) }{layoutGlobalObjectives(objectiveEvents, duration, timelineTrackWidth).map((placed, markerIndex) => { const event = placed.event; const teamLabel = event.side === 'allied' ? 'Tu equipo' : event.side === 'enemy' ? 'Equipo rival' : 'Equipo no identificado'; return <button type="button" key={`objective-${event.id}-${markerIndex}`} className={`deep-event objective global-objective ${event.side}`} style={{ left: `${placed.ratio * 100}%`, '--event-color': event.side === 'allied' ? '#6bc99b' : event.side === 'enemy' ? '#df7b70' : '#b1a88f' } as CSSProperties} title={`${clock(event.timestamp)} · ${teamLabel} · ${timelineEventLabel(event, 'objective')}`} aria-label={`${clock(event.timestamp)} · ${teamLabel} · ${timelineEventLabel(event, 'objective')}`} onClick={() => setInspection({ time: event.timestamp, metric: 'gold' })}><TimelineEventIcon kind="objective" event={event} itemAssets={itemAssets}/></button>; })}</div></div>
          {selected.length ? activePlayers.map((player, playerIndex) => <div className="deep-timeline-lane" key={player.participantId}>
            <div className="deep-lane-player" style={{ '--player-color': colors[paletteIndex.get(player.participantId) ?? playerIndex] } as CSSProperties}><GameImage src={assets?.champions[player.champion] ?? null} alt={player.champion} className="deep-lane-icon" fallback={player.champion.slice(0, 1)}/><b>{player.champion}</b></div>
            <div className="deep-lane-track">{rulerTicks.map(tick => <i key={`tick-${tick}`} className="deep-track-tick" style={{ left: `${tick / duration * 100}%` }}/>)}{layoutTimelineEvents(participantEventsByPlayer.get(player.participantId) ?? [], player, duration, timelineTrackWidth).map((placed, markerIndex) => { const event = placed.event; return <button type="button" key={`${player.participantId}-${markerIndex}`} className={`deep-event ${placed.kind}`} style={{ left: `${placed.ratio * 100}%`, top: `${5 + placed.lane * 28}px`, '--event-color': colors[paletteIndex.get(player.participantId) ?? playerIndex] } as CSSProperties} title={`${clock(event.timestamp)} · ${player.champion} · ${timelineEventLabel(event, placed.kind)}`} aria-label={`${clock(event.timestamp)} · ${player.champion} · ${timelineEventLabel(event, placed.kind)}`} onClick={() => setInspection({ time: event.timestamp, metric: 'gold' })}><TimelineEventIcon kind={placed.kind} event={event} itemAssets={itemAssets}/></button>; })}</div>
          </div>) : <p className="deep-timeline-empty">Selecciona participantes para ver sus eventos. La fila de objetivos permanece visible.</p>}
        </div></div>
        <div className="deep-event-legend"><span><TimelineEventIcon kind="kill" itemAssets={itemAssets}/> Asesinato</span><span><TimelineEventIcon kind="death" itemAssets={itemAssets}/> Muerte</span><span><TimelineEventIcon kind="assist" itemAssets={itemAssets}/> Asistencia</span><span><TimelineEventIcon kind="purchase" itemAssets={itemAssets}/> Compra</span><span><TimelineEventIcon kind="sale" itemAssets={itemAssets}/> Venta</span><span><TimelineEventIcon kind="objective" itemAssets={itemAssets}/> Objetivo</span></div>
      </section>

      <section className="deep-panel deep-scoreboard">
        <header><div><span className="eyebrow">MARCADOR COMPLETO</span><h2>Comparativa de participantes</h2></div></header>
        <div className="deep-score-columns">
          {([['Tu equipo', allies], ['Equipo rival', enemies]] as const).map(([title, roster]) => <section key={title}>
            <h3>{title} <span>· {roster.reduce((sum, player) => sum + Number(player.kills ?? 0), 0)} bajas</span></h3>
            {roster.map(player => <article className={`deep-score-row ${player.local ? 'local' : ''}`} key={player.participantId}>
              <GameImage src={assets?.champions[player.champion] ?? null} alt={player.champion} className="deep-score-icon" fallback={player.champion.slice(0, 1)}/>
              <div className="deep-score-player">
                <div className="deep-score-heading">
                  <div className="deep-score-title"><b>{player.champion}{player.local ? ' · Tú' : ''}</b><small>{player.role || 'Posición no disponible'} <i/> Nv. {player.level ?? '—'}</small></div>
                  <span className="deep-final-battlescore" style={{ color: battleScoreColor(player.battleScore) }}>{formatBattleScore(player.battleScore)}</span>
                  {scoreAward(player, participants) && <span className={`deep-award ${scoreAward(player, participants)!.toLowerCase().replace('/', '-')}`}>{scoreAward(player, participants)}</span>}
                </div>
                <div className="deep-score-stats" aria-label={`Estadísticas de ${player.champion}`}>
                  <span className="deep-score-kda"><b>{player.kills ?? '—'}</b><i>/</i><b className="death">{player.deaths ?? '—'}</b><i>/</i><b>{player.assists ?? '—'}</b><small>K / D / A</small></span>
                  <span><b>{player.cs ?? '—'}</b><small>CS</small></span>
                  <span><b>{fmt(player.championDamageDealt)}</b><small>Daño a campeones</small></span>
                  <span><b>{fmt(finalFrameValue(detail.frames, player.participantId, 'allSourceDamageReceived'))}</b><small>Daño recibido</small></span>
                  <span><b>{player.vision ?? '—'}</b><small>Visión</small></span>
                </div>
                <div className="deep-score-loadout">
                  <div className="deep-loadout-group"><small>Runas</small><div className="deep-loadout-icons">{participantRuneIds(player.runes).map((id, index) => <GameImage key={`${id}-${index}`} src={itemAssets[`rune:${id}`] ?? null} alt={index === 0 ? `Runa clave ${id}` : `Runa ${id}`} title={index === 0 ? `Runa clave ${id}` : `Runa ${id}`} className={index === 0 ? 'deep-rune-icon deep-keystone-icon' : 'deep-rune-icon'} fallback="·"/>)}</div></div>
                  <div className="deep-loadout-group"><small>Hechizos</small><div className="deep-loadout-icons">{spellIdsFor(player).map((id, index) => <GameImage key={`${id}-${index}`} src={itemAssets[`spell:${id}`] ?? null} alt={`Hechizo ${id}`} title={`Hechizo de invocador ${id}`} className="deep-spell-icon" fallback="·"/>)}</div></div>
                  <div className="deep-loadout-group deep-build-group"><small>Objetos</small><div className="deep-item-build">{(player.items ?? []).filter(id => id > 0).map((id, index) => <GameImage key={`${id}-${index}`} src={itemAssets[`item:${id}`] ?? null} alt={`Objeto ${id}`} title={`Objeto ${id}`} className="deep-score-item" fallback="·"/>)}</div></div>
                </div>
              </div>
            </article>)}
          </section>)}
        </div>
      </section>
    </div>
    {inspection?.cursor && <div className="deep-chart-cursor-tooltip" role="status" style={{ left: tooltipLeft, top: tooltipTop }}><div className="deep-inspection-heading"><b>{inspection.source === 'teams' ? inspection.metric === 'battleScore' ? 'BattleScore medio por equipo' : 'Oro acumulado por equipo' : inspectionMetric?.[0] ?? 'Comparativa'} · {clock(inspection.time)}</b><small>{inspection.source === 'teams' ? inspection.metric === 'battleScore' ? 'Promedio por participante' : 'Oro total' : inspection.metric === 'battleScore' ? 'Puntuación mostrada en la curva' : `${inspectionMetric?.[2] ?? ''} al minuto ${minuteLabel(inspection.time)}`}</small></div><div className="deep-inspection-values">{inspection.source === 'teams' ? inspectionTeamValues.map(({ series, value }) => <span key={series.label} style={{ '--player-color': series.color } as CSSProperties}><i className="deep-inspection-team-mark"/><b>{series.label}</b><strong>{value == null ? 'No disponible' : formatMetric(inspection.metric, value)}</strong></span>) : inspectionPlayerValues.map(({ player, value, rawValue }) => <span key={player.participantId} style={{ '--player-color': colors[paletteIndex.get(player.participantId) ?? 0] } as CSSProperties}><GameImage src={assets?.champions[player.champion] ?? null} alt="" className="deep-inspection-icon" fallback=""/><b>{player.champion}</b><strong>{value == null ? 'No disponible' : formatMetric(inspection.metric, value)}</strong>{inspection.metric === 'battleScore' && rawValue != null && value != null && Math.abs(rawValue - value) > 0.005 && <small>Real sin suavizar: {formatMetric('battleScore', rawValue)}</small>}</span>)}</div></div>}
    <div id="deep-view-panel-report" role="tabpanel" aria-labelledby="deep-view-tab-report" className="deep-analysis-scroll deep-view-panel deep-report-scroll" hidden={activeView !== 'report'}>
      <AiMatchReport key={matchId} value={aiAnalysis ?? null} itemAssets={itemAssets} timelineIndex={detail.timeline_event_index ?? null} busy={aiBusy} error={aiError} onGenerate={() => void openAI(Boolean(detail.ai_analysis))} matchId={matchId} cachedMatchups={detail.combat_matchups ?? null}/>
    </div>
  </main>;
}

function Roster({ title, players, selected, assets, toggle, paletteIndex }: { title: string; players: SoloQParticipant[]; selected: number[]; assets?: HomeAssets; toggle: (id: number) => void; paletteIndex: Map<number, number> }) {
  return <section className="deep-roster"><h3>{title}</h3><div>{players.map(player => <button type="button" key={player.participantId} className={`deep-portrait ${selected.includes(player.participantId) ? 'active' : ''} ${player.local ? 'local' : ''}`} style={{ '--player-color': colors[paletteIndex.get(player.participantId) ?? 0] } as CSSProperties} onClick={() => toggle(player.participantId)} title={`${player.champion}${player.local ? ' · Tú' : ''}`} aria-pressed={selected.includes(player.participantId)}><GameImage src={assets?.champions[player.champion] ?? null} alt={player.champion} className="deep-roster-icon" fallback={player.champion.slice(0, 1)}/><span>{player.champion}</span><strong className="deep-roster-score" style={{ color: battleScoreColor(player.battleScore) }}>{formatBattleScore(player.battleScore)}</strong></button>)}</div></section>;
}

function teamBattleScore(participants: SoloQParticipant[], duration: number, intervalMs: number, smoothingIntensity: number): Series[] {
  return (['allied', 'enemy'] as const).map((side, index) => {
    const members = participants.filter(player => player.side === side);
    if (!members.length || members.some(player => !(player.battleScoreSeries?.length))) {
      return { label: side === 'allied' ? 'Tu equipo' : 'Equipo rival', color: index === 0 ? '#6bc99b' : '#db746b', points: [] };
    }
    const timestamps = [...new Set(members.flatMap(player => player.battleScoreSeries?.map(point => point.timestamp) ?? []))].sort((a, b) => a - b);
    const points = timestamps.flatMap(timestamp => {
      const values = members.map(player => battleScoreAt(player.battleScoreSeries ?? [], timestamp)).filter((value): value is number => value != null && Number.isFinite(value));
      return values.length === members.length && members.length ? [{ x: timestamp, y: values.reduce((sum, value) => sum + value, 0) / members.length }] : [];
    });
    const finalScore = points[points.length - 1]?.y;
    const displayed = resampleAndSmoothBattleScore(
      points.map(point => ({ timestamp: point.x, score: point.y })),
      duration,
      finalScore,
      intervalMs,
      1 - smoothingIntensity,
    ).map(point => ({ x: point.x, y: point.y }));
    return { label: side === 'allied' ? 'Tu equipo' : 'Equipo rival', color: index === 0 ? '#6bc99b' : '#db746b', points: displayed };
  });
}

function scoreAward(player: SoloQParticipant, participants: SoloQParticipant[]): 'MVP' | 'SVP' | 'MVP/SVP' | null {
  const scored = participants.filter(item => item.battleScore != null && Number.isFinite(item.battleScore));
  if (!scored.length || player.battleScore == null) return null;
  const bestOverall = [...scored].sort((a, b) => Number(b.battleScore) - Number(a.battleScore) || a.participantId - b.participantId)[0];
  const losingSide = participants.find(item => item.win === false)?.side;
  const bestLosing = losingSide ? [...scored].filter(item => item.side === losingSide).sort((a, b) => Number(b.battleScore) - Number(a.battleScore) || a.participantId - b.participantId)[0] : undefined;
  const isMvp = bestOverall?.participantId === player.participantId;
  const isSvp = bestLosing?.participantId === player.participantId;
  return isMvp && isSvp ? 'MVP/SVP' : isMvp ? 'MVP' : isSvp ? 'SVP' : null;
}

function teamGold(frames: SoloQFrame[], participants: SoloQParticipant[]): Series[] {
  const sides = new Map(participants.map(player => [player.participantId, player.side]));
  const grouped = new Map<number, { allied: number; enemy: number }>();
  for (const frame of frames) {
    if (!Number.isFinite(frame.timestamp) || frame.gold == null) continue;
    const values = grouped.get(frame.timestamp) ?? { allied: 0, enemy: 0 };
    const side = sides.get(frame.participantId);
    if (side === 'allied') values.allied += frame.gold;
    if (side === 'enemy') values.enemy += frame.gold;
    grouped.set(frame.timestamp, values);
  }
  const points = [...grouped.entries()].sort((a, b) => a[0] - b[0]);
  return [{ label: 'Tu equipo', color: '#6bc99b', points: points.map(([x, value]) => ({ x, y: value.allied })) }, { label: 'Equipo rival', color: '#db746b', points: points.map(([x, value]) => ({ x, y: value.enemy })) }];
}

function seriesValueAt(series: Series, time: number): number | null {
  let found: number | null = null;
  for (const point of series.points) {
    if (point.x > time) break;
    found = point.y;
  }
  return found;
}

function LineChart({ label, metric, series, duration, inspection, onInspect }: { label: string; metric: 'gold' | 'battleScore'; series: Series[]; duration: number; inspection: Inspection; onInspect: (value: Inspection) => void }) {
  const all = series.flatMap(item => item.points);
  if (!all.length) return <div className="deep-chart-empty">{metric === 'gold' ? 'No hay puntos de oro disponibles en la cronología.' : 'No hay BattleScore disponible para comparar los equipos.'}</div>;
  const markerX = inspection ? 42 + Math.max(0, Math.min(1, inspection.time / duration)) * 748 : null;
  const handlePointer = (event: ReactPointerEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const start = rect.width * 42 / 800, plotWidth = rect.width * 748 / 800;
    if (plotWidth > 0) onInspect({ time: Math.round(Math.max(0, Math.min(1, (event.clientX - rect.left - start) / plotWidth)) * duration), metric, source: 'teams', cursor: { x: event.clientX, y: event.clientY } });
  };
  return <div className="deep-chart" onPointerLeave={() => onInspect(null)}><svg viewBox="0 0 800 180" preserveAspectRatio="none" role="img" aria-label={label} onPointerMove={handlePointer}><rect x="42" y="12" width="748" height="150" fill="transparent" pointerEvents="all"/><Grid/><ChartPaths series={series} maxX={duration} metric={metric}/>{markerX != null && <line className="deep-chart-crosshair" x1={markerX} x2={markerX} y1="12" y2="162"/>}</svg><div className="deep-chart-axis"><span>0:00</span><span>{clock(duration / 2)}</span><span>{clock(duration)}</span></div><div className="deep-chart-legend">{series.map(item => <span key={item.label}><i style={{ background: item.color }}/>{item.label}</span>)}</div></div>;
}
function Grid() { return <g className="deep-chart-grid-lines">{[0, 1, 2, 3, 4].map(value => <line key={value} x1="42" x2="790" y1={12 + value * 36} y2={12 + value * 36}/>)}</g>; }
function ChartPaths({ series, maxX, metric = 'gold' }: { series: Series[]; maxX: number; metric?: 'gold' | 'battleScore' }) {
  const all = series.flatMap(item => item.points);
  const domain = metric === 'battleScore' ? battleScoreDomain(all) : [0, Math.max(1, ...all.map(point => point.y))] as [number, number];
  const yFor = (value: number) => 162 - (value - domain[0]) / Math.max(0.01, domain[1] - domain[0]) * 150;
  return <>{series.map(item => { const path = item.points.map((point, index) => `${index ? 'L' : 'M'} ${42 + point.x / maxX * 748} ${yFor(point.y)}`).join(' '); return <g key={item.label}><path d={path} fill="none" stroke={item.color} strokeWidth="3" vectorEffect="non-scaling-stroke"/>{item.points.length === 1 && <circle cx={42 + item.points[0].x / maxX * 748} cy={yFor(item.points[0].y)} r="4" fill={item.color}/>}</g>; })}</>;
}

function battleScoreDomain(points: Array<{ x: number; y: number }>): [number, number] {
  if (!points.length) return [0.1, 10];
  const values = points.map(point => point.y).filter(Number.isFinite);
  if (!values.length) return [0.1, 10];
  const dataMin = Math.min(...values), dataMax = Math.max(...values);
  const padding = Math.max(0.12, (dataMax - dataMin) * 0.08);
  let low = Math.max(0.1, dataMin - padding);
  let high = Math.min(10, dataMax + padding);
  if (high - low < 1.25) {
    const center = (low + high) / 2;
    low = Math.max(0.1, center - 0.625);
    high = Math.min(10, center + 0.625);
  }
  return [low, high];
}

function scoreY(value: number, domain: [number, number], top: number, height: number) {
  return top + (domain[1] - value) / (domain[1] - domain[0]) * height;
}

function ParticipantChart({ label, metric, active, frames, events, duration, intervalMs, smoothingIntensity, paletteIndex, inspection, onInspect }: { label: string; metric: MetricKey; active: SoloQParticipant[]; frames: SoloQFrame[]; events: SoloQEvent[]; duration: number; intervalMs: number; smoothingIntensity: number; paletteIndex: Map<number, number>; inspection: Inspection; onInspect: (value: Inspection) => void }) {
  const series = useMemo(() => active.map(player => ({
    player,
    points: metric === 'battleScore'
      ? resampleAndSmoothBattleScore(player.battleScoreSeries ?? [], duration, player.battleScore,
          intervalMs, 1 - smoothingIntensity).map(({ x, y }) => ({ x, y }))
      : metricPoints(metric, player, frames, events),
    color: colors[paletteIndex.get(player.participantId) ?? 0],
  })), [active, metric, frames, events, duration, intervalMs, smoothingIntensity, paletteIndex]);
  const allPoints = series.flatMap(item => item.points);
  const scoreDomain = battleScoreDomain(allPoints);
  const maxY = metric === 'battleScore' ? scoreDomain[1] : Math.max(1, ...allPoints.map(point => point.y));
  const yFor = (value: number) => metric === 'battleScore' ? scoreY(value, scoreDomain, 14, 102) : 116 - value / maxY * 102;
  const markerX = inspection ? 8 + Math.max(0, Math.min(1, inspection.time / duration)) * 384 : null;
  const handlePointer = (event: ReactPointerEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    if (!rect.width) return;
    const plotStart = rect.width * 0.02;
    const plotWidth = rect.width * 0.96;
    const ratio = Math.max(0, Math.min(1, (event.clientX - rect.left - plotStart) / plotWidth));
    onInspect({ time: Math.round(ratio * duration), metric, cursor: { x: event.clientX, y: event.clientY } });
  };
  return <div className="deep-mini-chart" onPointerLeave={() => onInspect(null)}><svg viewBox="0 0 400 130" preserveAspectRatio="none" aria-label={label} onPointerMove={handlePointer}>
    <rect x="8" y="12" width="384" height="104" fill="transparent" pointerEvents="all"/><GridMini/>{series.map(item => { const path = item.points.map((point, index) => `${index ? 'L' : 'M'} ${8 + point.x / duration * 384} ${yFor(point.y)}`).join(' '); const current = inspection?.metric === metric ? (metric === 'battleScore' ? displayedBattleScoreAt(item.points, inspection.time) : metricValueAt(metric, item.player, frames, events, inspection.time)) : null; return <g key={item.player.participantId}><path d={path} fill="none" stroke={item.color} strokeWidth="2.5" vectorEffect="non-scaling-stroke"/>{current != null && markerX != null && <circle cx={markerX} cy={yFor(current)} r="3.4" fill={item.color} stroke="#151411" strokeWidth="1.5"/>}</g>; })}
    {markerX != null && <line className="deep-chart-crosshair" x1={markerX} x2={markerX} y1="12" y2="116"/>}
</svg><div className="deep-mini-legend">{series.map(item => <span key={item.player.participantId} style={{ '--player-color': item.color } as CSSProperties}><i/>{item.player.champion}</span>)}</div>{series.every(item => !item.points.length) && <small className="deep-chart-empty">Este dato no está disponible en la cronología de Riot.</small>}</div>;
}

function VisionBarChart({ active, assets, paletteIndex }: { active: SoloQParticipant[]; assets?: HomeAssets; paletteIndex: Map<number, number> }) {
  const [hovered, setHovered] = useState<{ player: SoloQParticipant; x: number; y: number } | null>(null);
  const maxVision = Math.max(1, ...active.map(player => player.vision ?? 0));
  return <div className="deep-mini-chart deep-vision-chart" onPointerLeave={() => setHovered(null)}>
    <div className="deep-vision-bars" style={{ '--vision-count': active.length } as CSSProperties} role="img" aria-label={`Puntuación final de visión de ${active.length} participantes`}>
      {active.map((player, index) => {
        const value = player.vision;
        const height = value == null ? 0 : Math.max(0, value / maxVision * 76);
        const color = colors[paletteIndex.get(player.participantId) ?? index];
        return <div className="deep-vision-column" key={player.participantId} style={{ '--player-color': color } as CSSProperties} onPointerMove={event => setHovered({ player, x: event.clientX, y: event.clientY })}>
          <span className="deep-vision-value">{value == null ? '—' : fmt(value)}</span>
          <div className="deep-vision-track" aria-hidden="true"><i style={{ height: `${height}px` }}/></div>
          <GameImage src={assets?.champions[player.champion] ?? null} alt={player.champion} className="deep-vision-icon" fallback={player.champion.slice(0, 1)}/>
          <span className="deep-vision-name" title={player.champion}>{player.champion}</span>
        </div>;
      })}
    </div>
    {hovered && <div className="deep-vision-tooltip" role="status" style={{ left: Math.min(hovered.x + 12, window.innerWidth - 190), top: Math.min(hovered.y + 12, window.innerHeight - 62) }}><b>{hovered.player.champion}</b><span>{hovered.player.vision == null ? 'Visión no disponible' : `${fmt(hovered.player.vision)} pts. de visión`}</span></div>}
    {active.every(player => player.vision == null) && <small className="deep-chart-empty">La puntuación final de visión no está disponible.</small>}
  </div>;
}
function GridMini() { return <g className="deep-chart-grid-lines">{[0, 1, 2, 3].map(value => <line key={value} x1="8" x2="392" y1={14 + value * 34} y2={14 + value * 34}/>)}</g>; }

function metricPoints(metric: MetricKey, player: SoloQParticipant, frames: SoloQFrame[], events: SoloQEvent[]) {
  const own = frames.filter(frame => frame.participantId === player.participantId).sort((a, b) => a.timestamp - b.timestamp);
  if (metric === 'gold') return own.flatMap(frame => frame.gold == null ? [] : [{ x: frame.timestamp, y: frame.gold }]);
  if (metric === 'xp') return own.flatMap(frame => frame.xp == null ? [] : [{ x: frame.timestamp, y: frame.xp }]);
  if (metric === 'cs') return own.flatMap(frame => frame.minions == null && frame.jungleMinions == null ? [] : [{ x: frame.timestamp, y: (frame.minions ?? 0) + (frame.jungleMinions ?? 0) }]);
  if (metric === 'battleScore') return (player.battleScoreSeries ?? []).map(point => ({ x: point.timestamp, y: point.score }));
  if (metric === 'championDamageDealt') return own.flatMap(frame => frame.championDamageDealt == null ? [] : [{ x: frame.timestamp, y: frame.championDamageDealt }]);
  if (metric === 'allSourceDamageReceived') return own.flatMap(frame => frame.allSourceDamageReceived == null ? [] : [{ x: frame.timestamp, y: frame.allSourceDamageReceived }]);
  if (metric === 'usefulDamageReceived') {
    const cumulative = new Map<number, number>(); let total = 0;
    for (const event of [...events].sort((a, b) => a.timestamp - b.timestamp)) {
      let amount = 0;
      if (metric === 'usefulDamageReceived' && event.victimId === player.participantId && event.usefulDamageReceived != null) { total = Math.max(total, Number(event.usefulDamageReceived)); cumulative.set(event.timestamp, total); continue; }
      if (amount > 0) { total += amount; cumulative.set(event.timestamp, total); }
    }
    return [...cumulative.entries()].map(([x, y]) => ({ x, y }));
  }
  return [];
}
function metricValueAt(metric: MetricKey, player: SoloQParticipant, frames: SoloQFrame[], events: SoloQEvent[], time: number): number | null {
  const points = metricPoints(metric, player, frames, events);
  if (metric === 'battleScore') return battleScoreAt(points.map(point => ({ timestamp: point.x, score: point.y })), time);
  let found: number | null = null;
  for (const point of points) { if (point.x > time) break; found = point.y; }
  return found;
}
function formatMetric(metric: MetricKey, value: number) {
  const number = value.toLocaleString('es-ES', { minimumFractionDigits: metric === 'battleScore' ? 2 : 0, maximumFractionDigits: metric === 'vision' ? 1 : metric === 'battleScore' ? 2 : 0 });
  if (metric === 'gold') return `${number} oro`;
  if (metric === 'xp') return `${number} XP`;
  if (metric === 'cs') return `${number} CS`;
  if (metric === 'championDamageDealt') return number + ' de daño infligido';
  if (metric === 'allSourceDamageReceived') return number + ' de daño recibido';
  if (metric === 'usefulDamageReceived') return number + ' de daño útil recibido';
  if (metric === 'vision') return `${number} pts.`;
  if (metric === 'battleScore') return `${number} pts.`;
  return number;
}

function isObjectiveEvent(event: SoloQEvent) {
  return ['ELITE_MONSTER_KILL', 'BUILDING_KILL'].includes(event.type);
}
function timelineEventKind(event: SoloQEvent, playerId: number): PlacedTimelineEvent['kind'] {
  if (event.type === 'CHAMPION_KILL') return event.killerId === playerId ? 'kill' : event.victimId === playerId ? 'death' : 'assist';
  if (event.type === 'ITEM_SOLD') return 'sale';
  if (event.type === 'ITEM_PURCHASED') return 'purchase';
  return 'objective';
}
function layoutGlobalObjectives(events: SoloQEvent[], duration: number, width: number): PlacedTimelineEvent[] {
  return [...events].sort((a, b) => a.timestamp - b.timestamp || a.id.localeCompare(b.id)).map(event => {
    const ratio = Math.max(0, Math.min(1, event.timestamp / duration));
    return { x: ratio * width, ratio, lane: 0, event, kind: 'objective' as const };
  });
}
function layoutTimelineEvents(events: SoloQEvent[], player: SoloQParticipant, duration: number, width: number): PlacedTimelineEvent[] {
  const ownEvents = events.filter(event => event.participantIds.includes(player.participantId)).sort((a, b) => a.timestamp - b.timestamp);
  const lanes: PlacedTimelineEvent[][] = [[], [], []];
  for (const event of ownEvents) {
    const ratio = Math.max(0, Math.min(1, event.timestamp / duration));
    const x = ratio * width;
    const lane = lanes.findIndex(items => {
      const previous = items[items.length - 1];
      return !previous || x - previous.x >= 34;
    });
    const targetLane = lane >= 0 ? lane : lanes.reduce((best, items, index) => {
      const previous = items[items.length - 1];
      const bestPrevious = lanes[best][lanes[best].length - 1];
      const gap = previous ? x - previous.x : Number.POSITIVE_INFINITY;
      const bestGap = bestPrevious ? x - bestPrevious.x : Number.POSITIVE_INFINITY;
      return gap > bestGap ? index : best;
    }, 0);
    lanes[targetLane].push({ x, ratio, lane: targetLane, event, kind: timelineEventKind(event, player.participantId) });
  }
  return lanes.flat().sort((a, b) => a.x - b.x);
}
function timelineEventLabel(event: SoloQEvent, kind: PlacedTimelineEvent['kind']) {
  if (kind === 'kill') return `Asesinato · ${event.victimChampion ?? 'rival'}`;
  if (kind === 'death') return `Muerte · ${event.killerChampion ?? 'rival'}`;
  if (kind === 'assist') return `Asistencia · ${event.killerChampion ?? 'aliado'} eliminó a ${event.victimChampion ?? 'rival'}`;
  if (kind === 'purchase' || kind === 'sale') return `${kind === 'purchase' ? 'Compra' : 'Venta'} · ${event.itemName || (event.itemId ? `Objeto ${event.itemId}` : 'Objeto')}`;
  return `Objetivo · ${event.category || event.monsterType || event.buildingType || 'Objetivo de mapa'}`;
}
function TimelineEventIcon({ kind, event, itemAssets }: { kind: PlacedTimelineEvent['kind']; event?: SoloQEvent; itemAssets: Record<string, string | null> }) {
  if ((kind === 'purchase' || kind === 'sale') && event?.itemId && itemAssets[`item:${event.itemId}`]) return <GameImage src={itemAssets[`item:${event.itemId}`] ?? null} alt="" className="deep-event-item" fallback=""/>;
  if (kind === 'objective') {
    const source = `${event?.category ?? ''} ${event?.monsterType ?? ''} ${event?.buildingType ?? ''}`.toUpperCase();
    const objective = source.includes('DRAGON') || source.includes('DRAGÓN')
      ? <><path d="M4 15c3-1 4-4 5-7l3 3 5-4-1 6 4 2-7 1-3 4-2-4z"/><path d="m8 10-4-3 1 6M15 13l4-2"/></>
      : source.includes('BARON') || source.includes('NASHOR')
        ? <><path d="M4 18c1-5 2-10 8-12l2 4 5-2-1 7-6 2-2 4-2-4z"/><path d="m13 10 3 1m-7 1-3-2"/></>
        : source.includes('HERALD') || source.includes('HERALDO')
          ? <><path d="M3 12s3-6 9-6 9 6 9 6-3 6-9 6-9-6-9-6Z"/><circle cx="12" cy="12" r="3"/><path d="m12 9 2 3-2 3-2-3z"/></>
          : source.includes('HORDE') || source.includes('LARVA') || source.includes('GRUB')
            ? <><circle cx="7" cy="9" r="2"/><circle cx="16" cy="8" r="2"/><circle cx="12" cy="16" r="2"/><path d="m8 11 3 3m4-4-2 4"/></>
            : source.includes('TOWER') || source.includes('TORRE')
              ? <><path d="M7 21V9l2-5h6l2 5v12M5 9h14M9 13h6M9 17h6M12 4v5"/></>
              : source.includes('INHIBITOR') || source.includes('INHIBIDOR')
                ? <><path d="M6 4h12v16H6zM9 7h6v10H9zM3 4v16M21 4v16"/></>
                : source.includes('NEXUS') || source.includes('NEXO')
                  ? <><circle cx="12" cy="12" r="7"/><path d="m12 2 1.5 5M22 12l-5 1.5M12 22l-1.5-5M2 12l5-1.5M9 9l6 6m0-6-6 6"/></>
                  : <><path d="m12 3 8 4v5c0 5-3.5 8-8 10-4.5-2-8-5-8-10V7z"/><circle cx="12" cy="12" r="3"/></>;
    return <svg className="deep-event-glyph" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{objective}</svg>;
  }
  const paths: Record<PlacedTimelineEvent['kind'], ReactNode> = {
    kill: <><path d="m5 5 14 14M7 3l4 4m6 10 4 4M3 7l4 4m10 6 4 4M15 3l6 6M3 15l6 6"/><path d="m7 17 10-10"/></>,
    death: <><path d="M6 18a7 7 0 1 1 12 0v3H6z"/><circle cx="9" cy="12" r="1"/><circle cx="15" cy="12" r="1"/><path d="M9 17h6"/></>,
    assist: <><path d="M12 21s8-4 8-10V5l-8-3-8 3v6c0 6 8 10 8 10z"/><path d="m8 12 2.5 2.5L16 9"/></>,
    purchase: <><path d="M3 7h18l-2 13H5zM3 7l2-4h14l2 4"/><path d="M9 11h6"/></>,
    sale: <><path d="M4 7h16l-2 13H6zM4 7l2-4h12l2 4"/><path d="m9 11 6 6m0-6-6 6"/></>,
    objective: <><path d="M12 3 20 7v5c0 5-4 8-8 10-4-2-8-5-8-10V7z"/><circle cx="12" cy="11" r="3"/><path d="M12 8v6m-3-3h6"/></>,
  };
  return <svg className="deep-event-glyph" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[kind]}</svg>;
}

function ImprovementCard({ finding }: { finding: ImprovementFinding }) {
  const cardRef = useRef<HTMLElement>(null);
  const tooltipRef = useRef<HTMLDivElement>(null);
  const tooltipContentRef = useRef<HTMLDivElement>(null);
  const timerRef = useRef<number | undefined>(undefined);
  const [visible, setVisible] = useState(false);
  const [compactTooltip, setCompactTooltip] = useState(false);
  const [tooltipHeight, setTooltipHeight] = useState(0);
  const [position, setPosition] = useState<CSSProperties>({ left: 8, top: 8 });
  const measured = Number(finding.measured_value).toLocaleString('es-ES', {maximumFractionDigits: 2});
  const statistic = `${measured} ${finding.unit}`;
  const evidence = finding.evidence?.length ? `${finding.evidence.length} evento(s) vinculado(s)` : '';
  const tooltipId = `improvement-tip-${finding.achievement_id}`;
  const showAfterDelay = () => {
    window.clearTimeout(timerRef.current);
    timerRef.current = window.setTimeout(() => setVisible(true), 190);
  };
  const dismiss = () => {
    window.clearTimeout(timerRef.current);
    setVisible(false);
    setCompactTooltip(false);
    setTooltipHeight(0);
  };

  useLayoutEffect(() => {
    if (!visible || !cardRef.current || !tooltipRef.current || !tooltipContentRef.current) return;
    const anchor = cardRef.current.getBoundingClientRect();
    const tipElement = tooltipRef.current;
    const tip = tipElement.getBoundingClientRect();
    const visual = window.visualViewport;
    const leftBound = visual?.offsetLeft ?? 0;
    const topBound = visual?.offsetTop ?? 0;
    const rightBound = leftBound + (visual?.width ?? window.innerWidth);
    const bottomBound = topBound + (visual?.height ?? window.innerHeight);
    const gap = 10;
    const availableHeight = Math.max(100, bottomBound - topBound - 16);
    const tipStyle = window.getComputedStyle(tipElement);
    const verticalPadding = parseFloat(tipStyle.paddingTop) + parseFloat(tipStyle.paddingBottom);
    const naturalHeight = Math.ceil(tooltipContentRef.current.scrollHeight + verticalPadding + 2);
    if (naturalHeight > availableHeight && !compactTooltip) { setCompactTooltip(true); return; }
    const measuredHeight = naturalHeight;
    if (tooltipHeight !== measuredHeight) setTooltipHeight(measuredHeight);
    let left = anchor.left;
    if (left + tip.width > rightBound - 8) left = anchor.right - tip.width;
    left = Math.max(leftBound + 8, Math.min(left, rightBound - tip.width - 8));
    let top = anchor.top - measuredHeight - gap;
    if (top < topBound + 8) top = anchor.bottom + gap;
    top = Math.max(topBound + 8, Math.min(top, bottomBound - measuredHeight - 8));
    setPosition({ left, top });
  }, [visible, compactTooltip, tooltipHeight]);

  useEffect(() => {
    if (!visible) return;
    const hide = () => setVisible(false);
    window.addEventListener('scroll', hide, true);
    window.addEventListener('resize', hide);
    window.visualViewport?.addEventListener('resize', hide);
    window.visualViewport?.addEventListener('scroll', hide);
    return () => {
      window.removeEventListener('scroll', hide, true);
      window.removeEventListener('resize', hide);
      window.visualViewport?.removeEventListener('resize', hide);
      window.visualViewport?.removeEventListener('scroll', hide);
    };
  }, [visible]);

  useEffect(() => () => window.clearTimeout(timerRef.current), []);
  const detailLabel = `${finding.name}. Severidad ${finding.severity_label}. Medición: ${statistic}. ${finding.description} ${finding.severity_reason} Cómo mejorarlo: ${finding.recommendation} Fuente: ${finding.source}`;
  return <article ref={cardRef} className={`deep-medal-card deep-improvement-card severity-${finding.severity}`} tabIndex={0}
    aria-label={detailLabel} aria-describedby={visible ? tooltipId : undefined}
    onPointerEnter={event => { if (event.pointerType === 'mouse') showAfterDelay(); }} onPointerLeave={dismiss}
    onFocus={event => { if (event.currentTarget.matches(':focus-visible')) setVisible(true); }} onBlur={dismiss}>
    <span className="medal-mark"><MedalGlyph kind={improvementIcon(finding.achievement_id)}/></span>
    <b>{finding.name}</b><strong>{statistic}</strong>
    {visible && createPortal(<div ref={tooltipRef} id={tooltipId} className="deep-improvement-tooltip" role="tooltip" style={{
      ...position, display: 'grid', alignContent: 'start', gap: compactTooltip ? 4 : 6,
      boxSizing: 'border-box', width: 'min(600px, calc(100vw - 28px))',
      height: tooltipHeight ? `${tooltipHeight}px` : 'max-content', maxHeight: 'none', minHeight: 0,
      overflow: 'visible', padding: compactTooltip ? '10px 12px' : '14px 16px',
      border: '1px solid #806f49', borderRadius: 9, background: '#201f1bf5',
      color: '#e9e1d1', boxShadow: '0 12px 32px #000a',
      fontSize: compactTooltip ? 11 : 13, lineHeight: compactTooltip ? 1.2 : 1.35,
      whiteSpace: 'normal', overflowWrap: 'anywhere', pointerEvents: 'none', zIndex: 2000,
    }}>
      <div ref={tooltipContentRef} style={{ display: 'grid', alignContent: 'start', gap: compactTooltip ? 3 : 5, width: '100%', height: 'max-content' }}>
        <strong style={{ color: '#f0d58a', fontSize: compactTooltip ? 13 : 15, lineHeight: 1.2 }}>{finding.name}</strong>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 14px', alignItems: 'baseline', paddingBottom: 4, borderBottom: '1px solid #ffffff18', fontSize: compactTooltip ? 10 : 12 }}>
          <strong style={{ color: '#ff7772' }}>{finding.severity_label}</strong><span>Medición: {statistic}</span>
        </div>
        <section style={{ display: 'grid', gap: 1 }}><strong style={{ color: '#e5c976', fontSize: compactTooltip ? 11 : 13 }}>Qué se observó</strong><p style={{ margin: 0, fontSize: compactTooltip ? 10 : 12, lineHeight: compactTooltip ? 1.2 : 1.3 }}>{finding.description} {finding.severity_reason}</p></section>
        <section style={{ display: 'grid', gap: 1 }}><strong style={{ color: '#e5c976', fontSize: compactTooltip ? 11 : 13 }}>Sugerencia</strong><p style={{ margin: 0, fontSize: compactTooltip ? 10 : 12, lineHeight: compactTooltip ? 1.2 : 1.3 }}>{finding.recommendation}</p></section>
        <small style={{ paddingTop: 3, borderTop: '1px solid #ffffff18', color: '#aaa18f', fontSize: compactTooltip ? 8 : 9, lineHeight: 1.25 }}>Fuente: {finding.source}{evidence ? ` | ${evidence}` : ''}{finding.data_quality ? ` | Calidad: ${finding.data_quality}` : ''}</small>
      </div>
    </div>, document.body)}
  </article>;
}

function improvementIcon(id: string): string {
  const icons: Record<string, string> = {
    no_pressure: 'towerBroken', forgotten_dragons: 'dragon', no_river_control: 'lamp', dead_too_long: 'clock',
    vision_abandoned: 'eyeOff', too_many_deaths: 'skull', dark_map: 'eyeOff', blind: 'eyeOff', absent_fights: 'swords',
    no_finisher: 'hammer', low_assists: 'swords', unattended_objectives: 'jungle', wasted_farm: 'minion',
    stalled_economy: 'coin', rough_start: 'skull', low_champion_damage: 'swords', xp_behind: 'trend-down',
    lane_behind: 'trend-down', low_protection: 'shield', low_teamfight_presence: 'swords', unspent_gold: 'coin',
  };
  return icons[id] ?? 'skull';
}
function AchievementCard({ medal }: { medal: MatchAchievement }) {
  let value = 'No disponible';
  if (medal.value !== null) {
    if (medal.metric === 'winning_duration') value = clock(medal.value * 1000);
    else if (medal.metric === 'team_damage_share') value = `${medal.value.toLocaleString('es-ES', { maximumFractionDigits: 1 })} %`;
    else {
      const measured = medal.metric === 'cs_per_minute'
        ? medal.value.toLocaleString('es-ES', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
        : medal.decimal ? medal.value.toLocaleString('es-ES', { maximumFractionDigits: 2 }) : Math.round(medal.value).toLocaleString('es-ES');
      value = `${measured} ${medal.unit}`;
    }
  }
  const coverageLabel = medal.coverage === 'partial' ? 'Cobertura parcial del dato observado.' : medal.coverage === 'unavailable' ? 'M?trica no disponible en esta partida.' : medal.source;
  return <article className={`deep-medal-card tier-${medal.tier.toLowerCase().replaceAll(' ', '-')}`} title={coverageLabel}>
    <span className="medal-mark"><MedalGlyph kind={medal.icon}/></span><b>{medal.name}</b>
    <small className="deep-medal-description">{medal.description}</small><strong>{value}{medal.coverage === 'partial' && <i className="deep-medal-partial">Parcial</i>}</strong><em>{medal.tier}</em>
  </article>;
}
function MedalGlyph({ kind }: { kind: string }) {
  const shape: Record<string, ReactNode> = {
    shield: <><path d="m12 3 8 3v5c0 5-3.5 8-8 10-4.5-2-8-5-8-10V6z"/><path d="m8 12 3 3 5-6"/></>, heart: <path d="M20.8 8.7c0 4.2-8.8 10.1-8.8 10.1S3.2 12.9 3.2 8.7A4.2 4.2 0 0 1 12 6.9a4.2 4.2 0 0 1 8.8 1.8Z"/>,
    coin: <><circle cx="12" cy="12" r="9"/><path d="M15 8.5c-.7-.8-1.6-1.2-3-1.2-1.6 0-2.8.9-2.8 2s.8 1.8 2.8 2.2 2.8 1.1 2.8 2.2-1.2 2-2.8 2c-1.3 0-2.4-.4-3.2-1.3M12 5.5v13"/></>, target: <><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1"/></>, swords: <><path d="m5 4 15 15M4 8l4-4 4 4-4 4zM16 12l4 4-4 4-4-4z"/></>, eye: <><path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12Z"/><circle cx="12" cy="12" r="2.5"/></>,
    star: <path d="m12 3 2.7 5.5 6 .9-4.3 4.2 1 6-5.4-2.8-5.4 2.8 1-6-4.3-4.2 6-.9z"/>, crown: <><path d="m3 8 5 4 4-7 4 7 5-4-2 11H5z"/><path d="M5 21h14"/></>, jungle: <><path d="M12 21V10M12 15C6 15 4 11 4 6c5 0 8 2 8 7M12 12c0-5 3-8 8-8 0 5-2 9-8 10"/></>, skull: <><path d="M5 13a7 7 0 1 1 14 0c0 2-1 3-2 4v3H7v-3c-1-1-2-2-2-4Z"/><circle cx="9" cy="12" r="1"/><circle cx="15" cy="12" r="1"/><path d="M10 17h4"/></>,
    dragon: <><path d="M4 16c2-1 3-3 3-6l4 2 4-5 1 5 5 1-5 2-2 5-3-4-4 1z"/><path d="m8 11-4-4 1 6m9-2 3-3"/></>, towerBroken: <><path d="M7 21V9l2-5h6l2 5v12M5 9h14M9 13h6M9 17h6"/><path d="m15 4 2-2m-1 5 4-1"/></>,
    snow: <><path d="M12 2v20M4 6l16 12M20 6 4 18M8 3l4 3 4-3M8 21l4-3 4 3M3 10l4-1-1-4M21 10l-4-1 1-4M3 14l4 1-1 4M21 14l-4 1 1 4"/></>, minion: <><circle cx="12" cy="12" r="9"/><path d="M8 9h.01M16 9h.01M8 15c2.5-2 5.5-2 8 0M12 3v3"/></>, lamp: <><path d="M9 18h6M10 21h4M8 14a6 6 0 1 1 8 0c-.7.6-1 1.3-1 2H9c0-.7-.3-1.4-1-2Z"/></>,
    clock: <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l4 2"/></>, ghost: <><path d="M5 20V10a7 7 0 0 1 14 0v10l-3-2-4 2-4-2z"/><circle cx="9" cy="10" r="1"/><circle cx="15" cy="10" r="1"/></>, shadow: <><path d="M19 4 5 20M7 4h12v12M5 8v12h12"/></>, eyeOff: <><path d="m3 3 18 18M10.6 6.2A10.7 10.7 0 0 1 12 6c6.5 0 10 6 10 6a16 16 0 0 1-3.2 3.7M6.2 6.4C3.5 8 2 12 2 12s3.5 6 10 6c.5 0 1 0 1.4-.1"/></>,
    hammer: <><path d="m14 5 5 5M12 7l5-5 5 5-5 5M3 21l10-10M7 5l5 5"/></>, inhibitor: <><path d="M5 4h14v16H5zM8 7h8v10H8zM3 4v16M21 4v16"/></>,
  };
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{shape[kind] ?? shape.star}</svg>;
}

