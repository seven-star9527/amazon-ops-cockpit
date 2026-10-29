import test from 'node:test';
import assert from 'node:assert/strict';

import {
  normalizeInventoryLayers,
  buildConfirmedEvents,
  simulateInventoryTimeline,
  calculateCoverage,
} from '../src/timeline-engine.mjs';

test('keeps FBA layers separate instead of manufacturing one total stock number', () => {
  const layers = normalizeInventoryLayers({
    fbaAvailable: 95,
    inventoryLayers: {
      reservedCustomerOrders: 3,
      fcTransfers: 33,
      fcProcessing: 2,
      receiving: 4,
      shippedRaw: 1040,
    },
    localAvailable: 120,
    overseasAvailable: 80,
  });

  assert.deepEqual(layers, {
    sellable: 95,
    reservedCustomerOrders: 3,
    fcTransfers: 33,
    fcProcessing: 2,
    receiving: 4,
    shippedRaw: 1040,
    local: 120,
    overseas: 80,
    procurementOpen: 0,
  });
});

test('unknown ETA quantity never delays stockout', () => {
  const result = simulateInventoryTimeline({
    asOf: '2026-10-20',
    dailyDemand: 10,
    sellable: 100,
    confirmedEvents: [],
    unknownEtaQty: 1000,
    horizonDays: 30,
  });

  assert.equal(result.stockoutDate, '2026-10-30');
  assert.equal(result.unknownEtaQty, 1000);
});

test('confirmed shipment is added exactly once', () => {
  const result = simulateInventoryTimeline({
    asOf: '2026-10-20',
    dailyDemand: 10,
    sellable: 100,
    confirmedEvents: [{ id: 'S1', etaStart: '2026-10-25', etaEnd: '2026-10-25', qty: 50 }],
    unknownEtaQty: 0,
    horizonDays: 30,
  });

  assert.equal(result.events.filter((event) => event.id === 'S1').length, 1);
  assert.equal(result.points.find((point) => point.date === '2026-10-25').arrivalQty, 50);
  const arrival = result.points.find((point) => point.date === '2026-10-25');
  assert.equal(arrival.openingStock, 60);
  assert.equal(arrival.forecastConsumption, 10);
  assert.equal(arrival.stock, 100);
  assert.deepEqual(arrival.shipmentIds, ['S1']);
});

test('baseline timeline uses ETA end and exposes ETA start for optimistic review', () => {
  const result = simulateInventoryTimeline({
    asOf: '2026-10-20',
    dailyDemand: 10,
    sellable: 80,
    confirmedEvents: [{ id: 'S1', etaStart: '2026-10-27', etaEnd: '2026-10-30', qty: 100 }],
    horizonDays: 30,
  });

  assert.equal(result.nextEtaStart, '2026-10-27');
  assert.equal(result.nextEtaEnd, '2026-10-30');
  assert.equal(result.points.find((point) => point.date === '2026-10-27').arrivalQty, 0);
  assert.equal(result.points.find((point) => point.date === '2026-10-30').arrivalQty, 100);
  assert.equal(result.gapBeforeNextEta, true);
});

test('caps matched ETA events at live shipped quantity and leaves the difference unknown', () => {
  const result = buildConfirmedEvents({
    inventoryLayers: { shippedRaw: 100 },
    inbound: [
      { shipment: 'S1', etaStart: '2026-11-01', etaEnd: '2026-11-03', qty: 80, confirmed: true },
      { shipment: 'S2', etaStart: '2026-11-05', etaEnd: '2026-11-08', qty: 80, confirmed: true },
    ],
  });

  assert.equal(result.confirmedQty, 100);
  assert.equal(result.events.reduce((sum, event) => sum + event.qty, 0), 100);
  assert.equal(result.unknownEtaQty, 0);
});

test('coverage distinguishes sellable, platform and confirmed supply quantities', () => {
  const layers = normalizeInventoryLayers({
    fbaAvailable: 100,
    inventoryLayers: { fcTransfers: 20, receiving: 30 },
  });
  const coverage = calculateCoverage(layers, 10, { confirmedQty: 50 });

  assert.equal(coverage.sellableDays, 10);
  assert.equal(coverage.platformDays, 12);
  assert.equal(coverage.confirmedSupplyDays, 20);
});
