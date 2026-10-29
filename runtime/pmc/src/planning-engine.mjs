const LEVEL_RANK = { high: 3, medium: 2, low: 1 };

const issue = (code, priority, label, reason, deadline = null, evidenceRefs = []) => ({
  code,
  priority,
  label,
  reason,
  deadline,
  evidenceRefs,
});

export function classifyIssues(context = {}) {
  const issues = [];
  const active = context.active !== false;
  const timeline = context.timeline || {};
  const bridge = context.bridgePlan || {};
  const shipments = context.shipmentBatches || [];
  const purchases = context.purchaseBatches || [];
  const redundancy = context.redundancy || {};
  const firstShipment = shipments[0] || {};
  const firstPurchase = purchases[0] || {};

  if (!active && Number(context.residualSupply || 0) > 0) {
    issues.push(issue('inactive_stock', 2, '停售有库存', 'Listing非在售但仍有库存或未来供应', null, ['listing', 'inventory']));
  }
  if (active && (timeline.gapBeforeNextEta || bridge.required)) {
    issues.push(issue(
      'stockout_before_supply', 0, '供应前断货',
      `现有库存预计在${timeline.stockoutDate || '下一供应前'}耗尽`,
      timeline.stockoutDate || null,
      ['timeline', 'eta'],
    ));
  }
  if (active && bridge.required && bridge.actionable) {
    issues.push(issue(
      'bridge_required', 0, '需要桥接',
      `需要桥接${Number(bridge.qty || 0)}件以覆盖首个供应断档`,
      bridge.latestArrivalDate || timeline.stockoutDate || null,
      ['bridgePlan'],
    ));
  }
  if (active && bridge.required && bridge.status === 'no_benefit') {
    issues.push(issue(
      'bridge_no_benefit', 0, '断档无法补救',
      `新发货最快${bridge.arrivalDate || '待确认'}到仓，晚于下一票，桥接无意义`,
      timeline.stockoutDate || null,
      ['bridgePlan', 'eta'],
    ));
  }
  if (active && bridge.required && bridge.status === 'no_source') {
    issues.push(issue(
      'supply_unreachable', 0, '无货可发',
      `本地与海外仓可发0件，最快${bridge.earliestReliefDate || bridge.procurementReadyDate || '待确认'}恢复供应`,
      bridge.latestArrivalDate || timeline.stockoutDate || null,
      ['bridgePlan', 'sourceInventory'],
    ));
  }
  const sourceShortage = Math.max(
    Number(bridge.actionable ? bridge.sourceShortageQty || 0 : 0),
    ...shipments.map((batch) => Number(batch.sourceShortageQty || 0)),
  );
  if (active && sourceShortage > 0) {
    issues.push(issue(
      'source_shortage', 1, '货源不足',
      `当前建议存在${sourceShortage}件源头库存缺口`,
      firstShipment.dispatchDate || null,
      ['sourceInventory', 'shipmentPlan'],
    ));
  }
  if (active && Number(firstShipment.executableQty || 0) > 0) {
    issues.push(issue(
      'shipment_due', 1, '应发货',
      `首批可执行发货${Number(firstShipment.executableQty)}件`,
      firstShipment.dispatchDate || null,
      ['shipmentPlan'],
    ));
  }
  if (active && Number(firstPurchase.suggestedQty || 0) > 0) {
    issues.push(issue(
      'purchase_due', 1, '应采购',
      `首批建议采购${Number(firstPurchase.suggestedQty)}件`,
      firstPurchase.orderDate || null,
      ['purchasePlan'],
    ));
  }
  if (Number(redundancy.actualAgedQty || 0) > 0 || Number(redundancy.estimatedRedundantQty || 0) > 0) {
    issues.push(issue(
      'overstock', 2, Number(redundancy.actualAgedQty || 0) > 0 ? '超龄库存' : '预计冗余',
      `预计冗余${Number(redundancy.estimatedRedundantQty || 0)}件，超龄${Number(redundancy.actualAgedQty || 0)}件`,
      null,
      ['redundancy'],
    ));
  }
  if (Number(timeline.unknownEtaQty || 0) > 0) {
    issues.push(issue(
      'eta_missing', 3, 'ETA缺失',
      `${Number(timeline.unknownEtaQty)}件在途没有可靠ETA，未用于推迟断货日`,
      null,
      ['eta'],
    ));
  }
  if (context.forecast?.confidence === 'low') {
    issues.push(issue(
      'demand_low_confidence', 3, '预测低置信度',
      context.forecast.confidenceReasons?.join('；') || '销量样本或波动不足以支持高置信度预测',
      null,
      ['demand'],
    ));
  }
  issues.sort((a, b) => a.priority - b.priority
    || String(a.deadline || '9999-12-31').localeCompare(String(b.deadline || '9999-12-31')));
  return {
    primaryIssue: issues[0] || issue('healthy', 4, '当前健康', '当前没有需要立即处理的库存动作'),
    issues,
  };
}

export function linkPurchaseBatches(purchaseBatches = [], shipmentBatches = []) {
  const uncovered = shipmentBatches.filter((batch) => Number(batch.sourceShortageQty || 0) > 0);
  return purchaseBatches.map((batch, index) => ({
    ...batch,
    supportsShipmentSequence: uncovered[index]?.sequence ?? shipmentBatches[index]?.sequence ?? null,
  }));
}

function confidenceItem(level, reasons, impact) {
  return { level, reasons: reasons?.length ? reasons : ['关键字段完整'], impact };
}

export function buildConfidence(context = {}) {
  const demandLevel = context.forecast?.confidence || 'medium';
  const timelineLevel = context.timeline?.confidence || 'medium';
  const completeness = Number(context.dataCompleteness ?? 70);
  let executionLevel = completeness >= 85 ? 'high' : completeness >= 60 ? 'medium' : 'low';
  const executionReasons = [];
  if (completeness < 85) executionReasons.push(`执行数据完整度${completeness}%`);
  if ((context.shipmentBatches || []).some((batch) => Number(batch.sourceShortageQty || 0) > 0)) {
    executionLevel = executionLevel === 'high' ? 'medium' : executionLevel;
    executionReasons.push('部分建议量缺少可执行货源');
  }
  if (context.batchUnitSource === 'demand_lot') {
    if (executionLevel === 'high') executionLevel = 'medium';
    executionReasons.push('缺少真实箱规，使用按销量分档的建议批量');
  }
  const levels = [demandLevel, timelineLevel, executionLevel];
  const overall = levels.reduce((lowest, level) => (
    LEVEL_RANK[level] < LEVEL_RANK[lowest] ? level : lowest
  ), 'high');
  return {
    demand: confidenceItem(
      demandLevel,
      context.forecast?.confidenceReasons,
      demandLevel === 'low' ? '预测日均采用保守回退值' : '用于库存消耗与批次数量计算',
    ),
    timeline: confidenceItem(
      timelineLevel,
      context.timeline?.confidenceReasons,
      timelineLevel === 'low' ? '未知ETA不进入确定性时间轴' : '用于预计断货日和桥接判断',
    ),
    execution: confidenceItem(
      executionLevel,
      executionReasons,
      executionLevel === 'low' ? '数量仅代表理论需要，执行前需补齐货源数据' : '用于发货和采购可执行量',
    ),
    overall,
  };
}

export function buildSupplyPlan(context = {}) {
  const purchaseBatches = linkPurchaseBatches(context.purchaseBatches || [], context.shipmentBatches || []);
  const enriched = { ...context, purchaseBatches };
  const issueResult = classifyIssues(enriched);
  return {
    ...issueResult,
    shipmentBatches: enriched.shipmentBatches || [],
    purchaseBatches,
    confidence: buildConfidence(enriched),
  };
}
