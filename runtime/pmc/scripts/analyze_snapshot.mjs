import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { analyzeInventoryRecord } from '../src/inventory-engine.mjs';

const compactPoint = point => ({ date:point.date, stock:point.stock, arrivals:point.arrivals,
  arrivalQty:point.arrivalQty, forecastConsumption:point.forecastConsumption,
  shipmentIds:point.shipmentIds });

export function projectForBoard(record, asOf) {
  const scenario=(record.scenarios||[]).find(item=>item.id===record.activeScenarioId&&item.isDefault);
  const params=scenario?.params||{};
  const result = analyzeInventoryRecord(record, { asOf,
    scenarioMultiplier:params.demandMultiplier, seasonal:params.seasonal,
    transitDays:params.transitDays, expressTransitDays:params.expressDays,
    airTransitDays:params.airTransitDays, purchaseLeadDays:params.purchaseLeadDays,
    safetyDays:params.safetyDays, cadenceDays:params.cadenceDays,
    cartonQty:params.cartonQty, moq:params.moq, minShipQty:params.minShipQty,
    localAvailable:params.localAvailable });
  const projectedShipments = result.shipmentBatches.slice(0, 12);
  const projectedSequences = new Set(projectedShipments.map((batch) => Number(batch.sequence)));
  const projectedPlan = {
    ...result.shipmentPlan,
    planned: (result.shipmentPlan?.planned || []).filter((sequence) => projectedSequences.has(Number(sequence))),
  };
  projectedPlan.plannedQty = projectedShipments
    .filter((batch) => projectedPlan.planned.includes(Number(batch.sequence)))
    .reduce((sum, batch) => sum + Number(batch.shipNowQty || batch.executableQty || 0), 0);
  projectedPlan.truncated = (result.shipmentPlan?.planned?.length || 0) > projectedPlan.planned.length;
  return {
    id: result.id, storeId: result.storeId, store: result.store, asin: result.asin,
    title: result.title, listingStatus: result.listingStatus, asOf,
    activeScenarioId:scenario?.id||null, activeScenarioName:scenario?.name||null,
    basis: record,
    policy: result.policy,
    forecast: { daily:result.forecast.daily, baseDaily:result.forecast.baseDaily,
      scenarioMultiplier:result.forecast.scenarioMultiplier,
      seasonalActive:result.forecast.seasonalActive,
      segments:result.forecast.segments, trend:result.forecast.trend,
      momentum:result.forecast.momentum, confidence:result.forecast.confidence,
      effectiveDays:result.forecast.effectiveDays, constrainedDays:result.forecast.constrainedDays,
      volatilityLevel:result.forecast.volatilityLevel },
    timeline: { stockoutDate:result.timeline.stockoutDate,
      safetyBreachDate:result.timeline.safetyBreachDate,
      stockoutDays:result.timeline.stockoutDays, nextEta:result.timeline.nextEta,
      unknownEtaQty:result.timeline.unknownEtaQty, confirmedQty:result.timeline.confirmedQty,
      points:result.timeline.points.map(compactPoint) },
    plannedTimeline: { stockoutDate:result.plannedTimeline.stockoutDate,
      points:result.plannedTimeline.points.map(compactPoint) },
    coverage:result.coverage, inventoryLayers:result.inventoryLayers,
    shipmentBatches:projectedShipments,
    shipmentPlan:projectedPlan,
    purchaseBatches:result.purchaseBatches.slice(0,12),
    redundancy:result.redundancy, bridgePlan:result.bridgePlan,
    calc:result.calc, confidence:result.confidence, risk:result.risk,
    primaryIssue:result.primaryIssue, issues:result.issues,
    decision:result.decision, lingxingCrosscheck:result.lingxingCrosscheck,
    etaReconciliation:result.etaReconciliation,
    evidence:result.evidence, evidenceChain:result.evidenceChain,
    dataGaps:result.dataGaps, completenessFlags:result.completenessFlags,
    dataCompleteness:result.dataCompleteness, stockAllocation:result.stockAllocation,
  };
}

function main() {
  const [input, output] = process.argv.slice(2);
  if (!input || !output) throw Error('usage: node analyze_snapshot.mjs snapshot.json projection.json');
  const snapshot = JSON.parse(fs.readFileSync(input, 'utf8'));
  if (!snapshot.metadata?.asOf || !Array.isArray(snapshot.records) || !snapshot.records.length)
    throw Error('PMC snapshot has no dated records');
  const records = snapshot.records.map(record => projectForBoard(record, snapshot.metadata.asOf));
  const payload = { metadata:snapshot.metadata, records };
  fs.mkdirSync(path.dirname(output), {recursive:true});
  fs.writeFileSync(output, JSON.stringify(payload));
  console.log(JSON.stringify({asOf:snapshot.metadata.asOf, records:records.length,
    withDailyEvidence:records.filter(row=>row.forecast.effectiveDays>=7).length,
    withConfirmedEta:records.filter(row=>row.timeline.confirmedQty>0).length}));
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) main();
