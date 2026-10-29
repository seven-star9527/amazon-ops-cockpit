import { forecastDemand as forecastDemandKernel } from './demand-engine.mjs';
import {
  normalizeInventoryLayers,
  buildConfirmedEvents,
  simulateInventoryTimeline,
  calculateCoverage,
} from './timeline-engine.mjs';
import { buildSupplyPlan } from './planning-engine.mjs';

const DAY_MS = 86_400_000;

function number(value, fallback = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function round(value, digits = 1) {
  const factor = 10 ** digits;
  return Math.round((number(value) + Number.EPSILON) * factor) / factor;
}

function average(values) {
  const clean = values.map((value) => number(value)).filter((value) => value >= 0);
  return clean.length ? clean.reduce((sum, value) => sum + value, 0) / clean.length : 0;
}

function parseDate(value) {
  if (!value) return null;
  const parsed = new Date(`${String(value).slice(0, 10)}T00:00:00Z`);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function formatDate(value) {
  return value.toISOString().slice(0, 10);
}

function addDays(value, days) {
  const date = value instanceof Date ? value : parseDate(value);
  if (!date) return null;
  return new Date(date.getTime() + number(days) * DAY_MS);
}

function daysBetween(start, end) {
  const first = start instanceof Date ? start : parseDate(start);
  const second = end instanceof Date ? end : parseDate(end);
  if (!first || !second) return 0;
  return Math.round((second.getTime() - first.getTime()) / DAY_MS);
}

function coefficientOfVariation(values) {
  const mean = average(values);
  if (!mean) return 0;
  const variance = average(values.map((value) => (number(value) - mean) ** 2));
  return Math.sqrt(variance) / mean;
}

function legacyForecastDemand(history = []) {
  const clean = history.map((value) => Math.max(0, number(value))).slice(-60);
  const padded = clean.length >= 60 ? clean : [...Array(60 - clean.length).fill(0), ...clean];
  const farValues = padded.slice(0, 20);
  const middleValues = padded.slice(20, 40);
  const recentValues = padded.slice(40, 60);
  const segments = {
    far: average(farValues),
    middle: average(middleValues),
    recent: average(recentValues),
  };
  const zeroRate = clean.length ? clean.filter((value) => value === 0).length / clean.length : 1;
  const volatility = coefficientOfVariation(clean);
  let state = 'stable';
  let weights = { recent: 0.5, middle: 0.3, far: 0.2 };

  if (clean.length < 28 || zeroRate > 0.35) {
    state = 'limited';
    weights = { recent: 0.4, middle: 0.4, far: 0.2 };
  } else if (volatility > 0.55) {
    state = 'volatile';
    weights = { recent: 0.45, middle: 0.35, far: 0.2 };
  } else if (segments.middle > 0 && segments.recent >= segments.middle * 1.18) {
    state = 'growth';
    weights = { recent: 0.65, middle: 0.25, far: 0.1 };
  } else if (segments.middle > 0 && segments.recent <= segments.middle * 0.82) {
    state = 'decline';
    weights = { recent: 0.6, middle: 0.3, far: 0.1 };
  }

  const daily = round(
    segments.recent * weights.recent +
      segments.middle * weights.middle +
      segments.far * weights.far,
    1,
  );
  const confidence = clean.length >= 56 && zeroRate < 0.15 && volatility < 0.55
    ? 'high'
    : clean.length >= 28 && zeroRate < 0.35
      ? 'medium'
      : 'low';

  return {
    daily,
    state,
    weights,
    segments: Object.fromEntries(Object.entries(segments).map(([key, value]) => [key, round(value, 1)])),
    confidence,
    volatility: round(volatility, 2),
    sampleDays: clean.length,
    zeroRate: round(zeroRate, 2),
  };
}

export const forecastDemand = forecastDemandKernel;

export function simulateInventory({
  asOf,
  available,
  dailyDemand,
  safetyDays = 0,
  horizonDays = 180,
  inbound = [],
}) {
  const start = parseDate(asOf);
  if (!start) throw new Error('asOf must be YYYY-MM-DD');
  const demand = Math.max(0, number(dailyDemand));
  let stock = Math.max(0, number(available));
  const confirmed = inbound
    .filter((item) => item?.confirmed !== false && parseDate(item?.date))
    .map((item) => ({ date: String(item.date).slice(0, 10), qty: Math.max(0, number(item.qty)) }));
  const unknownEtaQty = round(
    inbound.filter((item) => !parseDate(item?.date) || item?.confirmed === false)
      .reduce((sum, item) => sum + Math.max(0, number(item?.qty)), 0),
    0,
  );
  let safetyBreachDate = null;
  let stockoutDate = null;
  const points = [{ date: formatDate(start), stock: round(stock, 1), arrivals: 0 }];

  for (let offset = 1; offset <= Math.max(1, horizonDays); offset += 1) {
    const date = addDays(start, offset);
    const dateText = formatDate(date);
    const arrivals = confirmed
      .filter((item) => item.date === dateText)
      .reduce((sum, item) => sum + item.qty, 0);
    stock += arrivals;
    stock -= demand;
    if (demand > 0 && !safetyBreachDate && stock <= demand * Math.max(0, number(safetyDays))) {
      safetyBreachDate = dateText;
    }
    if (demand > 0 && !stockoutDate && stock <= 0) stockoutDate = dateText;
    points.push({ date: dateText, stock: round(stock, 1), arrivals: round(arrivals, 0) });
  }

  const nextEta = confirmed.map((item) => item.date).sort()[0] || null;
  return {
    stockoutDate,
    safetyBreachDate,
    nextEta,
    gapBeforeNextEta: Boolean(stockoutDate && nextEta && stockoutDate < nextEta),
    unknownEtaQty,
    confidence: unknownEtaQty > 0 ? 'low' : confirmed.length ? 'high' : 'medium',
    endingStock: round(stock, 1),
    points,
  };
}

export function calculateRedundancy({
  fbaAvailable,
  dailyDemand,
  safetyDays,
  cadenceDays,
  targetQty = null,
  agedBuckets = null,
}) {
  const fallbackDays = Math.max(0, number(safetyDays)) + Math.max(0, number(cadenceDays));
  const fallbackQty = Math.ceil(Math.max(0, number(dailyDemand)) * fallbackDays);
  const resolvedTargetQty = targetQty === null || targetQty === undefined
    ? fallbackQty
    : Math.max(0, Math.ceil(number(targetQty)));
  const targetDays = Math.max(0, number(safetyDays)) + Math.max(0, number(cadenceDays));
  const estimatedRedundantQty = Math.max(0, Math.floor(number(fbaAvailable) - resolvedTargetQty));
  const actualAgedQty = agedBuckets && typeof agedBuckets === 'object'
    ? Math.max(0, number(agedBuckets.over90))
    : null;
  let label = estimatedRedundantQty > 0 ? '预计冗余' : '库存正常';
  if (actualAgedQty > 0 && estimatedRedundantQty > 0) label = '超龄且冗余';
  else if (actualAgedQty > 0) label = '存在超龄';
  return {
    targetDays,
    targetQty: resolvedTargetQty,
    estimatedRedundantQty,
    actualAgedQty,
    hasActualAgeData: actualAgedQty !== null,
    label,
  };
}

function demandSum(demandAt, baseDaily, from, to) {
  const days = Math.max(0, daysBetween(from, to));
  if (!demandAt) return number(baseDaily) * days;
  let total = 0;
  const start = parseDate(from);
  for (let offset = 1; offset <= days; offset += 1) {
    total += Math.max(0, number(demandAt(formatDate(addDays(start, offset)))));
  }
  return total;
}

function forwardDemand(demandAt, baseDaily, dateText, days) {
  return demandSum(demandAt, baseDaily, dateText, formatDate(addDays(dateText, days)));
}

function planHorizonDays({ asOf, seasonalRanges = [], transitDays = 0, targetDays = 22 }) {
  const ends = seasonalRanges
    .map((range) => daysBetween(asOf, range?.to))
    .filter((value) => value !== null && value !== undefined);
  const lastEnd = ends.length ? Math.max(...ends) : 0;
  return seasonalRanges.length ? 240 : 180;
}

/**
 * Rolling weekly shipment plan. It walks the whole horizon instead of stopping
 * after four weeks, uses a forward target per arrival, and keeps planned
 * arrivals in the stock projection so later batches can see them.
 */
export function buildRollingShipmentPlan({
  asOf,
  sellable,
  confirmedInbound = [],
  demandAt = null,
  dailyDemand,
  safetyDays = 15,
  minShipQty = 0,
  transitDays = 60,
  urgentTransitDays = null,
  normalMode = '海运',
  urgentMode = '卡航',
  airMode = '空运',
  airTransitDays = null,
  horizonDays = 180,
  maxBatches = 120,
  sourceAvailable = null,
  purchaseLeadDays = 0,
  cartonQty = 0,
  moq = 0,
  seasonalRanges = [],
}) {
  const normalDays = Math.max(0, number(transitDays, 60));
  const urgentDays = urgentTransitDays === null || urgentTransitDays === undefined
    ? normalDays
    : Math.max(0, Math.min(number(urgentTransitDays, normalDays), normalDays));
  const airDays = airTransitDays === null || airTransitDays === undefined || number(airTransitDays) <= 0
    ? null
    : Math.max(1, number(airTransitDays));
  const confirmed = confirmedInbound
    .map((event) => ({ date: String(event.etaEnd || event.date || '').slice(0, 10), qty: number(event.qty) }))
    .filter((event) => event.date);
  const planned = [];
  const batches = [];
  const purchases = [];
  const shipments = [];
  const receipts = [];
  const startDate = parseDate(asOf);
  const carton = Math.max(0, Math.floor(number(cartonQty)));
  const minOrder = Math.max(0, Math.ceil(number(moq)));
  const minShip = Math.max(0, Math.ceil(number(minShipQty)));
  const safety = Math.max(0, number(safetyDays));
  const roundUp = (qty) => (carton > 0 ? Math.ceil(qty / carton) * carton : qty);
  const dailyAt = (dateText) => Math.max(0, number(demandAt ? demandAt(dateText) : dailyDemand, dailyDemand));
  // Target = safety-stock demand + one replenishment batch. The batch is at least
  // the minimum shipment and at least one week of demand, so a small minimum
  // cannot drag the peak target below the old weekly policy.
  const targetAt = (dateText) => Math.ceil(
    forwardDemand(demandAt, dailyDemand, dateText, safety)
    + Math.max(minShip, 7 * dailyAt(dateText)),
  );
  const sourceOf = (dateText) => {
    if (sourceAvailable === null || sourceAvailable === undefined) return Infinity;
    const received = receipts.filter((receipt) => receipt.date <= dateText).reduce((sum, receipt) => sum + receipt.qty, 0);
    const shipped = shipments.filter((shipment) => shipment.date <= dateText).reduce((sum, shipment) => sum + shipment.qty, 0);
    return Math.max(0, number(sourceAvailable) + received - shipped);
  };
  const stockAt = (dateText) => {
    if (daysBetween(asOf, dateText) < 0) return number(sellable);
    const confirmedQty = confirmed.filter((event) => event.date <= dateText).reduce((sum, event) => sum + event.qty, 0);
    const plannedQty = planned.filter((event) => event.date <= dateText).reduce((sum, event) => sum + event.qty, 0);
    return number(sellable) + confirmedQty + plannedQty - demandSum(demandAt, dailyDemand, asOf, dateText);
  };
  const peakStarts = seasonalRanges.map((range) => daysBetween(asOf, range?.from)).filter((value) => value !== null);
  const peakEnds = seasonalRanges.map((range) => daysBetween(asOf, range?.to)).filter((value) => value !== null);
  const peakStart = peakStarts.length ? Math.min(...peakStarts) : null;
  const peakEnd = peakEnds.length ? Math.max(...peakEnds) : null;
  const stockoutFrom = (fromDate) => {
    for (let step = 1; step <= Math.max(0, number(horizonDays)); step += 1) {
      const day = formatDate(addDays(fromDate, step));
      if (stockAt(day) <= 0) return day;
    }
    return null;
  };
  for (let offset = 0; offset <= Math.max(0, number(horizonDays)) && batches.length < maxBatches; offset += 7) {
    const dispatch = formatDate(addDays(asOf, offset));
    const stockout = stockoutFrom(dispatch);
    const inPeakLane = peakStart !== null && offset >= peakStart - normalDays && offset <= (peakEnd ?? peakStart);
    const lanes = [];
    const pushLane = (kind, days, mode) => {
      if (days === null || days === undefined) return;
      lanes.push({ kind, mode, transit: Math.max(0, number(days)), arrival: formatDate(addDays(dispatch, Math.max(0, number(days)))) });
    };
    const canMake = (arrival) => !stockout || arrival <= stockout;
    if (inPeakLane) {
      pushLane('urgent', urgentDays, urgentMode);
      if (airDays) pushLane('air', airDays, airMode);
    } else if (canMake(formatDate(addDays(dispatch, normalDays)))) {
      pushLane('normal', normalDays, normalMode);
      pushLane('urgent', urgentDays, urgentMode);
      if (airDays) pushLane('air', airDays, airMode);
    } else {
      // Sea misses the gap: try the urgent lane first, then air. The gap before
      // the first arrival is unavoidable, but the shipment still covers later
      // demand and must not be dropped.
      pushLane('urgent', urgentDays, urgentMode);
      if (airDays) pushLane('air', airDays, airMode);
      pushLane('normal', normalDays, normalMode);
    }
    let choice = null;
    for (const lane of lanes) {
      const projected = stockAt(lane.arrival);
      const targetQty = targetAt(lane.arrival);
      const need = targetQty - projected;
      if (need <= 0) break;
      const batchFloor = minShip;
      if (need >= batchFloor) {
        choice = { lane, qty: Math.max(batchFloor, roundUp(Math.ceil(need))), need, targetQty, rescue: false, projected, timingGap: Boolean(stockout && lane.arrival > stockout) };
        break;
      }
      // Need is below the minimum: wait unless waiting would let the batch land
      // after the stockout. In that case ship the minimum now and accept the
      // temporary overshoot; the higher stock pushes the next batch later.
      const waitDays = 7;
      const waitArrival = formatDate(addDays(lane.arrival, waitDays));
      if (stockout && waitArrival >= stockout) {
        choice = { lane, qty: roundUp(batchFloor), need, targetQty, rescue: true, projected, timingGap: Boolean(stockout && lane.arrival > stockout) };
      }
      break;
    }
    if (!choice) continue;
    const { lane, qty, need, targetQty, rescue, projected, timingGap } = choice;
    const available = sourceOf(dispatch);
    const executableQty = carton > 0
      ? Math.min(qty, Math.floor(available / carton) * carton)
      : Math.min(qty, available);
    const shortfall = Math.max(0, qty - executableQty);
    let purchase = null;
    let purchaseNote = '';
    if (shortfall > 0) {
      const rawOrder = addDays(dispatch, -number(purchaseLeadDays));
      const late = rawOrder < startDate;
      if (late) {
        purchaseNote = '采购已来不及，本批不采购';
      } else {
        const orderQty = Math.max(minOrder, roundUp(shortfall));
        purchase = {
          sequence: purchases.length + 1,
          orderDate: formatDate(rawOrder),
          date: formatDate(addDays(rawOrder, number(purchaseLeadDays))),
          qty: orderQty,
          late: false,
        };
        purchase.batchSequence = batches.length + 1;
        purchase.dispatchDate = dispatch;
        purchases.push(purchase);
        receipts.push({ date: purchase.date, qty: purchase.qty });
        if (orderQty > shortfall) {
          purchaseNote = `起订量/整箱使采购 ${orderQty} 件，多于缺口 ${shortfall} 件，余量留本地`;
        }
      }
    }
    // A batch whose purchase cannot be placed and whose local stock is zero cannot
    // ship at all; recording it would create a phantom daily batch.
    if (shortfall > 0 && !purchase && executableQty <= 0) continue;
    // Future stock must include the funded batch, not only today's local quantity;
    // otherwise every following day sees the same gap and plans it again.
    const plannedStockQty = purchase ? qty : executableQty;
    if (plannedStockQty > 0) {
      shipments.push({ date: dispatch, qty: plannedStockQty });
      planned.push({ date: lane.arrival, qty: plannedStockQty });
    }
    batches.push({
      sequence: batches.length + 1,
      dispatchDate: dispatch,
      arrivalDate: lane.arrival,
      mode: lane.mode,
      lane: lane.kind,
      transitDays: lane.transit,
      suggestedQty: qty,
      rawNeed: need,
      theoreticalQty: qty,
      executableQty,
      cartons: carton > 0 ? Math.floor(executableQty / carton) : null,
      plannedCartons: carton > 0 ? Math.ceil(qty / carton) : null,
      cartonQty: carton || null,
      purchaseOrderDate: purchase?.orderDate || null,
      purchaseReadyDate: purchase?.date || null,
      purchaseQty: purchase?.qty || 0,
      purchaseLate: Boolean(purchaseNote) && !purchase,
      purchaseNote,
      rescue,
      timingGap,
      targetQty,
      targetDays: Math.max(1, safety + Math.max(7, minShip / Math.max(0.1, dailyAt(lane.arrival)))),
      batchUnitQty: carton || null,
      batchUnitSource: carton > 0 ? 'carton' : 'demand-lot',
      sourceShortageQty: shortfall,
      fundedQty: plannedStockQty,
      remainingQty: Math.max(0, qty - plannedStockQty),
      projectedBeforeArrival: round(projected, 1),
      projectedAfterArrival: round(projected + plannedStockQty, 1),
      pilot: false,
      status: batches.length === 0 ? 'actionable' : 'planning',
      fundedByPurchase: true,
    });
  }
  const grouped = new Map();
  for (const purchase of purchases) {
    const key = `${purchase.orderDate}|${purchase.date}`;
    const existing = grouped.get(key);
    if (existing) {
      existing.qty += purchase.qty;
      existing.late = existing.late || purchase.late;
    } else {
      grouped.set(key, { ...purchase });
    }
  }
  const mergedPurchases = [...grouped.values()]
    .sort((a, b) => a.orderDate.localeCompare(b.orderDate))
    .map((purchase, index) => ({ ...purchase, sequence: index + 1 }));
  return { batches, purchases: mergedPurchases };
}

export function buildPurchaseFromShipments({ asOf, shipments = [], leadDays = 45, maxRows = 12 }) {
  return shipments.slice(0, maxRows).map((batch, index) => {
    const orderDate = formatDate(addDays(batch.dispatchDate, -number(leadDays)));
    const late = orderDate < asOf;
    const earliestReadyDate = late
      ? formatDate(addDays(asOf, number(leadDays)))
      : batch.dispatchDate;
    return {
      sequence: index + 1,
      orderDate,
      expectedReadyDate: batch.dispatchDate,
      earliestReadyDate,
      suggestedQty: batch.suggestedQty,
      theoreticalQty: batch.suggestedQty,
      targetAtReady: batch.targetQty,
      late,
      coverageDays: number(leadDays),
      note: late ? `下单日已过，最早 ${earliestReadyDate} 到货` : '',
    };
  });
}

function stockBeforeDate({ asOf, date, fbaAvailable, dailyDemand, demandAt = null, inbound }) {
  const arrivals = inbound
    .filter((item) => item?.confirmed !== false && parseDate(item?.date) && String(item.date).slice(0, 10) <= formatDate(date))
    .reduce((sum, item) => sum + Math.max(0, number(item.qty)), 0);
  return number(fbaAvailable) + arrivals - demandSum(demandAt, dailyDemand, asOf, date);
}

function batchUnit(dailyDemand, cartonQty) {
  const carton = Math.floor(number(cartonQty));
  if (carton > 0) return { qty: carton, source: 'carton' };
  const monthly = Math.max(0, number(dailyDemand)) * 30;
  return { qty: monthly >= 1000 ? 100 : monthly >= 150 ? 50 : monthly >= 30 ? 20 : 10, source: 'demand_lot' };
}

function roundBatch(theoreticalQty, unit) {
  return theoreticalQty <= 0 ? 0 : Math.ceil(theoreticalQty / unit) * unit;
}

export function buildShipmentBatches({
  asOf,
  fbaAvailable,
  dailyDemand,
  demandAt = null,
  safetyDays,
  cadenceDays,
  transitDays,
  urgentTransitDays = null,
  normalMode = '海运',
  urgentMode = '卡航',
  sourceAvailable = 0,
  cartonQty = 0,
  inbound = [],
  count = 4,
  firstBatchCap = null,
}) {
  const targetQty = Math.ceil(number(dailyDemand) * (number(safetyDays) + number(cadenceDays)));
  const plannedInbound = [...inbound];
  let sourceRemaining = Math.max(0, number(sourceAvailable));
  const unit = batchUnit(dailyDemand, cartonQty);
  const batches = [];
  const normalDays = Math.max(1, number(transitDays, 60));
  const urgentDays = urgentTransitDays === null || urgentTransitDays === undefined
    ? normalDays
    : Math.max(1, number(urgentTransitDays, normalDays));

  for (let index = 0; index < Math.max(1, count); index += 1) {
    const dispatch = addDays(asOf, index * number(cadenceDays));
    const normalArrival = addDays(dispatch, normalDays);
    const urgentArrival = addDays(dispatch, urgentDays);
    // Pick the cheapest lane that still lands before the projected stockout:
    // routine batches go by sea, only batches that would arrive too late go by truck.
    const normalProjected = stockBeforeDate({
      asOf,
      date: normalArrival,
      fbaAvailable,
      dailyDemand,
      demandAt,
      inbound: plannedInbound,
    });
    const useUrgent = normalProjected <= 0;
    const arrival = useUrgent ? urgentArrival : normalArrival;
    const projectedBefore = useUrgent
      ? stockBeforeDate({ asOf, date: urgentArrival, fbaAvailable, dailyDemand, demandAt, inbound: plannedInbound })
      : normalProjected;
    const rawQty = Math.max(0, Math.ceil(targetQty - projectedBefore));
    const capped = index === 0 && firstBatchCap !== null;
    const theoreticalQty = capped ? Math.min(rawQty, Math.max(0, number(firstBatchCap))) : rawQty;
    // Without a real carton spec, quote the exact quantity instead of inventing a lot size.
    const suggestedQty = unit.source === 'carton' ? roundBatch(theoreticalQty, unit.qty) : theoreticalQty;
    // Without a real carton spec there is no reason to reject a partial lot:
    // ship whatever the source can actually cover.
    const executableQty = unit.source === 'carton'
      ? Math.min(suggestedQty, Math.floor(sourceRemaining / unit.qty) * unit.qty)
      : Math.min(suggestedQty, sourceRemaining);
    const qtyForProjection = executableQty;
    sourceRemaining -= executableQty;
    plannedInbound.push({ date: formatDate(arrival), qty: qtyForProjection, confirmed: true, planned: true });
    batches.push({
      sequence: index + 1,
      dispatchDate: formatDate(dispatch),
      arrivalDate: formatDate(arrival),
      mode: useUrgent ? urgentMode : normalMode,
      transitDays: useUrgent ? urgentDays : normalDays,
      suggestedQty,
      theoreticalQty,
      executableQty,
      cartons: unit.source === 'carton' ? suggestedQty / unit.qty : null,
      batchUnitQty: unit.qty,
      batchUnitSource: unit.source,
      sourceShortageQty: Math.max(0, suggestedQty - executableQty),
      projectedBeforeArrival: round(projectedBefore, 1),
      projectedAfterArrival: round(projectedBefore + executableQty, 1),
      targetQty,
      pilot: capped && theoreticalQty < rawQty,
      status: index === 0 ? 'actionable' : 'planning',
    });
  }
  return batches;
}

export function buildPurchaseBatches({
  asOf,
  dailyDemand,
  demandAt = null,
  purchaseLeadDays,
  cadenceDays,
  safetyDays,
  transitDays = 0,
  pipelineSupply,
  effectiveInventory,
  cartonQty = 0,
  count = 3,
}) {
  const demand = Math.max(0, number(dailyDemand));
  const cadence = Math.max(1, number(cadenceDays));
  // The local layer must cover the full pipeline: buy -> produce -> sea -> FBA.
  const coverageDays = Math.max(1, number(purchaseLeadDays) + number(transitDays) + number(safetyDays));
  const targetAtReady = Math.ceil(demand * coverageDays);
  const supply = pipelineSupply === undefined || pipelineSupply === null
    ? number(effectiveInventory)
    : number(pipelineSupply);
  const unit = batchUnit(demand, cartonQty);
  const plannedReceipts = [];
  const batches = [];
  for (let index = 0; index < Math.max(1, count); index += 1) {
    const orderDate = addDays(asOf, index * cadence);
    const expectedReadyDate = addDays(orderDate, number(purchaseLeadDays));
    const elapsedDays = Math.max(0, daysBetween(asOf, expectedReadyDate));
    const receiptsByReady = plannedReceipts
      .filter((receipt) => receipt.date <= formatDate(expectedReadyDate))
      .reduce((sum, receipt) => sum + receipt.qty, 0);
    const projectedBeforeReady = supply - demandSum(demandAt, demand, asOf, expectedReadyDate) + receiptsByReady;
    const theoreticalQty = Math.max(0, Math.ceil(targetAtReady - projectedBeforeReady));
    const suggestedQty = unit.source === 'carton' ? roundBatch(theoreticalQty, unit.qty) : theoreticalQty;
    plannedReceipts.push({ date: formatDate(expectedReadyDate), qty: suggestedQty });
    batches.push({
      sequence: index + 1,
      orderDate: formatDate(orderDate),
      expectedReadyDate: formatDate(expectedReadyDate),
      suggestedQty,
      theoreticalQty,
      cartons: unit.source === 'carton' ? suggestedQty / unit.qty : null,
      batchUnitQty: unit.qty,
      batchUnitSource: unit.source,
      projectedBeforeReady: round(projectedBeforeReady, 1),
      targetAtReady,
      coverageDays,
      status: index === 0 ? 'actionable' : 'planning',
    });
  }
  return batches;
}

/**
 * UI-facing shipment phase adapter.
 *
 * The calculation engine decides quantities and lanes. This adapter only turns the
 * temporal batches into an explicit contract for the cockpit:
 * - immediate: dispatch date is the analysis date and fundedQty > 0
 * - planned: future fundedQty > 0 (including purchase-funded batches)
 * - unavailable: no funded quantity
 *
 * It never changes quantities or order. Consumers must use this view instead of
 * searching the raw batch array.
 */
export function buildShipmentPlanView(batches = [], purchases = [], asOf = null) {
  const asOfText = String(asOf || "").slice(0, 10);
  const annotated = batches.map((batch) => {
    const fundedQty = Math.max(0, number(batch.fundedQty ?? batch.executableQty));
    const dispatch = String(batch.dispatchDate || "").slice(0, 10);
    const immediate = Boolean(asOfText && dispatch === asOfText && fundedQty > 0);
    const phase = immediate ? "immediate" : fundedQty > 0 ? "planned" : "unavailable";
    // New engine batches carry purchaseQty/purchaseReadyDate. Keep a fallback for
    // older projected batches and unit fixtures that only carry a purchase list.
    const hasPurchaseFields = batch.purchaseQty !== undefined || batch.purchaseOrderDate !== undefined;
    const legacyPurchase = !hasPurchaseFields
      ? purchases
        .map((purchase) => String(purchase.expectedReadyDate || purchase.date || "").slice(0, 10))
        .filter((date) => date && date <= dispatch)
        .sort()
        .at(-1)
      : null;
    const purchaseFunded = !immediate && (Number(batch.purchaseQty) > 0 || Boolean(legacyPurchase));
    const funding = purchaseFunded ? "purchase" : "local";
    const availableAt = purchaseFunded
      ? (String(batch.purchaseReadyDate || batch.purchaseOrderDate || legacyPurchase || "").slice(0, 10) || null)
      : (asOfText || dispatch || null);
    return {
      ...batch,
      phase,
      funding,
      actionableNow: immediate,
      availableAt,
      needQty: Math.max(0, number(batch.suggestedQty)),
      shipNowQty: fundedQty,
      fundedQty,
      remainingQty: Math.max(0, number(batch.remainingQty ?? (number(batch.suggestedQty) - fundedQty))),
    };
  });
  const immediate = annotated.find((batch) => batch.phase === "immediate") || null;
  const planned = annotated.filter((batch) => batch.phase === "planned");
  return {
    batches: annotated,
    immediate,
    planned,
    next: immediate || planned[0] || null,
    immediateQty: immediate ? immediate.shipNowQty : 0,
    plannedQty: planned.reduce((sum, batch) => sum + batch.shipNowQty, 0),
  };
}

export function analyzeInventoryRecord(record, options = {}) {
  const asOf = options.asOf || record.asOf;
  if (!asOf) throw new Error('record analysis requires asOf');
  const seasonalRanges = Array.isArray(options.seasonal)
    ? options.seasonal
    : (Array.isArray(record.seasonal) ? record.seasonal : []);
  // A date-ranged season already defines the multiplier per day; a constant
  // multiplier on top would double count, so the range wins.
  const scenarioMultiplier = seasonalRanges.length
    ? 1
    : Math.max(0.1, number(options.scenarioMultiplier, 1));
  const demandBase = forecastDemand(record.history || []);
  const forecast = {
    ...demandBase,
    baseDaily: demandBase.daily,
    daily: round(demandBase.daily * scenarioMultiplier, 1),
    scenarioMultiplier,
  };
  const isActiveListing = record.listingStatus === undefined || record.listingStatus === null
    ? true
    : number(record.listingStatus, 1) === 1;
  const planningDaily = isActiveListing ? forecast.daily : 0;
  forecast.planningDaily = planningDaily;
  const seasonalMultiplierAt = (dateText) => {
    const target = parseDate(dateText);
    if (!target) return 1;
    for (const range of seasonalRanges) {
      const from = parseDate(range?.from);
      const to = parseDate(range?.to);
      if (from && to && target >= from && target <= to) {
        return Math.max(0, number(range?.multiplier, 1));
      }
    }
    return 1;
  };
  const demandAt = seasonalRanges.length
    ? (dateText) => number(forecast.baseDaily, planningDaily) * seasonalMultiplierAt(dateText)
    : null;
  forecast.seasonalActive = Boolean(demandAt);
  forecast.demandAt = demandAt;
  let seasonalPeak = planningDaily;
  let seasonalPeakDate = null;
  if (demandAt) {
    for (let offset = 0; offset <= 180; offset += 1) {
      const dayText = formatDate(addDays(asOf, offset));
      const value = number(demandAt(dayText), planningDaily);
      if (value > seasonalPeak) {
        seasonalPeak = value;
        seasonalPeakDate = dayText;
      }
    }
  }
  forecast.seasonalPeak = round(seasonalPeak, 1);
  forecast.seasonalPeakDate = seasonalPeakDate;
  const safetyDays = Math.max(0, number(options.safetyDays ?? record.safetyDays, 15));
  const cadenceDays = Math.max(1, number(options.cadenceDays ?? record.cadenceDays, 7));
  const transitDays = Math.max(0, number(options.transitDays ?? record.transitDays, 60));
  const expressRequested = Math.max(1, number(
    options.expressTransitDays ?? record.expressTransitDays ?? record.expediteTransitDays,
    30,
  ));
  // The urgent lane must never be slower than the routine lane for the same SKU.
  const expressTransitDays = transitDays > 0 ? Math.min(expressRequested, transitDays) : expressRequested;
  const normalMode = record.transitMode || '海运';
  const expressMode = record.expressMode || '卡航';
  const purchaseLeadDays = Math.max(0, number(options.purchaseLeadDays ?? record.purchaseLeadDays, 40));
  const airTransitDays = options.airTransitDays ?? record.airTransitDays ?? null;
  const purchaseCadenceDays = Math.max(1, number(options.purchaseCadenceDays ?? record.purchaseCadenceDays, 28));
  const inventoryLayers = normalizeInventoryLayers(record);
  const fbaAvailable = inventoryLayers.sellable;
  const localOverrideRaw = options.localAvailable ?? record.localAvailableOverride ?? null;
  const hasLocalOverride = localOverrideRaw !== null && localOverrideRaw !== undefined && localOverrideRaw !== '';
  const localOverride = hasLocalOverride ? Math.max(0, number(localOverrideRaw)) : null;
  const sourceAvailable = localOverride !== null
    ? localOverride
    : Math.max(0, number(record.sourceAvailable, inventoryLayers.local + inventoryLayers.overseas));
  const cartonQty = Math.max(0, Math.floor(number(options.cartonQty ?? record.cartonQty)));
  const moqQty = Math.max(0, Math.ceil(number(options.moq ?? record.moq, 0)));
  const minShipQty = Math.max(0, Math.ceil(number(options.minShipQty ?? record.minShipQty, 0)));
  const etaResolution = buildConfirmedEvents(record);
  const inbound = etaResolution.events.map((event) => ({
    ...event,
    date: event.etaEnd,
    confirmed: true,
  }));
  const minShipUnits = minShipQty;
  const dailyAt = (dateText) => Math.max(0, number(demandAt ? demandAt(dateText) : planningDaily, planningDaily));
  // Target = safety-stock demand + one batch. The batch is at least the minimum
  // shipment and at least one week of demand, so the peak target is not dragged
  // down by a small minimum shipment.
  const batchUnitsAt = (dateText) => Math.max(minShipUnits, 7 * dailyAt(dateText));
  const targetAt = (dateText) => Math.ceil(
    forwardDemand(demandAt, planningDaily, dateText, safetyDays) + batchUnitsAt(dateText),
  );
  const targetDays = Math.max(1, safetyDays + Math.max(7, minShipUnits / Math.max(0.1, planningDaily)));
  const horizonDays = planHorizonDays({ asOf, seasonalRanges, transitDays, targetDays });
  const timeline = simulateInventoryTimeline({
    asOf,
    dailyDemand: planningDaily,
    demandAt,
    sellable: fbaAvailable,
    safetyDays,
    horizonDays,
    confirmedEvents: etaResolution.events,
    unknownEtaQty: etaResolution.unknownEtaQty,
  });
  const coverage = calculateCoverage(inventoryLayers, planningDaily, timeline);
  const currentTarget = targetAt(asOf);
  let targetPeak = currentTarget;
  let targetPeakDate = asOf;
  for (let offset = 0; offset <= horizonDays; offset += 1) {
    const day = formatDate(addDays(asOf, offset));
    const value = targetAt(day);
    if (value > targetPeak) {
      targetPeak = value;
      targetPeakDate = day;
    }
  }
  const redundancy = calculateRedundancy({
    fbaAvailable,
    dailyDemand: Math.max(1, currentTarget / targetDays),
    safetyDays,
    cadenceDays,
    targetQty: currentTarget,
    agedBuckets: record.agedBuckets,
  });
  const pilotQtyCap = forecast.effectiveDays < 7 && planningDaily > 0
    ? Math.max(1, Math.ceil(planningDaily * 7))
    : null;
  const rollingPlan = buildRollingShipmentPlan({
    asOf,
    sellable: fbaAvailable,
    confirmedInbound: etaResolution.events,
    demandAt,
    dailyDemand: planningDaily,
    safetyDays,
    minShipQty: minShipUnits,
    transitDays,
    urgentTransitDays: expressTransitDays,
    normalMode,
    urgentMode: expressMode,
    horizonDays,
    sourceAvailable,
    purchaseLeadDays,
    cartonQty,
    moq: moqQty,
    minShipQty,
    seasonalRanges,
    airTransitDays,
  });
  const rolling = rollingPlan.batches;
  const shipmentBatches = rolling.map((batch, index) => {
    if (index !== 0 || !pilotQtyCap) return batch;
    const qty = Math.min(batch.executableQty, pilotQtyCap);
    return { ...batch, suggestedQty: qty, theoreticalQty: qty, executableQty: qty, pilot: true };
  });
  const confirmedInboundQty = etaResolution.confirmedQty;
  const effectiveInventory = fbaAvailable + inventoryLayers.receiving + confirmedInboundQty
    + sourceAvailable + inventoryLayers.procurementOpen;
  const localPipeline = inventoryLayers.local + inventoryLayers.overseas + inventoryLayers.procurementOpen;
  // Conservative purchase: local stock and open POs are SKU-level and may belong
  // to another store, so they are shown as reference but never reduce the order.
  const purchaseBatches = rollingPlan.purchases.slice(0, 12).map((purchase) => ({
    sequence: purchase.sequence,
    batchSequence: purchase.batchSequence ?? null,
    dispatchDate: purchase.dispatchDate ?? null,
    orderDate: purchase.orderDate,
    expectedReadyDate: purchase.date,
    earliestReadyDate: purchase.date,
    suggestedQty: purchase.qty,
    theoreticalQty: purchase.qty,
    cartons: cartonQty > 0 ? Math.ceil(purchase.qty / cartonQty) : null,
    targetAtReady: null,
    late: false,
    coverageDays: purchaseLeadDays,
    note: '',
  }));
  const planView = buildShipmentPlanView(shipmentBatches, purchaseBatches, asOf);
  const shipmentPlan = {
    immediate: planView.immediate?.sequence ?? null,
    planned: planView.planned.map((batch) => batch.sequence),
    next: planView.next?.sequence ?? null,
    immediateQty: planView.immediateQty,
    plannedQty: planView.plannedQty,
  };
  const plannedTimeline = simulateInventoryTimeline({
    asOf,
    dailyDemand: planningDaily,
    demandAt,
    sellable: fbaAvailable,
    safetyDays,
    horizonDays,
    confirmedEvents: [
      ...etaResolution.events,
      ...shipmentBatches.filter((batch) => Number(batch.fundedQty ?? batch.executableQty) > 0).map((batch) => ({
        id: `PLAN-${batch.sequence}`,
        shipment: null,
        etaStart: batch.arrivalDate,
        etaEnd: batch.arrivalDate,
        qty: Number(batch.fundedQty ?? batch.executableQty),
        source: '建议发货批次（未执行）',
        status: 'planned',
      })),
    ],
    unknownEtaQty: etaResolution.unknownEtaQty,
  });
  const stockoutDays = timeline.stockoutDate ? daysBetween(asOf, timeline.stockoutDate) : null;
  const fbaCoverageDays = coverage.sellableDays;
  const stockoutDate = timeline.stockoutDate ? parseDate(timeline.stockoutDate) : null;
  const nextSupplyDate = timeline.nextEta ? parseDate(timeline.nextEta) : null;
  const nextSupplyEvent = timeline.events[0] || null;
  // A gap only matters when even a normal sea shipment sent today would land after the
  // stockout. If there is still a full transit window left, the rolling batches cover it.
  const hasGap = Boolean(stockoutDate
    && stockoutDays !== null
    && stockoutDays < transitDays
    && (!nextSupplyDate || stockoutDate < nextSupplyDate));
  const gapEndDate = nextSupplyDate || (stockoutDate ? addDays(stockoutDate, cadenceDays) : null);
  const bridgeGapDays = hasGap ? Math.max(1, daysBetween(stockoutDate, gapEndDate)) : 0;
  const bridgeTheoreticalQty = hasGap ? Math.max(0, Math.ceil(bridgeGapDays * forecast.daily)) : 0;
  const bridgeBufferQty = hasGap ? Math.max(0, Math.ceil(safetyDays * forecast.daily)) : 0;
  const bridgeUnit = Math.max(1, Number(shipmentBatches[0]?.batchUnitQty) || 1);
  const bridgeQty = roundBatch(bridgeTheoreticalQty, bridgeUnit);
  const firstBatch = shipmentBatches.find((batch) => batch.dispatchDate === asOf) || null;
  const firstBatchArrival = firstBatch?.arrivalDate ? parseDate(firstBatch.arrivalDate) : null;
  const earliestArrival = addDays(asOf, expressTransitDays);
  // The first shipment and the bridge are the same physical dispatch, so the bridge is
  // never a separate order. It is "actionable" only when the first batch can still land
  // before supply resumes and actually has stock to move.
  const bridgeStatus = !hasGap
    ? 'not_needed'
    : sourceAvailable <= 0
      ? 'no_source'
      : nextSupplyDate && earliestArrival >= nextSupplyDate
        ? 'no_benefit'
        : !firstBatch || firstBatch.executableQty <= 0
          ? (sourceAvailable > 0 ? 'no_benefit' : 'no_source')
          : firstBatch.mode === expressMode
            ? (firstBatchArrival && firstBatchArrival <= stockoutDate ? 'ready' : 'partial')
            : 'no_benefit';
  const bridgeActionable = bridgeStatus === 'ready' || bridgeStatus === 'partial';
  const apiProcurement = Boolean(record.purchaseEvidence);
  const datedProcurement = (record.procurementLots || []).filter(lot => Number(lot.qty) > 0 && parseDate(lot.date) && lot.date >= asOf).sort((a,b)=>a.date.localeCompare(b.date));
  const procurementReadyDate = apiProcurement
    ? (datedProcurement[0] ? parseDate(datedProcurement[0].date) : null)
    : addDays(asOf, purchaseLeadDays);
  const reliefCandidates = [
    ...(bridgeActionable && firstBatchArrival ? [{ date: firstBatchArrival, source: expressMode }] : []),
    ...(nextSupplyDate ? [{ date: nextSupplyDate, source: '确认在途' }] : []),
    ...(!apiProcurement && inventoryLayers.procurementOpen > 0 ? [{ date: procurementReadyDate, source: '采购齐套' }] : []),
  ];
  reliefCandidates.sort((a, b) => a.date - b.date);
  const earliestRelief = reliefCandidates[0] || null;
  const earliestReliefDate = earliestRelief?.date || null;
  const daysToRelief = earliestReliefDate ? Math.max(1, daysBetween(asOf, earliestReliefDate)) : 0;
  const controlDaily = hasGap && daysToRelief > 0 && fbaAvailable > 0
    ? Math.floor((fbaAvailable / daysToRelief) * 10) / 10
    : null;
  const uncoveredDays = !hasGap
    ? null
    : bridgeStatus === 'ready'
      ? 0
      : bridgeStatus === 'partial'
        ? nextSupplyDate
          ? Math.max(0, daysBetween(firstBatchArrival, gapEndDate))
          : Math.max(0, daysBetween(stockoutDate, firstBatchArrival))
        : bridgeGapDays;
  const bridgePlan = {
    required: hasGap,
    actionable: bridgeActionable,
    qty: firstBatch?.executableQty || 0,
    theoreticalQty: bridgeTheoreticalQty,
    bufferQty: bridgeBufferQty,
    coversDays: forecast.daily > 0 && firstBatch?.executableQty
      ? round(firstBatch.executableQty / forecast.daily, 1)
      : null,
    batchUnitQty: bridgeUnit,
    batchUnitSource: shipmentBatches[0]?.batchUnitSource || null,
    expressMode,
    expediteTransitDays: expressTransitDays,
    dispatchDate: bridgeActionable ? String(asOf).slice(0, 10) : null,
    arrivalDate: bridgeActionable ? (firstBatch?.arrivalDate || formatDate(earliestArrival)) : formatDate(earliestArrival),
    latestArrivalDate: bridgeStatus === 'ready' ? (firstBatch?.arrivalDate || null) : (timeline.stockoutDate || null),
    executableQty: firstBatch?.executableQty || 0,
    sourceShortageQty: Math.max(0, (firstBatch?.suggestedQty || 0) - (firstBatch?.executableQty || 0)),
    earliestReliefDate: earliestReliefDate ? formatDate(earliestReliefDate) : null,
    reliefSource: earliestRelief?.source || null,
    procurementReadyDate: procurementReadyDate ? formatDate(procurementReadyDate) : null,
    gapDays: bridgeGapDays,
    uncoveredDays,
    controlDaily,
    status: bridgeStatus,
  };
  let risk = 'healthy';
  let nextAction = `库存覆盖 ${fbaCoverageDays ?? '—'} 天，按 ${cadenceDays} 天节奏复核`;
  if (!isActiveListing) {
    const residualSupply = fbaAvailable + inventoryLayers.receiving + confirmedInboundQty
      + timeline.unknownEtaQty + sourceAvailable + inventoryLayers.procurementOpen;
    if (residualSupply > 0) {
      risk = 'overstock';
      nextAction = `非在售：停止补货，处理剩余供应 ${round(residualSupply, 0)} 件`;
    } else {
      nextAction = '非在售且无库存：保持不补货，无需发货或采购';
    }
  } else if (hasGap) {
    risk = 'critical';
    const stockoutLabel = stockoutDays !== null && stockoutDays <= 0
      ? `已在 ${timeline.stockoutDate} 断货`
      : `预计 ${timeline.stockoutDate} 断货`;
    const nextSupplyText = nextSupplyEvent
      ? `下一票 ${nextSupplyEvent.shipment || nextSupplyEvent.id} ${timeline.nextEta} 到 ${round(nextSupplyEvent.qty, 0)} 件`
      : '没有已确认的下一票';
    if (bridgePlan.status === 'ready') {
      nextAction = `${stockoutLabel}；首批今日发${expressMode} ${bridgePlan.executableQty} 件，${bridgePlan.arrivalDate} 到仓，赶在断货前`;
    } else if (bridgePlan.status === 'partial') {
      const gapText = nextSupplyDate
        ? `，缺口从 ${bridgePlan.gapDays} 天缩到 ${bridgePlan.uncoveredDays} 天`
        : `，断档 ${bridgePlan.uncoveredDays} 天到恢复`;
      nextAction = `${stockoutLabel}；首批今日发${expressMode} ${bridgePlan.executableQty} 件，${bridgePlan.arrivalDate} 到仓${gapText}；${nextSupplyText}`;
    } else if (bridgePlan.status === 'no_benefit') {
      nextAction = `${stockoutLabel}；${nextSupplyText}，断档 ${bridgePlan.gapDays} 天；今天发货最快 ${bridgePlan.arrivalDate} 才到（${expressMode} ${expressTransitDays} 天），赶不上，不建议新发；建议催这票提前或改空运`;
    } else {
      const approval = apiProcurement
        ? (procurementReadyDate ? `采购预计 ${formatDate(procurementReadyDate)} 到自有仓（非 FBA 到仓）` : '采购未结缺可用预计到自有仓日期，不能推算齐套')
        : inventoryLayers.procurementOpen > 0
        ? `采购未结 ${round(inventoryLayers.procurementOpen, 0)} 件按 ${purchaseLeadDays} 天推算 ${bridgePlan.procurementReadyDate} 齐套`
        : `无在途采购，按 ${purchaseLeadDays} 天推算 ${bridgePlan.procurementReadyDate} 齐套`;
      nextAction = `${stockoutLabel}；本地与海外仓可发 0 件，断档 ${bridgePlan.gapDays} 天；${nextSupplyText}；${approval}，建议催单或改空运`;
    }
  } else if ((shipmentBatches[0]?.executableQty || 0) > 0) {
    risk = 'warning';
    nextAction = `按目标：${shipmentBatches[0].dispatchDate} 发 ${shipmentBatches[0].executableQty} 件（${shipmentBatches[0].mode}），${shipmentBatches[0].arrivalDate} 到仓；目标 ${redundancy.targetQty} 件`;
  } else if ((purchaseBatches[0]?.suggestedQty || 0) > 0) {
    risk = 'procurement';
    nextAction = `本地不足：${purchaseBatches[0].orderDate} 下采购 ${purchaseBatches[0].suggestedQty} 件（${purchaseLeadDays} 天），${purchaseBatches[0].expectedReadyDate} 齐套`;
  } else if (redundancy.estimatedRedundantQty > redundancy.targetQty * 0.5 || redundancy.actualAgedQty > 0) {
    risk = 'overstock';
    nextAction = `暂停新增补货，优先消化预计冗余 ${redundancy.estimatedRedundantQty} 件`;
  } else if ((shipmentBatches[0]?.sourceShortageQty || 0) > 0) {
    risk = 'procurement';
    nextAction = `源头缺口 ${shipmentBatches[0].sourceShortageQty} 件，需先补本地库存`;
  }
  if (isActiveListing && shipmentBatches[0]?.pilot && pilotQtyCap !== null) {
    nextAction = `${nextAction}（有效样本仅 ${forecast.effectiveDays} 天，首批按 7 天用量 ${pilotQtyCap} 件试点，补足销量样本后复核）`;
  }

  const sourceCompleteness = number(record.dataCompleteness, 70);
  const residualSupply = fbaAvailable + inventoryLayers.receiving + confirmedInboundQty
    + timeline.unknownEtaQty + sourceAvailable + inventoryLayers.procurementOpen;
  const supplyPlan = buildSupplyPlan({
    active: isActiveListing,
    residualSupply,
    timeline,
    forecast,
    bridgePlan,
    shipmentBatches,
    purchaseBatches,
    redundancy,
    dataCompleteness: sourceCompleteness,
    batchUnitSource: cartonQty > 0 ? 'carton' : 'demand_lot',
  });
  const linkedPurchaseBatches = supplyPlan.purchaseBatches;
  const confidence = supplyPlan.confidence.overall;

  const officialDaily = number(record.lingxingSuggestion?.estimatedDaily, 0);
  const lingxingCrosscheck = {
    officialDaily: officialDaily || null,
    dailyVariancePct: officialDaily > 0 ? round(((forecast.daily - officialDaily) / officialDaily) * 100, 1) : null,
    officialStockoutDate: record.lingxingSuggestion?.stockoutDate || null,
    officialSendDate: record.lingxingSuggestion?.suggestSendDate || null,
    officialSendQty: number(record.lingxingSuggestion?.suggestSendQty, 0),
    officialPurchaseDate: record.lingxingSuggestion?.suggestPurchaseDate || null,
    officialPurchaseQty: number(record.lingxingSuggestion?.suggestPurchaseQty, 0),
  };
  const demandFact = isActiveListing
    ? `预测日均 ${forecast.daily} 件（近7/30/60天：${forecast.segments.recent}/${forecast.segments.middle}/${forecast.segments.far}）`
    : `Listing非在售；历史预测日均 ${forecast.daily} 件仅作参考，发货与采购计划日均按0处理`;
  const inventoryFact = `FBA可售 ${fbaAvailable} 件，覆盖 ${fbaCoverageDays ?? '—'} 天；客户订单预留 ${inventoryLayers.reservedCustomerOrders} 件；FC调仓 ${inventoryLayers.fcTransfers} 件`;
  const etaFact = timeline.nextEta
    ? `确认ETA ${timeline.nextEta}，确认在途 ${round(confirmedInboundQty, 0)} 件；未知ETA ${timeline.unknownEtaQty} 件不推迟断货日`
    : `没有可进入时间轴的确认ETA；未知ETA在途 ${timeline.unknownEtaQty} 件不推迟断货日`;
  const shipmentFact = shipmentBatches[0]
    ? `首批建议 ${shipmentBatches[0].suggestedQty} 件，可执行 ${shipmentBatches[0].executableQty} 件，源头缺口 ${shipmentBatches[0].sourceShortageQty} 件`
    : '测算期内不再需要新发货';
  const purchaseFact = purchaseBatches[0]
    ? `采购周期 ${purchaseLeadDays} 天；首批采购 ${purchaseBatches[0].suggestedQty} 件，预计齐套 ${purchaseBatches[0].expectedReadyDate}`
    : `采购周期 ${purchaseLeadDays} 天；测算期内不需要采购`;
  const reason = `${demandFact}；${inventoryFact}；${etaFact}；${shipmentFact}；${purchaseFact}。`;
  const evidenceChain = [
    ...(Array.isArray(record.evidence) ? record.evidence : []),
    { stage: '需求判断', source: record.forecastSource || '销量历史', fact: demandFact },
    { stage: 'FBA风险', source: '领星实时库存 + 库存时间轴', fact: `${inventoryFact}；预计断货 ${timeline.stockoutDate || '模拟期外'}` },
    { stage: 'ETA校验', source: '领星实时在途 + 货件ETA台账', fact: etaFact },
    { stage: '发货计算', source: `日均×(${safetyDays}天安全库存+${cadenceDays}天批次)`, fact: shipmentFact },
    { stage: '采购计算', source: `采购周期${purchaseLeadDays}天 + ${purchaseCadenceDays}天滚动批次`, fact: purchaseFact },
    { stage: '结论', source: '上述证据链自动决策', fact: nextAction },
  ];
  const decision = {
    risk,
    conclusion: nextAction,
    reason,
    evidenceCompleteness: sourceCompleteness,
    actionDate: risk === 'procurement' ? linkedPurchaseBatches[0]?.orderDate : shipmentBatches[0]?.dispatchDate,
    actionQty: risk === 'procurement' ? (linkedPurchaseBatches[0]?.suggestedQty || 0) : (shipmentBatches[0]?.executableQty || 0),
  };

  const targetFba = currentTarget;
  const targetLocal = purchaseBatches[0]?.suggestedQty ?? 0;
  const supplyFba = fbaAvailable + inventoryLayers.receiving + confirmedInboundQty;
  const gapFba = Math.max(0, targetFba - supplyFba);
  const gapLocal = Math.max(0, targetLocal - localPipeline);
  const revenue30 = Math.max(0, number(record.revenue30));
  const dailyRevenue = revenue30 > 0
    ? revenue30 / 30
    : Math.max(0, number(record.price)) * planningDaily;
  const stockoutDuration = timeline.stockoutDays || 0;
  const lossAmount = round(dailyRevenue * stockoutDuration, 0);
  const agedQty = Math.max(0, number(record.agedBuckets?.over90));
  const agedValue = round(agedQty * Math.max(0, number(record.price) || (planningDaily > 0 ? dailyRevenue / planningDaily : 0)), 0);
  // Conservative purchase plan: every planned shipment is backed by an order
  // placed `purchaseLeadDays` earlier. Local stock and open POs are shown as
  // reference but never deducted, because they are SKU-level.
  const openPurchaseBatches = purchaseBatches.filter((batch) => batch.suggestedQty > 0);
  const localLedger = openPurchaseBatches.slice(0, 6).map((batch) => ({
    date: batch.orderDate,
    label: batch.late ? `第${batch.sequence}批 · 下单日已过` : `第${batch.sequence}批下单`,
    delta: batch.suggestedQty,
    readyDate: batch.expectedReadyDate,
    late: batch.late,
  }));
  const localRunoutDate = null;
  const latestOrderDate = openPurchaseBatches[0]?.orderDate || null;
  return {
    ...record,
    policy: { safetyDays, cadenceDays, transitDays, expressTransitDays, normalMode, expressMode, purchaseLeadDays, purchaseCadenceDays },
    calc: {
      daily: planningDaily,
      coverageFbaDays: targetDays,
      coverageLocalDays: purchaseLeadDays + transitDays + targetDays,
      targetFba,
      targetLocal,
      supplyFba: round(supplyFba, 0),
      supplyLocal: round(localPipeline, 0),
      gapFba,
      gapLocal,
      localOverride,
      fbaParts: {
        sellable: fbaAvailable,
        receiving: inventoryLayers.receiving,
        confirmedInbound: round(confirmedInboundQty, 0),
      },
      localParts: {
        local: inventoryLayers.local,
        overseas: inventoryLayers.overseas,
        procurementOpen: inventoryLayers.procurementOpen,
      },
      purchaseNote: openPurchaseBatches.length
        ? `保守口径：首批 ${targetLocal} 件，${purchaseBatches[0].orderDate} 下单、${purchaseBatches[0].expectedReadyDate} 到货；本地与在途不抵扣`
        : '保守口径下测算期内不需要采购',
      conservativePurchase: true,
      targetPeak,
      targetPeakDate,
      targetDays,
      minShipQty: minShipUnits,
      horizonDays,
      horizonEnd: formatDate(addDays(asOf, horizonDays)),
      dailyRevenue: round(dailyRevenue, 1),
      revenue30: round(revenue30, 0),
      lossAmount,
      stockoutDuration,
      agedQty,
      agedValue,
    },
    localPlan: {
      plan: openPurchaseBatches.slice(0, 6),
      ledger: localLedger,
      runoutDate: localRunoutDate,
      latestOrderDate,
      conservative: true,
      reference: {
        local: inventoryLayers.local,
        overseas: inventoryLayers.overseas,
        procurementOpen: inventoryLayers.procurementOpen,
      localOverride,
      },
    },
    priorityTier: record.priorityTier || 'P2',
    revenueRank: record.revenueRank || null,
    revenueShare: record.revenueShare || null,
    forecast,
    inventoryLayers,
    coverage,
    timeline,
    plannedTimeline,
    redundancy,
    shipmentBatches: planView.batches,
    shipmentPlan,
    purchaseBatches: linkedPurchaseBatches,
    bridgePlan,
    confirmedInboundQty: round(confirmedInboundQty, 0),
    etaReconciliation: record.etaReconciliation || null,
    ledgerTrimmedQty: etaResolution.trimmedQty,
    ledgerUnmatchedQty: etaResolution.unmatchedLedgerQty,
    procurement: {
      openQty: inventoryLayers.procurementOpen,
      readyDate: procurementReadyDate ? formatDate(procurementReadyDate) : null,
      sourceAvailable: round(sourceAvailable, 0),
    },
    effectiveInventory: round(effectiveInventory, 0),
    fbaCoverageDays,
    stockoutDays,
    risk,
    primaryIssue: supplyPlan.primaryIssue,
    issues: supplyPlan.issues,
    nextAction,
    confidence,
    confidenceDimensions: supplyPlan.confidence,
    evidenceChain,
    decision,
    lingxingCrosscheck,
  };
}

export const inventoryEngineUtils = { addDays, formatDate, parseDate, round };
