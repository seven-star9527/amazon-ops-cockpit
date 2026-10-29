import assert from 'node:assert/strict';
import test from 'node:test';
import { buildShipmentPlanView } from '../src/inventory-engine.mjs';

const asOf = '2026-10-22';
const purchases = [{ sequence: 1, orderDate: '2026-10-28', expectedReadyDate: '2026-12-17', suggestedQty: 693 }];

test('first batch with zero executable is not immediate; purchase-backed later batch is planned', () => {
  const plan = buildShipmentPlanView([
    { sequence: 1, dispatchDate: '2026-10-22', arrivalDate: '2026-11-21', suggestedQty: 289, executableQty: 0, mode: '卡航' },
    { sequence: 2, dispatchDate: '2026-10-29', arrivalDate: '2026-11-28', suggestedQty: 340, executableQty: 0, mode: '卡航' },
    { sequence: 10, dispatchDate: '2026-12-24', arrivalDate: '2027-01-23', suggestedQty: 743, executableQty: 693, mode: '海运' },
  ], purchases, asOf);
  assert.equal(plan.immediate, null);
  assert.deepEqual(plan.planned.map((batch) => batch.sequence), [10]);
  assert.equal(plan.planned[0].phase, 'planned');
  assert.equal(plan.planned[0].funding, 'purchase');
  assert.equal(plan.planned[0].availableAt, '2026-12-17');
  assert.equal(plan.planned[0].shipNowQty, 693);
  assert.equal(plan.batches[0].phase, 'unavailable');
  assert.equal(plan.immediateQty, 0);
  assert.equal(plan.plannedQty, 693);
});

test('first executable batch is immediate and later batches are planned, never immediate', () => {
  const plan = buildShipmentPlanView([
    { sequence: 1, dispatchDate: '2026-10-22', arrivalDate: '2026-11-21', suggestedQty: 100, executableQty: 100, mode: '卡航' },
    { sequence: 2, dispatchDate: '2026-10-29', arrivalDate: '2026-11-28', suggestedQty: 100, executableQty: 100, mode: '卡航' },
  ], [{ sequence: 1, expectedReadyDate: '2026-10-25', suggestedQty: 100 }], asOf);
  assert.equal(plan.immediate.sequence, 1);
  assert.equal(plan.immediate.phase, 'immediate');
  assert.equal(plan.immediate.funding, 'local');
  assert.deepEqual(plan.planned.map((batch) => batch.sequence), [2]);
  assert.equal(plan.planned[0].funding, 'purchase');
  assert.equal(plan.planned[0].phase, 'planned');
  assert.equal(plan.next.sequence, 1);
});

test('later executable batch without a purchase receipt is local funding', () => {
  const plan = buildShipmentPlanView([
    { sequence: 1, dispatchDate: '2026-10-22', suggestedQty: 0, executableQty: 0 },
    { sequence: 2, dispatchDate: '2026-10-29', suggestedQty: 20, executableQty: 20 },
  ], [], asOf);
  assert.equal(plan.immediate, null);
  assert.equal(plan.planned[0].funding, 'local');
  assert.equal(plan.planned[0].availableAt, asOf);
});
