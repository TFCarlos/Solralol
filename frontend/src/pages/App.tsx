import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { AnalysisUpdateState, Bootstrap, Champion, ChampionAnalysis, Lane, StorageMigrationStatus } from '../types/contracts';
import { HomeDashboard } from './HomeDashboard';
import { Icon, type IconName } from '../components/Icon';
import { SettingsPage } from './SettingsPage';
import { GameImage } from '../components/GameImage';
import { ChampionSelector } from '../components/ChampionSelector';
import { MetaPage } from './MetaPage';
import { DraftPage } from './DraftPage';
import { RecordingsPage } from './RecordingsPage';
import { SavedMatchesWorkspace } from './SavedMatchesWorkspace';
import { WindowTitleBar } from '../components/WindowTitleBar';
import { LiveMatchPage } from './LiveMatchPage';
import { LiveMatchStatus } from '../components/LiveMatchStatus';

const navIcons: Record<string, IconName> = { home: 'home', analysis: 'chart', draft: 'draft', live: 'live', 'saved-matches': 'history', recordings: 'video', meta: 'meta', settings: 'settings' };

const lanes: { id: Lane; label: string }[] = [
  { id: 'top', label: 'Top' }, { id: 'jungle', label: 'Jungla' }, { id: 'mid', label: 'Medio' }, { id: 'adc', label: 'Bot' }, { id: 'support', label: 'Apoyo' },
];

export function App() {
  const [bootstrap, setBootstrap] = useState<Bootstrap>();
  const [champions, setChampions] = useState<Champion[]>([]);
  const [selected, setSelected] = useState('Ahri');
  const [lane, setLane] = useState<Lane>('mid');
  const [championIcons, setChampionIcons] = useState<Record<string, string | null>>({});
  const iconRequests = useRef(new Set<string>());
  const championIconsRef = useRef(championIcons);
  championIconsRef.current = championIcons;
  const [analysis, setAnalysis] = useState<ChampionAnalysis>();
  const preferredRoleApplied = useRef('');
  const [analysisLoading, setAnalysisLoading] = useState(false);
  const [selectedRune, setSelectedRune] = useState(0);
  const [analysisRevision, setAnalysisRevision] = useState(0);
  const [analysisUpdate, setAnalysisUpdate] = useState<AnalysisUpdateState>({ state: 'idle', current: 0, total: 0, message: '' });
  const [error, setError] = useState('');
  const [section, setSection] = useState('home');
  const [settingsSection, setSettingsSection] = useState('cuenta');
  const [savedMatchToOpen, setSavedMatchToOpen] = useState('');
  const [savedMatchAutoAnalyze, setSavedMatchAutoAnalyze] = useState(false);
  const [backendState, setBackendState] = useState('starting');
  const [storageMigration, setStorageMigration] = useState<StorageMigrationStatus>();
  const storageMigrationRef = useRef(storageMigration);
  storageMigrationRef.current = storageMigration;
  const [leagueClientConnected, setLeagueClientConnected] = useState(false);
  const backendInitialized = useRef(false);
  const migrationPoll = useRef<{ active: boolean; failures: number; timer?: number }>({ active: false, failures: 0 });
  const backgroundLcuSync = useRef(false);
  const automaticLiveRoute = useRef({ selectionSeen: false, routedSession: '' });
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => {
    try { return window.localStorage.getItem('solralol.sidebarCollapsed') === 'true'; }
    catch { return false; }
  });
  const openSavedMatches = useCallback((id?: string, autoAnalyze = false) => { setSavedMatchToOpen(id ?? ''); setSavedMatchAutoAnalyze(autoAnalyze); setSection('saved-matches'); }, []);
  const openDraftOnChampSelect = useCallback(() => setSection('draft'), []);

  useEffect(() => { const openSettings = (event: Event) => { const requested = (event as CustomEvent<{section?: string}>).detail?.section; if (requested) setSettingsSection(requested); setSection('settings'); }; window.addEventListener('solralol:open-settings', openSettings); return () => window.removeEventListener('solralol:open-settings', openSettings); }, []);

  useEffect(() => {
    try { window.localStorage.setItem('solralol.sidebarCollapsed', String(sidebarCollapsed)); }
    catch { /* Local UI preference is optional when storage is unavailable. */ }
  }, [sidebarCollapsed]);

  useEffect(() => {
    let active = true;
    const publishMigration = (state: StorageMigrationStatus) => {
      if (!active) return;
      setStorageMigration(state);
      window.dispatchEvent(new CustomEvent('solralol:migration-update', { detail: state }));
    };
    const stopMigrationPoll = () => {
      migrationPoll.current.active = false;
      if (migrationPoll.current.timer) window.clearTimeout(migrationPoll.current.timer);
      migrationPoll.current.timer = undefined;
    };
    const pollMigration = async () => {
      if (!active || !migrationPoll.current.active) return;
      try {
        const state = await window.solralol.request('storage.migrate.status');
        migrationPoll.current.failures = 0;
        const staleSeconds = state.lastProgressAt ? Date.now() / 1000 - state.lastProgressAt : 0;
        const displayState = staleSeconds > 15 && ['copying','verifying'].includes(state.state)
          ? { ...state, message: state.currentFile
              ? `El backend sigue activo; la unidad está tardando con ${state.currentFile}.`
              : 'El backend sigue activo; está completando una operación de disco.' }
          : state;
        publishMigration(displayState);
        if (['preparing','assistant_ready','waiting_for_shutdown','validating','copying','verifying','committing','reinitializing','launching_destination','launching_source'].includes(state.state)) {
          migrationPoll.current.timer = window.setTimeout(pollMigration, 300);
        } else stopMigrationPoll();
      } catch {
        migrationPoll.current.failures += 1;
        if (migrationPoll.current.failures >= 12) {
          publishMigration({ migrationId: storageMigrationRef.current?.migrationId, state: 'recovery_required', phase: 'recovery_required',
            currentBytes: storageMigrationRef.current?.currentBytes ?? 0, verifiedBytes: storageMigrationRef.current?.verifiedBytes ?? 0,
            totalBytes: storageMigrationRef.current?.totalBytes ?? 0, processedFiles: storageMigrationRef.current?.processedFiles ?? 0,
            fileCount: storageMigrationRef.current?.fileCount ?? 0, message: 'Se perdió la conexión durante el traslado. La ubicación anterior se conserva; vuelve a conectar el backend para comprobar el estado.' });
          stopMigrationPoll();
        } else {
          migrationPoll.current.timer = window.setTimeout(pollMigration, Math.min(250 * migrationPoll.current.failures, 1500));
        }
      }
    };
    const startMigrationPoll = () => {
      migrationPoll.current.active = true;
      migrationPoll.current.failures = 0;
      if (migrationPoll.current.timer) window.clearTimeout(migrationPoll.current.timer);
      void pollMigration();
    };
    const onMigrationStarted = (event: Event) => {
      const state = (event as CustomEvent<StorageMigrationStatus>).detail;
      if (state) publishMigration(state);
      startMigrationPoll();
    };
    const offMigrationStatus = (event: Event) => publishMigration((event as CustomEvent<StorageMigrationStatus>).detail);
    window.addEventListener('solralol:migration-started', onMigrationStarted);
    window.addEventListener('solralol:migration-update', offMigrationStatus);
    const offMigrationBackend = window.solralol.onBackendStatus((status) => {
      if (status.state === 'ready' && migrationPoll.current.active) {
        if (migrationPoll.current.timer) window.clearTimeout(migrationPoll.current.timer);
        migrationPoll.current.timer = window.setTimeout(pollMigration, 0);
      }
    });
    const initializeBackend = (readyBootstrap?: Bootstrap) => {
      if (backendInitialized.current) return;
      backendInitialized.current = true;
      if (readyBootstrap) setBootstrap(readyBootstrap);
      window.solralol.request('champions.list').then((value) => { if (active) setChampions(value); }).catch((e: Error) => { if (active) setError(e.message); });
      window.solralol.request('storage.info').then((info) => {
        if (!active || !info.migration) return;
        publishMigration(info.migration);
        if (['preparing','assistant_ready','waiting_for_shutdown','validating','copying','verifying','committing','reinitializing','launching_destination','launching_source'].includes(info.migration.state)) startMigrationPoll();
      }).catch(() => {});
    };
    const offBackend = window.solralol.onBackendStatus((status) => {
      setBackendState(status.state);
      if (status.state === 'ready') initializeBackend(status.bootstrap);
      else {
        setLeagueClientConnected(false);
        if (status.state === 'restarting' || status.state === 'starting') backendInitialized.current = false;
      }
    });
    window.solralol.getBackendStatus().then((status) => {
      if (!active) return;
      setBackendState(status.state);
      if (status.state === 'ready') initializeBackend(status.bootstrap);
      else setLeagueClientConnected(false);
    }).catch(() => {});
    return () => { active = false; stopMigrationPoll(); offMigrationBackend(); window.removeEventListener('solralol:migration-started', onMigrationStarted); window.removeEventListener('solralol:migration-update', offMigrationStatus); offBackend(); };
  }, []);
  const requestChampionIcons = useCallback((ids: string[]) => {
    const requested = [...new Set(ids)].filter((id) => id && !(id in championIconsRef.current) && !iconRequests.current.has(id)).slice(0, 20);
    if (!requested.length) return;
    requested.forEach((id) => iconRequests.current.add(id));
    void window.solralol.request('home.assets', { champions: requested }).then((assets) => {
      setChampionIcons((current) => ({ ...current, ...assets.champions }));
    }).catch(() => {
      // The selector remains usable with its letter fallback when an asset is unavailable.
    }).finally(() => requested.forEach((id) => iconRequests.current.delete(id)));
  }, []);
  useEffect(() => {
    if (backendState !== 'ready') return;
    let active = true;
    const timer = window.setInterval(() => {
      if (backgroundLcuSync.current) return;
      backgroundLcuSync.current = true;
      void window.solralol.request('home.sync').catch(() => undefined).finally(() => { if (active) backgroundLcuSync.current = false; });
    }, 120_000);
    return () => { active = false; window.clearInterval(timer); backgroundLcuSync.current = false; };
  }, [backendState]);

  // Keep the one Python live-session monitor owned while any tab is visible.
  // Renderers consume this cached state; they do not create their own Riot pollers.
  useEffect(() => {
    if (backendState !== 'ready') return;
    let mounted=true, timer=0, busy=false;
    const poll=async()=>{
      if(!mounted||busy)return;
      busy=true;
      try {
        const state=await window.solralol.request('live.snapshot');
        if(mounted){
          window.dispatchEvent(new CustomEvent('solralol:live-update',{detail:state}));
          window.solralol.publishLiveOverlay(state);
          if(state.state==='champion_select'&&!automaticLiveRoute.current.selectionSeen){
            automaticLiveRoute.current.selectionSeen=true;
            setSection('draft');
          } else if(state.state==='active'&&automaticLiveRoute.current.selectionSeen){
            const session=String(state.sessionId||'active-session');
            if(automaticLiveRoute.current.routedSession!==session){
              automaticLiveRoute.current.routedSession=session;
              setSection('live');
            }
            automaticLiveRoute.current.selectionSeen=false;
          } else if(state.state==='post_game') automaticLiveRoute.current.selectionSeen=false;
        }
      } catch { /* Backend status already communicates service availability. */ }
      finally {busy=false;if(mounted)timer=window.setTimeout(poll,2000);}
    };
    void poll();
    return()=>{mounted=false;window.clearTimeout(timer);};
  },[backendState]);

  useEffect(() => {
    if (section !== 'analysis') return;
    let current = true;
    setAnalysisLoading(true);
    window.solralol.request('champions.analysis', { champion: selected, lane, rank: 'emerald_plus' })
      .then((result) => { if (current) { setAnalysis(result); setSelectedRune(0); } })
      .catch((e: Error) => { if (current) setError(e.message); })
      .finally(() => { if (current) setAnalysisLoading(false); });
    return () => { current = false; };
  }, [selected, lane, section, analysisRevision]);

  useEffect(() => {
    if (section !== 'analysis' || analysisUpdate.state !== 'running') return;
    let active = true;
    const timer = window.setInterval(() => {
      window.solralol.request('champions.analysis.update.status').then((state) => {
        if (!active) return;
        setAnalysisUpdate(state);
        if (state.state !== 'running') {
          window.clearInterval(timer);
          if (state.state === 'complete' || state.state === 'cancelled') setAnalysisRevision((value) => value + 1);
        }
      }).catch((e: Error) => { if (active) { window.clearInterval(timer); setAnalysisUpdate({ state:'error', current:0, total:0, message:e.message }); } });
    }, 700);
    return () => { active = false; window.clearInterval(timer); };
  }, [section, analysisUpdate.state]);

  const updateAnalysis = useCallback((all = false) => {
    setAnalysisUpdate({ state:'running', current:0, total:all ? 0 : 100, message:'Iniciando actualización…' });
    window.solralol.request('champions.analysis.update', all ? {} : { champion: selected })
      .then(setAnalysisUpdate)
      .catch((e: Error) => setAnalysisUpdate({ state:'error', current:0, total:0, message:e.message }));
  }, [selected]);

  const champ = useMemo(() => champions.find((item) => item.id === selected), [champions, selected]);
  const analysisIsCurrent = analysis?.champion.toLocaleLowerCase() === selected.toLocaleLowerCase();
  const preferredLane = useMemo(() => {
    const basics = record(analysisIsCurrent ? analysis?.data?.basic_info : undefined);
    const raw = array(basics.flex_potential).map((value) => text(value).toLocaleLowerCase());
    const aliases: Record<string, Lane> = { top:'top', superior:'top', jungle:'jungle', jungla:'jungle', mid:'mid', middle:'mid', medio:'mid', adc:'adc', bot:'adc', bottom:'adc', tirador:'adc', support:'support', soporte:'support', utility:'support', apoyo:'support' };
    const stats = record(record(analysisIsCurrent ? analysis?.data?.lane_stats : undefined).lanes);
    const rated = Object.entries(stats).filter(([key,value]) => lanes.some((item)=>item.id===key) && Number(record(value).games ?? record(value).total_games) > 0).sort((a,b)=>Number(record(b[1]).games ?? record(b[1]).total_games)-Number(record(a[1]).games ?? record(a[1]).total_games))[0]?.[0] as Lane | undefined;
    const matchRole = textAt(record(analysisIsCurrent ? analysis?.data : undefined), 'matchups', 'summary', 'primary_role').toLocaleLowerCase();
    return rated || (text(basics.primary_role) && aliases[text(basics.primary_role).toLocaleLowerCase()]) || aliases[matchRole] || (raw.map((role) => aliases[role]).find(Boolean) as Lane | undefined) || undefined;
  }, [analysis, analysisIsCurrent]);
  const heroLaneSummary = record(record(record(analysis?.data?.lane_stats).lanes)[lane]);
  const heroWinRate = heroLaneSummary.win_rate ?? heroLaneSummary.winrate ?? analysis?.data?.overall_win_rate;
  const heroGames = heroLaneSummary.games ?? heroLaneSummary.total_games ?? analysis?.data?.total_games_analyzed ?? analysis?.data?.sample_size;
  const championOptions = useMemo(() => champions.some((item) => item.id === selected) ? champions : [...champions, ...(champ ? [champ] : [])], [champions, selected, champ]);
  useEffect(() => {
    if (analysisIsCurrent && preferredLane && preferredRoleApplied.current !== selected) {
      preferredRoleApplied.current = selected;
      if (lane !== preferredLane) setLane(preferredLane);
    }
  }, [analysisIsCurrent, lane, preferredLane, selected]);
  const featureList = bootstrap?.features ?? [];
  const backendStatus = backendState === 'ready' ? 'Backend local conectado' : backendState === 'starting' || backendState === 'restarting' ? 'Conectando backend…' : 'Backend local desconectado';
  return <div className={`app-shell ${sidebarCollapsed ? 'sidebar-collapsed' : ''}`}>
    <aside className="rail" aria-label="Navegación principal">
      <div className="brand"><div className="brand-mark">S</div><span>SOLRALOL</span></div>
      <div className="rail-caption">ACOMPAÑANTE</div>
      <nav id="primary-navigation" aria-label="Secciones">{featureList.map((feature) => <button key={feature.id} className={`nav-item ${section === feature.id ? 'active' : ''}`} onClick={() => setSection(feature.id)} title={feature.label} aria-label={feature.label} aria-current={section === feature.id ? 'page' : undefined}>
        <Icon className="nav-glyph" name={navIcons[feature.id] ?? 'chart'} /><span className="nav-label">{feature.label}</span>
      </button>)}</nav>
      <div className="rail-bottom">
        <button className="sidebar-toggle" type="button" onClick={() => setSidebarCollapsed((collapsed) => !collapsed)} aria-label={sidebarCollapsed ? 'Expandir barra lateral' : 'Contraer barra lateral'} aria-controls="primary-navigation" aria-expanded={!sidebarCollapsed} title={sidebarCollapsed ? 'Expandir barra lateral' : 'Contraer barra lateral'}><Icon name={sidebarCollapsed ? 'panel-open' : 'panel-close'} /><span className="sidebar-toggle-label">{sidebarCollapsed ? 'Expandir barra lateral' : 'Contraer barra lateral'}</span></button>
        <div className={`connection ${backendState === 'ready' ? 'connected' : backendState === 'starting' || backendState === 'restarting' ? 'connecting' : 'disconnected'}`} aria-label={backendStatus} title={backendStatus}><span className="status-dot"/><span className="connection-label">{backendStatus}</span></div>
      </div>
    </aside>
    <main className="main-area">
      <WindowTitleBar label={featureList.find((item) => item.id === section)?.label ?? 'Cargando'}>{section==='live'&&<LiveMatchStatus/>}</WindowTitleBar>
      <div className="content" tabIndex={0} aria-label="Contenido principal">
        {storageMigration && ['preparing','validating','copying','verifying','committing','reinitializing'].includes(storageMigration.state) && <div className="storage-global-progress" role="status"><strong>Migrando datos</strong><span>{storageMigration.message} · {storageMigration.processedFiles ?? 0}/{storageMigration.fileCount} archivos</span></div>}
        <div hidden={section !== 'home'}><HomeDashboard active={section === 'home'} backendReady={backendState === 'ready'} leagueClientConnected={leagueClientConnected} onOpenSaved={openSavedMatches}/></div>
        {section === 'settings' && <SettingsPage backendReady={backendState === 'ready'} initialSection={settingsSection} />}
        <div hidden={section !== 'recordings'}><RecordingsPage active={section === 'recordings'} backendReady={backendState === 'ready'} onOpenSettings={() => setSection('settings')} /></div>
        <div hidden={section !== 'saved-matches'}><SavedMatchesWorkspace active={section === 'saved-matches'} backendReady={backendState === 'ready'} initialMatchId={savedMatchToOpen} autoAnalyzeInitialMatch={savedMatchAutoAnalyze} onInitialMatchOpened={() => setSavedMatchToOpen('')} onAutoAnalysisOpened={() => setSavedMatchAutoAnalyze(false)} /></div>
        <div hidden={section !== 'draft'}><DraftPage active={section === 'draft'} backendReady={backendState === 'ready'} champions={champions} championAssets={championIcons} onRequestChampionIcons={requestChampionIcons} onLeagueClientStatus={setLeagueClientConnected} onChampSelectStart={openDraftOnChampSelect}/></div>
        <div hidden={section !== 'live'}><LiveMatchPage active={section === 'live'} backendReady={backendState === 'ready'} onOpenSaved={()=>openSavedMatches()} /></div>
        <div hidden={section !== 'meta'}><MetaPage active={section === 'meta'} backendReady={backendState === 'ready'} onOpenAnalysis={(champion, role) => { setSelected(champion); setLane(role); setSection('analysis'); }} /></div>
        {section === 'analysis' ? <>
          <section className="analysis-hero">
            <div className="analysis-hero-art" style={{backgroundImage: analysis?.assets?.[`splash:${selected}`] ? `linear-gradient(90deg,#171612 4%,#171612d9 46%,#17161255),url(${analysis.assets[`splash:${selected}`]})` : undefined}} />
            <div className="analysis-hero-main">
              <GameImage src={analysis?.assets?.[`champion:${selected}`] ?? championIcons[selected]} alt={champ?.name ?? selected} className="analysis-champion-icon" fallback={(champ?.name ?? selected).slice(0,1)} />
              <div className="analysis-hero-profile"><div className="eyebrow">ANÁLISIS LOCAL · ESMERALDA+</div><h1>{champ?.name ?? selected}</h1><p>{champ?.title ?? 'League of Legends'}{analysis?.data ? ` · ${textAt(analysis.data, 'basic_info', 'play_style') || 'Datos locales disponibles'}` : ''}</p>
                {analysisIsCurrent && analysis?.data && <div className="analysis-header-stats"><AnalysisStat label="Win rate" value={pct(heroWinRate)} detail={`${heroGames == null ? 'Muestra local' : Number(heroGames).toLocaleString('es-ES')} partidas`} /><AnalysisStat label="Estilo" value={textAt(analysis.data, 'basic_info', 'play_style') || '—'} detail={textAt(analysis.data, 'basic_info', 'damage_type') ? `Daño ${textAt(analysis.data, 'basic_info', 'damage_type')}` : ''}/><AnalysisStat label="Dificultad" value={analysis.data.basic_info && record(analysis.data.basic_info).difficulty_floor != null ? `${text(record(analysis.data.basic_info).difficulty_floor)}–${text(record(analysis.data.basic_info).difficulty_ceiling ?? record(analysis.data.basic_info).difficulty_floor)}/10` : '—'} detail=""/><AnalysisStat label="Parche" value={text(analysis.data.patch_label ?? analysis.data.source_patch) || '—'} detail="Esmeralda+"/></div>}
              </div>
              <div className="analysis-header-controls">
              <div className="analysis-filters">
                <div className="analysis-search"><span>CAMPEÓN</span><ChampionSelector label="Seleccionar campeón" champions={championOptions} value={selected} getIcon={(id) => analysis?.assets?.[`champion:${id}`] ?? championIcons[id] ?? undefined} onOpen={requestChampionIcons} onChange={(id) => { preferredRoleApplied.current = ''; setSelected(id); }}/></div>
                <div className="analysis-role-picker"><div className="analysis-role-heading"><span>POSICIÓN</span><span className="analysis-rank">ESMERALDA+</span></div><div role="group" aria-label="Seleccionar posición">{lanes.map((item) => <button type="button" key={item.id} className={`${lane === item.id ? 'selected' : ''} ${preferredLane === item.id ? 'primary' : ''}`} aria-pressed={lane === item.id} onClick={() => setLane(item.id)}>{item.label}{preferredLane === item.id && <small>Principal</small>}</button>)}</div></div>
              </div>
              <div className="analysis-actions"><button type="button" disabled={analysisUpdate.state === 'running'} onClick={() => updateAnalysis(false)}>Actualizar campeón</button><button type="button" disabled={analysisUpdate.state === 'running'} onClick={() => updateAnalysis(true)}>Actualizar todos</button></div>
              </div>
            </div>
          </section>
          {analysisUpdate.state !== 'idle' && <div className={`analysis-update-status ${analysisUpdate.state}`}><span>{analysisUpdate.message}</span>{analysisUpdate.state === 'running' && <div><i style={{width:`${analysisUpdate.total ? Math.min(100, analysisUpdate.current / analysisUpdate.total * 100) : 0}%`}}/></div>}</div>}
          {analysisLoading && <div className="analysis-loading"><span className="spinner"/> Cargando análisis de {champ?.name ?? selected} · {lanes.find((item) => item.id === lane)?.label}</div>}
          {!analysisLoading && analysisIsCurrent && analysis?.data && <AnalysisView analysis={analysis} variantIndex={selectedRune} onVariantChange={setSelectedRune} laneLabel={lanes.find((item) => item.id === lane)?.label ?? lane} />}
          {!analysisLoading && analysisIsCurrent && analysis && !analysis.data && <div className="analysis-empty"><strong>{analysis.status === 'NO_LOCAL_DATA' ? 'No hay análisis guardado para esta posición' : 'No se pudo cargar este análisis'}</strong><span>{analysis.status === 'NO_LOCAL_DATA' ? `No hay datos locales de ${champ?.name ?? selected} para ${lanes.find((item) => item.id === lane)?.label ?? lane} en Esmeralda+.` : `Estado del repositorio: ${analysis.status.replaceAll('_',' ').toLocaleLowerCase('es')}.`}</span></div>}
        </> : section !== 'home' && section !== 'settings' && section !== 'meta' && section !== 'draft' && section !== 'live' && section !== 'recordings' && section !== 'saved-matches' ? <div className="pending-page"><div className="pending-icon"><Icon name="chart" /></div><div className="eyebrow">MIGRACIÓN EN CURSO</div><h1>{featureList.find((item) => item.id === section)?.label ?? 'Solralol'}</h1><p>Este módulo sigue funcionando en la aplicación de referencia. Su integración con Electron requiere migrar su flujo completo y sus contratos de backend.</p><button onClick={() => setSection('analysis')}>Abrir análisis disponible</button></div> : null}
        {error && <div className="toast" role="status">{error}<button onClick={() => setError('')}>Cerrar</button></div>}
      </div>
    </main>
  </div>;
}

type JsonRecord = Record<string, unknown>;
function record(value: unknown): JsonRecord { return value && typeof value === 'object' && !Array.isArray(value) ? value as JsonRecord : {}; }
function array(value: unknown): unknown[] { return Array.isArray(value) ? value : []; }
function text(value: unknown): string { return typeof value === 'string' || typeof value === 'number' ? String(value) : ''; }
function textAt(value: JsonRecord, ...keys: string[]): string { let current: unknown = value; for (const key of keys) current = record(current)[key]; return text(current); }
function pct(value: unknown): string { const n = Number(value); return Number.isFinite(n) ? `${(n <= 1 ? n * 100 : n).toFixed(1)}%` : '—'; }

function AnalysisView({ analysis, variantIndex, onVariantChange, laneLabel }: { analysis: ChampionAnalysis; variantIndex: number; onVariantChange: (index: number) => void; laneLabel: string }) {
  const [showAllCandidates, setShowAllCandidates] = useState(false);
  const data = analysis.data ?? {};
  const variants = analysis.runeVariants ?? [];
  const activeVariant = variants[Math.min(variantIndex, Math.max(0, variants.length - 1))];
  const profile = activeVariant?.profile ?? data;
  const page = activeVariant?.page ?? array(data.runes ?? data.common_runes)[0] ?? {};
  const assets = analysis.assets ?? {};
  const items = analysis.items ?? [];
  const itemByName = (value: unknown) => {
    const name = typeof value === 'object' && value !== null ? text(record(value).name ?? record(value).item ?? record(value).item_id ?? record(value).id) : text(value);
    return items.find((item) => item.id === name || item.name.toLocaleLowerCase() === name.toLocaleLowerCase() || item.nameEn.toLocaleLowerCase() === name.toLocaleLowerCase());
  };
  const imageForItem = (value: unknown) => { const item = itemByName(value); return item ? assets[`item:${item.id}`] : undefined; };
  const runePage = record(page);
  const primaryTree = text(runePage.primary_tree);
  const secondaryTree = text(runePage.secondary_tree);
  const runesPrimary = array(runePage.slots ?? runePage.runes);
  const runesSecondary = array(runePage.secondary_slots);
  const shards = array(runePage.shards);
  const strategy = record(profile.strategy_and_macro ?? data.strategy_and_macro);
  const curve = record(profile.power_curve_and_scaling ?? data.power_curve_and_scaling);
  const skillOrder = record(profile.skill_order ?? data.skill_order);
  const skillSequence = array(skillOrder.order).map(text).filter(Boolean);
  const matchup = record(profile.matchups ?? data.matchups);
  const situations = record(profile.situational_items ?? data.situational_items);
  const recommended = array(profile.recommended_build);
  const build = array(recommended.length ? recommended : profile.most_played_build ?? data.most_played_build);
  const popularBuild = array(profile.most_played_build ?? data.most_played_build);
  const starts = array(profile.starter_items ?? data.starter_items ?? runePage.starter_items);
  const spikes = array(curve.power_spike_items ?? runePage.power_spike_items ?? data.power_spike_items);
  const spellList = array(profile.summoner_spells ?? data.summoner_spells);
  const recommendations = showAllCandidates ? (analysis.itemCandidates ?? []) : (analysis.recommendations ?? []);
  const itemOptions = record(profile.item_options ?? data.item_options);
  const damage = record(profile.damage_breakdown ?? data.damage_breakdown);
  const control = record(profile.map_and_control ?? data.map_and_control);
  const survival = record(profile.resistances_and_survivability ?? data.resistances_and_survivability);
  const durationCurve = array(data.win_rate_vs_game_length);
  const championSpells = array(record(analysis.profile).spells);
  const profileImage = (kind: string, name: string) => assets[`${kind}:${name}`];

  return <div className="analysis-content">
    <section className="analysis-intro-grid">
      <article className="analysis-card analysis-plan-card"><AnalysisCardTitle eyebrow="PLAN DE PARTIDA" title="Habilidades y estrategia"/><div className="analysis-skill-order"><span>ORDEN DE HABILIDADES · NIVEL 1–18</span>{skillSequence.length ? <SkillOrderGrid order={skillSequence} champion={analysis.champion} assets={assets}/> : <div className="analysis-subempty">Sin orden de habilidades disponible.</div>}{text(skillOrder.priority) && <small>Prioridad: {text(skillOrder.priority).split('').join(' › ')}</small>}</div>{championSpells.length > 0 && <div className="analysis-spell-details">{championSpells.map((spellValue,index) => {const spell=record(spellValue),key=['Q','W','E','R'][index]; return <div key={key}><GameImage src={assets[`ability:${analysis.champion}|${key}`]} alt={key} className="analysis-skill-icon" fallback={key}/><span><b>{key} · {text(spell.name)}</b><small>{text(spell.description)}</small></span></div>;})}</div>}<p className="analysis-description">{text(strategy.about) || 'No hay una descripción estratégica guardada para este campeón.'}</p>{array(strategy.primary_combo).length > 0 && <div className="analysis-combo"><span>COMBO PRINCIPAL</span><b>{array(strategy.primary_combo).map(text).join(' → ')}</b></div>}{Object.keys(damage).length > 0 && <DamageDistribution damage={damage}/>}</article>
      <article className="analysis-card analysis-profile-card" aria-label={`Perfil del campeón ${analysis.champion}`}><RadarChart control={control} survival={survival}/>{durationCurve.length > 0 && <section className="analysis-profile-duration" aria-label="Win rate según la duración de la partida"><span className="eyebrow">RESULTADOS POR DURACIÓN</span><DurationLineChart points={durationCurve}/></section>}</article>
    </section>
    <section className="analysis-setup-grid">
      <article className="analysis-card rune-card"><div className="analysis-card-heading"><div><span className="eyebrow">CONFIGURACIÓN DE RUNAS · {laneLabel.toLocaleUpperCase('es')}</span><h2>Página de runas</h2></div><span className="analysis-source">{variants.length} {variants.length === 1 ? 'configuración' : 'configuraciones'}</span></div>
        {variants.length > 1 && <div className="rune-tabs" role="tablist" aria-label="Configuraciones de runas">{variants.map((variant, index) => <button type="button" role="tab" aria-selected={variantIndex === index} className={variantIndex === index ? 'selected' : ''} key={variant.key} onClick={() => onVariantChange(index)}>{safeLabel(text(record(variant.page).name), `Configuración ${index + 1}`)}<small>{record(variant.page).games ? `${Number(record(variant.page).games).toLocaleString('es-ES')} partidas` : ''}</small></button>)}</div>}
        {runePage && (primaryTree || runesPrimary.length) ? <div className="rune-page-content"><div className="rune-tree-column"><RuneTree assets={assets} name={primaryTree} title="ÁRBOL PRINCIPAL" keystone={text(runePage.keystone)} runes={runesPrimary} /><RuneTree assets={assets} name={secondaryTree} title="ÁRBOL SECUNDARIO" runes={runesSecondary} /></div>{shards.length > 0 && <div className="rune-shards"><span>FRAGMENTOS</span>{shards.map((shard, index) => <div key={`${text(shard)}-${index}`}><GameImage src={profileImage('rune', text(shard))} alt={text(shard)} className="rune-icon" fallback="✦"/><small>{text(shard)}</small></div>)}</div>}<div className="rune-page-meta"><span>{text(runePage.source) || 'Recomendación local'}</span>{runePage.win_rate != null && <b>{pct(runePage.win_rate)} WR</b>}{runePage.games != null && <span>{Number(runePage.games).toLocaleString('es-ES')} partidas</span>}</div></div> : <div className="analysis-subempty">No hay una página de runas válida para esta muestra.</div>}
      </article>
      <article className="analysis-card analysis-starter-card"><AnalysisCardTitle eyebrow="PREPARACIÓN" title="Hechizos y objetos iniciales"/><div className="analysis-spells">{spellList.map((spell, index) => <div className="analysis-spell" key={`${text(spell)}-${index}`}><GameImage src={assets[`spell:${text(spell)}`]} alt={text(spell)} className="analysis-spell-icon" fallback="✦"/><span>{text(spell)}</span></div>)}</div><AnalysisItemSection title="Inicio de partida" items={starts} assets={assets} itemByName={itemByName}/></article>
    </section>
    <section className="analysis-build-situational-grid">
      <article className="analysis-card analysis-build-card"><AnalysisCardTitle eyebrow={`BUILD ACTIVA · ${laneLabel.toLocaleUpperCase('es')}`} title="Build recomendada"/><div className="analysis-item-section"><div className="analysis-item-list">{build.length ? build.map((item, index) => <AnalysisItem key={`${text(item)}-${index}`} value={item} index={index} assets={assets} resolved={itemByName(item)} />) : <div className="analysis-subempty">No hay una build guardada para esta configuración.</div>}</div></div>{popularBuild.length > 0 && <details className="analysis-popular-build"><summary>Build más jugada en la muestra</summary><div className="analysis-item-list">{popularBuild.map((item,index)=><AnalysisItem key={`${text(item)}-${index}`} value={item} index={index} assets={assets} resolved={itemByName(item)} compact />)}</div></details>}<div className="analysis-spike-row"><span>PICOS DE PODER</span><div>{spikes.map((item, index) => <GameImage key={`${text(item)}-${index}`} src={imageForItem(item)} alt={text(item)} className="analysis-item-icon" fallback="✦" />)}</div></div><div className="analysis-build-meta">{profile.core_build_matches != null && <span>{text(profile.core_build_matches)} partidas de muestra</span>}{profile.core_build_win_rate != null && <b>{pct(profile.core_build_win_rate)} WR</b>}</div></article>
      <article className="analysis-card analysis-situational"><AnalysisCardTitle eyebrow="ADAPTACIÓN A LA PARTIDA" title="Objetos situacionales"/><div className="situational-groups">{Object.entries(situations).filter(([, values]) => Array.isArray(values) && values.length > 0).map(([group, values]) => <div className="situational-group" key={group}><h3>{humanize(group)}</h3><div>{(values as unknown[]).map((item, index) => <AnalysisItem key={`${text(item)}-${index}`} value={item} index={index} assets={assets} resolved={itemByName(item)} compact />)}</div></div>)}{Object.keys(situations).length === 0 && <div className="analysis-subempty">No hay grupos situacionales guardados para esta variante.</div>}</div>
        {Object.keys(itemOptions).length > 0 && <details className="analysis-alternatives"><summary>Opciones habituales</summary><div className="analysis-alternative-grid">{Object.entries(itemOptions).map(([group, options]) => <div key={group}><h3>{humanize(group)}</h3>{array(options).map((option, index) => { const item = record(option); const evidence=[item.games != null ? `${Number(item.games).toLocaleString('es-ES')} partidas` : '', item.win_rate != null ? `${pct(item.win_rate)} WR` : ''].filter(Boolean).join(' · '); return <AnalysisItem key={`${text(item.item_id ?? item.name)}-${index}`} value={item.name ?? item.item ?? item.item_id} index={index} assets={assets} resolved={itemByName(item.item_id ?? item.name ?? item.item)} compact description={evidence} />; })}</div>)}</div></details>}
      </article>
    </section>
    <section className={`analysis-final-grid ${recommendations.length ? '' : 'single'}`}>
      {recommendations.length > 0 && <article className="analysis-card"><div className="analysis-card-heading"><div><span className="eyebrow">RECOMENDACIONES CURADAS · SOLOQ</span><h2>Sinergia de objetos</h2></div>{analysis.itemCandidates?.length > analysis.recommendations?.length && <button className="analysis-more-button" type="button" onClick={() => setShowAllCandidates((value) => !value)}>{showAllCandidates ? 'Ver selección principal' : 'Ver más opciones'}</button>}</div><div className="analysis-recommendations">{recommendations.slice(0, showAllCandidates ? 30 : 8).map((item,index)=><div className="analysis-recommendation" key={`${item.item_id}-${index}`}><span className="analysis-rank-number">#{index+1}</span><AnalysisItem value={item} index={index} assets={assets} resolved={itemByName(item.item_id)} compact description={`${item.compatibility_label} · afinidad ${item.score.toFixed(1)}`} /><b className="analysis-synergy-score">{item.score.toFixed(1)}</b></div>)}</div></article>}
      <article className="analysis-card"><AnalysisCardTitle eyebrow="ENFRENTAMIENTOS" title="Matchups de línea"/><div className="analysis-matchup-grid"><MatchupGroup title="MÁS DIFÍCILES" values={array(matchup.counters)} assets={assets} bad/><MatchupGroup title="MÁS FAVORABLES" values={array(matchup.good_against)} assets={assets}/></div>{record(matchup.summary).total_games_analyzed != null && <div className="analysis-foot">Muestra de línea: {Number(record(matchup.summary).total_games_analyzed).toLocaleString('es-ES')} partidas</div>}</article>
    </section>
  </div>;
}

function AnalysisStat({ label, value, detail }: { label: string; value: string; detail: string }) { return <div className="analysis-stat"><span>{label}</span><b>{value}</b><small>{detail || ' '}</small></div>; }
function AnalysisCardTitle({ eyebrow, title }: { eyebrow: string; title: string }) { return <div className="analysis-card-heading"><div><span className="eyebrow">{eyebrow}</span><h2>{title}</h2></div></div>; }
function RuneTree({ assets, name, title, keystone, runes }: { assets: Record<string,string>; name: string; title: string; keystone?: string; runes: unknown[] }) { return <div className="rune-tree"><div className="rune-tree-title"><GameImage src={assets[`rune:${name}`]} alt={name} className="rune-tree-icon" fallback="✦"/><div><span>{title}</span><b>{name || 'Árbol no disponible'}</b></div></div>{keystone && <div className="rune-keystone"><GameImage src={assets[`rune:${keystone}`]} alt={keystone} className="rune-icon large" fallback="✦"/><b>{keystone}</b></div>}<div className="rune-slot-list">{runes.map((rune, index) => { const value = text(rune); return <div key={`${value}-${index}`}><GameImage src={assets[`rune:${value}`]} alt={value} className="rune-icon" fallback="✦"/><span>{value}</span></div>; })}</div></div>; }
function AnalysisItemSection({ title, items, assets, itemByName }: { title: string; items: unknown[]; assets: Record<string,string>; itemByName: (value: unknown) => ChampionAnalysis['items'][number] | undefined }) { return <div className="analysis-item-section"><span className="analysis-item-caption">{title}</span><div className="analysis-item-list">{items.length ? items.map((item,index) => <AnalysisItem key={`${text(item)}-${index}`} value={item} index={index} assets={assets} resolved={itemByName(item)} compact />) : <div className="analysis-subempty">Sin objetos iniciales disponibles.</div>}</div></div>; }
function AnalysisItem({ value, index, assets, resolved, compact = false, description }: { value: unknown; index: number; assets: Record<string,string>; resolved?: ChampionAnalysis['items'][number]; compact?: boolean; description?: string }) { const source=record(value); const name=text(source.name ?? source.item ?? source.item_id ?? source.id ?? value) || resolved?.name || 'Objeto'; const id=text(source.item_id ?? source.id) || resolved?.id; const src=(id && assets[`item:${id}`]) || (resolved && assets[`item:${resolved.id}`]) || assets[`item:${name}`]; const reasons=[...array(source.reasons),...array(source.compatibility_reasons)].map(text).filter(Boolean); const tip=[resolved?.description,description,...reasons].filter(Boolean).join(' · '); return <div className={`analysis-item ${compact?'compact':''}`} title={tip || name}><GameImage src={src} alt={name} className="analysis-item-icon" fallback="✦"/><div><b>{name}</b></div>{!compact && <span>{index+1}</span>}</div>; }
function MatchupGroup({ title, values, assets, bad = false }: { title: string; values: unknown[]; assets: Record<string,string>; bad?: boolean }) { return <div className="analysis-matchup-group"><span className={bad?'bad-text':'good-text'}>{title}</span>{values.slice(0,5).map((value,index)=>{const item=record(value),name=champName(item.champion ?? item.name),games=item.lane_games ?? item.games ?? item.overall_games;return <div className="analysis-matchup" key={`${name}-${index}`}><GameImage src={assets[`champion:${name}`]} alt={name} className="analysis-matchup-icon" fallback={name.slice(0,1)}/><b>{name}</b><span>{pct(item.win_rate ?? item.winrate)}</span><small>{games != null ? `${Number(games).toLocaleString('es-ES')} partidas` : '— partidas'}</small></div>;})}{!values.length&&<div className="analysis-subempty">Muestra no disponible.</div>}</div>; }
function SkillOrderGrid({ order, champion, assets }: { order: string[]; champion: string; assets: Record<string,string> }) { const abilities=['Q','W','E','R']; return <div className="analysis-skill-grid-wrap"><div className="analysis-skill-grid"><span className="skill-grid-corner"/> {Array.from({length:18},(_,i)=><span className="skill-level" key={`level-${i}`}>{i+1}</span>)}{abilities.map((ability)=><Fragment key={ability}><span className="skill-grid-ability"><GameImage src={assets[`ability:${champion}|${ability}`]} alt={ability} className="analysis-skill-icon" fallback={ability}/>{ability}</span>{Array.from({length:18},(_,col)=><span key={`${ability}-${col}`} className={`skill-cell ${order[col]===ability?'leveled':''} ${ability==='R'&&![5,10,15].includes(col)?'ultimate-locked':''}`} title={`Nivel ${col+1}${order[col]===ability?` · sube ${ability}`:''}`}>{order[col]===ability?'•':''}</span>)}</Fragment>)}</div></div>; }
function DamageDistribution({ damage }: { damage: JsonRecord }) { const entries=[['Físico','physical_damage_percent','#c58c58'],['Mágico','magic_damage_percent','#9b7bd0'],['Verdadero','true_damage_percent','#d9c274'] ] as const; const valid=entries.map(([label,key,color])=>({label,color,value:Number(damage[key])})).filter((item)=>Number.isFinite(item.value)&&item.value>=0); const total=valid.reduce((sum,item)=>sum+item.value,0); return <div className="analysis-damage"><span>TIPO DE DAÑO REGISTRADO</span>{total>0?<><div className="analysis-damage-bar" role="img" aria-label={valid.map((item)=>`${item.label} ${item.value}%`).join(', ')}>{valid.map((item)=><i key={item.label} style={{width:`${item.value/total*100}%`,background:item.color}} title={`${item.label}: ${item.value}%`}/>)}</div><div className="analysis-damage-legend">{valid.map((item)=><span key={item.label}><i style={{background:item.color}}/>{item.label} <b>{item.value.toFixed(1)}%</b></span>)}</div></>:<small>Distribución no disponible.</small>}</div>; }
function RadarChart({ control, survival }: { control: JsonRecord; survival: JsonRecord }) { const dimensions:[string,string][]=[['Control','crowd_control'],['Movilidad','mobility'],['Objetivos','objective_control'],['Alcance','range'],['Lateral','side_lane_pressure'],['Equipo','team_fight'],['Utilidad','utility'],['Oleadas','wave_clear'],['Supervivencia','survivability_overall'],['Armadura','armor'],['Res. mágica','magic_resistance'],['Res. CC','survivability_vs_cc']]; const values=dimensions.map(([label,key])=>({label,value:Number(control[key] ?? survival[key])})).filter(item=>Number.isFinite(item.value)); if(values.length<3)return <div className="analysis-subempty">Atributos del campeón no disponibles.</div>; const cx=175,cy=145,r=94,n=values.length; const point=(i:number,scale:number)=>{const a=-Math.PI/2+i*Math.PI*2/n;return `${cx+Math.cos(a)*r*scale},${cy+Math.sin(a)*r*scale}`}; const polygon=values.map((item,i)=>point(i,Math.max(0,Math.min(10,item.value))/10)).join(' '); return <div className="analysis-radar-wrap"><span>ATRIBUTOS · ESCALA 0–10</span><svg className="analysis-radar" viewBox="0 0 350 310" role="img" aria-label="Radar de atributos del campeón">{[.25,.5,.75,1].map(scale=><polygon key={scale} points={values.map((_,i)=>point(i,scale)).join(' ')} fill="none" stroke="#ffffff16"/>)}{values.map((item,i)=>{const a=-Math.PI/2+i*Math.PI*2/n;return <g key={item.label}><line x1={cx} y1={cy} x2={cx+Math.cos(a)*r} y2={cy+Math.sin(a)*r} stroke="#ffffff18"/><text x={cx+Math.cos(a)*(r+17)} y={cy+Math.sin(a)*(r+17)} textAnchor="middle" dominantBaseline="middle">{item.label}</text></g>})}<polygon points={polygon} fill="#c6a26138" stroke="#d4b66f" strokeWidth="2"/>{values.map((item,i)=>{const [x,y]=point(i,Math.max(0,Math.min(10,item.value))/10).split(',');return <circle key={item.label} cx={x} cy={y} r="3" fill="#e6ca87"><title>{item.label}: {item.value}/10</title></circle>})}</svg></div>; }
function DurationLineChart({ points }: { points: unknown[] }) {
  const rows = points.map(record).map((entry) => {
    const raw = Number(entry.winrate);
    return { label: text(entry.label), rate: Number.isFinite(raw) ? (raw <= 1 ? raw * 100 : raw) : Number.NaN, games: Number(entry.games) };
  }).filter((entry) => Number.isFinite(entry.rate));
  if (!rows.length) return <div className="analysis-subempty">No hay datos de duración disponibles.</div>;
  const minValue = Math.min(...rows.map((item) => item.rate));
  const maxValue = Math.max(...rows.map((item) => item.rate));
  const padding = Math.max(4, (maxValue - minValue) * 0.25);
  const low = Math.max(0, Math.floor((minValue - padding) / 5) * 5);
  const high = Math.min(100, Math.ceil((maxValue + padding) / 5) * 5);
  const range = Math.max(10, high - low);
  const top = Math.min(100, high + Math.max(0, (range - (high - low)) / 2));
  const bottom = Math.max(0, top - range);
  const tickStep = range <= 20 ? 5 : 10;
  const ticks = Array.from({ length: Math.floor(range / tickStep) + 1 }, (_, index) => bottom + index * tickStep);
  const w = 760, h = 360, p = { l: 48, r: 20, t: 24, b: 50 };
  const x = (index: number) => p.l + (rows.length < 2 ? 0 : index * (w - p.l - p.r) / (rows.length - 1));
  const y = (value: number) => p.t + (top - value) * (h - p.t - p.b) / Math.max(1, top - bottom);
  const path = rows.map((item, index) => `${index ? 'L' : 'M'} ${x(index)} ${y(item.rate)}`).join(' ');
  return <div className="analysis-duration-line"><svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="xMidYMid meet" role="img" aria-label={`Win rate por duración, escala vertical de ${bottom}% a ${top}%`}>
    {ticks.map((tick) => <g key={tick}><line x1={p.l} x2={w - p.r} y1={y(tick)} y2={y(tick)} stroke="#ffffff16"/><text x={p.l - 8} y={y(tick)} textAnchor="end" dominantBaseline="middle">{tick}%</text></g>)}
    <path d={path} fill="none" stroke="#d4b66f" strokeWidth="3" strokeLinejoin="round" strokeLinecap="round"/>
    {rows.map((item, index) => <g key={`${item.label}-${index}`}><circle cx={x(index)} cy={y(item.rate)} r="4" fill="#e4c77d" stroke="#171612" strokeWidth="2"><title>{item.label} · {item.rate.toFixed(1)}% · {Number.isFinite(item.games) ? item.games : '—'} partidas</title></circle>{(rows.length <= 6 || index === 0 || index === rows.length - 1 || index === Math.floor(rows.length / 2)) && <text x={x(index)} y={h - 9} textAnchor="middle">{item.label}</text>}</g>)}
  </svg><small className="analysis-axis-note">Escala vertical: {bottom}%–{top}%</small></div>;
}
function champName(value: unknown): string { const item=record(value);return text(item.champion??item.name??value); }
function humanize(value: string): string { return value.replaceAll('_',' ').replace(/\b\w/g, char => char.toLocaleUpperCase('es')); }
function safeLabel(value: string, fallback: string): string { return value && !value.includes('\uFFFD') ? value : fallback; }

