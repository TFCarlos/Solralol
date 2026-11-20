import { useEffect, useState } from 'react';
import type { EnemyShopTimer, LiveMatchState, LiveSnapshot } from '../types/contracts';
import { useRef } from 'react';
import { GameImage } from '../components/GameImage';
import { Icon } from '../components/Icon';

type AlertNotice = {key:string;kind:'objective'|'structure'|'purchase';name:string;objective?:string;structure?:string;lane?:string;remaining?:number;persistent?:boolean;champion?:string;item_id?:string;item_name?:string;side?:string};

export type OverlayPanel = 'gold'|'alerts'|'purchase'|'recall'|'ability';
const empty: LiveMatchState = {state:'disconnected',connected:false,telemetry:'unavailable',snapshot:null,message:'',source:'live'};
const titles:Record<OverlayPanel,string>={gold:'GOLD DIFFERENCE',alerts:'AVISOS',purchase:'OBJETOS',recall:'ÚLTIMO BACKEO',ability:'ORDEN DE HABILIDADES'};
const roles=['TOP','JUNGLE','MIDDLE','BOTTOM','UTILITY'] as const;
const roleLabels:Record<string,string>={TOP:'TOP',JUNGLE:'JUNGLE',MIDDLE:'MID',BOTTOM:'BOT',UTILITY:'SUPPORT'};
const normalizeRole=(role:string)=>({MID:'MIDDLE',BOT:'BOTTOM',SUPPORT:'UTILITY',ADC:'BOTTOM',SUP:'UTILITY'}[role.toUpperCase()]??role.toUpperCase());
const clock=(value:number|null|undefined)=>value==null?'—':`${String(Math.floor(value/60)).padStart(2,'0')}:${String(Math.floor(value%60)).padStart(2,'0')}`;
const deltaText=(value:unknown)=>typeof value==='number'&&Number.isFinite(value)?`${value>0?'+':''}${new Intl.NumberFormat('es-ES',{maximumFractionDigits:0}).format(value)}`:'—';
const tone=(value:unknown)=>typeof value==='number'?value>0?'positive':value<0?'negative':'neutral':'unavailable';
function purchaseRows(snapshot:Partial<LiveSnapshot>) {
  const rows=snapshot.recommendations??snapshot.overlay?.recommendations??[];
  return rows.filter(row=>row&&row.id&&typeof row.name==='string').slice(0,3);
}
export const overlayPreview: Partial<LiveSnapshot> = {
  gameMode:'CLASSIC',gameTime:845,localPlayer:{championName:'Ahri'},
  overlay:{gold:{team:{delta:1400},lanes:roles.map((role,index)=>({role,delta:[700,-800,1250,450,-200][index],paired:true}))},
    alerts:[{key:'preview-dragon',kind:'objective',name:'Dragón',objective:'dragon',remaining:10,persistent:true},
      {key:'preview-purchase',kind:'purchase',name:'Ha comprado',champion:'Ahri',item_id:'6655',item_name:'Eco de Luden',side:'ally'},
      {key:'preview-inhibitor',kind:'structure',name:'Inhibidor de MID',structure:'inhibitor',lane:'MID',side:'enemy',remaining:45}],
    recommendations:[{id:'6655',name:'Eco de Luden',synergy_score:92,nextPurchase:{status:'buy',id:'3802',name:'Capítulo perdido',cost:900,text:'Muestra de vista previa'}},{id:'3157',name:'Reloj de arena de Zhonya',synergy_score:85,nextPurchase:{status:'buy',id:'1058',name:'Vara innecesariamente grande',cost:1250,text:'Muestra de vista previa'}},{id:'3089',name:'Sombrero mortal de Rabadon',synergy_score:78,nextPurchase:{status:'buy',id:'1058',name:'Vara innecesariamente grande',cost:1250,text:'Muestra de vista previa'}}]},
  enemyShopTimers:roles.map((role,index)=>({participantId:`preview-${index}`,champion:['Darius','Lee Sin','Ahri','Jinx','Lulu'][index],role,elapsedSeconds:[154,72,47,198,25][index],origin:'respawn_observed',state:index===1?'dead':'normal'} as EnemyShopTimer)),pendingAbility:{slot:'Q',source:'preview'},
};
export function OverlayContent({panel,snapshot,assets={},slotSpacing=47,elapsed=0}:{panel:OverlayPanel;snapshot:Partial<LiveSnapshot>;assets?:Record<string,string|null>;slotSpacing?:number;elapsed?:number}) {
  const overlay=snapshot.overlay;
  const gold=overlay?.gold as {team?:{delta?:number|null};lanes?:Array<{role:string;delta:number|null}>}|undefined;
  const alerts=(overlay?.alerts??[]) as AlertNotice[];
  const recommendations=purchaseRows(snapshot);
  if(panel==='ability')return <div className="overlay-ability" style={{gap:Math.max(0,Math.min(29,slotSpacing-43))}} aria-label={`Subir ${snapshot.pendingAbility?.slot??'habilidad'}`}>
    {(['Q','W','E','R'] as const).map(slot=>{const icon=Object.entries(assets).find(([key])=>key.startsWith('ability:')&&key.endsWith(`|${slot.toLowerCase()}`))?.[1];return <span className={slot===snapshot.pendingAbility?.slot?'active':''} key={slot}>{icon&&<img src={icon} alt=""/>}<b>{slot}</b></span>;})}
  </div>;
  if(panel==='alerts')return alerts.length?<div className="overlay-notifications" role="status" aria-live="polite">{alerts.slice(0,3).map(alert=>{
    const side=alert.side==='ally'?'ALIADO':alert.side==='enemy'?'ENEMIGO':'';
    const icon=alert.kind==='structure'?(alert.structure==='inhibitor'?'shield':'turret'):
      alert.objective==='dragon'?'dragon':alert.objective==='baron'?'baron':alert.objective==='herald'?'herald':'voidgrub';
    const seconds=typeof alert.remaining==='number'?Math.max(1,Math.ceil(alert.remaining-(alert.persistent?elapsed:0))):null;
    return <div className={`overlay-notification${alert.persistent?' is-countdown':''}${alert.side?` side-${alert.side}`:''}`} key={alert.key}>
      {alert.kind==='purchase'?<GameImage src={assets[`champion:${alert.champion??''}`]} alt={alert.champion??'Campeón'} className="overlay-notification-portrait" fallback={(alert.champion??'?').slice(0,1)}/>:
        <span className="overlay-notification-symbol"><Icon name={icon}/></span>}
      <div className="overlay-notification-copy"><b>{alert.kind==='purchase'?alert.champion??'Campeón':alert.name}</b><span>{alert.kind==='purchase'?'Ha comprado':`${side?`${side} · `:''}${alert.kind==='structure'?'Reaparece en':'Aparece en'} ${seconds===null?'—':`${seconds} s`}`}</span>{alert.kind==='purchase'&&alert.item_name&&<small>{alert.item_name}</small>}</div>
      {alert.kind==='purchase'&&<GameImage src={assets[`item:${alert.item_id??''}`]} alt={alert.item_name??'Objeto'} className="overlay-notification-item" fallback="·"/>}
    </div>;
  })}</div>:null;
  return <article className="live-overlay-card" data-panel={panel}>
    <header><span className="overlay-led"/><small>{titles[panel]}</small><b>{snapshot.gameMode}{snapshot.gameTime!=null?` · ${clock(snapshot.gameTime)}`:''}</b></header>
    {panel==='gold'&&<div className="overlay-gold-rows">{roles.map(role=>{const row=gold?.lanes?.find(item=>item.role===role);return <div key={role}><span>{roleLabels[role]}</span><strong className={tone(row?.delta)}>{deltaText(row?.delta)}</strong></div>})}<div className="team-total"><span>TEAM TOTAL</span><strong className={tone(gold?.team?.delta)}>{deltaText(gold?.team?.delta)}</strong></div></div>}
    {panel==='purchase'&&<div className="overlay-item-cards">{recommendations.map(item=>{const next=item.nextPurchase?.status==='buy'&&item.nextPurchase.id?item.nextPurchase:undefined;return <div className="overlay-item-card" key={String(item.id)}><div className="overlay-item-art">{assets[`item:${item.id}`]?<img src={assets[`item:${item.id}`]??''} alt=""/>:<span>◇</span>}{next&&assets[`item:${next.id}`]&&<img className="overlay-next-item" src={assets[`item:${next.id}`]??''} alt="" title={`Siguiente compra: ${next.name??'Objeto'} — ${next.cost} de oro`}/>}</div><div className="overlay-item-caption"><b>{String(item.name)}</b><small>{typeof item.synergy_score==='number'?`SINERGIA ${new Intl.NumberFormat('es-ES',{maximumFractionDigits:1}).format(item.synergy_score)} pts`:'SINERGIA —'}</small></div></div>})}{!recommendations.length&&<i>Sin recomendaciones verificadas para esta partida.</i>}</div>}
    {panel==='recall'&&<div className="overlay-recall-list">{roles.map(role=>{const matches=(snapshot.enemyShopTimers??[]).filter(row=>normalizeRole(row.role)===role);const row=matches.length===1?matches[0]:null;return <div key={role}><span className="overlay-role">{roleLabels[role]}</span>{row&&assets[`champion:${row.champion}`]?<img src={assets[`champion:${row.champion}`]??''} alt=""/>:<span className="overlay-recall-fallback">{row?.champion.slice(0,1)??'?'}</span>}<b>{row?.champion??'No disponible'}</b><time>{row?.state==='dead'?'MUERTO':row?.origin==='respawn_observed'?clock(row.elapsedSeconds):'—'}</time></div>})}</div>}
  </article>;
}
export function LiveOverlayPanel({panel}:{panel:OverlayPanel}) {
  const [state,setState]=useState<LiveMatchState>(empty);
  const receivedAt=useRef(0);
  const [clockNow,setClockNow]=useState(0);
  const [editing,setEditing]=useState(false);
  const [assets,setAssets]=useState<Record<string,string|null>>({});
  useEffect(()=>{document.documentElement.classList.add('live-overlay-document');document.body.classList.add('live-overlay-document');const off=window.solralol.onLiveOverlayState(value=>{receivedAt.current=performance.now();setState(value);});return()=>{off();document.documentElement.classList.remove('live-overlay-document');document.body.classList.remove('live-overlay-document');};},[]);
  useEffect(()=>{let active=true;void window.solralol.getOverlayEditing().then(value=>{if(active)setEditing(value)});const off=window.solralol.onOverlayEditing(setEditing);return()=>{active=false;off();};},[]);
  const snapshot=state.snapshot;
  const activeSnapshot=state.state==='active'?snapshot:null;
  const preview=editing?{...overlayPreview,overlayPanelScale:state.overlayPanelScale,abilitySlotSpacing:state.abilitySlotSpacing}:null;
  const displaySnapshot=panel==='alerts'&&editing&&!activeSnapshot?.overlay?.alerts?.length?preview:activeSnapshot??preview;
  const showingPreview=Boolean(preview&&displaySnapshot===preview);
  const champion=String(displaySnapshot?.localPlayer?.championName??'');
  const itemIds=displaySnapshot?purchaseRows(displaySnapshot).flatMap(row=>[row.id,...(row.nextPurchase?.status==='buy'&&row.nextPurchase.id?[row.nextPurchase.id]:[])]).slice(0,6).join(','):'';
  const alertRows=displaySnapshot?.overlay?.alerts as AlertNotice[]|undefined;
  const hasCountdown=panel==='alerts'&&!showingPreview&&Boolean(alertRows?.some(row=>row.persistent));
  useEffect(()=>{if(!hasCountdown)return;const timer=window.setInterval(()=>setClockNow(performance.now()),500);return()=>window.clearInterval(timer);},[hasCountdown]);
  const alertItemIds=[...new Set((alertRows??[]).map(row=>row.item_id).filter((id):id is string=>Boolean(id)))].slice(0,3).join(',');
  const alertChampions=[...new Set((alertRows??[]).map(row=>row.champion).filter((name):name is string=>Boolean(name)))].slice(0,3).join('|');
  const enemyNames=(displaySnapshot?.enemyShopTimers??[]).map(row=>row.champion).slice(0,5).join('|');
  useEffect(()=>{if(panel!=='purchase'||!itemIds)return;let active=true;void window.solralol.request('meta.assets',{items:itemIds.split(',')}).then(result=>{if(active)setAssets(result);}).catch(()=>{});return()=>{active=false;};},[panel,itemIds]);
  useEffect(()=>{if(panel!=='alerts'||!alertItemIds)return;let active=true;void window.solralol.request('meta.assets',{items:alertItemIds.split(',')}).then(result=>{if(active)setAssets(old=>({...old,...result}));}).catch(()=>{});return()=>{active=false;};},[panel,alertItemIds]);
  useEffect(()=>{if(panel!=='alerts'||!alertChampions)return;let active=true;void window.solralol.request('home.assets',{champions:alertChampions.split('|')}).then(result=>{if(active)setAssets(old=>({...old,...Object.fromEntries(Object.entries(result.championAliases??{}).map(([name,id])=>[`champion:${name}`,result.champions[String(id)]??null]))}));}).catch(()=>{});return()=>{active=false;};},[panel,alertChampions]);
  useEffect(()=>{if(panel!=='recall'||!enemyNames)return;let active=true;void window.solralol.request('home.assets',{champions:enemyNames.split('|')}).then(result=>{if(active)setAssets(Object.fromEntries(Object.entries(result.championAliases??{}).map(([name,id])=>[`champion:${name}`,result.champions[String(id)]??null])));}).catch(()=>{});return()=>{active=false;};},[panel,enemyNames]);
  useEffect(()=>{if(panel!=='ability'||!champion)return;let active=true;void window.solralol.request('meta.assets',{abilities:(['q','w','e','r'] as const).map(slot=>({champion,slot}))}).then(result=>{if(active)setAssets(result);}).catch(()=>{});return()=>{active=false;};},[panel,champion]);
  const scale=Math.max(.5,Math.min(1.5,Number(displaySnapshot?.overlayPanelScale??1)||1));
  const visibleSnapshot=displaySnapshot;
  return <main className={`live-overlay-root${editing?' overlay-editing':''}`} data-panel={panel} style={{transform:`scale(${scale})`,transformOrigin:'top left',width:`${100/scale}vw`,height:`${100/scale}vh`}}>{visibleSnapshot?<><OverlayContent panel={panel} snapshot={visibleSnapshot} assets={assets} slotSpacing={visibleSnapshot.abilitySlotSpacing} elapsed={hasCountdown&&receivedAt.current?Math.max(0,(clockNow-receivedAt.current)/1000):0}/>{showingPreview&&<span className="overlay-preview-badge">VISTA PREVIA</span>}</>:null}</main>;
}
