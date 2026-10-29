const DAY_MS = 86_400_000;

const number = (value, fallback = 0) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
};

const round = (value, digits = 1) => {
  const factor = 10 ** digits;
  return Math.round((number(value) + Number.EPSILON) * factor) / factor;
};

const parseDate = (value) => {
  if (!value) return null;
  const parsed = new Date(`${String(value).slice(0, 10)}T00:00:00Z`);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
};

const formatDate = (value) => value.toISOString().slice(0, 10);

const addDays = (value, days) => {
  const date = value instanceof Date ? value : parseDate(value);
  return date ? new Date(date.getTime() + number(days) * DAY_MS) : null;
};

export function normalizeInventoryLayers(record = {}) {
  const source = record.inventoryLayers || {};
  return {
    sellable: Math.max(0, number(source.sellable, record.fbaAvailable)),
    reservedCustomerOrders: Math.max(0, number(source.reservedCustomerOrders, record.reservedCustomerOrders ?? record.fbaReserved)),
    fcTransfers: Math.max(0, number(source.fcTransfers, record.reservedFcTransfers)),
    fcProcessing: Math.max(0, number(source.fcProcessing, record.reservedFcProcessing)),
    receiving: Math.max(0, number(source.receiving, record.fbaInboundReceiving)),
    shippedRaw: Math.max(0, number(source.shippedRaw, record.fbaInboundLive)),
    local: Math.max(0, number(source.local, record.localAvailable)),
    overseas: Math.max(0, number(source.overseas, record.overseasAvailable)),
    procurementOpen: Math.max(0, number(source.procurementOpen, record.procurementOpen)),
  };
}

export function buildConfirmedEvents(record = {}) {
  const layers = normalizeInventoryLayers(record);
  const inbound = Array.isArray(record.inbound) ? record.inbound : [];
  const candidates = inbound
    .filter((item) => item?.confirmed !== false && (item?.etaEnd || item?.date || item?.etaStart))
    .map((item, index) => ({
      id: item.id || item.shipment || item.shipmentId || `ETA-${index + 1}`,
      shipment: item.shipment || item.shipmentId || null,
      etaStart: String(item.etaStart || item.date || item.etaEnd).slice(0, 10),
      etaEnd: String(item.etaEnd || item.date || item.etaStart).slice(0, 10),
      qty: Math.max(0, number(item.qty ?? item.remainingQty)),
      source: item.source || 'ETA货件台账',
      status: item.status || null,
    }))
    .filter((item) => parseDate(item.etaEnd) && item.qty > 0)
    .sort((a, b) => a.etaEnd.localeCompare(b.etaEnd));

  const liveCap = layers.shippedRaw;
  const hasLiveCap = liveCap > 0;
  let remaining = hasLiveCap ? liveCap : 0;
  const events = [];
  for (const candidate of candidates) {
    if (remaining <= 0) break;
    const qty = Math.min(candidate.qty, remaining);
    if (qty <= 0) continue;
    events.push({ ...candidate, qty });
    remaining -= qty;
  }
  const confirmedQty = events.reduce((sum, event) => sum + event.qty, 0);
  const undatedQty = inbound
    .filter((item) => item?.confirmed === false || !(item?.etaEnd || item?.date || item?.etaStart))
    .reduce((sum, item) => sum + Math.max(0, number(item?.qty ?? item?.remainingQty)), 0);
  const candidateQty = candidates.reduce((sum, event) => sum + event.qty, 0);
  // No live in-transit quantity in Lingxing means the ledger cannot prove supply:
  // keep every dated ledger row as undated (unknown ETA) instead of trusting it.
  const unmatchedLedgerQty = hasLiveCap ? 0 : candidateQty;
  const unknownEtaQty = hasLiveCap
    ? Math.max(0, liveCap - confirmedQty)
    : undatedQty + unmatchedLedgerQty;
  const trimmedQty = hasLiveCap ? Math.max(0, candidateQty - liveCap) : 0;
  return {
    events,
    confirmedQty: round(confirmedQty, 0),
    unknownEtaQty: round(unknownEtaQty, 0),
    trimmedQty: round(trimmedQty, 0),
    unmatchedLedgerQty: round(unmatchedLedgerQty, 0),
    quantityMismatch: round(candidateQty - liveCap, 0),
  };
}

export function simulateInventoryTimeline({
  asOf,
  dailyDemand,
  demandAt = null,
  sellable,
  safetyDays = 0,
  confirmedEvents = [],
  unknownEtaQty = 0,
  horizonDays = 180,
}) {
  const start = parseDate(asOf);
  if (!start) throw new Error('asOf must be YYYY-MM-DD');
  const baseDemand = Math.max(0, number(dailyDemand));
  let stock = Math.max(0, number(sellable));
  const events = confirmedEvents
    .map((event, index) => ({
      ...event,
      id: event.id || event.shipment || `ETA-${index + 1}`,
      etaStart: String(event.etaStart || event.date || event.etaEnd || '').slice(0, 10),
      etaEnd: String(event.etaEnd || event.date || event.etaStart || '').slice(0, 10),
      qty: Math.max(0, number(event.qty)),
    }))
    .filter((event) => parseDate(event.etaEnd) && event.qty > 0)
    .sort((a, b) => a.etaEnd.localeCompare(b.etaEnd));
  let safetyBreachDate = null;
  let stockoutDate = null;
  const gaps = [];
  let openGapStart = null;
  const points = [{ date: formatDate(start), stock: round(stock, 1), openingStock: round(stock, 1), forecastConsumption: 0, arrivals: 0, arrivalQty: 0, shipmentIds: [] }];

  for (let offset = 1; offset <= Math.max(1, number(horizonDays)); offset += 1) {
    const dateText = formatDate(addDays(start, offset));
    const dayEvents = events.filter((event) => event.etaEnd === dateText);
    const arrivalQty = dayEvents.reduce((sum, event) => sum + event.qty, 0);
    const demand = demandAt
      ? Math.max(0, number(demandAt(dateText), baseDemand))
      : baseDemand;
    const openingStock = stock;
    stock += arrivalQty;
    stock -= demand;
    if (demand > 0 && !safetyBreachDate && stock <= demand * Math.max(0, number(safetyDays))) {
      safetyBreachDate = dateText;
    }
    const inGap = demand > 0 && stock <= 0;
    if (demand > 0 && !stockoutDate && inGap) stockoutDate = dateText;
    if (inGap && !openGapStart) openGapStart = dateText;
    if (!inGap && openGapStart) {
      gaps.push({ start: openGapStart, end: dateText });
      openGapStart = null;
    }
    points.push({
      date: dateText,
      stock: round(stock, 1),
      openingStock: round(openingStock, 1),
      forecastConsumption: round(demand, 1),
      arrivals: round(arrivalQty, 0),
      arrivalQty: round(arrivalQty, 0),
      shipmentIds: dayEvents.map((event) => event.shipment || event.id),
    });
  }
  if (openGapStart) gaps.push({ start: openGapStart, end: null });
  const dayDiff = (first, second) => Math.round((parseDate(second).getTime() - parseDate(first).getTime()) / 86400000);
  const stockoutIntervals = gaps.map((gap) => ({
    start: gap.start,
    end: gap.end,
    days: gap.end ? dayDiff(gap.start, gap.end) : dayDiff(gap.start, formatDate(addDays(start, horizonDays))) + 1,
    open: !gap.end,
  }));
  const firstGap = stockoutIntervals[0] || null;

  const next = events[0] || null;
  const confirmedQty = events.reduce((sum, event) => sum + event.qty, 0);
  return {
    stockoutDate,
    stockoutIntervals,
    stockoutEndDate: firstGap?.end || null,
    stockoutDays: firstGap?.days || 0,
    safetyBreachDate,
    nextEta: next?.etaEnd || null,
    nextEtaStart: next?.etaStart || null,
    nextEtaEnd: next?.etaEnd || null,
    gapBeforeNextEta: Boolean(stockoutDate && next?.etaEnd && stockoutDate < next.etaEnd),
    unknownEtaQty: round(unknownEtaQty, 0),
    confirmedQty: round(confirmedQty, 0),
    confidence: unknownEtaQty > 0 ? 'low' : events.length ? 'high' : 'medium',
    confidenceReasons: unknownEtaQty > 0
      ? [`${round(unknownEtaQty, 0)}件在途缺少可靠ETA，未用于推迟断货日`]
      : events.length ? ['确认ETA货件已进入逐日库存时间轴'] : ['没有确认ETA货件'],
    endingStock: round(stock, 1),
    events,
    points,
  };
}

export function calculateCoverage(layers, dailyDemand, timeline = {}) {
  const demand = Math.max(0, number(dailyDemand));
  if (demand <= 0) {
    return { sellableDays: null, platformDays: null, confirmedSupplyDays: null };
  }
  const sellableQty = Math.max(0, number(layers.sellable));
  const platformQty = sellableQty + Math.max(0, number(layers.fcTransfers));
  const confirmedSupplyQty = platformQty
    + Math.max(0, number(layers.receiving))
    + Math.max(0, number(timeline.confirmedQty));
  return {
    sellableDays: round(sellableQty / demand, 1),
    platformDays: round(platformQty / demand, 1),
    confirmedSupplyDays: round(confirmedSupplyQty / demand, 1),
  };
}
