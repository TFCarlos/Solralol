import { memo } from 'react';
import type { Ref } from 'react';
import { GameImage } from './GameImage';
import { Icon } from './Icon';
import type { ChampionPerformance, HomeAssets, RecentPerformance } from '../types/contracts';

export const RecentPerformanceCard = memo(function RecentPerformanceCard({ data, cardRef }: { data?: RecentPerformance; cardRef?: Ref<HTMLElement> }) {
  const metrics = data?.metrics;
  return <section className="card home-card recent-performance-card" ref={cardRef}>
    <header className="card-title"><div className="eyebrow">SOLOQ · COLA 420</div><h3>Rendimiento reciente</h3></header>
    <p className="performance-subtitle">Últimas 10 partidas frente a las 10 anteriores</p>
    <div className="performance-metrics">
      <PerformanceMetric label="KDA" value={metrics?.kda.current} metric={metrics?.kda} format="ratio" description="Ratio agregado: (kills + asistencias) / muertes. Si hubo cero muertes, el ratio no tiene un valor finito."/>
      <PerformanceMetric label="CS/MIN" value={metrics?.cs_per_min.current} metric={metrics?.cs_per_min} format="decimal" description="Suma de súbditos y monstruos elegibles dividida entre los minutos totales de partidas con duración válida."/>
      <PerformanceMetric label="VISIÓN" value={metrics?.vision.current} metric={metrics?.vision} format="decimal" description="Promedio de puntuación de visión solo en partidas que proporcionan ese dato."/>
    </div>
    <div className={`performance-summary ${data?.trend.state ?? 'insufficient'}`}>
      <strong>{data?.trend.state === 'improving' ? 'Mejorando' : data?.trend.state === 'declining' ? 'En descenso' : data?.trend.state === 'mixed' ? 'Cambios mixtos' : data?.trend.state === 'stable' ? 'Estable' : 'Comparación pendiente'}</strong>
      <span>{data?.trend.summary ?? 'No hay datos suficientes para comparar las dos muestras.'}</span>
    </div>
    <small className="performance-sample-note">Muestra reciente: {data?.recent_matches ?? 0}/10 partidas SoloQ{data?.comparison_available ? ` · periodo anterior: ${data.previous_matches}/10` : ' · se necesitan 20 partidas para comparar periodos completos'}</small>
  </section>;
});

function PerformanceMetric({ label, value, metric, format, description }: {
  label: string;
  value: number | null | undefined;
  metric?: RecentPerformance['metrics']['kda'];
  format: 'ratio' | 'decimal';
  description: string;
}) {
  const zeroDeaths = metric?.current_zero_deaths && label === 'KDA';
  const trend = metric?.trend ?? 'neutral';
  const delta = metric?.delta;
  const formattedValue = zeroDeaths ? '∞' : value == null ? '—' : value.toLocaleString('es-ES', { minimumFractionDigits: 1, maximumFractionDigits: format === 'ratio' ? 2 : 1 });
  const formattedDelta = delta == null ? '—' : `${delta > 0 ? '+' : ''}${delta.toLocaleString('es-ES', { minimumFractionDigits: 1, maximumFractionDigits: 2 })}`;
  return <div className="performance-metric" title={description} aria-label={`${label}. ${description}`}>
    <small>{label}</small><strong>{formattedValue}</strong>
    <span className={`performance-delta ${trend}`}>
      {delta != null && <Icon name={trend === 'positive' ? 'trend-up' : trend === 'negative' ? 'trend-down' : 'trend-flat'}/>}
      {formattedDelta}
    </span>
    <em>{metric?.current_sample_size ?? 0} partidas{delta != null ? ` · ant. ${metric?.previous_sample_size ?? 0}` : ''}</em>
  </div>;
}

export const ChampionPerformanceCard = memo(function ChampionPerformanceCard({ champions, assets }: {
  champions?: ChampionPerformance[];
  assets?: HomeAssets;
}) {
  return <section className="card home-card champion-performance-card">
    <header className="card-title"><div className="eyebrow">SOLOQ · HISTORIAL LOCAL</div><h3>Rendimiento por campeón</h3></header>
    {champions?.length ? <div className="champion-performance-list">{champions.slice(0, 3).map((champion) => <article className="champion-performance-row" key={champion.champion_id}>
      <GameImage src={assets?.champions[champion.champion_id]} alt={champion.champion_name} className="champion-performance-icon" fallback={champion.champion_name.slice(0, 1)}/>
      <div className="champion-performance-info">
        <div className="champion-performance-heading"><b>{champion.champion_name}</b><strong>{champion.winrate.toLocaleString('es-ES', { maximumFractionDigits: 1 })}% <small>WR</small></strong></div>
        <div className="champion-winrate-track" role="img" aria-label={`${champion.champion_name}: ${champion.winrate}% de victorias`}><i style={{ width: `${Math.max(0, Math.min(100, champion.winrate))}%` }}/></div>
        <div className="champion-performance-meta"><span>{champion.matches} partidas · {champion.wins}V / {champion.losses}D</span><span>{champion.kda_ratio == null ? 'KDA —' : `KDA ${champion.kda_ratio.toLocaleString('es-ES', { maximumFractionDigits: 2 })}`}</span></div>
        {!champion.sample_sufficient && <small className="champion-sample-warning">Muestra limitada (menos de 5 partidas)</small>}
      </div>
    </article>)}</div> : <div className="performance-empty">No hay suficientes partidas SoloQ con campeón identificado para mostrar rendimiento.</div>}
  </section>;
});
