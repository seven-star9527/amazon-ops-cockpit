import test from 'node:test';
import assert from 'node:assert/strict';

import {
  forecastDemand,
  simulateInventory,
  calculateRedundancy,
  buildShipmentBatches,
  buildPurchaseBatches,
  analyzeInventoryRecord,
} from '../src/inventory-engine.mjs';
import { simulateInventoryTimeline } from '../src/timeline-engine.mjs';

test('seasonal demand range pulls the stockout earlier and lifts the batch', () => {
  const peak = (date) => (date >= '2026-10-20' ? 50 : 10);
  const baseTimeline = simulateInventoryTimeline({ asOf: '2026-10-14', dailyDemand: 10, sellable: 500, horizonDays: 90 });
  const peakTimeline = simulateInventoryTimeline({ asOf: '2026-10-14', dailyDemand: 10, demandAt: peak, sellable: 500, horizonDays: 90 });
  assert.ok(peakTimeline.stockoutDate < baseTimeline.stockoutDate, `${peakTimeline.stockoutDate} vs ${baseTimeline.stockoutDate}`);

  const baseBatch = buildShipmentBatches({
    asOf: '2026-10-14', fbaAvailable: 500, dailyDemand: 10, safetyDays: 15, cadenceDays: 7,
    transitDays: 60, sourceAvailable: 10000, count: 1,
  });
  const peakBatch = buildShipmentBatches({
    asOf: '2026-10-14', fbaAvailable: 500, dailyDemand: 10, demandAt: peak, safetyDays: 15, cadenceDays: 7,
    transitDays: 60, sourceAvailable: 10000, count: 1,
  });
  assert.ok(peakBatch[0].suggestedQty > baseBatch[0].suggestedQty, `${peakBatch[0].suggestedQty} vs ${baseBatch[0].suggestedQty}`);
});

test('growth history puts the most weight on the last 7 days', () => {
  const history = [
    ...Array(20).fill(5),
    ...Array(20).fill(8),
    ...Array(20).fill(12),
  ];
  const result = forecastDemand(history);

  assert.equal(result.state, 'growth');
  assert.ok(result.weights.recent > result.weights.middle);
  assert.ok(result.weights.recent > result.weights.far);
  assert.ok(result.daily >= 10.5 && result.daily <= 12.5);
  assert.equal(result.confidence, 'high');
});

test('stable history stays close to its ordinary daily sales', () => {
  const history = Array.from({ length: 60 }, (_, index) => 9 + (index % 3));
  const result = forecastDemand(history);

  assert.equal(result.state, 'stable');
  assert.equal(result.daily, 10);
  assert.deepEqual(result.weights, { recent: 0.2, middle: 0.5, far: 0.3 });
});

test('stockout date ignores an inbound event that arrives after the gap', () => {
  const result = simulateInventory({
    asOf: '2026-10-14',
    available: 100,
    dailyDemand: 10,
    safetyDays: 5,
    horizonDays: 30,
    inbound: [{ date: '2026-10-27', qty: 120, confirmed: true }],
  });

  assert.equal(result.stockoutDate, '2026-10-24');
  assert.equal(result.safetyBreachDate, '2026-10-19');
  assert.equal(result.gapBeforeNextEta, true);
});

test('unknown ETA does not silently postpone a confirmed stockout date', () => {
  const result = simulateInventory({
    asOf: '2026-10-14',
    available: 70,
    dailyDemand: 10,
    safetyDays: 3,
    horizonDays: 20,
    inbound: [{ date: null, qty: 300, confirmed: false }],
  });

  assert.equal(result.stockoutDate, '2026-10-21');
  assert.equal(result.unknownEtaQty, 300);
  assert.equal(result.confidence, 'low');
});

test('zero demand does not manufacture a next-day stockout', () => {
  const result = simulateInventory({
    asOf: '2026-10-15',
    available: 0,
    dailyDemand: 0,
    safetyDays: 15,
    horizonDays: 30,
    inbound: [],
  });

  assert.equal(result.stockoutDate, null);
  assert.equal(result.safetyBreachDate, null);
});

test('actual aged stock and estimated redundancy remain separate measures', () => {
  const result = calculateRedundancy({
    fbaAvailable: 520,
    dailyDemand: 10,
    safetyDays: 15,
    cadenceDays: 7,
    agedBuckets: { over90: 80, over180: 35, over270: 12, over365: 3 },
  });

  assert.equal(result.targetQty, 220);
  assert.equal(result.estimatedRedundantQty, 300);
  assert.equal(result.actualAgedQty, 80);
  assert.equal(result.label, '超龄且冗余');
});

test('shipment planning returns one actionable and three rolling batches', () => {
  const result = buildShipmentBatches({
    asOf: '2026-10-14',
    fbaAvailable: 80,
    dailyDemand: 10,
    safetyDays: 15,
    cadenceDays: 7,
    transitDays: 14,
    sourceAvailable: 700,
    inbound: [],
    count: 4,
  });

  assert.equal(result.length, 4);
  assert.deepEqual(result.map((item) => item.dispatchDate), [
    '2026-10-14', '2026-10-21', '2026-10-28', '2026-11-04',
  ]);
  assert.equal(result[0].status, 'actionable');
  assert.ok(result[0].suggestedQty > 0);
  assert.ok(result.slice(1).every((item) => item.status === 'planning'));
});

test('purchase plan uses lead time and never returns negative quantities', () => {
  const result = buildPurchaseBatches({
    asOf: '2026-10-14',
    dailyDemand: 10,
    purchaseLeadDays: 40,
    cadenceDays: 28,
    safetyDays: 15,
    effectiveInventory: 300,
    count: 3,
  });

  assert.equal(result.length, 3);
  assert.equal(result[0].orderDate, '2026-10-14');
  assert.equal(result[0].expectedReadyDate, '2026-11-23');
  assert.equal(result[0].theoreticalQty, 650);
  assert.equal(result[0].suggestedQty, 650);
  assert.ok(result.every((item) => item.suggestedQty >= 0));
});

test('known carton quantity produces whole-carton shipment and purchase suggestions', () => {
  const shipments = buildShipmentBatches({ asOf:'2026-10-14', fbaAvailable:80, dailyDemand:10,
    safetyDays:15, cadenceDays:7, transitDays:14, sourceAvailable:700, cartonQty:36, inbound:[], count:4 });
  const purchases = buildPurchaseBatches({ asOf:'2026-10-14', dailyDemand:10, purchaseLeadDays:40,
    cadenceDays:28, safetyDays:15, effectiveInventory:300, cartonQty:36, count:3 });
  assert.equal(shipments[0].theoreticalQty, 280);
  assert.equal(shipments[0].suggestedQty, 288);
  assert.equal(shipments[0].executableQty % 36, 0);
  assert.equal(shipments[0].cartons, 8);
  assert.equal(purchases[0].theoreticalQty, 650);
  assert.equal(purchases[0].suggestedQty, 684);
  assert.equal(purchases[0].cartons, 19);
});

test('insufficient source stock does not propose a partial carton', () => {
  const shipments = buildShipmentBatches({ asOf:'2026-10-14', fbaAvailable:80, dailyDemand:10,
    safetyDays:15, cadenceDays:7, transitDays:14, sourceAvailable:35, cartonQty:36, inbound:[], count:4 });
  assert.equal(shipments[0].executableQty, 0);
  assert.equal(shipments[0].sourceShortageQty, 288);
});

test('future purchase batches stay at zero while existing inventory still covers their ready dates', () => {
  const result = buildPurchaseBatches({
    asOf: '2026-10-14',
    dailyDemand: 5,
    purchaseLeadDays: 35,
    cadenceDays: 28,
    safetyDays: 20,
    effectiveInventory: 1450,
    count: 3,
  });

  assert.deepEqual(result.map((item) => item.suggestedQty), [0, 0, 0]);
});

test('record analysis keeps demand, timeline and four-batch plans consistent', () => {
  const result = analyzeInventoryRecord({
    asin: 'DEMO-B0A1',
    sku: 'DEMO-SKU-01',
    history: [...Array(20).fill(5), ...Array(20).fill(8), ...Array(20).fill(12)],
    fbaAvailable: 86,
    fbaInboundLive: 200,
    sourceAvailable: 700,
    localAvailable: 500,
    overseasAvailable: 200,
    procurementOpen: 0,
    purchaseLeadDays: 40,
    transitDays: 14,
    safetyDays: 15,
    cadenceDays: 7,
    purchaseCadenceDays: 28,
    inbound: [{ date: '2026-10-28', qty: 200, confirmed: true }],
  }, { asOf: '2026-10-14', scenarioMultiplier: 1 });

  assert.equal(result.forecast.daily, 11.2);
  assert.ok(result.shipmentBatches.length >= 4);
  assert.ok(result.purchaseBatches.length >= 1);
  assert.equal(result.risk, 'critical');
  assert.equal(result.bridgePlan.required, true);
  assert.equal(result.bridgePlan.latestArrivalDate, result.timeline.stockoutDate);
  assert.equal(result.bridgePlan.dispatchDate, null);
  assert.equal(result.bridgePlan.status, 'no_benefit');
  assert.match(result.nextAction, /不建议新发/);
});

test('record analysis emits a complete evidence chain and a direct conclusion', () => {
  const result = analyzeInventoryRecord({
    store: '济桓-UK',
    asin: 'B0REAL1234',
    sku: 'LOCAL-SKU',
    history: [...Array(20).fill(4), ...Array(20).fill(6), ...Array(20).fill(9)],
    forecastSource: '领星销量统计：60天逐日销量',
    fbaAvailable: 70,
    fbaReserved: 8,
    fbaInboundLive: 120,
    localAvailable: 300,
    overseasAvailable: 40,
    sourceAvailable: 340,
    procurementOpen: 0,
    purchaseLeadDays: 36,
    transitDays: 20,
    expediteTransitDays: 10,
    safetyDays: 15,
    cadenceDays: 7,
    purchaseCadenceDays: 28,
    dataCompleteness: 86,
    evidence: [{ stage: '映射', source: '领星', fact: 'ASIN → SKU' }],
    inbound: [{ date: '2026-11-20', qty: 120, confirmed: true, shipment: 'FBA123' }],
    lingxingSuggestion: { estimatedDaily: 8.2, suggestSendDate: '2026-10-16', suggestPurchaseDate: '' },
  }, { asOf: '2026-10-15' });

  assert.ok(result.evidenceChain.length >= 6);
  assert.equal(result.evidenceChain.at(-1).stage, '结论');
  assert.equal(result.decision.conclusion, result.nextAction);
  assert.ok(result.decision.reason.length > 10);
  assert.equal(result.lingxingCrosscheck.officialDaily, 8.2);
});

test('inactive listings never receive a replenishment or stockout action', () => {
  const result = analyzeInventoryRecord({
    asin: 'B0INACTIVE1',
    sku: 'OLD-SKU',
    listingStatus: 0,
    history: Array(60).fill(5),
    fbaAvailable: 0,
    sourceAvailable: 0,
    procurementOpen: 0,
    purchaseLeadDays: 40,
    transitDays: 50,
    safetyDays: 15,
    cadenceDays: 7,
    purchaseCadenceDays: 28,
    inbound: [],
  }, { asOf: '2026-10-15' });

  assert.equal(result.risk, 'healthy');
  assert.equal(result.timeline.stockoutDate, null);
  assert.match(result.nextAction, /非在售且无库存/);
  assert.ok(result.shipmentBatches.every((batch) => batch.suggestedQty === 0));
  assert.ok(result.purchaseBatches.every((batch) => batch.suggestedQty === 0));
});

test('an infeasible bridge produces a concrete sales ceiling instead of a vague handoff', () => {
  const result = analyzeInventoryRecord({
    asin: 'B0BRIDGE01',
    sku: 'BRIDGE-SKU',
    listingStatus: 1,
    history: Array(60).fill(10),
    fbaAvailable: 40,
    sourceAvailable: 200,
    procurementOpen: 0,
    purchaseLeadDays: 40,
    transitDays: 50,
    expediteTransitDays: 10,
    safetyDays: 15,
    cadenceDays: 7,
    purchaseCadenceDays: 28,
    inbound: [],
  }, { asOf: '2026-10-15' });

  assert.equal(result.bridgePlan.status, 'partial');
  assert.match(result.nextAction, /断档 \d+ 天到恢复/);
  assert.equal(result.bridgePlan.controlDaily, 4);
});

test('a feasible dispatch date is still not a feasible bridge when source stock is zero', () => {
  const result = analyzeInventoryRecord({
    asin: 'B0NOSOURCE1',
    sku: 'NO-SOURCE-SKU',
    listingStatus: 1,
    history: Array(60).fill(1),
    fbaAvailable: 20,
    sourceAvailable: 0,
    procurementOpen: 0,
    purchaseLeadDays: 40,
    transitDays: 50,
    expediteTransitDays: 10,
    safetyDays: 15,
    cadenceDays: 7,
    purchaseCadenceDays: 28,
    inbound: [],
  }, { asOf: '2026-10-15' });

  assert.equal(result.risk, 'critical');
  assert.equal(result.bridgePlan.status, 'no_source');
  assert.equal(result.bridgePlan.executableQty, 0);
  assert.match(result.nextAction, /本地与海外仓可发 0 件/);
  assert.match(result.nextAction, /齐套/);
  assert.doesNotMatch(result.nextAction, /最晚.*发出加急桥接/);
});

test('an expedited lane is never slower than the normal lane', () => {
  const result = analyzeInventoryRecord({
    asin: 'B0EXPEDITE1',
    sku: 'EXPEDITE-SKU',
    listingStatus: 1,
    history: Array(60).fill(5),
    fbaAvailable: 30,
    sourceAvailable: 500,
    procurementOpen: 0,
    purchaseLeadDays: 40,
    transitDays: 6,
    expediteTransitDays: 10,
    safetyDays: 15,
    cadenceDays: 7,
    purchaseCadenceDays: 28,
    inbound: [],
  }, { asOf: '2026-10-15' });

  assert.equal(result.bridgePlan.expediteTransitDays, 6);
});

test('a zero-source stockout points at a procurement ready date instead of a zero sales ceiling', () => {
  const result = analyzeInventoryRecord({
    asin: 'B0NOSOURCE2',
    sku: 'NO-SOURCE-SKU-2',
    listingStatus: 1,
    history: Array(60).fill(4),
    fbaAvailable: 0,
    sourceAvailable: 0,
    procurementOpen: 900,
    purchaseLeadDays: 45,
    transitDays: 40,
    expediteTransitDays: 10,
    safetyDays: 15,
    cadenceDays: 7,
    purchaseCadenceDays: 28,
    inbound: [],
  }, { asOf: '2026-10-15' });

  assert.equal(result.bridgePlan.status, 'no_source');
  assert.equal(result.bridgePlan.controlDaily, null);
  assert.match(result.nextAction, /采购未结/);
  assert.match(result.nextAction, /2026-11-29 齐套/);
  assert.doesNotMatch(result.nextAction, /日销上限/);
});


test('domestic procurement dates never become FBA relief and closed receipts cannot invent dates',()=>{
  const record={id:'supply-test',history:Array(30).fill(10),fbaAvailable:10,inventoryLayers:{sellable:10,local:0,overseas:0,procurementOpen:50,shippedRaw:0},purchaseEvidence:{},procurementLots:[],purchaseLeadDays:40,transitDays:60};
  const closed=analyzeInventoryRecord(record,{asOf:'2026-10-29'});
  assert.equal(closed.bridgePlan.procurementReadyDate,null);
  const open=analyzeInventoryRecord({...record,procurementLots:[{qty:50,date:'2026-11-03'}]},{asOf:'2026-10-29'});
  assert.equal(open.bridgePlan.procurementReadyDate,'2026-11-03');
  assert.notEqual(open.bridgePlan.reliefSource,'采购齐套');
  assert.equal(open.timeline.confirmedQty,0);
});
