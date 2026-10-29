const round = (value, digits = 1) => {
  const factor = 10 ** digits;
  return Math.round((Number(value || 0) + Number.EPSILON) * factor) / factor;
};

const average = (values) => {
  const clean = values.map(Number).filter((value) => Number.isFinite(value) && value >= 0);
  return clean.length ? clean.reduce((sum, value) => sum + value, 0) / clean.length : 0;
};

const clamp = (value, low, high) => Math.min(high, Math.max(low, value));

const coefficientOfVariation = (values) => {
  const mean = average(values);
  if (!mean) return 0;
  const variance = average(values.map((value) => (value - mean) ** 2));
  return Math.sqrt(variance) / mean;
};

const median = (values) => {
  const clean = values.map(Number).filter((value) => Number.isFinite(value) && value >= 0).sort((a, b) => a - b);
  if (!clean.length) return 0;
  const middle = Math.floor(clean.length / 2);
  return clean.length % 2 ? clean[middle] : (clean[middle - 1] + clean[middle]) / 2;
};

export const DEMAND_POLICY = Object.freeze({
  historyDays: 60,
  // PMC 常用口径：近 7 天看拐点，近 30 天看当前水平，近 60 天看基线。
  windows: { recent: 7, middle: 30, far: 60 },
  minimumEffectiveDays: 7,
  growthRatio: 1.15,
  declineRatio: 0.85,
  accelerationRatio: 1.2,
  decelerationRatio: 0.8,
  // 7 天窗口最多把日均拉高 35%、拉低 25%，避免一次促销带偏整月。
  sevenDayUpperCap: 1.35,
  sevenDayLowerCap: 0.75,
  volatilityMediumCv: 0.35,
  volatilityHighCv: 0.7,
  weights: {
    stable: { recent: 0.2, middle: 0.5, far: 0.3 },
    growth: { recent: 0.55, middle: 0.35, far: 0.1 },
    decline: { recent: 0.15, middle: 0.4, far: 0.45 },
  },
});

export function normalizeDemandDays(history = []) {
  return history.slice(-DEMAND_POLICY.historyDays).map((entry, index) => {
    if (typeof entry === 'number') {
      return {
        date: null,
        sales: Math.max(0, Number(entry) || 0),
        fbaSellable: null,
        inboundReceiving: null,
        constrained: false,
        numericInput: true,
        sourceIndex: index,
      };
    }
    const rawSales = entry?.sales ?? entry?.units ?? entry?.volume;
    const salesKnown = rawSales != null && rawSales !== '' && Number.isFinite(Number(rawSales)) && Number(rawSales) >= 0;
    const sales = salesKnown ? Number(rawSales) : null;
    const fbaSellable = Number(entry?.fbaSellable ?? entry?.afn_fulfillable_quantity ?? NaN);
    const inboundReceiving = Number(entry?.inboundReceiving ?? entry?.afn_inbound_receiving_quantity ?? NaN);
    const hasStockEvidence = Number.isFinite(fbaSellable) && Number.isFinite(inboundReceiving);
    const constrained = salesKnown && hasStockEvidence
      && Math.max(0, Number.isFinite(fbaSellable) ? fbaSellable : 0)
        + Math.max(0, Number.isFinite(inboundReceiving) ? inboundReceiving : 0) <= 0
      && sales <= 0;
    return {
      date: entry?.date || entry?.rdate || null,
      sales,
      fbaSellable: Number.isFinite(fbaSellable) ? Math.max(0, fbaSellable) : null,
      inboundReceiving: Number.isFinite(inboundReceiving) ? Math.max(0, inboundReceiving) : null,
      constrained,
      numericInput: false,
      sourceIndex: index,
    };
  });
}

function windowAverage(days, size) {
  const slice = days.slice(-size);
  const valid = slice.filter((day) => !day.constrained && day.sales != null);
  return { value: average(valid.map((day) => day.sales)), validDays: valid.length };
}

export function classifyTrend(segments) {
  // Trend is the medium-term direction: 30-day level against the 60-day baseline.
  if (segments.far > 0 && segments.middle >= segments.far * DEMAND_POLICY.growthRatio) return 'growth';
  if (segments.far > 0 && segments.middle <= segments.far * DEMAND_POLICY.declineRatio) return 'decline';
  return 'stable';
}

export function classifyMomentum(segments) {
  // Momentum is the short-term turn: last 7 days against the 30-day level.
  if (segments.middle > 0 && segments.recent >= segments.middle * DEMAND_POLICY.accelerationRatio) return 'accelerating';
  if (segments.middle > 0 && segments.recent <= segments.middle * DEMAND_POLICY.decelerationRatio) return 'decelerating';
  return 'steady';
}

export function classifyVolatility(values) {
  const cv = coefficientOfVariation(values);
  if (cv > DEMAND_POLICY.volatilityHighCv) return { level: 'high', cv };
  if (cv > DEMAND_POLICY.volatilityMediumCv) return { level: 'medium', cv };
  return { level: 'low', cv };
}

function adjustWeights(trend, momentum, volatilityLevel) {
  const weights = { ...DEMAND_POLICY.weights[trend] };
  if (momentum === 'accelerating') {
    weights.recent += 0.05;
    weights.far -= 0.05;
  } else if (momentum === 'decelerating') {
    weights.recent -= 0.05;
    weights.far += 0.05;
  }
  if (volatilityLevel === 'high') {
    weights.recent -= 0.1;
    weights.middle += 0.05;
    weights.far += 0.05;
  } else if (volatilityLevel === 'medium') {
    weights.recent -= 0.05;
    weights.middle += 0.03;
    weights.far += 0.02;
  }
  const recent = clamp(weights.recent, 0.05, 0.7);
  const far = clamp(weights.far, 0.05, 0.6);
  const middle = Math.max(0.05, 1 - recent - far);
  const total = recent + middle + far;
  return { recent: round(recent / total, 2), middle: round(middle / total, 2), far: round(far / total, 2) };
}

function computeForecast(days, options = {}) {
  const w7 = windowAverage(days, DEMAND_POLICY.windows.recent);
  const w30 = windowAverage(days, DEMAND_POLICY.windows.middle);
  const w60 = windowAverage(days, DEMAND_POLICY.windows.far);
  const recent = w7.validDays >= 3 ? w7.value : (w30.validDays ? w30.value : w60.value);
  const middle = w30.validDays >= 7 ? w30.value : w60.value;
  const far = w60.value;
  const segments = { recent, middle, far };
  const eligible = days.filter((day) => !day.constrained && day.sales != null);
  const fallbackUsed = eligible.length < DEMAND_POLICY.minimumEffectiveDays;
  const trend = fallbackUsed ? 'stable' : classifyTrend(segments);
  const momentum = fallbackUsed ? 'steady' : classifyMomentum(segments);
  const volatilityResult = classifyVolatility(eligible.map((day) => day.sales));
  const weights = fallbackUsed
    ? { recent: 0.2, middle: 0.5, far: 0.3 }
    : adjustWeights(trend, momentum, volatilityResult.level);
  const blended = recent * weights.recent + middle * weights.middle + far * weights.far;
  // Anchor the cap on the 30-day median: a sustained step change is allowed,
  // a one-week promo spike is not.
  const anchor = median(days.slice(-30).filter((day) => !day.constrained && day.sales != null).map((day) => day.sales)) || far || 1;
  const baseDaily = fallbackUsed
    ? average(eligible.slice(-30).map((day) => day.sales))
    : clamp(blended, anchor * DEMAND_POLICY.sevenDayLowerCap, anchor * DEMAND_POLICY.sevenDayUpperCap);
  const multiplier = Math.max(0.1, Number(options.scenarioMultiplier) || 1);
  const zeroRate = eligible.length
    ? eligible.filter((day) => day.sales === 0).length / eligible.length
    : 1;
  const confidenceReasons = [];
  let confidence = 'high';
  if (fallbackUsed) {
    confidence = 'low';
    confidenceReasons.push(`仅${eligible.length}个有效销售日，使用最近有效日均回退`);
  }
  if (volatilityResult.level === 'high') {
    if (confidence === 'high') confidence = 'medium';
    confidenceReasons.push('销量波动较高，已降低近7天权重');
  }
  if (days.some((day) => day.constrained)) {
    if (confidence === 'high') confidence = 'medium';
    confidenceReasons.push(`${days.filter((day) => day.constrained).length}天销量受库存约束并已剔除`);
  }
  if (momentum !== 'steady') {
    confidenceReasons.push(momentum === 'accelerating' ? '近7天在加速，权重已向短期倾斜' : '近7天在减速，权重已向长期倾斜');
  }
  if (!confidenceReasons.length) confidenceReasons.push('有效样本完整且波动可控');
  const daily = round(baseDaily * multiplier, 1);
  return {
    daily,
    baseDaily: round(baseDaily, 1),
    scenarioDaily: daily,
    state: fallbackUsed ? 'limited' : trend,
    trend,
    momentum,
    combinedState: `${volatilityResult.level}-volatility-${trend}-${momentum}`,
    weights,
    segments: {
      recent: round(segments.recent, 1),
      middle: round(segments.middle, 1),
      far: round(segments.far, 1),
    },
    windowDays: DEMAND_POLICY.windows,
    confidence,
    confidenceReasons,
    volatility: round(volatilityResult.cv, 2),
    volatilityLevel: volatilityResult.level,
    sampleDays: days.length,
    effectiveDays: eligible.length,
    constrainedDays: days.filter((day) => day.constrained).length,
    missingDays: days.filter((day) => day.sales == null).length,
    zeroRate: round(zeroRate, 2),
    fallbackUsed,
    dailySeries: days,
  };
}

export function forecastDemand(history = [], options = {}) {
  return computeForecast(normalizeDemandDays(history), options);
}
