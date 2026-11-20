import { memo, useEffect, useMemo, useRef, useState } from 'react';
import type { HomeMatch, RollingWinRatePoint, RollingWinRateSeries } from '../types/contracts';

type Props = { series?: RollingWinRateSeries; matches?: HomeMatch[] };

const WIDTH = 760;
const HEIGHT = 220;
const PLOT = { left: 48, right: 14, top: 14, bottom: 40 };
const TICKS = [0, 25, 50, 75, 100];
const SIZE_STEP = 2;

export const WinRateEvolution = memo(function WinRateEvolution({ series: backendSeries, matches = [] }: Props) {
  const [activePosition, setActivePosition] = useState<number>();
  const [size, setSize] = useState({ width: WIDTH, height: HEIGHT });
  const chartRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const element = chartRef.current;
    if (!element || typeof ResizeObserver === 'undefined') return;
    let frame = 0;
    const observer = new ResizeObserver(([entry]) => {
      if (!entry) return;
      const width = Math.round(entry.contentRect.width / SIZE_STEP) * SIZE_STEP;
      const height = Math.round(entry.contentRect.height / SIZE_STEP) * SIZE_STEP;
      if (width <= 0 || height <= 0) return;
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        setSize((current) => current.width === width && current.height === height
          ? current
          : { width, height });
      });
    });
    observer.observe(element);
    return () => {
      observer.disconnect();
      cancelAnimationFrame(frame);
    };
  }, []);
  // Keep the chart usable with an already-running backend that predates this
  // analytics field. It derives only from the match page already in memory.
  const fallbackSeries = useMemo(() => buildSeriesFromMatches(matches), [matches]);
  const series = backendSeries?.points.length ? backendSeries : fallbackSeries;
  const points = series?.points ?? [];
  const chart = useMemo(() => {
    const plotWidth = size.width - PLOT.left - PLOT.right;
    const plotHeight = size.height - PLOT.top - PLOT.bottom;
    const coordinates = points.map((point, index) => ({
      point,
      x: points.length === 1 ? PLOT.left + plotWidth / 2 : PLOT.left + index * plotWidth / (points.length - 1),
      y: PLOT.top + (1 - Math.max(0, Math.min(100, point.winrate)) / 100) * plotHeight,
    }));
    const tickIndices = points.length <= 5
      ? points.map((_, index) => index)
      : Array.from({ length: 5 }, (_, index) => Math.round(index * (points.length - 1) / 4));
    return { coordinates, tickIndices: [...new Set(tickIndices)] };
  }, [points, size]);
  const activePoint = chart.coordinates.find(({ point }) => point.position === activePosition);
  const current = points.at(-1);

  if (!series || points.length === 0) {
    return <div className="winrate-evolution-empty">
      <strong>Sin partidas SoloQ registradas</strong>
      <span>El historial local todavía no contiene partidas SoloQ con resultado y fecha disponibles.</span>
    </div>;
  }

  const windowLabel = current && current.sample_size < series.window_size
    ? `Ventana parcial · ${current.sample_size}/${series.window_size} partidas`
    : `Últimas ${series.window_size} partidas`;

  return <div className="winrate-evolution">
    <div className="winrate-evolution-summary">
      <div><small>WR MÓVIL ACTUAL</small><strong>{current?.winrate.toLocaleString('es-ES')}%</strong><span>{windowLabel}</span></div>
      <div><small>WR ÚLTIMAS 30 SOLOQ</small><strong>{series.overall_winrate == null ? '—' : `${series.overall_winrate.toLocaleString('es-ES')}%`}</strong><span>{series.wins}V · {series.losses}D · {series.total_matches} partidas</span></div>
    </div>
    <div className="winrate-chart-wrap" ref={chartRef} onPointerLeave={() => setActivePosition(undefined)}>
      <svg className="winrate-chart-svg" viewBox={`0 0 ${size.width} ${size.height}`} preserveAspectRatio="none" role="img" aria-label={`Evolución del win rate móvil de SoloQ en ${series.total_matches} partidas registradas`}>
        {TICKS.map((tick) => {
          const y = PLOT.top + (1 - tick / 100) * (size.height - PLOT.top - PLOT.bottom);
          return <g key={tick} className="winrate-chart-tick">
            <line x1={PLOT.left} x2={size.width - PLOT.right} y1={y} y2={y}/>
            <text x={PLOT.left - 9} y={y + 3} textAnchor="end">{tick}%</text>
          </g>;
        })}
        <text className="winrate-y-label" transform={`translate(11 ${size.height / 2}) rotate(-90)`} textAnchor="middle">Win Rate</text>
        <line className="winrate-axis" x1={PLOT.left} x2={size.width - PLOT.right} y1={size.height - PLOT.bottom} y2={size.height - PLOT.bottom}/>
        {chart.tickIndices.map((index) => {
          const item = chart.coordinates[index];
          return <text className="winrate-x-tick" key={item.point.position} x={item.x} y={size.height - 22} textAnchor="middle">#{item.point.position}</text>;
        })}
        {chart.coordinates.length > 1 && <path className="winrate-line" d={chart.coordinates.map(({ x, y }, index) => `${index ? 'L' : 'M'} ${x} ${y}`).join(' ')}/>}
        {chart.coordinates.map(({ point, x, y }) => <circle
          className={`winrate-point${point.position === activePosition ? ' active' : ''}`}
          key={point.match_id}
          cx={x}
          cy={y}
          r={point.position === activePosition ? 4.5 : 2.7}
          tabIndex={0}
          role="button"
          aria-label={describePoint(point, series.window_size)}
          onPointerEnter={() => setActivePosition(point.position)}
          onFocus={() => setActivePosition(point.position)}
          onBlur={() => setActivePosition(undefined)}
        />)}
      </svg>
      {activePoint && <WinRateTooltip point={activePoint.point} windowSize={series.window_size} x={activePoint.x} y={activePoint.y} width={size.width} height={size.height}/>}
    </div>
    <div className="winrate-chart-footnote"><span>30 partidas SoloQ más recientes · de antiguas a recientes</span><span>El historial local puede no contener todas tus partidas de Riot.</span></div>
  </div>;
});

function buildSeriesFromMatches(matches: HomeMatch[]): RollingWinRateSeries {
  const unique = new Map<string, HomeMatch>();
  matches.forEach((match, index) => {
    if (String(match.queue_id ?? '') !== '420' || !['victory', 'defeat'].includes(match.result ?? '') || !match.started_at || !Number.isFinite(Date.parse(match.started_at))) return;
    const id = String(match.stable_match_id || match.game_id || `${match.started_at}:${match.champion_name || index}`);
    if (!unique.has(id)) unique.set(id, match);
  });
  const recent = [...unique.entries()]
    .sort((a, b) => Date.parse(a[1].started_at || '') - Date.parse(b[1].started_at || ''))
    .slice(-30);
  const points: RollingWinRatePoint[] = recent.map(([matchId, match], index) => {
    const sample = recent.slice(Math.max(0, index - 9), index + 1);
    const wins = sample.filter(([, item]) => item.result === 'victory').length;
    return {
      position: index + 1,
      match_id: matchId,
      started_at: match.started_at!,
      champion_name: match.champion_name ?? null,
      result: match.result as 'victory' | 'defeat',
      window_wins: wins,
      window_losses: sample.length - wins,
      sample_size: sample.length,
      winrate: Math.round(wins * 1000 / sample.length) / 10,
    };
  });
  const wins = points.filter((point) => point.result === 'victory').length;
  return {
    window_size: 10,
    points,
    total_matches: points.length,
    wins,
    losses: points.length - wins,
    overall_winrate: points.length ? Math.round(wins * 1000 / points.length) / 10 : null,
    current_winrate: points.at(-1)?.winrate ?? null,
    current_sample_size: points.at(-1)?.sample_size ?? 0,
    incomplete_matches: 0,
  };
}

function WinRateTooltip({ point, windowSize, x, y, width, height }: { point: RollingWinRatePoint; windowSize: number; x: number; y: number; width: number; height: number }) {
  const left = Math.max(12, Math.min(88, x / width * 100));
  const top = Math.max(8, y / height * 100);
  return <div className="winrate-tooltip" role="tooltip" style={{ left: `${left}%`, top: `${top}%` }}>
    <strong>Partida #{point.position} · {point.champion_name || 'Campeón no disponible'}</strong>
    <span>{formatMatchDate(point.started_at)}</span>
    <span>Resultado: {point.result === 'victory' ? 'Victoria' : 'Derrota'}</span>
    <span>{point.sample_size < windowSize ? `Ventana parcial (${point.sample_size}/${windowSize})` : `Últimas ${windowSize} clasificatorias`}: {point.window_wins} victorias / {point.window_losses} derrotas</span>
    <b>Win rate móvil: {point.winrate.toLocaleString('es-ES')}%</b>
  </div>;
}

function describePoint(point: RollingWinRatePoint, windowSize: number) {
  const window = point.sample_size < windowSize ? `ventana parcial ${point.sample_size} de ${windowSize}` : `últimas ${windowSize}`;
  return `Partida ${point.position}, ${point.champion_name || 'campeón no disponible'}, ${point.result === 'victory' ? 'victoria' : 'derrota'}, ${point.window_wins} victorias y ${point.window_losses} derrotas en ${window}, win rate ${point.winrate} por ciento`;
}

function formatMatchDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? 'Fecha no disponible' : new Intl.DateTimeFormat('es-ES', { day: '2-digit', month: 'short', year: 'numeric' }).format(date);
}
