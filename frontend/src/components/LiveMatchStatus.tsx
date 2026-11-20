import { useEffect, useState } from 'react';
import type { LiveMatchState } from '../types/contracts';

const labels: Record<LiveMatchState['state'], string> = {disconnected:'Desconectado',connected:'Listo',lobby:'Sala / búsqueda',champion_select:'Selección de campeón',loading:'Cargando partida',active:'En partida',game_ending:'Finalizando',post_game:'Postpartida'};

export function LiveMatchStatus() {
  const [status, setStatus] = useState({label:'Esperando al cliente',tone:'offline',detail:'',clock:''});
  useEffect(()=>{
    const receive=(event:Event)=>{
      const live=(event as CustomEvent<LiveMatchState>).detail;
      if(!live)return;
      const seconds=live.snapshot?.gameTime;
      const time=typeof seconds==='number'&&seconds>=0?`${Math.floor(seconds/60).toString().padStart(2,'0')}:${Math.floor(seconds%60).toString().padStart(2,'0')}`:'';
      const next={label:labels[live.state],tone:live.telemetry==='stale'?'stale':live.connected?'connected':'offline',detail:[live.snapshot?.gameMode,time,live.message].filter(Boolean).join(' · '),clock:[live.snapshot?.gameMode,time].filter(Boolean).join(' · ')};
      setStatus(previous=>JSON.stringify(previous)===JSON.stringify(next)?previous:next);
    };
    window.addEventListener('solralol:live-update',receive);
    return()=>window.removeEventListener('solralol:live-update',receive);
  },[]);
  return <span className="live-nav-status" role="status" title={status.detail}><i className={`live-dot ${status.tone}`}/><b>{status.label}</b>{status.clock&&<small>{status.clock}</small>}</span>;
}
