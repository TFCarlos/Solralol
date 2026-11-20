import { useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import type { LiveMatchState, LivePlayer, LivePostGame } from '../types/contracts';
import { GameImage } from '../components/GameImage';
import { liveFixture } from './liveFixtures';
import { EnemyShopTimers, RecommendationCards, SkillOrderGrid } from '../components/LivePreparation';

const empty: LiveMatchState = { state: 'disconnected', connected: false, telemetry: 'unavailable', snapshot: null, message: 'Esperando al cliente de League of Legends.', source: 'live' };
const stateLabels: Record<LiveMatchState['state'], string> = { disconnected:'Desconectado', connected:'Listo', lobby:'Sala / búsqueda', champion_select:'Selección de campeón', loading:'Cargando partida', active:'En partida', game_ending:'Finalizando', post_game:'Postpartida' };
const n = (v: unknown): number | null => {
  if(typeof v==='number')return Number.isFinite(v)?v:null;
  if(typeof v==='string'&&v.trim()!==''){const parsed=Number(v);return Number.isFinite(parsed)?parsed:null;}
  return null;
};
const score = (p: LivePlayer | undefined, key: string) => n((p?.scores as Record<string,unknown>|undefined)?.[key]);
const visionScore = (p: LivePlayer | undefined) => { const value=score(p,'wardScore'); return value===null||value<0?'—':new Intl.NumberFormat('es-ES',{maximumFractionDigits:0}).format(Math.round(value)); };
const items = (p: LivePlayer) => (p.items ?? []).filter((x) => Number(x.itemID ?? x.itemId) > 0);
const spellEntries = (p: LivePlayer) => Object.entries(p.summonerSpells ?? {}).map(([slot,s])=>({slot,name:String(s?.displayName??''),id:String((s as Record<string,unknown>)?.spellKey??(s as Record<string,unknown>)?.id??'')})).filter((s)=>!!s.name);
type RuneEntry = {name:string; id:string; shard?:boolean; tree?:boolean};
const shardNames:Record<string,string>={'5001':'Vida escalable','5002':'Armadura','5003':'Resistencia m\u00e1gica','5005':'Velocidad de ataque','5007':'Aceleraci\u00f3n de habilidad','5008':'Fuerza adaptable','5010':'Velocidad de movimiento','5011':'Vida','5013':'Tenacidad'};
function runeEntries(value: unknown): RuneEntry[] {
  if(!value||typeof value!=='object')return[];
  const row=value as Record<string,unknown>;
  const toEntry=(item:unknown):RuneEntry|null=>{
    if(!item||typeof item!=='object')return null;
    const rune=item as Record<string,unknown>;
    const id=String(rune.perkId??rune.runeId??rune.id??'');
    const name=shardNames[id]??String(rune.displayName??rune.name??'');
    return (name||/^\d+$/.test(id))?{id,name:name||'Runa no identificada'}:null;
  };
  // Riot's documented activeplayerrunes response separates selected perks
  // from the two style names. Reading every nested object treated Precision
  // and Domination as selected perks and duplicated the keystone.
  const trees=[row.primaryRuneTree,row.secondaryRuneTree].map(toEntry).filter((entry):entry is RuneEntry=>!!entry).map(entry=>({...entry,tree:true}));
  const general=Array.isArray(row.generalRunes)?row.generalRunes.map(toEntry).filter((entry):entry is RuneEntry=>!!entry):[];
  const shards=Array.isArray(row.statRunes)?row.statRunes.map(toEntry).filter((entry):entry is RuneEntry=>!!entry).map(entry=>({...entry,shard:true})):[];
  if(general.length)return [...trees,...general,...shards];
  const keystone=toEntry(row.keystone);
  if(keystone)return [...trees,keystone,...shards];
  if(shards.length)return [...trees,...shards];
  if(Array.isArray(value))return value.map(toEntry).filter((entry):entry is RuneEntry=>!!entry);
  return [];
}
const roleName = (value: unknown) => { const raw=String(value??'').trim().toLocaleLowerCase('en'); const aliases:Record<string,string>={top:'Top',jungle:'Jungla',jung:'Jungla',mid:'Medio',middle:'Medio',bottom:'Bot',bot:'Bot',adc:'Bot',utility:'Apoyo',support:'Apoyo',sup:'Apoyo'}; return aliases[raw]??''; };
const gold = (value: unknown) => { const amount=n(value); return amount===null?'—':new Intl.NumberFormat('es-ES',{maximumFractionDigits:0}).format(Math.round(amount)); };
const clock = (seconds: unknown) => { const x=n(seconds); return x===null||x<0?'--:--':`${Math.floor(x/60).toString().padStart(2,'0')}:${Math.floor(x%60).toString().padStart(2,'0')}`; };
const eventKinds:Record<string,string>={ChampionKill:'kill',championkill:'kill',Death:'kill',death:'kill',death_exact:'kill',FirstBlood:'kill',MultiKill:'kill',MultiKillAchievement:'kill',Shutdown:'kill',DragonKill:'objective',HordeKill:'objective',BaronKill:'objective',HeraldKill:'objective',TurretKilled:'objective',InhibKilled:'objective',InhibitorKilled:'objective',InhibRespawned:'objective',InhibRespawningSoon:'objective',CompletedItemAcquired:'items'};
const objectiveNames:Record<string,string>={Air:'Drag\u00f3n de viento',Cloud:'Drag\u00f3n de viento',Water:'Drag\u00f3n de oc\u00e9ano',Ocean:'Drag\u00f3n de oc\u00e9ano',Fire:'Drag\u00f3n infernal',Infernal:'Drag\u00f3n infernal',Earth:'Drag\u00f3n de monta\u00f1a',Mountain:'Drag\u00f3n de monta\u00f1a',Hextech:'Drag\u00f3n hextech',Chemtech:'Drag\u00f3n tecnoqu\u00edmico',Elder:'Drag\u00f3n anciano',Baron:'Bar\u00f3n Nashor',RiftHerald:'Heraldo de la Grieta'};
const eventLabel=(event:Record<string,unknown>)=>{
  const name=String(event.EventName??'');
  if(event.EventDescription)return String(event.EventDescription);
  if(name==='ChampionKill')return event.KillerActorType==='tower'?`${String(event.VictimChampion??'El campe\u00f3n')} muri\u00f3 por una torre`:`${String(event.KillerChampion??'Participante desconocido')} elimin\u00f3 a ${String(event.VictimChampion??'participante desconocido')}`;
  if(name==='CompletedItemAcquired')return `${event.KillerChampion?`${String(event.KillerChampion)} \u00b7 `:''}${String(event.ItemName??'Objeto completo')}`;
  if(name==='DragonKill')return `${String(event.KillerChampion??'')} ${String(objectiveNames[String(event.DragonType??event.MonsterType??'')]??'Drag\u00f3n eliminado')}`.trim();
  if(name==='BaronKill')return `${String(event.KillerChampion??'')} Bar\u00f3n Nashor eliminado`.trim();
  if(name==='HeraldKill')return `${String(event.KillerChampion??'')} Heraldo de la Grieta eliminado`.trim();
  if(name==='HordeKill')return `${String(event.KillerChampion??'')} Larva del Vac\u00edo eliminada`.trim();
  if(name==='TurretKilled')return `${String(event.KillerChampion??event.KillerActorName??'')} ${String(event.ObjectiveLabel??'Torre destruida')}`.trim();
  if(['InhibKilled','InhibitorKilled','InhibRespawned','InhibRespawningSoon'].includes(name))return `${String(event.KillerChampion??event.KillerActorName??'')} ${String(event.ObjectiveLabel??'Inhibidor destruido')}`.trim();
  if(name==='FirstBlood')return 'Primera sangre';
  if(name==='MultiKill'||name==='MultiKillAchievement')return `${String(event.KillerChampion??'Participante')} consigui\u00f3 una multikill`;
  if(name==='Shutdown')return `${String(event.KillerChampion??'Participante')} confirm\u00f3 un shutdown`;
  return '';
};
function normalizedEventText(value:unknown):string {
  return String(value??'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLocaleLowerCase('es');
}
function killerActorType(event:Record<string,unknown>, champion:string):string {
  const declared=String(event.KillerActorType??event.KillerType??'').trim().toLocaleLowerCase('en').replace(/[\s-]+/g,'_');
  if(['turret','tower','structure_turret','structure_tower'].includes(declared))return 'tower';
  if(['minion','lane_minion','sru_minion'].includes(declared))return 'minion';
  if(['champion','neutral_monster','baron','rift_herald','dragon','void_grub','environment'].includes(declared))return declared;
  // An explicit unresolved actor must never fall through to KillerChampion:
  // older snapshots occasionally copied the victim into that field.
  if(['unknown','unresolved','none'].includes(declared))return 'environment';
  if(declared)return 'environment';
  // Compatibility for archived snapshots without typed actors. Localized
  // descriptions are presentation, never evidence of the killing entity.
  const actor=normalizedEventText(event.KillerActorName??event.KillerName??'');
  if(/turret|tower|torre/.test(actor))return 'tower';
  if(/minion|subdit/.test(actor))return 'minion';
  if(champion)return 'champion';
  return 'environment';
}

// Clock-only publications are consumed by the small time-dependent components.
// They do not trigger a new render of the player list or the full Live page.
export function livePresentationKey(live:LiveMatchState):string {
  return JSON.stringify({...live,lastUpdated:null,snapshot:live.snapshot?{...live.snapshot,gameTime:null,enemyShopTimers:null,overlay:null}:null});
}

function LiveCsRate({cs,time,active}:{cs:number|null;time:number;active:boolean}) {
  const [value,setValue]=useState({cs,time});
  useEffect(()=>setValue({cs,time}),[cs,time]);
  useEffect(()=>{
    if(!active)return;
    const receive=(event:Event)=>{const snap=(event as CustomEvent<LiveMatchState>).detail.snapshot;if(!snap)return;const next={cs:score(snap.localPlayer,'creepScore'),time:snap.gameTime};setValue(previous=>previous.cs===next.cs&&previous.time===next.time?previous:next);};
    window.addEventListener('solralol:live-update',receive);
    return()=>window.removeEventListener('solralol:live-update',receive);
  },[active]);
  return <>{value.cs!==null&&value.time>0?(value.cs/(value.time/60)).toFixed(1):'—'}</>;
}

function LastLiveReading({stamp,active}:{stamp?:string|null;active:boolean}) {
  const [value,setValue]=useState(stamp);
  useEffect(()=>setValue(stamp),[stamp]);
  useEffect(()=>{
    if(!active)return;
    const receive=(event:Event)=>setValue((event as CustomEvent<LiveMatchState>).detail.lastUpdated);
    window.addEventListener('solralol:live-update',receive);
    return()=>window.removeEventListener('solralol:live-update',receive);
  },[active]);
  return <>{value?new Date(value).toLocaleTimeString('es-ES'):'—'}</>;
}
export function LiveMatchPage({ active, backendReady, onOpenSaved }: {active:boolean; backendReady:boolean; onOpenSaved:()=>void}) {
  const [live, setLive] = useState<LiveMatchState>(empty);
  const [assets, setAssets] = useState<Record<string, string | null>>({});
  const assetRequests = useRef(new Set<string>());
  const [error, setError] = useState('');
  const last = useRef('');
  const fixtureMode = import.meta.env.DEV && new URLSearchParams(window.location.search).get('liveFixture') === 'active';
  useEffect(() => {
    if (!active) return;
    if (fixtureMode) { const update=()=>{const fixture=liveFixture();const key=livePresentationKey(fixture);if(key!==last.current){last.current=key;setLive(fixture);}window.dispatchEvent(new CustomEvent('solralol:live-update',{detail:fixture}));}; update(); const timer=window.setInterval(update,1500); return()=>window.clearInterval(timer); }
    if (!backendReady) return;
    const receive=(event:Event)=>{const next=(event as CustomEvent<LiveMatchState>).detail;if(!next)return;const key=livePresentationKey(next);if(key!==last.current){last.current=key;setLive(next);}setError('');};
    window.addEventListener('solralol:live-update',receive);
    return()=>window.removeEventListener('solralol:live-update',receive);
  },[active,backendReady,fixtureMode]);
  const snap=live.snapshot;
  const assetKey=`${live.sessionId??snap?.sessionId??live.postGame?.sessionId??'none'}:${live.state}`;
  useEffect(()=>{
    if(!snap||!backendReady)return;
    const champions=[...new Set([...snap.players,...(live.postGame?.players??[])].map(p=>String(p.championName??'')).filter(Boolean))].slice(0,20);
    const missing=champions.filter(name=>!assetRequests.current.has(`champion:${name}`));
    if(!missing.length)return;
    missing.forEach(name=>assetRequests.current.add(`champion:${name}`));
    void window.solralol.request('home.assets',{champions:missing}).then(result=>{const aliases=Object.entries(result.championAliases??{}).map(([name,id])=>[`champion:${name}`,result.champions[String(id)]??null] as const);setAssets(old=>({...old,...Object.fromEntries(aliases)}));}).catch(()=>missing.forEach(name=>assetRequests.current.delete(`champion:${name}`)));
  },[assetKey,snap?.players,live.postGame?.players,backendReady]);
  useEffect(()=>{
    if(!snap||!backendReady)return;
    const roster=[...snap.players,...(live.postGame?.players??[])];
    const ids=[...new Set([...(snap.recommendations??[]).flatMap(item=>[item.id,item.nextPurchase?.id??'']),...roster.flatMap(p=>items(p).map(item=>String(item.itemID??item.itemId??''))),...(snap.events??[]).map(event=>String(event.ItemId??'')),...(live.postGame?.events??[]).map(event=>String(event.ItemId??''))].filter(id=>/^\d+$/.test(id)))].slice(0,100);
    const missing=ids.filter(id=>!assetRequests.current.has(`item:${id}`));if(!missing.length)return;
    missing.forEach(id=>assetRequests.current.add(`item:${id}`));
    void window.solralol.request('meta.assets',{items:missing}).then(result=>setAssets(old=>({...old,...result}))).catch(()=>missing.forEach(id=>assetRequests.current.delete(`item:${id}`)));
  },[assetKey,snap?.players,snap?.events,snap?.recommendations,live.postGame?.players,live.postGame?.events,backendReady]);
  useEffect(()=>{
    if(!snap||!backendReady)return;
    const roster=[...snap.players,...(live.postGame?.players??[])];
    const spells=roster.flatMap(p=>spellEntries(p));
    const names=[...new Set(spells.flatMap(spell=>[spell.name,spell.id]).filter(Boolean))].slice(0,20);
    const missing=names.filter(name=>!assetRequests.current.has(`spell:${name}`));if(!missing.length)return;
    missing.forEach(name=>assetRequests.current.add(`spell:${name}`));
    void window.solralol.request('meta.assets',{spells:missing}).then(result=>{const aliases=spells.filter(spell=>spell.id&&result[`spell:${spell.id}`]).map(spell=>[`spell:${spell.name}`,result[`spell:${spell.id}`]] as const);setAssets(old=>({...old,...result,...Object.fromEntries(aliases)}));}).catch(()=>missing.forEach(name=>assetRequests.current.delete(`spell:${name}`)));
  },[assetKey,snap?.players,live.postGame?.players,backendReady]);
  // activeplayerrunes is attached to localPlayer; playerlist does not carry the
  // full local page, so include it in asset acquisition as well as rendering.
  const runeRoster=useMemo(()=>[...(snap?.players??[]),...(snap?.localPlayer?[snap.localPlayer]:[]),...(live.postGame?.players??[])],[snap?.players,snap?.localPlayer,live.postGame?.players]);
  useEffect(()=>{
    if(!backendReady)return;
    const values=[...new Map(runeRoster.flatMap(p=>runeEntries(p.runes)).map(entry=>[entry.id||entry.name,entry])).values()];
    const requests=[...new Set(values.map(entry=>entry.id||entry.name).filter(Boolean))].slice(0,40);
    const missing=requests.filter(value=>!assetRequests.current.has(`rune:${value}`));if(!missing.length)return;
    missing.forEach(value=>assetRequests.current.add(`rune:${value}`));
    // Live snapshots refresh every two seconds. Keep an in-flight response
    // after effect cleanup so slow first-time rune downloads are not lost.
    void window.solralol.request('meta.assets',{runes:missing}).then(result=>setAssets(old=>({...old,...result}))).catch(()=>missing.forEach(value=>assetRequests.current.delete(`rune:${value}`)));
  },[assetKey,runeRoster,backendReady]);
  const local=snap?.localPlayer;
  const teamGroups=useMemo(()=>{const groups=new Map<string,LivePlayer[]>();for(const player of snap?.players??[]){const team=String(player.team??'UNKNOWN');groups.set(team,[...(groups.get(team)??[]),player]);}return [...groups.entries()];},[snap?.players]);
  const totalKills=(team:string)=> (snap?.players??[]).filter(p=>String(p.team)===team).reduce((sum,p)=>sum+(score(p,'kills')??0),0);
  const localK=score(local,'kills'), localD=score(local,'deaths'), localA=score(local,'assists'), cs=score(local,'creepScore');
  const kpValue=n(snap?.localStats?.killParticipation);
  const kp=kpValue!==null?`${kpValue.toFixed(1)}%`:'\u2014';
  const events=useMemo(()=>{
    const unique=new Map<string,Record<string,unknown>>();
    for(const [index,event] of (snap?.events??[]).entries()){
      const name=String(event.EventName??'');if(!eventKinds[name])continue;
      const id=String(event.EventID??'');
      const actors=[event.KillerChampion,event.KillerName,event.VictimChampion,event.VictimName,event.ItemId].map(value=>String(value??'').trim());
      const key=id?`id:${id}`:`${name}:${Math.round((n(event.EventTime)??0)*10)}:${actors.some(Boolean)?actors.join('|'):`unattributed:${index}`}`;
      unique.set(key,{...(unique.get(key)??{}),...event});
    }
    return [...unique.values()].slice(-100).reverse();
  },[snap?.events]);
  const visibleEventCount=events.filter((event)=>!['FirstBlood','MultiKill','MultiKillAchievement','Shutdown'].includes(String(event.EventName??''))).length;
  const statusClass=live.telemetry==='stale'?'stale':live.connected?'connected':'offline';
  const showPostGame=!!live.postGame&&live.state!=='active';
  return <main className="live-page" data-active={active}>
    {error&&<div className="live-notice">{error}</div>}
    {showPostGame&&live.postGame?<PostGameView postGame={live.postGame} assets={assets} onOpenSaved={onOpenSaved}/>:snap&&local ? <>
      {live.source==='fixture'&&<div className="live-fixture-banner">DATOS SIMULADOS · Vista previa de desarrollo</div>}
      <section className="live-player-card"><div className="live-player-main"><GameImage src={assets[`champion:${String(local.championName??'')}`]} alt={String(local.championName??'Campeón')} className="live-champion" fallback={String(local.championName??'—').slice(0,2)}/><div><span className="eyebrow">TU CAMPEÓN{roleName(local.position)?` · ${roleName(local.position)}`:''}</span><h2>{String(local.championName??'Desconocido')}</h2><span className="live-sub">Nivel {n(local.level)??n(snap.localStats.level)??'—'} {spellEntries(local).map(spell=><GameImage key={spell.slot} src={assets[`spell:${spell.name}`]} alt={spell.name} title={spell.name} className="live-spell-icon" fallback="·"/>)}</span></div></div><div className="live-primary-stats"><LiveMetric label="K / D / A" value={`${localK??'—'} / ${localD??'—'} / ${localA??'—'}`}/><LiveMetric label="CS" value={cs??'—'}/><LiveMetric label="CS / min" value={<LiveCsRate cs={cs} time={snap.gameTime} active={active&&live.telemetry==='current'}/>}/><LiveMetric label="Visión" value={visionScore(local)}/><LiveMetric label="Oro actual" value={gold(snap.localStats.currentGold??snap.localStats.gold)}/><LiveMetric label="Participación" value={kp}/></div><div className="live-items">{items(local).map((item,i)=><GameImage key={`${item.itemID}-${i}`} src={assets[`item:${item.itemID??item.itemId}`]} alt={item.displayName||'Objeto equipado'} title={item.displayName||'Objeto equipado'} className="live-item-icon" fallback="·"/>)}{items(local).length===0&&<span className="live-sub">Objetos no disponibles</span>}</div><RuneIcons player={local} assets={assets} compact={false}/></section>
      <div className="live-content-grid"><section className="live-card live-preparation"><RecommendationCards recommendations={snap.recommendations??[]} assets={assets}/><div className="live-preparation-tracking"><SkillOrderGrid skill={snap.skillOrder} level={n(local.level)??0}/><EnemyShopTimers rows={snap.enemyShopTimers??[]} assets={assets} active={active&&live.telemetry==='current'}/></div></section><section className="live-card live-teams"><div className="live-section-title"><div><span className="eyebrow">COMPARACIÓN</span><h2>Los dos equipos</h2></div><span>{live.telemetry==='stale'?'Lectura anterior':'Live Client'}</span></div><div className="live-team-grid">{teamGroups.slice(0,2).map(([team,players],teamIndex)=><div className={`live-team ${team===snap.localTeam?'own':''}`} key={team}><header><b>{team===snap.localTeam?'Tu equipo':teamIndex===0?'Equipo rival':'Equipo'} · {team}</b><strong>{totalKills(team)} <small>bajas</small></strong></header>{players.slice(0,5).map((player,i)=><div className="live-row" key={`${team}-${player.championName}-${i}`}><div className="live-row-main"><GameImage src={assets[`champion:${String(player.championName??'')}`]} alt={String(player.championName??'Campe\u00f3n')} className="live-row-champ" fallback={String(player.championName??'\u2014').slice(0,1)}/><div className="live-row-name"><b>{String(player.championName??'Desconocido')}</b><small>Niv. {n(player.level)??'\u2014'}{roleName(player.position)?` \u00b7 ${roleName(player.position)}`:''}</small></div><span>{score(player,'kills')??'\u2014'}/{score(player,'deaths')??'\u2014'}/{score(player,'assists')??'\u2014'}</span><span>{score(player,'creepScore')??'\u2014'} CS</span></div><div className="live-row-bottom"><div className="live-row-utility"><div className="live-row-spells">{spellEntries(player).map(spell=><GameImage key={spell.slot} src={assets[`spell:${spell.name}`]} alt={spell.name} title={spell.name} className="live-row-spell-icon" fallback="\u00b7"/>)}</div><RuneIcons player={player} assets={assets} compact/></div><div className="live-row-items">{items(player).slice(0,6).map((item,j)=><GameImage key={`${item.itemID}-${j}`} src={assets[`item:${item.itemID??item.itemId}`]} alt={item.displayName||'Objeto equipado'} title={item.displayName||'Objeto equipado'} className="live-row-item-icon" fallback="\u00b7"/>)}</div></div></div>)}</div>)}</div></section>
        <section className="live-card live-timeline"><div className="live-section-title"><div><span className="eyebrow">EVENTOS Y OBSERVACIONES</span><h2>Línea de tiempo</h2></div><span>{visibleEventCount} eventos</span></div><TimelineList events={events} localTeam={snap.localTeam} assets={assets}/></section>
      </div>
      <footer className="live-foot">Última lectura correcta: <LastLiveReading stamp={live.lastUpdated} active={active}/> · Los eventos de objetos indican una adquisición observada en inventario.</footer>
    </> : <section className="live-wait"><div className="live-wait-mark">◉</div><span className="eyebrow">{stateLabels[live.state].toLocaleUpperCase('es')}</span><h2>{live.state==='disconnected'?'Conecta con League of Legends':live.state==='champion_select'?'Preparando tu partida':live.state==='lobby'?'Listo para la próxima partida':'Esperando telemetría de juego'}</h2><p>{live.message}{live.state==='connected'?' Cuando empiece la partida, los datos aparecerán aquí automáticamente.':''}</p><div className={`live-connection-pill ${statusClass}`}><i/> {live.connected?'Cliente conectado':'Sin conexión con el cliente'}</div></section>}
  </main>;
}

function RuneIcons({player,assets,compact}:{player:LivePlayer;assets:Record<string,string|null>;compact:boolean}) {
  const runeData=player.runes as Record<string,unknown>|undefined;
  const allEntries=runeEntries(runeData);
  const general=allEntries.filter(entry=>!entry.tree&&!entry.shard);
  const trees=allEntries.filter(entry=>entry.tree);
  const entries=compact?[...(general.length?[general[0]]:[]),...trees].slice(0,3):allEntries.filter(entry=>!entry.tree).slice(0,9);
  if(!entries.length)return compact?<span className="live-rune-unavailable" title="Runas no disponibles">·</span>:<div className="live-rune-row"><small>RUNAS</small><i>No disponibles</i></div>;
  if(compact)return <div className="live-row-runes">{entries.map((entry,index)=><GameImage key={`${entry.id||entry.name}-${index}`} src={assets[`rune:${entry.id||entry.name}`]??assets[`rune:${entry.name}`]} alt={entry.name} title={entry.name} className="live-row-rune-icon" fallback="·"/>)}</div>;
  return <div className="live-rune-row"><small>RUNAS</small>{trees.map((entry,index)=><span className="live-rune-styles" key={`tree-${entry.id}-${index}`}><GameImage src={assets[`rune:${entry.id}`]} alt="" title={entry.name} className="live-player-rune-icon" fallback="·"/><b>{entry.name}</b></span>)}<div className="live-rune-selections">{entries.map((entry,index)=><span className={`live-rune-selection ${entry.shard?'shard':''}`} key={`${entry.id||entry.name}-${index}`}><GameImage src={assets[`rune:${entry.id||entry.name}`]??assets[`rune:${entry.name}`]} alt="" title={entry.name} className="live-player-rune-icon" fallback="·"/><b>{entry.name}</b></span>)}</div></div>;
}

function EventMark({kind,label,actorType}:{kind:string;label:string;actorType?:string}) {
  const paths:Record<string,ReactNode>={
    tower:<><path d="M4 3h4v3h2V3h4v3h2V3h4v7l-3 3v8H7v-8l-3-3V3ZM3 21h18M10 13h4v4h-4z"/></>,
    inhibitor:<><circle cx="12" cy="12" r="8"/><path d="M12 4v16M4 12h16M8 8l8 8m0-8-8 8"/></>,
    dragon:<><path d="M4 15c4-1 4-6 8-7l2-4 1 5 5 2-4 2-2 6-3-4-4 1-3-1Zm8-7-3-3M16 12l4-2"/></>,
    void_grub:<><path d="M4 12h16M7 8l-3-3m3 11-3 3m13-11 3-3m-3 11 3 3M8 9c2-3 6-3 8 0v6c-2 3-6 3-8 0z"/></>,
    rift_herald:<><path d="M4 12c2-5 5-7 8-7s6 2 8 7c-2 5-5 7-8 7s-6-2-8-7Z"/><circle cx="12" cy="12" r="3"/><path d="m9 6-2-3m8 3 2-3"/></>,
    baron:<><path d="M4 18c3-1 3-5 5-7l-1-5 4 3 4-3-1 5c2 2 2 6 5 7l-4 2H8l-4-2Z"/><path d="M9 13h.01M15 13h.01"/></>,
    minion:<><path d="M6 20h12l-1-7H7l-1 7ZM8 13a4 4 0 1 1 8 0M9 17h.01M15 17h.01M5 8l3 2m11-2-3 2"/></>,
    neutral_monster:<><path d="M5 20 7 9l5-5 5 5 2 11H5Z"/><path d="M9 13h.01M15 13h.01M9 17h6"/></>,
    environment:<><circle cx="12" cy="12" r="9"/><path d="M12 11v5m0-9h.01"/></>
  };
  const variant=kind.startsWith('inhibitor')?'inhibitor':kind;
  return <span className={`live-objective-mark live-mark-${variant}`} title={label} aria-label={label} data-actor-type={actorType}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[variant]??paths.environment}</svg></span>;
}
function EventActor({kind,name,assets}:{kind:string;name:string;assets:Record<string,string|null>}) {
  if(!kind||kind==='unknown')return null;
  const actorType=kind==='tower'?'TURRET':kind==='champion'?'CHAMPION':kind==='minion'?'MINION':kind==='environment'?'UNKNOWN':kind.toUpperCase();
  if(kind==='champion'&&name)return <GameImage src={assets[`champion:${name}`]} alt={name} title={name} className="live-event-champion" actorType={actorType} fallback={name.slice(0,1)}/>;
  const labels:Record<string,string>={minion:'S\u00fabdito',tower:'Torre',inhibitor:'Inhibidor',baron:'Bar\u00f3n Nashor',rift_herald:'Heraldo de la Grieta',dragon:'Drag\u00f3n',void_grub:'Larva del Vac\u00edo',neutral_monster:'Monstruo neutral',environment:'Causa no identificada'};
  return <EventMark kind={kind} label={labels[kind]??name??'Entidad del juego'} actorType={actorType}/>;
}
export function TimelineList({events,localTeam,assets,filter='all'}:{events:Array<Record<string,unknown>>;localTeam:string;assets:Record<string,string|null>;filter?:string}) {
  const diagnosedEvents=useRef(new Set<string>());
  const firstBloods=events.filter(event=>event.EventName==='FirstBlood');
  const auxiliary=new Set(['FirstBlood','MultiKill','MultiKillAchievement','Shutdown']);
  const shown=events.filter(event=>!auxiliary.has(String(event.EventName??''))&&(filter==='all'||eventKinds[String(event.EventName??'')]===(filter==='items'?'items':filter)));
  if(!shown.length)return <p className="live-sub">{'A\u00fan no hay eventos disponibles.'}</p>;
  return <div className="live-event-list">{shown.slice().sort((a,b)=>(n(b.EventTime)??0)-(n(a.EventTime)??0)).map((event,index)=>{
    const name=String(event.EventName??'');
    const killer=String(event.KillerChampion??'');
    const victim=String(event.VictimChampion??((String(event.VictimActorType??'').toLowerCase()==='champion')?event.VictimActorName:'')??'');
    const killerType=killerActorType(event,killer);
    const kill=['championkill','death','death_exact'].includes(name.toLocaleLowerCase('en'));
    const team=String(event.EventTeam??event.KillerTeam??'');
    const neutralActor=kill&&['tower','minion','neutral_monster','environment'].includes(killerType);
    const side=neutralActor||!team||!localTeam?'neutral':team===localTeam?'ally':'enemy';
    const item=name==='CompletedItemAcquired';
    const objective=eventKinds[name]==='objective';
    const itemLabel=String(event.ItemName??'Objeto completo');
    const objectiveKind=String(event.ObjectiveKind??(name==='TurretKilled'?'tower':name.startsWith('Inhib')?'inhibitor':name==='HordeKill'?'void_grub':name==='DragonKill'?'dragon':name==='BaronKill'?'baron':name==='HeraldKill'?'rift_herald':''));
    const objectiveLabel=String(event.ObjectiveLabel??(name==='BaronKill'?'Bar\u00f3n Nashor eliminado':name==='HeraldKill'?'Heraldo de la Grieta eliminado':name==='HordeKill'?'Larva del Vac\u00edo eliminada':name==='DragonKill'?(objectiveNames[String(event.DragonType??event.MonsterType??'')]??'Drag\u00f3n eliminado'):name==='TurretKilled'?'Torre destruida':name.startsWith('Inhib')?'Inhibidor destruido':''));
    const killerName=killerType==='tower'?'Torre':killerType==='minion'?'S\u00fabdito':String(event.KillerActorName??killer);
    const victimType=victim?'champion':String(event.VictimActorType??'');
    const victimName=victim||String(event.VictimActorName??'');
    const time=n(event.EventTime)??0;
    const nearby=(type:string)=>killer?events.find(candidate=>candidate!==event&&candidate.EventName===type&&candidate.KillerChampion===killer&&Math.abs((n(candidate.EventTime)??-100)-time)<=1.5):undefined;
    const multiEvent=kill?nearby('MultiKill')??nearby('MultiKillAchievement'):undefined;
    const multikill=n(event.MultiKill??event.MultiKillCount??event.KillCount??multiEvent?.MultiKill??multiEvent?.MultiKillCount??multiEvent?.KillCount);
    const shutdown=event.shutdown_confirmed===true||event.Shutdown===true||event.IsShutdown===true||(kill&&!!nearby('Shutdown'));
    const first=kill&&(event.IsFirstBlood===true||firstBloods.some(candidate=>killer&&candidate.KillerChampion===killer&&Math.abs((n(candidate.EventTime)??-100)-time)<2));
    const deathCause=killerType==='tower'?'una torre':killerType==='minion'?'los s\u00fabditos':killerType==='neutral_monster'?'un monstruo neutral':'una causa no identificada';
    const description=kill?(killerType==='champion'&&killer?`${killer} elimin\u00f3 a ${victim||'un campe\u00f3n'}`:`${victim||'El campe\u00f3n'} muri\u00f3 por ${deathCause}`):eventLabel(event);
    const id=String(event.EventID??`${name}-${event.EventTime}-${index}`);
    const actorLabel=killerType==='tower'?'Torre':killerType==='minion'?'S\u00fabdito':killerType==='champion'?(killer||killerName):killerType==='environment'?'Causa no identificada':killerName;
    const actorSemanticType=killerType==='tower'?'TURRET':killerType==='champion'?'CHAMPION':killerType==='minion'?'MINION':'UNKNOWN';
    const accessibleEventLabel=`${clock(event.EventTime)} ${kill?`${actorLabel} \u2192 ${victim||'campe\u00f3n'}. `:''}${description}`;
    if(import.meta.env.DEV&&kill&&killerType==='tower'&&!diagnosedEvents.current.has(id)){diagnosedEvents.current.add(id);const rawKiller=String(event.KillerName??'');console.debug('[live-match] ChampionKill actor/victim',{eventId:id,raw:{eventName:name,eventTime:event.EventTime,killerName:/turret|tower/i.test(rawKiller)?rawKiller:'<not exposed>',victimName:'<redacted>'},normalized:{event:'CHAMPION_KILL',actor:{type:'TURRET',name:'Torre'},victim:{type:'CHAMPION',champion:victim}},icons:{actor:'inline:turret-svg',victim:`champion:${victim}`},timestamp:clock(event.EventTime)});}
    const actorExists=kill||!['unknown','environment'].includes(killerType);
    const targetExists=kill?!!victimType:objective;
    return <div className={`live-event live-event-${side}`} key={id} role="group" aria-label={accessibleEventLabel} title={accessibleEventLabel} data-event-type={kill?'CHAMPION_KILL':name} data-actor-type={kill?actorSemanticType:undefined} data-actor-name={kill?actorLabel:undefined} data-victim-champion={kill?victim:undefined}>
      <time>{clock(event.EventTime)}</time><i aria-hidden="true"/>
      <div className="live-event-content"><div className="live-event-actors">
        {kill&&actorExists&&<><EventActor kind={killerType} name={killerName} assets={assets}/>{targetExists&&<><span className="live-event-arrow" aria-hidden="true">{'\u2192'}</span><EventActor kind={victimType} name={victimName} assets={assets}/></>}</>}
        {kill&&!actorExists&&targetExists&&<EventActor kind={victimType} name={victimName} assets={assets}/>}
        {objective&&actorExists&&<><EventActor kind={killerType} name={killerName} assets={assets}/><span className="live-event-arrow" aria-hidden="true">{'\u2192'}</span><EventMark kind={objectiveKind} label={objectiveLabel}/></>}
        {objective&&!actorExists&&<EventMark kind={objectiveKind} label={objectiveLabel}/>}
        {item&&killer&&<GameImage src={assets[`champion:${killer}`]} alt={killer} title={killer} className="live-event-champion" fallback={killer.slice(0,1)}/>}
        {item&&<GameImage src={assets[`item:${String(event.ItemId??'')}`]} alt={itemLabel} title={itemLabel} className="live-event-item" fallback="\u25c8"/>}
      </div><div className="live-event-detail"><b>{item?`${killer?`${killer} \u00b7 `:''}${itemLabel}`:description}</b>
        {first&&<em className="live-first-blood">PRIMERA SANGRE</em>}{multikill&&multikill>=2&&<em className="live-multikill">{multikill===2?'DOBLE':multikill===3?'TRIPLE':multikill===4?'CU\u00c1DRUPLE':'PENTAKILL'}</em>}{shutdown&&<em className="live-shutdown">SHUTDOWN</em>}{event.Stolen===true&&<em className="live-stolen">ROBADO</em>}
      </div></div>
    </div>;
  })}</div>;
}

function PostGameView({postGame,assets,onOpenSaved}:{postGame:LivePostGame;assets:Record<string,string|null>;onOpenSaved:()=>void}) {
  const [filter,setFilter]=useState('all');
  const local=postGame.players.find(player=>player.local);
  const localScore=local?.scores as Record<string,unknown>|undefined;
  const duration=n(postGame.duration);
  const localCs=n(localScore?.creepScore);
  const kda=[localScore?.kills,localScore?.deaths,localScore?.assists].map(value=>n(value)??'—').join(' / ');
  const teams=useMemo(()=>{const groups=new Map<string,typeof postGame.players>();for(const player of postGame.players){const team=String(player.team??'UNKNOWN');groups.set(team,[...(groups.get(team)??[]),player]);}return [...groups.entries()];},[postGame.players]);
  const outcome=postGame.result===true?'VICTORIA':postGame.result===false?'DERROTA':'RESULTADO PENDIENTE';
  return <section className="postgame-view">
    <section className="postgame-summary"><GameImage src={assets[`champion:${postGame.localChampion??''}`]} alt={postGame.localChampion??'Campeón'} className="postgame-champion" fallback="?"/><div className="postgame-summary-name"><span className="eyebrow">{postGame.provisional?'DATOS PROVISIONALES':'PARTIDA FINALIZADA'}</span><h2>{postGame.localChampion??'Partida completada'}</h2><p>{postGame.gameMode} · {clock(duration)}</p><strong className={postGame.result===true?'win':postGame.result===false?'loss':'pending'}>{outcome}</strong></div><div className="postgame-summary-stats"><LiveMetric label="K / D / A" value={kda}/><LiveMetric label="CS" value={localCs??'—'}/><LiveMetric label="CS / min" value={localCs!==null&&duration&&duration>0?(localCs/(duration/60)).toFixed(1):'—'}/><LiveMetric label="Visión" value={visionScore(local)}/></div><button type="button" className="postgame-saved-button" onClick={onOpenSaved}>Ver partidas guardadas</button></section>
    <section className="live-card postgame-scoreboard">
      <div className="live-section-title"><div><span className="eyebrow">RESULTADO DE LA PARTIDA</span><h2>Marcador final</h2></div><span>Datos finales observados · sin oro total estimado</span></div>
      <div className="postgame-teams">{teams.map(([team,players],teamIndex)=><div className={`postgame-team ${team===postGame.localTeam?'own':''}`} key={team}>
        <h3>{team===postGame.localTeam?'Tu equipo':teamIndex===0?'Equipo rival':'Equipo'} <small>{team}</small></h3>
        {players.map((player,index)=><div className={`postgame-player ${player.local?'local':''}`} key={`${team}-${player.championName}-${index}`}>
          <div className="postgame-player-main">
            <GameImage src={assets[`champion:${String(player.championName??'')}`]} alt={String(player.championName??'Campeón')} className="postgame-player-icon" fallback="?"/>
            <div className="postgame-player-identity"><b title={String(player.championName??'')}>{player.championName??'Desconocido'}</b><small>Niv. {n(player.level)??'—'}</small></div>
            <div className="postgame-player-stats"><span title="Bajas / muertes / asistencias">{score(player,'kills')??'—'}/{score(player,'deaths')??'—'}/{score(player,'assists')??'—'}</span><span>{score(player,'creepScore')??'—'} CS</span><span>{visionScore(player)} visión</span></div>
          </div>
          <div className="postgame-player-loadout">
            <div className="postgame-combat-icons">{spellEntries(player).map(spell=><GameImage key={spell.slot} src={assets[`spell:${spell.name}`]} alt={spell.name} title={spell.name} className="live-row-spell-icon" fallback="·"/>)}<RuneIcons player={player} assets={assets} compact/></div>
            {n(player.damageToChampions)!==null&&<small className="postgame-damage" title={`${new Intl.NumberFormat('es-ES').format(n(player.damageToChampions)!)} daño a campeones`}>{new Intl.NumberFormat('es-ES').format(n(player.damageToChampions)!)} daño</small>}
            <div className="postgame-items">{items(player).slice(0,6).map((item,i)=><GameImage key={`${item.itemID}-${i}`} src={assets[`item:${item.itemID??item.itemId}`]} alt={item.displayName||'Objeto'} title={item.displayName||'Objeto'} className="live-row-item-icon" fallback="·"/>)}</div>
          </div>
        </div>)}
      </div>)}</div>
    </section>
    <section className="live-card postgame-history"><div className="live-section-title"><div><span className="eyebrow">HISTORIAL DE PARTIDA</span><h2>Eventos y adquisiciones</h2></div><div className="postgame-filter">{[['all','Todo'],['kill','Bajas'],['objective','Objetivos'],['items','Objetos']].map(([id,label])=><button key={id} type="button" className={filter===id?'active':''} onClick={()=>setFilter(id)}>{label}</button>)}</div></div><TimelineList events={postGame.events} localTeam={postGame.localTeam} assets={assets} filter={filter}/></section>
    <p className="live-foot">El marcador se conserva desde la última telemetría local. El resultado y los datos oficiales se completan en Partidas guardadas cuando la fuente los proporciona.</p>
  </section>;
}
function LiveMetric({label,value}:{label:string;value:ReactNode}) { return <div className="live-metric"><small>{label}</small><b>{value}</b></div>; }
