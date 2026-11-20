export interface BattleScorePoint {
  timestamp: number;
  score: number;
}

export interface DisplayBattleScorePoint {
  x: number;
  y: number;
  rawScore: number;
}

export const BATTLESCORE_DISPLAY_INTERVAL_MS = 30_000;
export const BATTLESCORE_EMA_CURRENT_WEIGHT = 0.8;

function orderedFinitePoints(points: BattleScorePoint[]) {
  return points
    .map((point, index) => ({ point, index }))
    .filter(({ point }) => Number.isFinite(point.timestamp) && Number.isFinite(point.score))
    .sort((a, b) => a.point.timestamp - b.point.timestamp || a.index - b.index)
    .map(({ point }) => point);
}

function scoreAtOrdered(ordered: BattleScorePoint[], timestamp: number): number | null {
  if (!ordered.length || !Number.isFinite(timestamp)) return null;

  let previousIndex = -1;
  for (let index = 0; index < ordered.length; index += 1) {
    if (ordered[index].timestamp > timestamp) break;
    previousIndex = index;
  }
  if (previousIndex < 0) return null;

  const previous = ordered[previousIndex];
  let nextIndex = previousIndex + 1;
  if (nextIndex >= ordered.length) return previous.score;

  const nextTimestamp = ordered[nextIndex].timestamp;
  while (nextIndex < ordered.length && ordered[nextIndex].timestamp === nextTimestamp) nextIndex += 1;
  const nextGroupSize = nextIndex - (previousIndex + 1);
  const next = ordered[previousIndex + 1];

  // Duplicate timestamps are event impulses. They are applied at that instant,
  // so never interpolate a later impulse into an earlier sample.
  if (nextGroupSize > 1 || nextTimestamp <= previous.timestamp) return previous.score;
  const fraction = Math.max(0, Math.min(1, (timestamp - previous.timestamp) / (nextTimestamp - previous.timestamp)));
  return previous.score + (next.score - previous.score) * fraction;
}

/** Read the canonical score at a time without leaking a future event backward. */
export function battleScoreAt(points: BattleScorePoint[], timestamp: number): number | null {
  return scoreAtOrdered(orderedFinitePoints(points), timestamp);
}

/** Build chart-only samples. The supplied canonical array remains untouched. */
export function resampleAndSmoothBattleScore(
  points: BattleScorePoint[],
  durationMs: number,
  finalScore?: number | null,
  intervalMs = BATTLESCORE_DISPLAY_INTERVAL_MS,
  currentWeight = BATTLESCORE_EMA_CURRENT_WEIGHT,
): DisplayBattleScorePoint[] {
  const ordered = orderedFinitePoints(points);
  if (!ordered.length || !Number.isFinite(durationMs) || durationMs < 0 || !Number.isFinite(intervalMs) || intervalMs <= 0) return [];

  const end = durationMs;
  const timestamps = [0];
  for (let timestamp = intervalMs; timestamp < end; timestamp += intervalMs) timestamps.push(timestamp);
  if (end > 0) timestamps.push(end);

  const raw = timestamps.flatMap((timestamp, index) => {
    const isFinal = index === timestamps.length - 1;
    const measuredFinal = typeof finalScore === 'number' && Number.isFinite(finalScore)
      ? finalScore
      : ordered[ordered.length - 1].score;
    const rawScore = isFinal ? measuredFinal : scoreAtOrdered(ordered, timestamp);
    return rawScore == null ? [] : [{ x: timestamp, rawScore }];
  });

  if (!raw.length) return [];
  const weight = Number.isFinite(currentWeight)
    ? Math.max(0, Math.min(1, currentWeight))
    : BATTLESCORE_EMA_CURRENT_WEIGHT;
  let previousDisplay = raw[0].rawScore;
  return raw.map((point, index) => {
    if (index === 0 || index === raw.length - 1) {
      previousDisplay = point.rawScore;
      return { ...point, y: point.rawScore };
    }
    const y = weight * point.rawScore + (1 - weight) * previousDisplay;
    previousDisplay = y;
    return { ...point, y };
  });
}

/** Match the SVG's straight segments for displayed-value tooltips. */
export function displayedBattleScoreAt(points: Array<{ x: number; y: number }>, timestamp: number): number | null {
  if (!points.length || !Number.isFinite(timestamp)) return null;
  if (timestamp < points[0].x) return null;
  if (timestamp === points[0].x) return points[0].y;
  for (let index = 1; index < points.length; index += 1) {
    const right = points[index];
    const left = points[index - 1];
    if (timestamp <= right.x) {
      const fraction = (timestamp - left.x) / (right.x - left.x);
      return left.y + (right.y - left.y) * fraction;
    }
  }
  return points[points.length - 1].y;
}
