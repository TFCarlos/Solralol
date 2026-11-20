import { useEffect, useMemo, useRef, useState } from 'react';
import { WindowTitleBar } from '../components/WindowTitleBar';
import type { RecordingReview, RecordingReviewEvent, RecordingReviewParticipant } from '../types/contracts';

type SideKey = 'allied' | 'enemy';
type Selection = Record<SideKey, string | 'team' | ''>;
type ReviewTab = 'scoreboard' | 'review' | 'ai';
const groups: Array<[string,string]> = [['kill','Asesinatos'],['death','Muertes'],['assist','Asistencias'],['dragon','Dragones'],['herald','Heraldos'],['baron','Barones'],['horde','Larvas'],['tower','Torres'],['inhibitor','Inhibidores'],['nexus','Nexo'],['item_purchase','Compras'],['item_sale','Ventas']];
const labels=['CS/min','Oro/min','Visión','KDA','Kills + asist.'];
const roleLabels:Record<string,string>={TOP:'Top',JUNGLE:'Jungla',MIDDLE:'Medio',MID:'Medio',BOTTOM:'Bot',ADC:'Bot',UTILITY:'Apoyo',SUPPORT:'Apoyo'};
const fmt=(s:number)=>{const n=Math.max(0,Math.floor(Number.isFinite(s)?s:0));return `${String(Math.floor(n/60)).padStart(2,'0')}:${String(n%60).padStart(2,'0')}`;};
const category=(e:RecordingReviewEvent)=>String(e.category||e.type||'other').toLowerCase();
const categoriesFor=(e:RecordingReviewEvent)=>e.categories?.length?e.categories:[category(e)];
const categoryForSelection=(e:RecordingReviewEvent,ids:Set<string>)=>e.participant_roles?.find(role=>ids.has(role.participantId))?.category||category(e);
const categoryLabels:Record<string,string>={kill:'Asesinato',death:'Muerte',assist:'Asistencia',dragon:'Dragón',baron:'Nashor',herald:'Heraldo',rift_herald:'Heraldo',horde:'Larvas',tower:'Torre',inhibitor:'Inhibidor',nexus:'Nexo',item_purchase:'Compra',item_sale:'Venta'};
const categorySummary=(e:RecordingReviewEvent,ids:Set<string>)=>{const roles=e.participant_roles?.filter(role=>ids.has(role.participantId))||[];const values=roles.length?roles.map(role=>role.category):categoriesFor(e);return [...new Set(values)].map(value=>categoryLabels[value]||value).join(' · ');};
const eventDisplayLabel=(event:RecordingReviewEvent,roster:RecordingReviewParticipant[],allEvents:RecordingReviewEvent[])=>{
  const roles=event.participant_roles||[];
  const kinds=categoriesFor(event);
  const combatNames=[...new Set([
    ...roles.map(role=>role.champion),
    ...(event.champions||[]),
    ...(event.participants||[]).map(id=>roster.find(player=>player.participantId===id)?.champion||''),
  ].filter(Boolean))];
  const hasKill=kinds.some(value=>['kill','kill_exact'].includes(value))||event.type==='kill';
  const killer=event.killerChampion||roles.find(role=>role.category==='kill')?.champion||(hasKill?event.champion:undefined);
  let victim=event.victimChampion||roles.find(role=>role.category==='death')?.champion||combatNames.find(name=>name!==killer);
  if(!victim&&killer&&hasKill){
    const deathName=(candidate:RecordingReviewEvent)=>candidate.victimChampion||candidate.participant_roles?.find(role=>role.category==='death')?.champion||
      (categoriesFor(candidate).some(value=>['death','death_exact'].includes(value))?candidate.champion:'')||'';
    const sameEvent=allEvents.filter(candidate=>candidate.event_id&&candidate.event_id===event.event_id).map(deathName).filter(name=>name&&name!==killer);
    const eventTime=event.game_time??event.time;
    const nearby=allEvents.filter(candidate=>categoriesFor(candidate).some(value=>['death','death_exact'].includes(value))&&
      Number.isFinite(eventTime)&&Number.isFinite(candidate.game_time??candidate.time)&&Math.abs(Number(candidate.game_time??candidate.time)-Number(eventTime))<=1.25)
      .map(deathName).filter(name=>name&&name!==killer);
    const candidates=[...new Set(sameEvent.length?sameEvent:nearby)];
    if(candidates.length===1)victim=candidates[0];
  }
  const assister=roles.find(role=>role.category==='assist')?.champion;
  const isCombat=kinds.some(value=>['kill','death','assist','kill_exact','death_exact','assist_exact'].includes(value));
  if(killer&&victim)return `${killer} asesin\u00f3 a ${victim}`;
  if(killer)return `${killer} consigui\u00f3 una eliminaci\u00f3n`;
  if(victim)return `${victim} murió; asesino no identificado`;
  if(assister)return `${assister} asistió en una eliminaci\u00f3n`;
  if(isCombat&&event.champion&&hasKill&&victim)return `${event.champion} asesin\u00f3 a ${victim}`;
  // La etiqueta histórica puede contener Riot ID o el nombre de invocador. Para
  // combate incompleto preferimos un texto neutro antes que exponer esa identidad.
  if(isCombat)return categorySummary(event,new Set())||'Evento de combate';
  return event.label||event.type||'Evento';
};
const totalKills=(players:RecordingReviewParticipant[])=>players.length===5&&players.every(p=>p.kills!=null)?players.reduce((sum,p)=>sum+(p.kills||0),0):'—';

function Radar({datasets}:{datasets:Array<{label:string;values:Array<number|null>;raw:RecordingReviewParticipant[];side:SideKey}>}) {
  const point=(values:Array<number|null>)=>values.map((v,i)=>{const a=-Math.PI/2+i*2*Math.PI/5,r=72*(v??0);return `${94+r*Math.cos(a)},${82+r*Math.sin(a)}`;}).join(' ');
  return <section className="review-radar"><h3>Comparativa de rendimiento</h3>{!datasets.length?<p className="review-empty">Selecciona jugadores o un equipo para comparar.</p>:<><svg viewBox="0 0 188 170" role="img" aria-label="Comparativa normalizada de rendimiento">{[.25,.5,.75,1].map(r=><polygon key={r} points={labels.map((_,i)=>{const a=-Math.PI/2+i*2*Math.PI/5;return `${94+72*r*Math.cos(a)},${82+72*r*Math.sin(a)}`;}).join(' ')} className="review-radar-grid"/>)}{datasets.map(d=><polygon key={d.side} points={point(d.values)} className={`review-radar-shape ${d.side}`}/>)}{labels.map((l,i)=>{const a=-Math.PI/2+i*2*Math.PI/5;return <text key={l} x={94+87*Math.cos(a)} y={82+87*Math.sin(a)} textAnchor="middle" dominantBaseline="middle">{l}</text>;})}</svg><div className="review-radar-legend">{datasets.map(d=><div key={d.side} className={d.side}><b>{d.label}</b><small>{d.raw.map(p=>`${p.champion}: ${p.kills??'—'}/${p.deaths??'—'}/${p.assists??'—'} · ${p.cs??'—'} CS`).join(' | ')}</small></div>)}</div></>}</section>;
}

export function RecordingReviewWindow({recordingId}:{recordingId:string}) {
  const [review,setReview]=useState<RecordingReview>();const [error,setError]=useState('');const [loading,setLoading]=useState(true);const [tab,setTab]=useState<ReviewTab>('scoreboard');
  const [selection,setSelection]=useState<Selection>({allied:'',enemy:''});const [categories,setCategories]=useState(()=>new Set(groups.map(([id])=>id)));
  const [duration,setDuration]=useState(0);const [current,setCurrent]=useState(0);const [playing,setPlaying]=useState(false);const [volume,setVolume]=useState(1);const [muted,setMuted]=useState(false);const [rate,setRate]=useState(1);const [generating,setGenerating]=useState(false);const [selectedEventId,setSelectedEventId]=useState('');
  const [source,setSource]=useState('');const [title,setTitle]=useState('Repaso de partida');const [championIcons,setChampionIcons]=useState<Record<string,string|null>>({});const [itemIcons,setItemIcons]=useState<Record<string,string|null>>({});
  const videoRef=useRef<HTMLVideoElement>(null);const seekRef=useRef<HTMLInputElement>(null);
  useEffect(()=>{let live=true;setLoading(true);window.solralol.request('recordings.list').then(rows=>{const row=rows.find(item=>item.id===recordingId);if(!row?.playbackUrl)throw new Error('No se encontró el archivo de vídeo.');if(live){setSource(row.playbackUrl);setTitle(row.title);}return window.solralol.request('recordings.review',{id:recordingId});}).then(value=>{if(live){setReview(value);setDuration(value.duration||0);}}).catch((e:Error)=>{if(live)setError(e.message);}).finally(()=>{if(live)setLoading(false);});return()=>{live=false;videoRef.current?.pause();if(videoRef.current){videoRef.current.removeAttribute('src');videoRef.current.load();}};},[recordingId]);
  useEffect(()=>{if(!review)return;let active=true;const champs=[...new Set([...review.participants.map(p=>p.champion),...review.events.flatMap(e=>e.champions||[])].filter(Boolean))].slice(0,20);const items=[...new Set([...review.participants.flatMap(p=>p.items||[]).map(String),...review.events.map(e=>e.itemId).filter((id):id is string=>Boolean(id))])].filter(id=>/^\d{1,8}$/.test(id)&&Number(id)>0).slice(0,200);void window.solralol.request('home.assets',{champions:champs}).then(r=>{if(active)setChampionIcons(r.champions)}).catch(()=>{});for(let i=0;i<items.length;i+=20){void window.solralol.request('meta.assets',{items:items.slice(i,i+20)}).then(result=>{if(active)setItemIcons(previous=>({...previous,...Object.fromEntries(items.slice(i,i+20).map(id=>[id,result[`item:${id}`]||null]))}))}).catch(()=>{});}return()=>{active=false};},[review]);
  const participants=review?.participants??[];const allies=participants.filter(p=>p.side==='allied'||p.allied===true);const enemies=participants.filter(p=>p.side==='enemy'||p.allied===false);
  const membership=(side:SideKey)=>side==='allied'?allies:enemies;
  const chosen=(side:SideKey)=>selection[side]==='team'?membership(side):membership(side).filter(p=>p.participantId===selection[side]);
  const selectedIds=new Set([...chosen('allied'),...chosen('enemy')].map(p=>p.participantId).filter((id):id is string=>Boolean(id)));
  const events=useMemo(()=>{const alliedPicked=chosen('allied');const enemyPicked=chosen('enemy');const picked=new Set([...alliedPicked,...enemyPicked].map(p=>p.participantId).filter(Boolean));if(!picked.size)return [];return (review?.events??[]).filter(e=>{const roles=e.participant_roles||[];const selectedRoles=roles.filter(role=>picked.has(role.participantId));const roleMatch=selectedRoles.some(role=>categories.has(role.category));const teamMatch=!roles.length&&!e.participants?.length&&((e.side==='allied'&&alliedPicked.length>0)||(e.side==='enemy'&&enemyPicked.length>0)||(e.side==='unknown'&&alliedPicked.length>0&&enemyPicked.length>0));const legacyMatch=!roles.length&&(e.participants??[]).some(id=>picked.has(id));return categoriesFor(e).some(value=>categories.has(value))&&(roleMatch||teamMatch||legacyMatch);});},[review,selection,categories]);
  const markers=useMemo(()=>events.filter(e=>typeof e.video_time==='number'&&e.video_time<= (duration||Infinity)),[events,duration]);
  // Mantén sincronizados el marcador y la fila más cercana al cabezal, tanto al
  // reproducir como al desplazarse con la barra de búsqueda.
  const activeEvent=useMemo(()=>{
    let closest:RecordingReviewEvent|undefined;let distance=1.25;
    for(const event of markers){const delta=Math.abs((event.video_time??Infinity)-current);if(delta<=distance){closest=event;distance=delta;}}
    return closest;
  },[markers,current]);
  const highlightedEventId=activeEvent?.event_id||(selectedEventId&&events.some(event=>event.event_id===selectedEventId&&typeof event.video_time!=='number')?selectedEventId:'');
  const radarDatasets=useMemo(()=>{const result:Array<{label:string;values:Array<number|null>;raw:RecordingReviewParticipant[];side:SideKey}>=[];for(const side of ['allied','enemy'] as SideKey[]){const raw=chosen(side);if(!raw.length)continue;const isTeam=selection[side]==='team';const values=isTeam?review?.radarTeams?.[side]??[]:raw[0].radar??[];result.push({label:isTeam?(side==='allied'?'Tu equipo':'Equipo rival'):raw[0].champion,values,raw,side});}return result;},[selection,review,participants]);
  const setSide=(side:SideKey,id:string|'team')=>setSelection(prev=>({...prev,[side]:prev[side]===id?'':id}));
  const jump=(s:number)=>{const v=videoRef.current;const target=Math.max(0,Math.min(v?.duration||duration,s));setCurrent(target);if(v)v.currentTime=target;};
  const toggle=()=>{const v=videoRef.current;if(!v)return;if(v.paused)void v.play().catch(e=>setError(e.message));else v.pause();};
  const setAll=()=>setSelection({allied:'team',enemy:'team'});
  const selectParticipant=(id:string)=>{const side:SideKey=allies.some(p=>p.participantId===id)?'allied':'enemy';setSide(side,id);};
  const seekEvent=(event:RecordingReviewEvent)=>{if(!event.event_id)return;setSelectedEventId(event.event_id);if(typeof event.video_time==='number')jump(event.video_time);};
  const badgeFor=(event:RecordingReviewEvent)=>{
    const chosenPlayers=[...chosen('allied'),...chosen('enemy')];
    const involvedIds=new Set([...(event.participant_roles||[]).map(role=>role.participantId),...(event.participants||[])]);
    const names=[...new Set((event.participant_roles||[]).filter(role=>selectedIds.has(role.participantId)||chosenPlayers.some(player=>player.champion.toLocaleLowerCase()===role.champion.toLocaleLowerCase())).map(role=>role.champion).filter(Boolean))];
    for(const player of chosenPlayers){if(player.participantId&&involvedIds.has(player.participantId)&&!names.includes(player.champion))names.push(player.champion);}
    // Las transacciones normalizadas también conservan el campeón del comprador;
    // úsalo como respaldo para sesiones antiguas que no serializaban participant_roles.
    if(event.champion&&chosenPlayers.some(player=>player.champion.toLocaleLowerCase()===event.champion!.toLocaleLowerCase())&&!names.includes(event.champion))names.push(event.champion);
    for(const id of involvedIds){const player=participants.find(candidate=>candidate.participantId===id);if(player&&selectedIds.has(id)&&!names.includes(player.champion))names.push(player.champion);}
    if(names.length)return `Evento de ${names.slice(0,2).join(' · ')}`;
    if(!involvedIds.size&&event.side==='allied'&&selection.allied==='team')return 'Evento de tu equipo';
    if(!involvedIds.size&&event.side==='enemy'&&selection.enemy==='team')return 'Evento del equipo rival';
    return event.side==='unknown'?'Evento de equipo no identificado':event.side==='allied'?'Evento aliado':'Evento enemigo';
  };
  useEffect(()=>{if(selectedEventId&&!events.some(event=>event.event_id===selectedEventId))setSelectedEventId('');},[events,selectedEventId]);
  const generate=async()=>{if(generating)return;setGenerating(true);setError('');try{setReview(await window.solralol.request('recordings.review.generate',{id:recordingId}));}catch(e){setError((e as Error).message);}finally{setGenerating(false);}};
  useEffect(()=>{const v=videoRef.current;if(v){v.volume=volume;v.muted=muted;v.playbackRate=rate;}},[volume,muted,rate]);
  const player=(p:RecordingReviewParticipant,side:SideKey)=><button key={p.participantId||p.champion} className={`review-player-card ${p.local?'local':''} ${selection[side]===p.participantId?'selected':''} ${side}`} onClick={()=>setSide(side,p.participantId||'')} title={p.champion}><span className="review-player-portrait">{championIcons[p.champion]?<img src={championIcons[p.champion]||''} alt=""/>:p.champion.slice(0,1)}</span><span className="review-player-main"><b>{p.champion}{p.local?' · Tú':''}</b><small>{roleLabels[p.role.toUpperCase()]||p.role||'Posición no disponible'} · {p.kills??'—'}/{p.deaths??'—'}/{p.assists??'—'} KDA</small><small>{p.cs??'—'} CS · {p.gold==null?'Oro no disponible':p.gold.toLocaleString('es-ES')} oro · {p.vision??'—'} visión</small></span><span className="review-items">{(p.items||[]).filter(item=>Number(item)>0).slice(0,6).map(item=><i key={String(item)} title={`Objeto ${item}`}>{itemIcons[String(item)]?<img src={itemIcons[String(item)]||''} alt=""/>:<small>{item}</small>}</i>)}</span></button>;
  if(loading)return <div className="review-window"><p className="review-loading">Cargando repaso…</p></div>;
  return <main className="review-window">
    <WindowTitleBar label="Repaso de partida" className="review-titlebar topbar" />
    <header className="review-window-header"><div><span className="eyebrow">REPASO DE PARTIDA</span><h1>{title}</h1><p>{review?.gameMode||'Modo no disponible'} · {review?.champion||'Campeón no disponible'} · {review?.result==null?'Resultado no disponible':review.result?'Victoria':'Derrota'}{review?.winningTeam?` · Ganador: ${review.winningTeam==='allied'?'Tu equipo':'Equipo rival'}`:''}</p></div><span className="review-source">{review?.available?'Telemetría local':'Sin telemetría'}</span></header>
    <div className="review-columns"><section className="review-video-column"><div className="review-video-frame"><video ref={videoRef} src={source} preload="metadata" playsInline onLoadedMetadata={e=>{if(e.currentTarget.duration)setDuration(e.currentTarget.duration);}} onTimeUpdate={e=>{setCurrent(e.currentTarget.currentTime);if(seekRef.current)seekRef.current.value=String(e.currentTarget.currentTime);}} onPlay={()=>setPlaying(true)} onPause={()=>setPlaying(false)} onError={()=>setError('No se pudo reproducir este archivo. Comprueba que la grabación siga disponible.')} onClick={toggle}/></div>
      <div className="review-timebar"><span>{fmt(current)}</span><div className="review-track"><input ref={seekRef} aria-label="Posición del vídeo" type="range" min="0" max={duration||0} step="0.1" value={current} onChange={e=>jump(Number(e.target.value))}/>{markers.map((m,i)=><button key={m.event_id||i} className={`review-marker marker-${categoryForSelection(m,selectedIds)} ${m.side||'unknown'} ${highlightedEventId===m.event_id?'selected':''}`} style={{left:`${duration?Math.min(100,m.video_time!/duration*100):0}%`}} title={`${m.label||m.type} · partida ${fmt(m.time??0)}${m.video_time!=null?` · vídeo ${fmt(m.video_time)}`:''}`} onClick={()=>seekEvent(m)}/>)}</div><span>{fmt(duration)}</span></div>
      <div className="review-controls"><button onClick={()=>jump(current-10)} aria-label="Retroceder 10 segundos">−10</button><button className="primary" onClick={toggle} aria-label={playing?'Pausar':'Reproducir'}>{playing?'Ⅱ':'▶'}</button><button onClick={()=>jump(current+10)} aria-label="Avanzar 10 segundos">+10</button><button onClick={()=>setMuted(v=>!v)}>{muted?'Activar sonido':'Silenciar'}</button><input aria-label="Volumen" type="range" min="0" max="1" step=".05" value={volume} onChange={e=>setVolume(Number(e.target.value))}/><select aria-label="Velocidad" value={rate} onChange={e=>setRate(Number(e.target.value))}><option value="0.5">0,5×</option><option value="0.75">0,75×</option><option value="1">1×</option><option value="1.25">1,25×</option><option value="1.5">1,5×</option><option value="2">2×</option></select><button onClick={()=>{const v=videoRef.current;if(v?.requestFullscreen)void v.requestFullscreen();}}>Pantalla completa</button></div>
      <div className="review-filters"><div>{groups.map(([id,label])=><button key={id} className={categories.has(id)?'active':''} onClick={()=>setCategories(prev=>{const n=new Set(prev);n.has(id)?n.delete(id):n.add(id);return n;})}>{label}<small>{events.filter(e=>categoriesFor(e).includes(id)).length}</small></button>)}</div></div>
      </section><aside className="review-analysis-column"><nav className="review-tabs"><button className={tab==='scoreboard'?'active':''} onClick={()=>setTab('scoreboard')}>Marcador</button><button className={tab==='review'?'active':''} onClick={()=>setTab('review')}>Revisión <small>{events.length}</small></button><button className={tab==='ai'?'active':''} onClick={()=>setTab('ai')}>Análisis con IA</button></nav><div className="review-tab-content">
        {tab==='scoreboard'&&<>
          {!review?.available ? <p className="review-empty">Esta grabación no tiene una partida guardada asociada. El vídeo sigue disponible.</p>
            : review.teamAssignmentKnown ? <>
              <div className="review-teams">
                <section><header><h2>Tu equipo <b>{totalKills(allies)} bajas</b></h2><button className={`review-team-toggle ${selection.allied==='team'?'selected':''}`} onClick={()=>setSide('allied','team')}>Equipo completo</button></header>{allies.map(p=>player(p,'allied'))}</section>
                <div className="review-vs">VS</div>
                <section><header><h2>Equipo rival <b>{totalKills(enemies)} bajas</b></h2><button className={`review-team-toggle ${selection.enemy==='team'?'selected':''}`} onClick={()=>setSide('enemy','team')}>Equipo completo</button></header>{enemies.map(p=>player(p,'enemy'))}</section>
              </div>
              <Radar datasets={radarDatasets}/>
            </> : <>
              <h2 className="review-subheading">Participantes · orden disponible</h2>
              <p className="review-empty">La telemetría no identifica con fiabilidad los dos equipos; se muestran los participantes sin asignar bandos.</p>
              <div className="review-unknown-roster">{participants.map(p=><article key={p.participantId||p.champion}><b>{p.champion}</b><span>{roleLabels[p.role.toUpperCase()]||p.role||'Posición no disponible'} · {p.kills??'—'}/{p.deaths??'—'}/{p.assists??'—'} KDA · {p.cs??'—'} CS</span></article>)}</div>
            </>}
        </>}
        {tab==='review'&&<><div className="review-event-filter"><label>Participantes</label><select value="shared" onChange={e=>{if(e.target.value==='all')setAll();else if(e.target.value.startsWith('participant:'))selectParticipant(e.target.value.slice(12));}}><option value="shared">{selection.allied==='team'&&selection.enemy==='team'?'Todos · ambos equipos':selectedIds.size?`${selectedIds.size} seleccionados`:'Elige participantes'}</option><option value="all">Todos</option>{participants.map(p=><option key={p.participantId} value={`participant:${p.participantId}`}>{p.champion}{p.local?' · Tú':''}</option>)}</select></div>{events.length?<div className="review-events">{events.map((e,i)=><button key={e.event_id||i} className={`review-event ${e.side||'unknown'} ${highlightedEventId===e.event_id?'selected':''}`} onClick={()=>seekEvent(e)}><time>{fmt(e.time??0)}<small>{e.video_time==null?'Sin sincronización':`Vídeo ${fmt(e.video_time)}`}</small></time><span className="review-event-visual">{e.itemId&&itemIcons[e.itemId]?<img className="review-item-event-icon" src={itemIcons[e.itemId]||''} alt={eventDisplayLabel(e,participants,review?.events??[])}/>:null}{(e.champions||[]).slice(0,3).map((champion,index)=>championIcons[champion]?<img key={`${champion}-${index}`} src={championIcons[champion]||''} alt={champion} title={champion}/>:<i key={`${champion}-${index}`} title={champion}>{champion.slice(0,1)}</i>)}</span><span className="review-event-copy"><b>{eventDisplayLabel(e,participants,review?.events??[])}</b><small>{e.itemId?'Objeto completo':categorySummary(e,selectedIds)}</small></span><span className="review-event-badge">{badgeFor(e)}</span></button>)}</div>:<p className="review-empty">No hay sucesos para los participantes y categorías seleccionados.</p>}</>}
        {tab==='ai'&&<><p className="review-ai-source">Análisis generado con telemetría de partida. No analiza fotogramas del vídeo.</p>{review?.analysis?<div className="review-ai-report">{review.analysisState==='stale'&&<p className="review-stale">El informe guardado puede estar desactualizado respecto a la telemetría actual.</p>}<h2>{String(review.analysis.summary?.overall_assessment||'Análisis de partida')}</h2>{typeof review.analysis.summary?.main_strength==='string'&&<p><b>Punto fuerte</b><br/>{review.analysis.summary.main_strength}</p>}{typeof review.analysis.summary?.main_improvement==='string'&&<p><b>Área de mejora</b><br/>{review.analysis.summary.main_improvement}</p>}{(review.analysis.insights||[]).map((it,i)=><article key={String(it.id||i)}><small>{String(it.evaluation||'').toUpperCase()} · partida {fmt(Number(it.match_timestamp_seconds)||0)}</small><h3>{String(it.title||'Observación')}</h3><p>{String(it.description||it.learning||'')}</p></article>)}</div>:<p className="review-empty">{review?.available?'Aún no hay un análisis guardado.':'Falta telemetría suficiente para generar un análisis.'}</p>}<button className="review-generate" disabled={!review?.available||generating} onClick={()=>void generate()}>{generating?'Generando análisis…':review?.analysis?'Regenerar análisis':'Generar análisis'}</button></>}
      </div></aside></div>{error&&<div className="review-error" role="alert">{error}<button onClick={()=>setError('')}>Cerrar</button></div>}
  </main>;
}

