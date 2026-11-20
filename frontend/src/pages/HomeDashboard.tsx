import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { CSSProperties } from 'react';
import type { HomeAnalytics, HomeAssets, HomeDashboard as HomeData, HomeMatch, PerformanceEvolutionPoint, RankedRoleStats } from '../types/contracts';
import { GameImage } from '../components/GameImage';
import { Icon } from '../components/Icon';
import { RecentPerformanceCard } from '../components/HomePerformanceCards';
import { WinRateEvolution } from '../components/WinRateEvolution';
import { battleScoreColor, formatBattleScore } from '../utils/battleScore';
import { riotAnalysisActionLabel } from '../services/riotReadiness';
import type { RiotReadiness } from '../services/riotReadiness';

type Props = { active?: boolean; backendReady: boolean; leagueClientConnected: boolean; onOpenSaved: (id?: string, autoAnalyze?: boolean) => void };
const FILTERS: Array<[string, string]> = [['all', 'Todas'], ['420', 'SoloQ'], ['440', 'Flex'], ['450', 'ARAM'], ['normal', 'Normal']];

export const HomeDashboard = memo(function HomeDashboard({ active = true, backendReady, leagueClientConnected, onOpenSaved }: Props) {
  const [data, setData] = useState<HomeData>();
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState('');
  const [filter, setFilter] = useState('all');
  const [visible, setVisible] = useState(25);
  const [detail, setDetail] = useState<HomeMatch>();
  const [detailLoading, setDetailLoading] = useState(false);
  const detailRequestId = useRef(0);
  const [assets, setAssets] = useState<HomeAssets>();
  const [rankedRole, setRankedRole] = useState('all');
  const [registeringMatch, setRegisteringMatch] = useState('');
  const [riotReadiness, setRiotReadiness] = useState<RiotReadiness>('checking');
  const dataRef = useRef(data);
  const requestInFlight = useRef(false);
  const refreshPending = useRef(false);
  const wasActive = useRef(active);
  dataRef.current = data;

  const load = useCallback(async (sync: boolean) => {
    if (!backendReady) { setLoading(false); return; }
    if (requestInFlight.current) { if (!sync) refreshPending.current = true; return; }
    requestInFlight.current = true;
    if (sync) setSyncing(true);
    if (!dataRef.current) setLoading(true);
    setError('');
    try { const next = await window.solralol.request(sync ? 'home.sync' : 'home.dashboard'); dataRef.current = next; setData(next); }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'No se pudo cargar Inicio.'); }
    finally {
      requestInFlight.current = false; setLoading(false); setSyncing(false);
      if (refreshPending.current) {
        refreshPending.current = false;
        window.setTimeout(() => { void load(false); }, 0);
      }
    }
  }, [backendReady]);

  useEffect(() => { if (!backendReady) return; void (async () => { await load(false); await load(true); })(); }, [backendReady, load]);
  useEffect(() => { if (!active) return; if (!backendReady) { setRiotReadiness('unavailable'); return; } let current = true; setRiotReadiness('checking'); window.solralol.request('riot.readiness').then(value => { if (current) setRiotReadiness(value.state); }).catch(() => { if (current) setRiotReadiness('unavailable'); }); return () => { current = false; }; }, [active, backendReady]);
  useEffect(() => {
    if (active && backendReady && leagueClientConnected) void load(true);
  }, [active, backendReady, leagueClientConnected, load]);
  useEffect(() => window.solralol.onHomeSavedScoresChanged(() => {
    if (active && backendReady) void load(false);
    else refreshPending.current = true;
  }), [active, backendReady, load]);
  useEffect(() => {
    if (active && !wasActive.current && backendReady) { refreshPending.current = false; void load(false); }
    wasActive.current = active;
  }, [active, backendReady, load]);

  const analytics = data?.analytics;
  const ranked = analytics?.ranked_dashboard;
  const selectedStats = ranked?.stats_by_role[rankedRole] ?? ranked?.stats_by_role.all;
  useEffect(() => {
    if (rankedRole !== 'all' && !ranked?.stats_by_role[rankedRole]) setRankedRole('all');
  }, [rankedRole, ranked?.stats_by_role]);
  const filteredMatches = useMemo(() => {
    const all = data?.matches ?? [];
    if (filter === 'all') return all;
    return all.filter(match => String(match.queue_id) === filter || (filter === 'normal' && ['400', '430'].includes(String(match.queue_id))));
  }, [data?.matches, filter]);

  const assetRefs = useMemo(() => {
    const ids = [selectedStats?.top_champion_id, ranked?.counter?.champion_id,
      ...(ranked?.champions ?? []).map(champion => champion.champion_id),
      ...(analytics?.champion_performance ?? []).map(champion => champion.champion_id),
      ...(detail?.participants ?? []).map(player => String(player.champion_id ?? '')), ...(data?.matches ?? []).slice(0, 8).map(match => String(match.champion_id ?? ''))];
    return [...new Set(ids.filter((id): id is string => Boolean(id)))].slice(0, 20);
  }, [analytics?.champion_performance, data?.matches, detail?.participants, ranked?.champions, ranked?.counter?.champion_id, selectedStats?.top_champion_id]);
  const splashRefs = useMemo(() => [...new Set([selectedStats?.top_champion_id, ranked?.counter?.champion_id].filter((id): id is string => Boolean(id)))], [ranked?.counter?.champion_id, selectedStats?.top_champion_id]);
  const assetKey = `${assetRefs.join('|')}:${splashRefs.join('|')}:${data?.profile?.profileIconId ?? ''}`;
  useEffect(() => {
    if (!backendReady || (!assetRefs.length && !data?.profile?.profileIconId)) { setAssets(undefined); return; }
    let active = true;
    window.solralol.request('home.assets', { champions: assetRefs, splashChampions: splashRefs, profileIconId: data?.profile?.profileIconId })
      .then(result => { if (active) setAssets(result); }).catch(() => { if (active) setAssets(undefined); });
    return () => { active = false; };
  }, [backendReady, assetKey]);

  const loadMore = async () => {
    if (visible < filteredMatches.length) { setVisible(value => value + 25); return; }
    if (!backendReady || !data?.hasMore) return;
    try {
      const page = await window.solralol.request('home.matches', { offset: data.matches.length, limit: 50 });
      setData(current => current ? { ...current, matches: [...current.matches, ...page.matches], totalMatches: page.totalMatches, hasMore: page.hasMore } : current);
      setVisible(value => value + 25);
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'No se pudo cargar más historial.'); }
  };
  const openMatch = async (match: HomeMatch) => {
    const requestId = ++detailRequestId.current;
    setDetail(match);
    const matchId = String(match.stable_match_id || match.game_id || '');
    if (!matchId || match.participants?.length) return;
    setDetailLoading(true);
    try {
      const expanded = await window.solralol.request('home.match.detail', { matchId });
      if (requestId === detailRequestId.current) setDetail(expanded);
    } catch (cause) {
      if (requestId === detailRequestId.current) setError(cause instanceof Error ? cause.message : 'No se pudieron cargar los equipos de la partida.');
    } finally {
      if (requestId === detailRequestId.current) setDetailLoading(false);
    }
  };
  const closeMatch = () => { detailRequestId.current += 1; setDetailLoading(false); setDetail(undefined); };
  const clearHistory = async () => {
    if (!window.confirm('¿Eliminar el historial local de esta cuenta? Los datos guardados en partidas y grabaciones no se borrarán.')) return;
    try { setData(await window.solralol.request('home.clear-history')); setVisible(25); }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'No se pudo limpiar el historial.'); }
  };
  const registerAnalysis = async (match: HomeMatch) => {
    const matchId = String(match.stable_match_id || match.game_id || '');
    if (!matchId || String(match.queue_id) !== '420' || registeringMatch) return;
    let readiness = riotReadiness;
    if (readiness !== 'ready') {
      if (['missing', 'invalid', 'forbidden'].includes(readiness)) { window.dispatchEvent(new Event('solralol:open-settings')); return; }
      setRiotReadiness('checking');
      try { const state = await window.solralol.request('riot.readiness'); readiness = state.state; setRiotReadiness(readiness); }
      catch { setRiotReadiness('unavailable'); return; }
      if (readiness !== 'ready') return;
    }
    try {
      const local = await window.solralol.request('home.match.detail', { matchId });
      if (!local.participants?.some(player => player.is_local)) { setError('No se pudo identificar a tu participante local; los datos de la partida se conservan.'); return; }
    } catch { setError('No se pudieron verificar los participantes locales de esta partida.'); return; }
    setRegisteringMatch(matchId);
    try {
      const registered = await window.solralol.request('saved_matches.sync', { id: matchId });
      setData(current => current ? { ...current, matches: current.matches.map(item =>
        String(item.stable_match_id || item.game_id) === matchId ? { ...item, soloq_analysis_status: registered.status, soloq_analysis_message: registered.status_message ?? '' } : item
      ) } : current);
      closeMatch();
      onOpenSaved(registered.history_match_id ?? matchId, true);
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'No se pudo registrar el análisis SoloQ.'); }
    finally { setRegisteringMatch(''); }
  };

  return <div className="home-page home-redesign">
    {!backendReady && <div className="notice-card"><b>Backend local desconectado</b><span>Inicio conserva los datos cargados y se actualizará al reconectar.</span></div>}
    {error && <div className="notice-card error-card"><b>No se pudo actualizar Inicio</b><span>{error}</span><button onClick={() => void load(false)}>Reintentar</button></div>}
    {data?.message && !leagueClientConnected && <div className="notice-card"><b>League Client no disponible</b><span>{data.message}</span></div>}
    {loading && !data ? <div className="home-loading"><span className="spinner"/>Cargando información local…</div> : <>
      <div className="home-redesign-top">
        <main className="home-redesign-left">
          <PlayerStatisticsCard profile={data?.profile} ranked={ranked} stats={selectedStats}
            trends={ranked?.performance_evolution_by_role?.[rankedRole] ?? ranked?.performance_evolution ?? []} roleId={rankedRole}
            onRoleChange={setRankedRole} assets={assets} syncing={syncing} backendReady={backendReady} leagueClientConnected={leagueClientConnected} onSync={() => void load(true)} />
          <div className="home-dashboard-tiles">
            <ActivityCard analytics={ranked?.activity} />
            <SkinCollection collection={data?.collection ?? {}} />
            <YourCounter counter={ranked?.counter ?? null} assets={assets} />
            <section className="card home-card winrate-evolution-card"><CardTitle eyebrow="SOLOQ · ÚLTIMAS 30" title="Evolución del Win Rate"/><p className="winrate-chart-subtitle">Win rate móvil en partidas clasificatorias registradas</p><WinRateEvolution series={analytics?.rolling_winrate} matches={data?.matches}/></section>
            <section className="card home-card"><CardTitle eyebrow="ENFRENTAMIENTOS" title="Matchups de línea"/><div className="matchup-columns"><MatchupList title="MÁS TE CUESTAN" rows={analytics?.hardest_matchups ?? []} bad/><MatchupList title="MÁS GANAS" rows={analytics?.matchups ?? []}/></div><small className="card-foot">Rivales con identidad y línea suficientemente fiables.</small></section>
            <section className="card home-card"><CardTitle eyebrow="COMPAÑEROS" title="Aliados frecuentes"/><div className="compact-list">{analytics?.teammates?.length ? analytics.teammates.slice(0, 3).map((mate, index) => <div key={`${mate.name}-${mate.tag_line}-${index}`}><span className="mate-avatar" aria-hidden="true">{String(mate.name ?? '?').slice(0, 1).toUpperCase()}</span><b>{mate.name}{mate.tag_line ? `#${mate.tag_line}` : ''}</b><small>{mate.games} partidas · {mate.winrate}% WR</small></div>) : <Empty text={`No hay identidades de aliados suficientes · ${analytics?.team_data_matches ?? 0} partidas con datos de equipo.`}/>}</div></section>
          </div>
        </main>
        <aside className="home-redesign-side">
          <RankSummary profile={data?.profile} />
          <MatchHistoryCard matches={filteredMatches} assets={assets} count={data?.totalMatches ?? 0} visible={visible} hasMore={Boolean(data?.hasMore)}
            filter={filter} onFilter={value => { setFilter(value); setVisible(25); }} onLoadMore={() => void loadMore()}
            onClear={() => void clearHistory()} onSelect={match => void openMatch(match)} onAnalyze={match => void registerAnalysis(match)} registeringMatch={registeringMatch} onOpenSaved={onOpenSaved} riotReadiness={riotReadiness} />
          <ChampionPerformance champions={ranked?.champions ?? []} assets={assets} />
          <div className="card home-card playstyle-card">
            <CardTitle eyebrow="PREFERENCIAS SOLOQ" title="Roles y arquetipo" />
            <RoleDistribution roles={ranked?.roles ?? []} total={ranked?.ranked_match_count ?? 0} />
            <div className="archetype-summary"><small>ARQUETIPO PRINCIPAL</small><b>{ranked?.archetype.primary ?? 'Sin datos'}</b>
              <span>{ranked?.archetype.secondary ? `Secundario: ${ranked.archetype.secondary}` : ranked?.archetype.provisional ? 'Perfil provisional' : 'Sin arquetipo secundario'}</span>
              <small title={ranked?.archetype.method}>{ranked?.archetype.sample ?? 0} partidas clasificatorias con clase identificada</small></div>
          </div>
          <RecentPerformanceCard data={analytics?.recent_performance} />
        </aside>
      </div>

      {data?.lastSync && <footer className="home-footer">Historial local · actualizado {formatDate(data.lastSync)} <button onClick={() => onOpenSaved()}>Ver partidas guardadas</button></footer>}
    </>}
    {detail && <MatchDetail match={detail} assets={assets} loading={detailLoading} onClose={closeMatch} onOpenSaved={() => { const id = detail.saved_match_link?.saved_match_id; closeMatch(); onOpenSaved(id); }} onAnalyze={() => void registerAnalysis(detail)} registering={registeringMatch === String(detail.stable_match_id || detail.game_id || '')} riotReadiness={riotReadiness} backendReady={backendReady} />}
  </div>;
});

function CardTitle({ eyebrow, title }: { eyebrow: string; title: string }) { return <header className="card-title"><div className="eyebrow">{eyebrow}</div><h3>{title}</h3></header>; }
function Empty({ text }: { text: string }) { return <div className="home-empty">{text}</div>; }
function Metric({ label, value, note, title }: { label: string; value: string | number; note: string; title?: string }) { return <article className="metric-card" title={title}><small>{label}</small><strong>{value}</strong><span>{note}</span></article>; }

function PlayerStatisticsCard({ profile, ranked, stats, trends, roleId, onRoleChange, assets, syncing, backendReady, leagueClientConnected, onSync }: {
  profile?: HomeData['profile']; ranked?: HomeAnalytics['ranked_dashboard']; stats?: RankedRoleStats; trends: PerformanceEvolutionPoint[]; roleId: string;
  onRoleChange: (role: string) => void; assets?: HomeAssets; syncing: boolean; backendReady: boolean; leagueClientConnected: boolean; onSync: () => void;
}) {
  const splashId = stats?.top_champion_id ?? '';
  const splash = splashId ? assets?.splashes[splashId] : null;
  const style = splash ? { '--player-splash': `url("${splash}")` } as CSSProperties : undefined;
  const metrics: Array<[string, RankedRoleStats['kda'] | undefined, string, string, keyof PerformanceEvolutionPoint]> = [
    ['KDA', stats?.kda, stats?.kda.zero_deaths ? '∞' : num(stats?.kda.value, 2), 'KDA agregado: (bajas + asistencias) / muertes.', 'kda'],
    ['DAÑO/MIN', stats?.damage_per_minute, num(stats?.damage_per_minute.value), 'Daño infligido por minuto, agregado por daño y duración válidos.', 'damage_per_minute'],
    ['KP', stats?.kill_participation, pct(stats?.kill_participation.value), 'Bajas y asistencias del jugador divididas entre las muertes del equipo rival (bajas de tu equipo).', 'kill_participation'],
    ['CS/MIN', stats?.cs_per_minute, num(stats?.cs_per_minute.value), 'Súbditos y monstruos neutrales por minuto.', 'cs_per_minute'],
    ['VISIÓN', stats?.vision_score, num(stats?.vision_score.value, 1), 'Puntuación de visión promedio registrada por partida.', 'vision_score'],
    ['ORO @15', stats?.gold_diff_15, signed(stats?.gold_diff_15.value), 'Diferencia de oro al minuto 15 frente al rival directo de posici?n.', 'gold_diff_15'],
    ['BATTLESCORE', stats?.performance_score, num(stats?.performance_score.value, 1), 'Media de partidas SoloQ guardadas con BattleScore válido.', 'performance_score'],
  ];
  const rank = profile?.ranked?.find(queue => String(queue.queue ?? '').toUpperCase().includes('SOLO'));
  return <section className="card player-statistics-card" style={style}>
    <div className="player-statistics-top"><GameImage src={assets?.profileIcon} alt="Icono de perfil" className="profile-image player-stat-avatar" fallback={String(profile?.gameName || 'S').slice(0, 1).toUpperCase()}/>
      <div className="player-stat-identity"><div className="eyebrow">PERFIL DE JUGADOR · SOLOQ</div><h2>{profile ? `${profile.gameName}${profile.tagLine ? `#${profile.tagLine}` : ''}` : 'Invocador'}</h2>
        <span>{profile ? `Nivel ${profile.summonerLevel ?? '—'} · ${profile.region || 'Región no disponible'}` : 'Sin perfil LCU sincronizado'}</span></div>
      <div className="player-stat-rank"><small>CLASIFICATORIA SOLO/DÚO</small><b>{rank ? `${String(rank.tier ?? '').replaceAll('_', ' ')} ${rank.division ?? ''}`.trim() : 'Rango no disponible'}</b><span>{rank?.league_points != null ? `${rank.league_points} LP` : 'Sin datos de LP'}</span></div>
      <div className="player-stat-actions"><span className={`lcu-pill ${leagueClientConnected ? 'online' : 'offline'}`}><i/>{leagueClientConnected ? 'League Client conectado' : 'League Client no disponible'}</span><button className="gold-button" disabled={!backendReady || syncing} onClick={onSync}>{syncing ? 'Sincronizando…' : <><Icon name="refresh"/> Sincronizar</>}</button></div>
    </div>
    <div className="ranked-role-filter" role="group" aria-label="Filtrar métricas SoloQ por posición"><span>COLA 420</span><button className={roleId === 'all' ? 'selected' : ''} onClick={() => onRoleChange('all')}>Todas</button>
      {(ranked?.roles ?? []).filter(role => role.selectable).map(role => <button key={role.id} className={roleId === role.id ? 'selected' : ''} onClick={() => onRoleChange(role.id)} title={`${role.matches} partidas`}>{role.label}</button>)}
      <small>{stats?.matches ?? 0} partidas · {ranked?.scope ?? 'historial local SoloQ'}</small>
    </div>
    <div className="player-stat-metrics">{metrics.map(([label, item, value, description, key]) => <div className="player-stat-metric" key={label} title={description}><small>{label}</small><div className="player-stat-metric-value"><b>{value}</b><MiniSparkline metric={key} points={trends} label={label}/></div><span>{label === 'BATTLESCORE' ? (item?.sample ? `Media · ${item.sample} partidas puntuadas` : 'No disponible') : <>{item?.trend ? <MetricTrend trend={item.trend}/> : item?.sample ? `${item.sample} con dato` : 'No disponible'}{item?.trend && item.sample ? ` · ${item.sample} con dato` : ''}</>}</span></div>)}</div>
    <div className="player-stat-footnote">Campeón más usado en esta selección: <b>{stats?.top_champion_name ?? 'Sin muestra'}</b>{stats?.performance_score.sample ? ` · BattleScore, ${stats.performance_score.sample} partidas puntuadas` : ' · BattleScore no disponible en partidas guardadas'}</div>
  </section>;
}

function MetricTrend({ trend }: { trend: NonNullable<RankedRoleStats['kda']['trend']> }) {
  const symbol = trend.direction === 'positive' ? '↗' : trend.direction === 'negative' ? '↘' : '→';
  const delta = `${trend.delta > 0 ? '+' : ''}${num(trend.delta, trend.precision)}`;
  const label = trend.direction === 'neutral' ? 'sin cambio' : `${delta} vs. media previa`;
  return <span className={`metric-trend ${trend.direction}`} aria-label={`Última partida: ${label}`} title={`Última válida ${num(trend.latest, trend.precision)}; media previa ${num(trend.previous_average, trend.precision)} (${trend.sample} partidas)`}><i aria-hidden="true">{symbol}</i>{label}</span>;
}

const SPARK_METRICS = new Set<keyof PerformanceEvolutionPoint>(['kda', 'damage_per_minute', 'kill_participation', 'cs_per_minute', 'vision_score', 'gold_diff_15', 'performance_score']);
const MiniSparkline = memo(function MiniSparkline({ metric, points, label }: { metric: keyof PerformanceEvolutionPoint; points: PerformanceEvolutionPoint[]; label: string }) {
  if (!SPARK_METRICS.has(metric)) return null;
  const series = points.map(point => point[metric]);
  const values = series.filter((value): value is number => typeof value === 'number' && Number.isFinite(value));
  if (values.length < 2) return null;
  const min = Math.min(...values), max = Math.max(...values), span = max - min || Math.max(Math.abs(max) * 0.08, 1);
  const segments: string[][] = [];
  series.forEach((value, index) => {
    if (typeof value !== 'number' || !Number.isFinite(value)) { if (segments.at(-1)?.length) segments.push([]); return; }
    if (!segments.length) segments.push([]);
    segments.at(-1)?.push(`${(index / Math.max(1, series.length - 1)) * 60},${20 - ((value - min) / span) * 16}`);
  });
  return <svg className="player-stat-sparkline" viewBox="0 0 60 22" role="img" aria-label={`${label}: tendencia de ${values.length} partidas recientes`}>
    {segments.filter(segment => segment.length > 1).map((segment, index) => <polyline key={index} points={segment.join(' ')}/>)}
  </svg>;
});

function RankSummary({ profile }: { profile?: HomeData['profile'] }) {
  const queue = profile?.ranked?.find(item => String(item.queue ?? '').toUpperCase().includes('SOLO'));
  const wins = queue?.wins, losses = queue?.losses, total = (wins ?? 0) + (losses ?? 0);
  const wr = total ? Math.round((wins ?? 0) * 100 / total) : null;
  return <section className="card rank-summary-card"><div><div className="eyebrow">CLASIFICATORIA · SOLO/DÚO</div><h3>{queue ? `${String(queue.tier ?? '').replaceAll('_', ' ')} ${queue.division ?? ''}`.trim() : 'Rango no disponible'}</h3>
    <b>{queue?.league_points != null ? `${queue.league_points} LP` : 'LP no disponible'}</b></div>
    <div className="rank-summary-record"><strong>{wr == null ? '—' : `${wr}%`}</strong><span>win rate de temporada</span><small>{wins == null || losses == null ? 'Registro no disponible' : `${wins}V · ${losses}D`}</small></div>
  </section>;
}

function MatchHistoryCard({ matches, assets, count, visible, hasMore, filter, onFilter, onLoadMore, onClear, onSelect, onAnalyze, registeringMatch, onOpenSaved, riotReadiness }: {
  matches: HomeMatch[]; assets?: HomeAssets; count: number; visible: number; hasMore: boolean; filter: string; onFilter: (id: string) => void;
  onLoadMore: () => void; onClear: () => void; onSelect: (match: HomeMatch) => void; onAnalyze: (match: HomeMatch) => void; registeringMatch: string; onOpenSaved: (id?: string) => void; riotReadiness: RiotReadiness;
}) {
  return <section className="card home-card redesign-history-card">
    <div className="redesign-history-header"><div className="history-heading"><CardTitle eyebrow="HISTORIAL LOCAL" title="Partidas recientes"/><button className="quiet-button" onClick={onClear} disabled={!count}>Limpiar</button></div>
      <div className="history-toolbar"><div className="filter-buttons">{FILTERS.map(([id, label]) => <button key={id} className={filter === id ? 'selected' : ''} onClick={() => onFilter(id)}>{label}</button>)}</div><span>{count} partidas</span></div>
    </div>
    <div className="redesign-match-list">{matches.length ? matches.slice(0, visible).map((match, index) => {
      const matchId = String(match.stable_match_id || match.game_id || `${match.started_at}-${index}`);
      const analyzed = Boolean(match.soloq_analysis_ready);
      const syncing = ['pending', 'downloading', 'processing'].includes(match.soloq_analysis_status ?? '');
      const seconds = Number(match.duration_seconds);
      const durationLabel = Number.isFinite(seconds) && seconds > 0 ? `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, '0')}` : '';
      return <div role="button" tabIndex={0} key={matchId} className={`redesign-match-row ${match.result === 'victory' ? 'win' : match.result === 'defeat' ? 'loss' : ''}`} onClick={() => onSelect(match)} onKeyDown={event => { if (event.target === event.currentTarget && (event.key === 'Enter' || event.key === ' ')) { event.preventDefault(); onSelect(match); } }}>
        <GameImage src={assets?.champions[String(match.champion_id ?? '')]} alt={match.champion_name ?? 'Campe\u00f3n'} className="redesign-match-avatar" fallback={String(match.champion_name ?? '?').slice(0, 1)}/>
        <span className="redesign-match-main"><span className="redesign-match-heading"><b>{match.champion_name ?? 'Campe\u00f3n'}</b><strong className={match.result === 'victory' ? 'positive' : match.result === 'defeat' ? 'negative' : ''}>{match.result === 'victory' ? 'Victoria' : match.result === 'defeat' ? 'Derrota' : 'Sin resultado'}</strong></span><small>{match.mode || `Cola ${match.queue_id ?? 'desconocida'}`} · {match.lane || 'Posici\u00f3n no disponible'} · {match.kills ?? '?'}/{match.deaths ?? '?'}/{match.assists ?? '?'}</small><small>{relativeDate(match.started_at)}{durationLabel ? ` · ${durationLabel}` : ''}</small></span>
        <span className="redesign-match-battlescore" style={{ color: battleScoreColor(match.battle_score) }} title={match.battle_score == null ? 'BattleScore no disponible' : 'BattleScore del jugador'}>{formatBattleScore(match.battle_score)}</span>
        {String(match.queue_id) === '420' && <button className={`history-analyze-action ${analyzed ? 'ready' : ''}`} disabled={Boolean(registeringMatch) || syncing} onClick={event => { event.stopPropagation(); if (analyzed) onOpenSaved(matchId); else onAnalyze(match); }}>{registeringMatch === matchId ? 'Registrando?' : riotAnalysisActionLabel(riotReadiness, match.soloq_analysis_status ?? '', analyzed)}</button>}
      </div>;
    }) : <Empty text={count ? 'No hay partidas para este filtro.' : 'No hay partidas locales. Conecta League Client y sincroniza.'}/>}</div>
    {(visible < matches.length || hasMore) && <footer className="redesign-history-footer"><button className="load-more" onClick={onLoadMore}>Cargar 25 partidas más</button></footer>}
  </section>;
}

function ChampionPerformance({ champions, assets }: { champions: HomeAnalytics['ranked_dashboard']['champions']; assets?: HomeAssets }) {
  return <section className="card home-card redesign-champion-performance"><CardTitle eyebrow="SOLOQ · MÁS JUGADOS" title="Rendimiento por campeón"/>
    {champions.length ? <div className="redesign-champion-list">{champions.map(champion => <article key={champion.champion_id} className="redesign-champion-row">
      <GameImage src={assets?.champions[champion.champion_id]} alt={champion.name} className="redesign-champion-icon" fallback={champion.name.slice(0, 1)}/>
      <div className="redesign-champion-data"><div><b>{champion.name}</b><strong>{champion.winrate.toLocaleString('es-ES', { maximumFractionDigits: 1 })}% <small>WR</small></strong></div>
        <div className="redesign-winrate-track"><i style={{ width: `${clamp(champion.winrate, 0, 100)}%` }}/></div>
        <small>{champion.matches} partidas · {champion.wins}V / {champion.losses}D · KDA {champion.kda == null ? '—' : num(champion.kda, 2)}{champion.score == null ? '' : ` · BS ${num(champion.score, 1)}`}</small></div>
    </article>)}</div> : <Empty text="Sin partidas SoloQ con campeón identificado."/>}
  </section>;
}

function RoleDistribution({ roles, total }: { roles: HomeAnalytics['ranked_dashboard']['roles']; total: number }) {
  const order = ['top', 'jungle', 'mid', 'adc', 'support'];
  const labels: Record<string, string> = { top: 'Superior', jungle: 'Jungla', mid: 'Medio', adc: 'Inferior', support: 'Soporte' };
  const counts = new Map(roles.map(role => [role.id, role.matches]));
  return <div className="role-distribution">{order.map(role => { const count = counts.get(role) ?? 0; const percent = total ? count * 100 / total : 0; return <div key={role} title={`${labels[role]}: ${count} de ${total} partidas`}><span>{labels[role]}</span><i><b style={{ width: `${percent}%` }}/></i><small>{Math.round(percent)}%</small></div>; })}</div>;
}

function ActivityCard({ analytics }: { analytics?: HomeAnalytics['ranked_dashboard']['activity'] }) {
  const hours = Array.from({ length: 24 }, (_, hour) => analytics?.hours.find(row => row.key === hour));
  const max = Math.max(0, ...hours.map(row => row?.matches ?? 0));
  const busiestHour = analytics?.busiest_hour;
  const busiestDay = analytics?.busiest_day;
  return <section className="card home-card redesign-activity-card"><CardTitle eyebrow="ACTIVIDAD · HISTORIAL LOCAL" title="Cuándo juegas"/>
    <div className="redesign-activity-peak"><div><small>HORA PREFERIDA</small><b>{busiestHour?.label ?? 'Sin datos'}</b><span>{busiestHour ? `${busiestHour.matches} partidas · ${pct(busiestHour.winrate)} WR` : 'Fechas insuficientes'}</span></div><div><small>DÍA MÁS ACTIVO</small><b>{busiestDay?.label ?? 'Sin datos'}</b><span>{busiestDay ? `${busiestDay.matches} partidas · ${pct(busiestDay.winrate)} WR` : 'Fechas insuficientes'}</span></div></div>
    <div className="redesign-hour-chart" role="img" aria-label="Partidas SoloQ por hora de inicio local">{hours.map((row, hour) => <div key={hour} title={`${String(hour).padStart(2, '0')}:00 · ${row?.matches ?? 0} partidas · ${pct(row?.winrate)} WR`}><i className={row && row.matches === max && max > 0 ? 'peak' : ''} style={{ height: max ? `${Math.max(5, (row?.matches ?? 0) / max * 100)}%` : '0%' }}/><small>{hour % 4 === 0 || hour === 23 ? String(hour).padStart(2, '0') : ''}</small></div>)}</div>
    <small className="redesign-data-note">{analytics?.assignment ?? 'Cada partida se cuenta una vez por hora de inicio local.'}</small>
    <div className="redesign-weekdays">{analytics?.weekdays.map(day => <div key={day.key} title={`${day.label}: ${day.matches} partidas, ${pct(day.winrate)} win rate`}><span>{day.label.slice(0, 2)}</span><b>{day.matches}</b><small>{pct(day.winrate)}</small></div>)}</div>
  </section>;
}

function SkinCollection({ collection }: { collection: Record<string, unknown> }) {
  const skins = collection.skins as Record<string, unknown> | undefined;
  const masteries = Array.isArray(collection.masteries) ? collection.masteries as Array<Record<string, unknown>> : [];
  const challenges = collection.challenges as Record<string, unknown> | undefined;
  const titles = collection.titles as Record<string, unknown> | undefined;
  const owned = typeof skins?.owned_count === 'number' ? skins.owned_count : null;
  return <section className="card home-card redesign-skin-card"><div className="skin-card-art" aria-hidden="true"/><div className="skin-card-content"><CardTitle eyebrow="COLECCIÓN LCU" title="Colección de aspectos"/>
    {owned == null ? <Empty text="Propiedad de aspectos no disponible. Abre League Client y sincroniza."/> : <><div className="skin-owned-count"><b>{owned.toLocaleString('es-ES')}</b><span>aspectos propios</span></div><div className="skin-total-unavailable">Catálogo total no disponible en los datos locales</div></>}
    <div className="collection-retained-data"><small>MAESTRÍAS DESTACADAS</small>{masteries.length ? masteries.slice(0, 3).map((item, index) => <span key={`${item.champion_id}-${index}`}>{String(item.champion_name ?? `Campeón ${item.champion_id ?? '—'}`)} · {Number(item.points ?? 0).toLocaleString('es-ES')} pts · Nv. {String(item.level ?? '—')}</span>) : <span>Maestrías no disponibles</span>}
      <small>DESAFÍOS Y TÍTULO</small><span>{challenges ? `${String(challenges.tier ?? 'Nivel no disponible')} · ${challenges.points == null ? 'puntos no disponibles' : `${Number(challenges.points).toLocaleString('es-ES')} pts`}` : 'Desafíos no disponibles'} · {String(titles?.selected ?? 'Título no disponible')}</span></div>
  </div></section>;
}

function YourCounter({ counter, assets }: { counter: HomeAnalytics['ranked_dashboard']['counter']; assets?: HomeAssets }) {
  const art = counter ? assets?.splashes[counter.champion_id] : null;
  const style = art ? { '--counter-art': `url("${art}")` } as CSSProperties : undefined;
  return <section className="card home-card your-counter-card" style={style}><div className="your-counter-overlay"><div className="eyebrow">TU COUNTER · HISTORIAL LOCAL</div>
    {counter ? <><h3>{counter.name}</h3><b>{counter.losses} derrotas</b><span>{pct(counter.winrate)} WR en {counter.encounters} enfrentamientos</span></> : <><h3>Sin counter registrado</h3><span>No hay derrotas contra campeones identificados en el historial local.</span></>}
  </div></section>;
}

function MatchDetail({ match, assets, loading, onClose, onOpenSaved, onAnalyze, registering, riotReadiness, backendReady }: { match: HomeMatch; assets?: HomeAssets; loading: boolean; onClose: () => void; onOpenSaved: () => void; onAnalyze: () => void; registering: boolean; riotReadiness: RiotReadiness; backendReady: boolean }) {
  const participants = match.participants ?? [];
  const battleScore = match.battle_score;
  const teams = [...new Set(participants.map(participant => participant.team_id).filter((id): id is number => typeof id === 'number'))];
  const localParticipants = participants.filter(participant => participant.is_local);
  const localTeamId = localParticipants.length === 1 ? localParticipants[0].team_id : undefined;
  const teamAssignmentKnown = localTeamId != null && teams.length === 2;
  const actionLabel = riotAnalysisActionLabel(riotReadiness, match.soloq_analysis_status ?? '', Boolean(match.soloq_analysis_ready));
  return <div className="modal-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}>
    <article className="match-detail card redesign-match-detail">
      <button className="modal-close" aria-label="Cerrar detalle" onClick={onClose}>&times;</button>
      <div className="eyebrow">DETALLE DE PARTIDA</div>
      <h2>{match.champion_name ?? 'Campe\u00f3n'} · {match.result === 'victory' ? 'Victoria' : match.result === 'defeat' ? 'Derrota' : 'Resultado no disponible'}</h2>
      <p>{match.mode ?? 'Modo desconocido'} · {formatDate(match.started_at)} · {duration(match.duration_seconds)}</p>
      <div className="detail-stats"><Metric label="KDA" value={`${match.kills ?? '?'} / ${match.deaths ?? '?'} / ${match.assists ?? '?'}`} note="Resumen de partida"/><Metric label="Farm" value={match.cs ?? '?'} note={match.cs_per_min == null ? 'CS/min no disponible' : `${num(match.cs_per_min)} por minuto`}/><Metric label="BATTLESCORE" value={battleScore == null ? '—' : num(battleScore, 1)} note={battleScore == null ? 'No disponible en esta partida guardada.' : 'Resultado final BattleScore guardado'}/></div>
      {participants.length ? <>
        {!teamAssignmentKnown && <p className="home-empty">No hay datos suficientes para confirmar los dos equipos.</p>}
        <div className="redesign-match-teams">{teams.map(team => <section key={team}>
          <b>{teamAssignmentKnown ? (team === localTeamId ? 'Tu equipo' : 'Equipo rival') : 'Equipo no confirmado'}</b>
          {participants.filter(player => player.team_id === team).map((player, index) => <div key={`${team}-${player.participant_id ?? index}`} className={player.is_local ? 'local' : ''}>
            <GameImage src={assets?.champions[String(player.champion_id ?? '')]} alt={player.champion_name ?? 'Campe\u00f3n'} className="redesign-team-icon" fallback={String(player.champion_name ?? '?').slice(0, 1)}/>
            <span>{player.champion_name ?? 'Campe\u00f3n'}{player.is_local ? ' · T\u00fa' : ''}</span><small>{player.kills ?? '?'} / {player.deaths ?? '?'} / {player.assists ?? '?'}</small>
          </div>)}
        </section>)}</div>
      </> : <div className="home-empty">{loading ? 'Cargando equipos...' : 'El roster detallado no est\u00e1 disponible en el historial local.'}</div>}
      {String(match.queue_id) === '420' && <button className="gold-button" disabled={!backendReady || registering || ['pending', 'downloading', 'processing'].includes(match.soloq_analysis_status ?? '') || riotReadiness === 'checking'} onClick={match.soloq_analysis_ready ? onOpenSaved : onAnalyze}>{registering ? 'Registrando...' : actionLabel}</button>}
    </article>
  </div>;
}

function MatchupList({ title, rows, bad = false }: { title: string; rows: HomeData['analytics']['matchups']; bad?: boolean }) { return <div><small className={bad ? 'bad-text' : 'good-text'}>{title}</small>{rows.length ? rows.slice(0, 3).map(item => <p className="matchup-row" key={item.champion}><b>{item.champion}</b><span>{item.winrate}% WR · {item.games} partidas</span></p>) : <div className="mini-empty">Muestra insuficiente</div>}</div>; }
function num(value: number | null | undefined, digits = 1): string { return value == null || !Number.isFinite(value) ? '—' : value.toLocaleString('es-ES', { maximumFractionDigits: digits }); }
function pct(value: number | null | undefined): string { return value == null || !Number.isFinite(value) ? '—' : `${num(value)}%`; }
function signed(value: number | null | undefined): string { return value == null ? '—' : `${value > 0 ? '+' : ''}${Math.round(value).toLocaleString('es-ES')} g`; }
function clamp(value: number, min: number, max: number): number { return Math.max(min, Math.min(max, value)); }
function formatDate(value?: string): string { if (!value) return 'Fecha no disponible'; const date = new Date(value); return Number.isNaN(date.valueOf()) ? 'Fecha no disponible' : new Intl.DateTimeFormat('es-ES', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }).format(date); }
function relativeDate(value?: string): string { if (!value) return 'Fecha no disponible'; const date = new Date(value); if (Number.isNaN(date.valueOf())) return 'Fecha no disponible'; const days = Math.floor((Date.now() - date.getTime()) / 86_400_000); return days <= 0 ? 'Hoy' : days === 1 ? 'Ayer' : `Hace ${days} días`; }
function duration(value?: number): string { return value == null ? '—' : `${Math.floor(value / 60)}:${String(value % 60).padStart(2, '0')}`; }
