import assert from 'node:assert/strict';
import test from 'node:test';
import {
  BATTLESCORE_DISPLAY_INTERVAL_MS,
  BATTLESCORE_EMA_CURRENT_WEIGHT,
  battleScoreAt,
  displayedBattleScoreAt,
  resampleAndSmoothBattleScore,
} from '../../frontend/src/utils/battleScoreTimeline.ts';

test('samples every 30 seconds, interpolates only measured decay, and includes an irregular final point', () => {
  const canonical = [
    { timestamp: 0, score: 5 },
    { timestamp: 10_000, score: 4.9 },
    { timestamp: 10_000, score: 5.5 }, // event impulse; use after-event state at the boundary
    { timestamp: 20_000, score: 5.4 },
    { timestamp: 40_000, score: 5.2 },
    { timestamp: 45_000, score: 5.1 },
  ];
  const original = structuredClone(canonical);
  const displayed = resampleAndSmoothBattleScore(canonical, 45_000, 5.1);

  assert.equal(BATTLESCORE_DISPLAY_INTERVAL_MS, 30_000);
  assert.equal(BATTLESCORE_EMA_CURRENT_WEIGHT, 0.8);
  assert.deepEqual(displayed.map(point => point.x), [0, 30_000, 45_000]);
  assert.ok(Math.abs(displayed[1].rawScore - 5.3) < 1e-9);
  assert.equal(displayed[2].x, 45_000);
  assert.equal(displayed[2].y, 5.1);
  assert.deepEqual(canonical, original); // visualization never mutates canonical history
});

test('an event between boundaries contributes at the next sample, not before it', () => {
  const canonical = [
    { timestamp: 0, score: 5 },
    { timestamp: 30_000, score: 5.1 },
    { timestamp: 40_000, score: 5.05 },
    { timestamp: 40_000, score: 5.8 },
    { timestamp: 50_000, score: 5.75 },
    { timestamp: 60_000, score: 5.7 },
  ];
  assert.equal(battleScoreAt(canonical, 39_999), 5.1);
  assert.equal(battleScoreAt(canonical, 40_000), 5.8);
  const displayed = resampleAndSmoothBattleScore(canonical, 60_000, 5.7);
  assert.deepEqual(displayed.map(point => point.x), [0, 30_000, 60_000]);
  assert.equal(displayed[2].rawScore, 5.7);
  assert.equal(displayed[2].y, 5.7);
});

test('light EMA reduces repeated small oscillations and tooltips can read both display and raw values', () => {
  const canonical = [
    { timestamp: 0, score: 5 },
    { timestamp: 30_000, score: 5.2 },
    { timestamp: 60_000, score: 5.0 },
    { timestamp: 90_000, score: 5.2 },
    { timestamp: 120_000, score: 5.0 },
  ];
  const displayed = resampleAndSmoothBattleScore(canonical, 120_000, 5.0);
  const rawMovement = canonical.slice(1).reduce((sum, point, index) => sum + Math.abs(point.score - canonical[index].score), 0);
  const displayMovement = displayed.slice(1).reduce((sum, point, index) => sum + Math.abs(point.y - displayed[index].y), 0);
  assert.ok(displayMovement < rawMovement);
  assert.ok(displayed[1].y > displayed[2].y); // a negative swing remains visible
  assert.equal(displayedBattleScoreAt(displayed, 120_000), 5.0);
  assert.equal(battleScoreAt(canonical, 75_000), 5.1);
});

test('handles a short match and exact interval endings without duplicate final samples', () => {
  const short = resampleAndSmoothBattleScore([
    { timestamp: 0, score: 5 }, { timestamp: 20_000, score: 5.25 },
  ], 20_000, 5.25);
  assert.deepEqual(short.map(point => point.x), [0, 20_000]);
  assert.equal(short.at(-1).y, 5.25);

  const exact = resampleAndSmoothBattleScore([
    { timestamp: 0, score: 5 }, { timestamp: 30_000, score: 5.1 }, { timestamp: 60_000, score: 5.3 },
  ], 60_000, 5.3);
  assert.deepEqual(exact.map(point => point.x), [0, 30_000, 60_000]);
  assert.equal(exact.at(-1).y, 5.3);
});

test('does not invent a timestamped state before the first canonical observation', () => {
  const canonical = [{ timestamp: 12_000, score: 5.2 }, { timestamp: 42_000, score: 5.1 }];
  assert.equal(battleScoreAt(canonical, 0), null);
  const displayed = resampleAndSmoothBattleScore(canonical, 42_000, 5.1);
  assert.deepEqual(displayed.map(point => point.x), [30_000, 42_000]);
});

test('a 30-minute match has 61 plotted samples and preserves its exact final score', () => {
  const canonical = Array.from({ length: 181 }, (_, index) => ({
    timestamp: index * 10_000,
    score: 5 + index * 0.002,
  }));
  const displayed = resampleAndSmoothBattleScore(canonical, 30 * 60_000, 5.36);
  assert.equal(displayed.length, 61);
  assert.deepEqual(displayed.slice(0, 3).map(point => point.x), [0, 30_000, 60_000]);
  assert.equal(displayed.at(-1).x, 30 * 60_000);
  assert.equal(displayed.at(-1).y, 5.36);
});
