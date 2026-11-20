import { memo, useEffect, useState } from 'react';
import type { EnemyShopTimer, LiveMatchState, LiveRecommendation, LiveSkillOrder } from '../types/contracts';
import { GameImage } from './GameImage';

type Assets = Record<string,string|null>;
const clock=(seconds:number|null)=>seconds===null?'--:--':`${Math.floor(Math.max(0,seconds)/60).toString().padStart(2,'0')}:${Math.floor(Math.max(0,seconds)%60).toString().padStart(2,'0')}`;
const analysisRoleLabel:Record<string,string>={top:'Superior',jungle:'Jungla',mid:'Medio',adc:'Inferior',support:'Apoyo'};

export const RecommendationCards = memo(function RecommendationCards({recommendations,assets}:{recommendations:LiveRecommendation[];assets:Assets}) {
  return <section className="live-recommendations" aria-label="Recomendaciones de objetos"><div className="live-section-title"><div><span className="eyebrow">ADAPTADAS A LA PARTIDA</span><h2>Tu siguiente objeto</h2></div></div>
    {recommendations.length?<div className="live-recommendation-grid">{recommendations.slice(0,3).map((item,index)=>{
      const next=item.nextPurchase;
      const explanation=[...item.reasons,...item.responses].join('\n');
      const purchaseTip=next?`${next.name||'Compra siguiente'} · ${next.cost??'—'} oro\n${next.status==='buy'?'Asequible al volver a tienda.':next.status==='save'?`Objetivo: faltan ${next.missing??'—'} de oro.`:next.text}\n${next.text}`:'Ruta de compra no disponible';
      return <article className={`live-recommendation ${index===0?'preferred':''}`} key={item.id} title={explanation}>
        <span className="live-recommendation-rank">{index+1}</span><div className="live-recommendation-art"><GameImage src={assets[`item:${item.id}`]} alt={item.name} className="live-recommendation-icon" fallback="·"/>{next?.id&&<span className={`live-next-purchase ${next.status}`} title={purchaseTip}><GameImage src={assets[`item:${next.id}`]} alt={`Próxima compra: ${next.name}`} className="live-next-purchase-icon" fallback="·"/></span>}</div>
        <h3>{item.name}</h3><span className="live-synergy"><b>{item.score.toLocaleString('es-ES',{maximumFractionDigits:1})}</b> afinidad</span><small>{item.responses[0]||item.reasons[0]||'Alternativa compatible'}</small><p className="live-purchase-caption" title={purchaseTip}>{next?.name?`${next.status==='buy'?'Comprar':'Objetivo'}: ${next.name}`:next?.text||'Esperando ruta de compra'}</p>
      </article>;
    })}</div>:<p className="live-preparation-unavailable">Sin alternativas compatibles verificables con el perfil, inventario y catálogo disponibles.</p>}
    <p className="live-advice-note">Afinidad del motor local · alternativas, no una probabilidad de victoria.</p>
  </section>;
}, (previous,next)=>previous.assets===next.assets&&JSON.stringify(previous.recommendations)===JSON.stringify(next.recommendations));

export const SkillOrderGrid = memo(function SkillOrderGrid({skill,level}:{skill?:LiveSkillOrder;level:number}) {
  return <section className="live-skill-order" aria-label="Orden de habilidades"><div className="live-section-title"><h2>Orden de habilidades</h2><span>{skill?.roleFallback?`Análisis local · ${analysisRoleLabel[skill.role||'']||skill.role}`:skill?.priority||'Análisis local'}</span></div>{skill?.status==='available'&&skill.order.length?<div className="live-skill-grid" role="table" aria-label={`Habilidades recomendadas, nivel actual ${level}`}>
    <div role="row" className="live-skill-grid-row"><span/>{Array.from({length:18},(_,index)=><span key={index} className={index+1===level?'current':''} role="columnheader">{index+1}</span>)}</div>
    {['Q','W','E','R'].map(ability=><div className="live-skill-grid-row" role="row" key={ability}><b role="rowheader">{ability}</b>{Array.from({length:18},(_,index)=>{const selected=skill.order[index]===ability;return <span role="cell" key={index} className={`${selected?'selected':''} ${index+1===level?'current':''} ${index+1<level?'past':''}`} title={`Nivel ${index+1}: ${skill.order[index]&&skill.order[index]!=='-'?skill.order[index]:'sin dato'}${index+1===level?' · nivel actual':''}`} aria-label={`${ability}, nivel ${index+1}${selected?', recomendada':''}`}>{selected?ability:''}</span>;})}</div>)}
  </div>:<p className="live-preparation-unavailable">No hay un orden de habilidades guardado para este campeón y rol.</p>}</section>;
}, (previous,next)=>previous.level===next.level&&JSON.stringify(previous.skill)===JSON.stringify(next.skill));

const classifications:Record<string,string>={automatic_progression:'Adquisición o evolución automática; contador conservado.',field_crafting_unverified:'Ornn puede forjar fuera de base; no se infiere una visita.',consumed_or_removed:'Consumo o retirada de objeto; no confirma tienda.',unverified_change:'Cambio sin evidencia suficiente.',gap_baseline:'Inventario actualizado tras un corte; no se infiere cuándo se compró.'};
export const EnemyShopTimers = memo(function EnemyShopTimers({rows,assets,active}:{rows:EnemyShopTimer[];assets:Assets;active:boolean}) {
  const [observed,setObserved]=useState(rows);
  useEffect(()=>setObserved(rows),[rows]);
  useEffect(()=>{
    if(!active)return;
    const receive=(event:Event)=>{
      const next=(event as CustomEvent<LiveMatchState>).detail.snapshot?.enemyShopTimers??[];
      setObserved(previous=>JSON.stringify(previous)===JSON.stringify(next)?previous:next);
    };
    window.addEventListener('solralol:live-update',receive);
    return()=>window.removeEventListener('solralol:live-update',receive);
  },[active]);
  return <section className="live-enemy-timers" aria-label="Tiempo sin backear enemigos"><h2>Tiempo sin backear enemigos</h2><p>Desde observación o tienda inferida · visión no verificable</p><div className="live-enemy-timer-grid">{observed.map(row=>{
    const tip=[row.champion,`Última lectura de inventario API: ${clock(row.lastObservedAt)}`,`Último cambio: ${clock(row.lastInventoryChangeAt)}`,`Tienda inferida: ${clock(row.lastInferredShopAt)}`,row.state==='dead'?'Muerto: contador pausado.':`Tiempo: ${clock(row.elapsedSeconds)}`,row.origin==='inferred_purchase'?'Origen: compra inferida; no confirma Recall.':row.origin==='respawn_observed'?'Origen: primera lectura con el campeón vivo tras morir; la reaparición pudo ocurrir antes.':row.origin==='first_observation'?'Origen: primera observación API; no confirma visita a base.':'Sin inventario fiable.',classifications[row.classification]||'', 'Live Client no informa de visibilidad ni del momento real de compra.'].filter(Boolean).join('\n');
    return <div key={row.participantId} className={`live-enemy-timer ${row.state} ${active&&row.state!=='dead'?'running':'paused'}`} title={tip} data-participant={row.participantId}><GameImage src={assets[`champion:${row.champion}`]} alt={row.champion} className="live-enemy-portrait" fallback={row.champion.slice(0,1)}/><time>{row.state==='dead'?'Muerto':clock(row.elapsedSeconds)}</time></div>;
  })}</div>{!observed.length&&<p className="live-preparation-unavailable">Esperando inventarios enemigos fiables · --:--</p>}</section>;
});
