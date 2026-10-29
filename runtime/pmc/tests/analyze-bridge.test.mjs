import test from 'node:test';
import assert from 'node:assert/strict';
import { projectForBoard } from '../scripts/analyze_snapshot.mjs';

test('board projection retains evidence, stock timeline and executable-vs-theoretical quantities', () => {
  const record = { id:'1-B000000001', storeId:'1', asin:'B000000001', store:'店铺',
    title:'测试品', listingStatus:1, history:Array(60).fill(2),
    inventoryLayers:{sellable:25,local:0,overseas:0,procurementOpen:0},
    fbaAvailable:25, sourceAvailable:0, inbound:[], agedBuckets:{over90:0,over180:0,over270:0,over365:0},
    purchaseLeadDays:30,transitDays:30,expressTransitDays:12,safetyDays:15,cadenceDays:7,
    revenue30:600,price:10,units30:60,evidence:[{stage:'FBA',source:'Lingxing',fact:'25'}],dataGaps:[]};
  const projected = projectForBoard(record, '2026-10-21');
  assert.equal(projected.asin, record.asin);
  assert.equal(projected.forecast.daily, 2);
  assert.ok(projected.timeline.points.length >= 120);
  assert.ok(projected.shipmentBatches.length > 0);
  assert.equal(projected.evidence[0].fact, '25');
});

test('saved default scenario applies only to its ASIN and is disclosed', () => {
  const record={id:'1-B000000001',storeId:'1',asin:'B000000001',store:'店铺',
    history:Array(60).fill(2),listingStatus:1,inventoryLayers:{sellable:40,local:0,overseas:0,procurementOpen:0},
    fbaAvailable:40,sourceAvailable:0,inbound:[],agedBuckets:{over90:0},
    purchaseLeadDays:30,transitDays:30,expressTransitDays:12,
    scenarios:[{id:'peak',isDefault:true,params:{demandMultiplier:2}}],activeScenarioId:'peak'};
  const projected=projectForBoard(record,'2026-10-21');
  assert.equal(projected.forecast.daily,4);
  assert.equal(projected.activeScenarioId,'peak');
});
