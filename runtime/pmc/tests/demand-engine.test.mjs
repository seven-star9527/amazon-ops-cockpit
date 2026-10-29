import test from 'node:test';
import assert from 'node:assert/strict';

import { forecastDemand, DEMAND_POLICY } from '../src/demand-engine.mjs';

test('missing stock fields are unknown, not proven stockout', () => {
  const history = Array.from({ length: 60 }, (_, index) => ({
    date: `day-${index + 1}`, sales: index < 10 ? 0 : 5,
    fbaSellable: index < 10 ? 0 : null, inboundReceiving: null,
  }));
  const result = forecastDemand(history);
  assert.equal(result.constrainedDays, 0);
  assert.equal(result.effectiveDays, 60);
});

const enriched = (values) => values.map((sales, index) => ({ date: `day-${index + 1}`, sales, fbaSellable: 100 }));

test('excludes zero-sales days proven to be stock constrained', () => {
  const days = Array.from({ length: 60 }, (_, index) => ({
    date: `day-${index + 1}`,
    sales: index < 10 ? 0 : 10,
    fbaSellable: index < 10 ? 0 : 100,
    inboundReceiving: 0,
  }));

  const result = forecastDemand(days);

  assert.equal(result.constrainedDays, 10);
  assert.equal(result.effectiveDays, 50);
  assert.equal(result.daily, 10);
  assert.equal(result.dailySeries.filter((day) => day.constrained).length, 10);
});

test('uses 7/30/60 windows and separates trend from momentum', () => {
  const history = enriched([...Array(20).fill(3), ...Array(20).fill(6), ...Array(20).fill(10)]);

  const result = forecastDemand(history);

  assert.equal(result.trend, 'growth');
  assert.equal(result.momentum, 'steady');
  assert.equal(result.windowDays.recent, 7);
  assert.equal(result.windowDays.middle, 30);
  assert.equal(result.windowDays.far, 60);
  assert.ok(result.combinedState.includes('-growth-'));
  assert.ok(result.daily > result.segments.middle);
  assert.ok(result.daily < result.segments.recent);
});

test('falls back to the latest effective mean when fewer than 7 usable days remain', () => {
  const history = Array.from({ length: 60 }, (_, index) => ({
    date: `day-${index + 1}`,
    sales: index < 57 ? 0 : 4,
    fbaSellable: index < 57 ? 0 : 40,
    inboundReceiving: 0,
  }));

  const result = forecastDemand(history);

  assert.equal(result.effectiveDays, 3);
  assert.equal(result.daily, 4);
  assert.equal(result.confidence, 'low');
  assert.equal(result.fallbackUsed, true);
});

test('keeps numeric history backward compatible', () => {
  const result = forecastDemand([
    ...Array(20).fill(5),
    ...Array(20).fill(8),
    ...Array(20).fill(12),
  ]);

  assert.equal(result.state, 'growth');
  assert.ok(result.weights.recent > result.weights.middle);
  assert.ok(result.daily >= 10.5 && result.daily <= 12.5);
});

test('stable history stays close to its ordinary daily sales', () => {
  const result = forecastDemand(enriched(Array(60).fill(10)));
  assert.equal(result.state, 'stable');
  assert.equal(result.daily, 10);
});

test('caps a one-week promo spike instead of baking it into the baseline', () => {
  const history = enriched([...Array(53).fill(10), ...Array(7).fill(100)]);
  const result = forecastDemand(history);

  assert.equal(result.trend, 'growth');
  assert.equal(result.momentum, 'accelerating');
  assert.ok(result.daily <= 10 * DEMAND_POLICY.sevenDayUpperCap + 0.1, `daily=${result.daily}`);
  assert.ok(result.daily > 10);
});


test('missing sales days are excluded rather than zero filled', () => {
  const result = forecastDemand([{sales: null}, {sales: 6}, {sales: 0}]);
  assert.equal(result.effectiveDays, 2);
  assert.equal(result.missingDays, 1);
  assert.equal(result.daily, 3);
});
