import test from 'node:test';
import assert from 'node:assert/strict';

import {
  classifyIssues,
  linkPurchaseBatches,
  buildConfidence,
  buildSupplyPlan,
} from '../src/planning-engine.mjs';

function fixture(overrides = {}) {
  return {
    active: true,
    timeline: {
      stockoutDate: '2026-11-05',
      gapBeforeNextEta: false,
      unknownEtaQty: 0,
      confidence: 'high',
    },
    forecast: { confidence: 'high', confidenceReasons: [] },
    bridgePlan: { required: false, qty: 0, sourceShortageQty: 0, actionable: false },
    shipmentBatches: [
      { sequence: 1, dispatchDate: '2026-10-20', suggestedQty: 100, executableQty: 100, sourceShortageQty: 0 },
      { sequence: 2, dispatchDate: '2026-10-27', suggestedQty: 100, executableQty: 100, sourceShortageQty: 0 },
      { sequence: 3, dispatchDate: '2026-11-03', suggestedQty: 100, executableQty: 100, sourceShortageQty: 0 },
      { sequence: 4, dispatchDate: '2026-11-10', suggestedQty: 100, executableQty: 100, sourceShortageQty: 0 },
    ],
    purchaseBatches: [
      { sequence: 1, orderDate: '2026-10-20', suggestedQty: 0 },
      { sequence: 2, orderDate: '2026-11-17', suggestedQty: 0 },
      { sequence: 3, orderDate: '2026-12-15', suggestedQty: 0 },
    ],
    redundancy: { estimatedRedundantQty: 0, actualAgedQty: 0 },
    dataCompleteness: 95,
    ...overrides,
  };
}

test('emits bridge and source-shortage issues together', () => {
  const result = buildSupplyPlan(fixture({
    timeline: { stockoutDate: '2026-10-25', gapBeforeNextEta: true, unknownEtaQty: 0, confidence: 'high' },
    bridgePlan: { required: true, qty: 200, sourceShortageQty: 120, actionable: true },
    shipmentBatches: [
      { sequence: 1, dispatchDate: '2026-10-20', suggestedQty: 200, executableQty: 80, sourceShortageQty: 120 },
    ],
  }));

  const codes = result.issues.map((issue) => issue.code);
  assert.equal(result.primaryIssue.code, 'stockout_before_supply');
  assert.ok(codes.includes('bridge_required'));
  assert.ok(codes.includes('source_shortage'));
});

test('links purchase lots to uncovered shipment lots', () => {
  const purchases = linkPurchaseBatches(
    [
      { sequence: 1, suggestedQty: 120 },
      { sequence: 2, suggestedQty: 80 },
      { sequence: 3, suggestedQty: 40 },
    ],
    [
      { sequence: 1, sourceShortageQty: 120 },
      { sequence: 2, sourceShortageQty: 80 },
      { sequence: 3, sourceShortageQty: 0 },
      { sequence: 4, sourceShortageQty: 40 },
    ],
  );

  assert.deepEqual(purchases.map((batch) => batch.supportsShipmentSequence), [1, 2, 4]);
});

test('returns demand, timeline and execution confidence separately', () => {
  const result = buildConfidence(fixture({
    forecast: { confidence: 'medium', confidenceReasons: ['销量高波动'] },
    timeline: { stockoutDate: null, gapBeforeNextEta: false, unknownEtaQty: 500, confidence: 'low', confidenceReasons: ['ETA缺失'] },
    dataCompleteness: 72,
  }));

  assert.equal(result.demand.level, 'medium');
  assert.equal(result.timeline.level, 'low');
  assert.equal(result.execution.level, 'medium');
  assert.equal(result.overall, 'low');
});

test('healthy result still provides a primary issue contract', () => {
  const result = classifyIssues(fixture({
    timeline: { stockoutDate: null, gapBeforeNextEta: false, unknownEtaQty: 0, confidence: 'high' },
    shipmentBatches: [{ sequence: 1, suggestedQty: 0, executableQty: 0, sourceShortageQty: 0 }],
  }));

  assert.equal(result.primaryIssue.code, 'healthy');
  assert.deepEqual(result.issues, []);
});
