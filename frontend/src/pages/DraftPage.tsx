import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { Champion, DraftSnapshot, DraftTeamComposition, HomeDashboard, Lane } from '../types/contracts';
import { GameImage } from '../components/GameImage';
import { ChampionSelector } from '../components/ChampionSelector';
import { Icon } from '../components/Icon';

type ManualSlot = { champion: string; role: Lane | ''; locked: boolean };
const roleOptions: Array<{id: Lane; label: string}> = [
  {id:'top',label:'Top'}, {id:'jungle',label:'Jungla'}, {id:'mid',label:'Medio'}, {id:'adc',label:'Bot'}, {id:'support',label:'Apoyo'},
];
const blankSlots = (allies: boolean): ManualSlot[] => roleOptions.map((role) => ({ champion:'', role: allies ? role.id : '', locked:false }));
const roleLabels: Record<string,string> = {top:'Top',jungle:'Jungla',mid:'Medio',adc:'Bot',support:'Apoyo'};
const phaseLabels: Record<string,string> = {Disconnected:'Cliente desconectado',Lobby:'En sala',ChampSelect:'Selección de campeón',SessionUnavailable:'No hay una sesión de selección activa',InProgress:'Partida en curso',ReadyCheck:'Confirmación',Matchmaking:'Buscando partida',EndOfGame:'Fin de partida'};
const labelText = (value: unknown) => typeof value === 'string' || typeof value === 'number' ? String(value) : '';

export function DraftPage({active,backendReady,champions,championAssets,onRequestChampionIcons,onLeagueClientStatus,onChampSelectStart}:{active:boolean;backendReady:boolean;champions:Champion[];championAssets:Record<string,string|null>;onRequestChampionIcons:(ids:string[])=>void;onLeagueClientStatus:(connected:boolean)=>void;onChampSelectStart:()=>void}) {
  const [localRole,setLocalRole]=useState<Lane>('mid');
  const [allies,setAllies]=useState<ManualSlot[]>(()=>[{champion:'Ahri',role:'mid',locked:false},...roleOptions.filter((role)=>role.id!=='mid').map((role)=>({champion:'',role:role.id,locked:false}))]);
  const [enemies,setEnemies]=useState<ManualSlot[]>(()=>blankSlots(false));
  const [manualBans,setManualBans]=useState<{allies:string[];enemies:string[]}>(()=>({allies:['','','','',''],enemies:['','','','','']}));
  const [snapshot,setSnapshot]=useState<DraftSnapshot>();
  const [personalCounter,setPersonalCounter]=useState<HomeDashboard['analytics']['ranked_dashboard']['counter']>();
  const [counterError,setCounterError]=useState('');
  const [counterRetry,setCounterRetry]=useState(0);
  const counterRequested=useRef(false);
  const [loading,setLoading]=useState(false);
  const [error,setError]=useState('');
  const [notice,setNotice]=useState('');
  const [selectedPage,setSelectedPage]=useState(0);
  const [importing,setImporting]=useState('');
  const inFlight=useRef(false);
  const requestGeneration=useRef(0);
  const hasSnapshot=useRef(false);
  const snapshotFingerprint=useRef('');
  const champSelectSeen=useRef(false);
  const params=useMemo(()=>({champion:allies[0]?.champion||'Ahri',role:localRole,allies:allies.map((slot)=>({champion:slot.champion||undefined,role:slot.role,locked:slot.locked})),enemies:enemies.map((slot)=>({champion:slot.champion||undefined,role:slot.role,locked:slot.locked})),manualBans}),[allies,enemies,localRole,manualBans]);
  const refresh=useCallback(async()=>{
    if (!backendReady || inFlight.current) return;
    inFlight.current=true; const generation=++requestGeneration.current;
    if (!hasSnapshot.current) setLoading(true);
    try { const value=await window.solralol.request('draft.snapshot',params); if(generation===requestGeneration.current) {onLeagueClientStatus(value.connection==='connected');hasSnapshot.current=true;const fingerprint=JSON.stringify(value);if(fingerprint!==snapshotFingerprint.current){snapshotFingerprint.current=fingerprint;setSnapshot(value);setSelectedPage((index)=>Math.min(index,Math.max(0,value.analysis.runes.length-1)));}setError('');} }
    catch(e){if(generation===requestGeneration.current){onLeagueClientStatus(false);setError(e instanceof Error?e.message:'No se pudo consultar el estado del Draft.');}}
    finally {inFlight.current=false;if(generation===requestGeneration.current)setLoading(false);}
  },[backendReady,onLeagueClientStatus,params]);
  useEffect(()=>{if(!backendReady)onLeagueClientStatus(false);},[backendReady,onLeagueClientStatus]);
  useEffect(()=>{
    const selecting=snapshot?.phase==='ChampSelect' && snapshot.live;
    if(selecting&&!champSelectSeen.current){champSelectSeen.current=true;onChampSelectStart();}
    else if(!selecting)champSelectSeen.current=false;
  },[snapshot?.phase,snapshot?.live,onChampSelectStart]);
  useEffect(()=>{void refresh();const timer=window.setInterval(()=>void refresh(),active?3000:8000);return()=>{window.clearInterval(timer);requestGeneration.current++;};},[refresh,active]);
  useEffect(()=>{
    if(!active||!backendReady||counterRequested.current)return;
    counterRequested.current=true; let current=true, settled=false;
    void (async()=>{
      let counter:HomeDashboard['analytics']['ranked_dashboard']['counter']=null;
      try { counter=await window.solralol.request('home.counter'); } catch { /* Older backend process: use the established Home contract. */ }
      if(!counter){
        const home=await window.solralol.request('home.dashboard');
        counter=home.analytics?.ranked_dashboard?.counter??null;
      }
      settled=true;
      if(!current)return;
      setPersonalCounter(counter);
      setCounterError('');
      if(counter?.champion_id)onRequestChampionIcons([counter.champion_id]);
    })().catch(()=>{
      settled=true;
      if(current){setPersonalCounter(null);setCounterError('No se pudo consultar el historial local.');counterRequested.current=false;}
    });
    return()=>{current=false;if(!settled)counterRequested.current=false;};
  },[active,backendReady,onRequestChampionIcons,counterRetry]);
  useEffect(()=>{
    if(!error&&!notice)return;
    const timer=window.setTimeout(()=>{setError('');setNotice('');},5000);
    return()=>window.clearTimeout(timer);
  },[error,notice]);
  const live=snapshot?.live===true;
  const selectedChampion=snapshot?.localChampion||(live?'':params.champion);
  const candidateAnalysis=snapshot?.analysis;
  // Never render champion-specific material unless the response is for the
  // champion currently selected by the local player/manual slot.
  const data=selectedChampion&&candidateAnalysis?.champion===selectedChampion?candidateAnalysis:undefined;
  const build=data?.builds?.[selectedPage]??data?.build;
  const warnings=data?.warnings??[];
  const updateSlot=(team:'allies'|'enemies',index:number,field:'champion'|'role'|'locked',value:string)=>{
    if(live)return;
    const setter=team==='allies'?setAllies:setEnemies;
    setter((current)=>current.map((item,i)=>i===index?(field==='locked'?{...item,locked:value==='true'}:field==='champion'?{...item,champion:value,locked:value?item.locked:false}:{...item,role:value as Lane|''}):item));
    setNotice('');
  };
  const visibleAllies=snapshot?.allies??[];const visibleEnemies=snapshot?.enemies??[];
  const enemyNames=visibleEnemies.map((item)=>item.champion).filter((name):name is string=>!!name);
  const icon=(name:string|undefined|null)=>name?snapshot?.assets[`champion:${name}`]??championAssets[name]??undefined:undefined;
  const itemIcon=(id:string)=>snapshot?.assets[`item:${id}`]??undefined;
  const runes=data?.runes??[];const page=runes[selectedPage];const pageRecord=page??{};
  const importAction=async(kind:'runes'|'build'|'spells'|'all')=>{
    if(!data||!snapshot)return;setImporting(kind);setNotice('');setError('');
    try {const result=await window.solralol.request('draft.import',{kind,champion:snapshot.localChampion,role:(data.role in roleLabels?data.role:'mid') as Lane,pageIndex:selectedPage,enemies:enemyNames});(result.ok?setNotice:setError)(result.message);}
    catch(e){setError(e instanceof Error?e.message:'No se pudo importar la preparación.');}
    finally{setImporting('');}
  };
  const championsOptions=useMemo(()=>[...champions].sort((a,b)=>a.name.localeCompare(b.name,'es')),[champions]);
  return <section className="draft-page">
    <header className="draft-heading"><div><div className="eyebrow">PREPARACIÓN · ESMERALDA+</div><h1>Draft</h1><p>Composición, preparación e integración con League Client.</p></div><div className={`draft-connection ${backendReady&&snapshot?.connection==='connected'?'online':'offline'}`} data-active={active}><i/>{backendReady&&snapshot?.connection==='connected'?'League Client conectado':'League Client no disponible'}<button type="button" onClick={()=>void refresh()} aria-label="Actualizar estado del cliente" title="Actualizar"><Icon name="refresh"/></button></div></header>
    <section className="draft-session-card"><div className="draft-session-head"><div><span className="eyebrow">SESIÓN</span><strong>{phaseLabels[snapshot?.phase??'']??(snapshot?.phase??'Conectando')}</strong></div><span className={`draft-mode ${live?'live':''}`}>{live?'EN VIVO':'PREPARACIÓN MANUAL'}</span></div>
      <div className="draft-teams"><TeamColumn title="Tu equipo" slots={visibleAllies} allies={allies} champions={championsOptions} live={live} icon={icon} onChange={(index,field,value)=>updateSlot('allies',index,field,value)}/><div className="draft-vs">VS</div><TeamColumn title="Equipo rival" slots={visibleEnemies} allies={enemies} champions={championsOptions} live={live} icon={icon} onChange={(index,field,value)=>updateSlot('enemies',index,field,value)}/></div>
      <div className="draft-bans"><BanRow title="Baneos de tu equipo" names={live?(snapshot?.bans.allies??[]):manualBans.allies} icon={icon} live={live} champions={championsOptions} onOpen={onRequestChampionIcons} onSelect={(index,value)=>setManualBans((old)=>({...old,allies:old.allies.map((name,i)=>i===index?value:name)}))}/><BanRow title="Baneos rivales" names={live?(snapshot?.bans.enemies??[]):manualBans.enemies} icon={icon} live={live} champions={championsOptions} onOpen={onRequestChampionIcons} onSelect={(index,value)=>setManualBans((old)=>({...old,enemies:old.enemies.map((name,i)=>i===index?value:name)}))}/></div>
      {live&&<p className="draft-live-note">Las posiciones rivales inferidas se muestran como hipótesis; no se atribuyen enfrentamientos de línea hasta que el cliente las confirme.</p>}
    </section>
    <DraftComposition teams={data?.composition.teams} />
    <div className="draft-analysis-grid">
      <section className="draft-panel draft-bans-panel"><PanelTitle eyebrow="SEGÚN TUS DATOS LOCALES" title="Baneos recomendados"/><p className="draft-explain">Campeones que dificultan la partida de {selectedChampion||(live?'tu selección':'tu selección')}.</p>{data?.bans.length?<div className="draft-ban-recs">{data.bans.map((ban,index)=><div key={`${ban.champion}-${index}`}><span className="draft-ban-rank">{String(index+1).padStart(2,'0')}</span><GameImage src={icon(labelText(ban.champion))} alt={labelText(ban.champion)} fallback="?"/><span className="draft-ban-name"><b>{labelText(ban.champion)}</b><small>{format(Number(ban.win_rate))}% WR <i>·</i> {Number(ban.games)||0} partidas</small></span><span className="draft-ban-tag">Baneo recomendado</span></div>)}</div>:<div className="draft-empty-inline">{live&&!selectedChampion?'Selecciona tu campeón para cargar baneos y preparación.':'No hay counters fiables registrados para este campeón.'}</div>}</section>
      <PersonalCounterCard counter={personalCounter} loading={personalCounter===undefined&&!counterError} error={counterError} icon={icon} onRetry={()=>{counterRequested.current=false;setCounterError('');setPersonalCounter(undefined);setCounterRetry((value)=>value+1);}}/>
      {data&&data.matchups?.length>0&&<section className="draft-panel draft-matchups-panel"><PanelTitle eyebrow="EMPAREJAMIENTOS CON DATOS" title="Matchups de l\u00ednea"/><div className="draft-matchups">{data.matchups.map((match,index)=><div key={`${match.champion}-${index}`}><GameImage src={icon(labelText(match.champion))} alt={labelText(match.champion)} fallback="?"/><b>{labelText(match.champion)}</b><span>{labelText(match.kind)==='counters'?'Counter registrado':'A favor'}</span><strong>{format(Number(match.winRate)>1?Number(match.winRate):Number(match.winRate)*100)}% WR</strong><small>{Number(match.games)||'-'} partidas</small></div>)}</div></section>}
      {data&&data.matchups?.length>0&&<section className="draft-panel"><PanelTitle eyebrow="EMPAREJAMIENTOS CON DATOS" title="Matchups de l\u00ednea"/><div className="draft-matchups">{data.matchups.map((match,index)=><div key={`${match.champion}-${index}`}><GameImage src={icon(labelText(match.champion))} alt={labelText(match.champion)} fallback="?"/><b>{labelText(match.champion)}</b><span>{labelText(match.kind)==='counters'?'Counter registrado':'A favor'}</span><strong>{format(Number(match.winRate)>1?Number(match.winRate):Number(match.winRate)*100)}% WR</strong><small>{Number(match.games)||'-'} partidas</small></div>)}</div></section>}
    </div>
    <section className="draft-panel draft-preparation"><div className="draft-prep-head"><div><PanelTitle eyebrow="IMPORTACIÓN LCU · ESMERALDA+" title="Preparación"/><p>{selectedChampion||'Sin campeón seleccionado'} · {roleLabels[data?.role??(live?'':'mid')]??(live?'Posición pendiente':'Medio')}{live&&!snapshot?.localRoleKnown?' · provisional':''}</p></div><label className="draft-local-role">Mi posición<select disabled={live&&!!snapshot?.localRoleKnown} value={live?(data?.role??localRole):localRole} onChange={(event)=>setLocalRole(event.target.value as Lane)}>{roleOptions.map((role)=><option key={role.id} value={role.id}>{role.label}</option>)}</select></label><span className="draft-mode">DATOS LOCALES</span></div>{warnings.length>0&&<div className="draft-warnings">{warnings.map((warning,index)=><span key={`${index}-${warning}`}>{warning}</span>)}</div>}
      {runes.length>0?<><div className="draft-rune-tabs" role="tablist" aria-label="Páginas recomendadas">{runes.map((rune,index)=><button type="button" role="tab" aria-selected={index===selectedPage} className={index===selectedPage?'selected':''} onClick={()=>setSelectedPage(index)} key={String(rune.source??rune.name??index)}>Página {index+1}{rune.source?` · ${labelText(rune.source)}`:''}</button>)}</div><RunePage page={pageRecord} assets={snapshot?.assets??{}}/></>:<div className="draft-empty-inline">{data?.variantStatus==='AVAILABLE'?'Esta variante aún no incluye páginas de runas.':'No hay preparación Esmeralda+ guardada para este campeón y posición.'}</div>}
      <div className="draft-prep-columns"><div className="draft-build-block"><h3>Build recomendada</h3><div className="draft-item-list">{(build?.items??[]).map((item:any,index:number)=><div key={`${item.id}-${index}`}><span className="draft-order">{index+1}</span><GameImage src={itemIcon(String(item.id))} alt={String(item.name??item.id)} fallback="◇"/><b>{String(item.name??item.id)}</b></div>)}{build?.boots&&<div><span className="draft-order">+</span><GameImage src={itemIcon(String(build.boots.id))} alt={String(build.boots.name)} fallback="◇"/><b>{String(build.boots.name)}</b></div>}</div>{!build?.items?.length&&<small>Sin build local disponible.</small>}</div>
      <div className="draft-spells-block"><h3>Hechizos de invocador</h3><div className="draft-spell-list">{(data?.spells??[]).map((spell)=><div key={spell}><GameImage src={snapshot?.assets[`spell:${spell}`]??undefined} alt={spell} fallback="✦"/><b>{spell}</b></div>)}</div><h3>Objetos situacionales</h3><div className="draft-situational">{(data?.situational??[]).map((group)=><div key={String(group.key)}><b>{String(group.label)}</b>{(Array.isArray(group.items)?group.items:[]).map((item:any)=><span key={String(item.id)}><GameImage src={itemIcon(String(item.id))} alt={String(item.name)} fallback="◇"/>{String(item.name)}</span>)}</div>)}</div></div></div>
      <div className="draft-import-actions"><button type="button" disabled={!!importing||!page} onClick={()=>void importAction('runes')}>{importing==='runes'?'Importando…':'Importar runas'}</button><button type="button" disabled={!!importing||!build?.items?.length} onClick={()=>void importAction('build')}>{importing==='build'?'Importando…':'Importar build'}</button><button type="button" disabled={!!importing||!(data?.spells?.length)} onClick={()=>void importAction('spells')}>{importing==='spells'?'Aplicando…':'Aplicar hechizos'}</button><button className="primary" type="button" disabled={!!importing||!page||!build?.items?.length} onClick={()=>void importAction('all')}>{importing==='all'?'Preparando…':'Importar preparación'}</button></div>
    </section>
    {(loading||error||notice)&&<div className={`draft-feedback ${error?'error':''}`} role="status" aria-live="polite"><span className="draft-feedback-message">{loading?'Conectando con el backend...':error||notice}</span>{!loading&&<button type="button" className="draft-feedback-close" aria-label="Cerrar notificaci?n" title="Cerrar" onClick={()=>{setError('');setNotice('');}}>×</button>}</div>}
  </section>;
}
const DRAFT_PHASES=['0-15','15-20','20-25','25-30','30-35','35-40','40+'] as const;

function PersonalCounterCard({counter,loading,error,icon,onRetry}:{counter:HomeDashboard['analytics']['ranked_dashboard']['counter']|undefined;loading:boolean;error:string;icon:(name:string|undefined|null)=>string|undefined;onRetry:()=>void}) {
  return <section className="draft-panel draft-personal-counter"><PanelTitle eyebrow="HISTORIAL SOLOQ GLOBAL" title="Tu rival más difícil"/><p className="draft-explain">Resume todas tus partidas guardadas; no depende del campeón que estás seleccionando.</p>
    {loading?<div className="draft-counter-empty">Cargando tu counter...</div>:error?<div className="draft-counter-empty"><b>No se pudo cargar tu counter</b><span>{error}</span><button type="button" onClick={onRetry}>Reintentar</button></div>:counter?<div className="draft-counter-feature"><GameImage src={icon(counter.champion_id)} alt={counter.name} fallback="?"/><div className="draft-counter-details"><span>Tu rival más difícil</span><h3>{counter.name}</h3><strong>{counter.losses} derrotas</strong><small>{counter.winrate==null?'WR no disponible':`${format(counter.winrate)}% WR`} <i>·</i> {counter.encounters} enfrentamientos</small></div><span className="draft-counter-mark">!</span></div>:<div className="draft-counter-empty"><b>Sin counter registrado</b><span>No hay derrotas contra campeones identificados en tu historial local.</span></div>}
  </section>;
}

function DraftComposition({teams}:{teams?:{allies:DraftTeamComposition;enemies:DraftTeamComposition}}) {
  const allies=teams?.allies, enemies=teams?.enemies;
  const rows=DRAFT_PHASES.map((phase)=>({phase,ally:allies?.powerCurve?.[phase],allyN:allies?.powerCurveSamples?.[phase]??0,enemy:enemies?.powerCurve?.[phase],enemyN:enemies?.powerCurveSamples?.[phase]??0}));
  const values=rows.flatMap((row)=>[row.ally,row.enemy]).filter((value):value is number=>typeof value==='number'&&Number.isFinite(value));
  const minValue=values.length?Math.min(...values):40, maxValue=values.length?Math.max(...values):60;
  // The 40-60% default makes near-50% variations easier to read and expands for real outliers.
  // in steps of 10 when real values fall outside, so valid points are never clipped.
  const minY=Math.max(0,Math.min(40,Math.floor(minValue/10)*10));
  const maxY=Math.min(100,Math.max(60,Math.ceil(maxValue/10)*10));
  const x0=76,x1=944,y0=24,y1=266;
  const xAt=(index:number)=>x0+(x1-x0)*index/(DRAFT_PHASES.length-1);
  const yAt=(value:number)=>y1-(value-minY)/(maxY-minY)*(y1-y0);
  const segments=(key:'ally'|'enemy')=>{
    const output:string[][]=[]; let active:string[]=[];
    rows.forEach((row,index)=>{const value=row[key];if(typeof value==='number'&&Number.isFinite(value)){active.push(`${xAt(index)},${yAt(value)}`);}else if(active.length){output.push(active);active=[];}});
    if(active.length)output.push(active); return output;
  };
  const tickStep=maxY-minY<=30?5:10;
  const firstTick=Math.ceil(minY/tickStep)*tickStep;
  const ticks=Array.from({length:Math.floor((maxY-firstTick)/tickStep)+1},(_,i)=>firstTick+i*tickStep);
  return <section className="draft-panel draft-composition-panel"><PanelTitle eyebrow="ANÁLISIS DE EQUIPO" title="Composición"/>
    <div className="draft-team-counts"><span><b>{allies?.selected??0}/5</b> aliados seleccionados</span><span><b>{enemies?.selected??0}/5</b> rivales revelados</span></div>
    <div className="draft-damage-section"><div className="draft-damage-heading"><b>Distribución estimada de daño</b><small>Calculada con perfiles locales; no representa daño observado en una partida.</small></div><div className="draft-damage-comparison"><DamageEstimate title="Tu equipo" team={allies}/><DamageEstimate title="Equipo rival" team={enemies}/></div></div>
    <div className="draft-curve-comparison"><div className="draft-curve-heading"><div><b>Win rate estimado por duración</b><small>Medias históricas de los perfiles locales disponibles; no son una predicción directa del enfrentamiento.</small></div><div className="draft-curve-legend"><span><i className="ally"/>Tu equipo</span><span><i className="enemy"/>Equipo rival</span></div></div>
      {values.length?<div className="draft-curve-chart-wrap"><svg className="draft-curve-chart" viewBox="0 0 980 330" role="img" aria-label="Comparación del win rate histórico de perfiles por duración de partida">
        <title>Win rate estimado por duración de partida</title>
        {ticks.map((tick)=><g key={`tick-${tick}`}><line x1={x0} x2={x1} y1={yAt(tick)} y2={yAt(tick)}/><text x={x0-12} y={yAt(tick)+4} textAnchor="end">{tick}%</text></g>)}
        {minY<=50&&maxY>=50&&!ticks.includes(50)&&<line x1={x0} x2={x1} y1={yAt(50)} y2={yAt(50)} className="reference"/>}
        {rows.map((row,index)=><text key={`phase-${row.phase}`} x={xAt(index)} y={y1+30} textAnchor="middle">{row.phase}</text>)}
        {segments('ally').map((points,index)=><polyline key={`ally-segment-${index}`} points={points.join(' ')} className="ally-line"/>)}
        {segments('enemy').map((points,index)=><polyline key={`enemy-segment-${index}`} points={points.join(' ')} className="enemy-line"/>)}
        {rows.map((row,index)=>row.ally==null?null:<circle key={`ally-${row.phase}`} cx={xAt(index)} cy={yAt(row.ally)} r="5"><title>{`${row.phase} min · Tu equipo · ${format(row.ally)}% · ${row.allyN} perfiles`}</title></circle>)}
        {rows.map((row,index)=>row.enemy==null?null:<circle key={`enemy-${row.phase}`} cx={xAt(index)} cy={yAt(row.enemy)} r="5" className="enemy-point"><title>{`${row.phase} min · Equipo rival · ${format(row.enemy)}% · ${row.enemyN} perfiles`}</title></circle>)}
      </svg></div>:<div className="draft-empty-inline">No hay curvas históricas locales disponibles para los campeones seleccionados.</div>}
    </div>
  </section>;
}
function DamageEstimate({title,team}:{title:string;team?:DraftTeamComposition}) {
  const damage=team?.damage;
  return <div className="draft-team-estimate"><div className="draft-team-estimate-heading"><b>{title}</b><small>{team?.damageSamples??0}/5 perfiles disponibles</small></div>
    {damage?<><div className="draft-damage-bar" role="img" aria-label={`${title}: físico ${format(damage.physical)}%, mágico ${format(damage.magic)}%, verdadero ${format(damage.true)}%`}><i className="physical" style={{width:`${damage.physical}%`}}/><i className="magic" style={{width:`${damage.magic}%`}}/><i className="true" style={{width:`${damage.true}%`}}/></div><div className="draft-damage-legend"><span><i className="physical"/>Físico <b>{format(damage.physical)}%</b></span><span><i className="magic"/>Mágico <b>{format(damage.magic)}%</b></span><span><i className="true"/>Verdadero <b>{format(damage.true)}%</b></span></div></>:<div className="draft-empty-inline">Sin perfiles de daño fiables para esta composición.</div>}
  </div>;
}

function TeamColumn({title,slots,allies,champions,live,icon,onChange}:{title:string;slots:DraftSnapshot['allies'];allies:ManualSlot[];champions:Champion[];live:boolean;icon:(name:string|null|undefined)=>string|undefined;onChange:(index:number,field:'champion'|'role'|'locked',value:string)=>void}) {return <div className="draft-team-column"><h2>{title}</h2>{slots.map((slot,index)=>{const effective=slot.locked?slot.champion:(slot.intent??slot.champion);const status=slot.locked?'':slot.intent?'Intención: ':slot.champion?'Hover: ':'';return <div className={`draft-slot ${slot.local?'local':''}`} key={`${title}-${slot.cellId}-${index}`}><GameImage src={icon(effective)} alt={effective??'Sin selección'} fallback={effective?.slice(0,1)??'+'}/><div className="draft-slot-main">{live?<><b>{effective?`${status}${effective}`:'Sin selección'}</b><small>{[slot.player,slot.role?`${roleLabels[slot.role]??slot.role}${slot.roleKnown?'':' · probable'}`:'Posición desconocida',slot.winRate!=null?`WR ${format(slot.winRate)}%`:'' ].filter(Boolean).join(' · ')}</small></>:<><select value={allies[index]?.champion??''} onChange={(e)=>onChange(index,'champion',e.target.value)} aria-label={`${title}, campeón ${index+1}`}><option value="">Seleccionar campeón</option>{champions.map((champion)=><option key={champion.id} value={champion.id}>{champion.name}</option>)}</select><small>{slot.winRate!=null?`WR global local ${format(slot.winRate)}%`:allies[index]?.champion?'Sin win rate local fiable':''}</small></>}</div>{!live?<><select className="draft-role-select" value={allies[index]?.role??''} onChange={(e)=>onChange(index,'role',e.target.value)} aria-label={`${title}, posición ${index+1}`}><option value="">Posición</option>{roleOptions.map((role)=><option key={role.id} value={role.id}>{role.label}</option>)}</select><label className="draft-confirm-state"><input type="checkbox" checked={!!allies[index]?.locked} disabled={!allies[index]?.champion} onChange={(e)=>onChange(index,'locked',String(e.target.checked))}/><span>{allies[index]?.locked?'Confirmado':'Provisional'}</span></label></>:<span className="draft-slot-state">{slot.locked?'Confirmado':'Provisional'}</span>}</div>;})}</div>}
function BanRow({title,names,icon,live,champions,onOpen,onSelect}:{title:string;names:string[];icon:(name:string|null|undefined)=>string|undefined;live:boolean;champions:Champion[];onOpen:(ids:string[])=>void;onSelect:(index:number,value:string)=>void}) {
  return <div className="draft-ban-row"><b>{title}</b><div className="draft-ban-slots">{Array.from({length:5},(_,index)=><ChampionSelector key={`${title}-${index}`} variant="compact" label={`${title}, hueco ${index+1}`} placeholder={`B${index+1}`} champions={champions} value={names[index]??''} getIcon={(id)=>icon(id)} disabled={live} onOpen={onOpen} onChange={(id)=>onSelect(index,id)}/>)}</div></div>;
}
export function RunePage({page,assets}:{page:Record<string,unknown>;assets:Record<string,string|null>}) {
  const list = (value:unknown):unknown[] => Array.isArray(value) ? value : [];
  const groups = [
    {kind:'primary', title:`RUNAS PRINCIPALES · ${labelText(page.primary_tree)||'—'}`, names:[page.keystone,...list(page.slots)], ids:[page.keystone_id,...list(page.slot_ids)]},
    {kind:'secondary', title:`SECUNDARIAS · ${labelText(page.secondary_tree)||'—'}`, names:list(page.secondary_slots), ids:list(page.secondary_slot_ids)},
    {kind:'shards', title:'FRAGMENTOS', names:list(page.shards), ids:list(page.shard_ids)},
  ];
  return <div className="draft-rune-page">{groups.map(group=><div className={`draft-rune-tree ${group.kind}`} key={group.kind}><span>{group.title}</span><div className="draft-rune-icons">{Array.from({length:Math.max(group.names.length,group.ids.length)},(_,index)=>{
    const name=labelText(group.names[index])||'Runa';
    const id=String(group.ids[index]??'');
    return <div key={`${id||name}-${index}`}><GameImage src={assets[`rune:${id}`]??assets[`rune:${name}`]??undefined} alt={name} title={name} fallback="·"/><b>{name}</b></div>;
  })}</div></div>)}</div>;
}
function PanelTitle({eyebrow,title,compact=false}:{eyebrow:string;title:string;compact?:boolean}) {return <div className={`draft-panel-title ${compact?'compact':''}`}><span className="eyebrow">{eyebrow}</span><h2>{title}</h2></div>}
function format(value:number|undefined) {return Number.isFinite(value)?Number(value).toLocaleString('es-ES',{maximumFractionDigits:1}):'—';}
