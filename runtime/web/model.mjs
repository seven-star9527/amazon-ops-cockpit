export function selectProducts(products, scope='problem', query='') {
  const text = query.trim().toLowerCase();
  return products.filter(product => {
    if (scope === 'problem' && !(String(product.status) === '1' && (product.issues || []).some(i => i.severity !== 'gap'))) return false;
    if (scope === 'active' && String(product.status) !== '1') return false;
    return !text || [product.name, product.asin, product.shop, product.sid].some(v => String(v || '').toLowerCase().includes(text));
  }).sort((a,b) => {
    const rank = {critical:4,high:3,medium:2,low:1,gap:0};
    const score = p => Math.max(0,...(p.issues||[]).map(i=>rank[i.severity]||0));
    return score(b)-score(a) || a.name.localeCompare(b.name,'zh');
  });
}

export function shortName(name, max=25) {
  const points = Array.from(String(name || '未命名产品'));
  return points.length > max ? points.slice(0,max).join('') + '…' : points.join('');
}

export function actionCount(actions) {
  return new Set(actions.filter(a=>a.reviewable ?? a.executable).map(a=>a.action_key)).size;
}

export function keywordRows(product) {
  const terms = product.keyword_state?.terms || [];
  const actions = product.actions || [];
  return terms.map(term => {
    const related = actions.filter(a => a.normalized_keyword === term.normalized);
    return {...term, actions:related, bestAction:related.find(a=>a.reviewable ?? a.executable) || related[0] || null};
  });
}

export function filterKeywordRadar(rows, filter='core') {
  const phrases=(rows||[]).filter(row=>!/^B0[A-Z0-9]{8}$/i.test(String(row.keyword||'').trim()));
  if(filter==='all') return phrases;
  if(filter==='internal') return phrases.filter(row=>!(row.sources||[]).includes('sif_asin_signals'));
  if(filter==='opportunity') return phrases.filter(row=>keywordLane(row)==='external_unverified');
  return phrases.filter(row=>row.tracking?.state!=='suppressed' &&
    (row.tracking?.state==='active' || (row.sources||[]).includes('sif_asin_signals')));
}

export function keywordActionKey(row) {
  const actions=row?.actions||[];
  const action=actions.find(item=>item.kind==='exact' && item.reviewable) ||
    actions.find(item=>item.kind==='negative' && item.reviewable) ||
    actions.find(item=>item.kind==='negative_asin' && item.reviewable) ||
    actions.find(item=>item.kind==='exact') ||
    actions.find(item=>['negative','negative_asin'].includes(item.kind)) ||
    actions.find(item=>item.kind==='bid_review');
  return action?.action_key||null;
}

export function keywordLane(row) {
  const actions=row?.actions||[];
  if(actions.some(item=>item.kind==='bid_review')) return 'exact_active';
  if(actions.some(item=>item.kind==='exact' && item.processed_status==='already_exact_running')) return 'already_exact';
  if(actions.some(item=>item.kind==='exact' && item.reviewable)) return 'specialist_exact';
  if(actions.some(item=>['negative','negative_asin'].includes(item.kind) && item.reviewable)) return 'specialist_negative';
  if(actions.some(item=>['exact','negative','negative_asin'].includes(item.kind) &&
    item.reviewable===false && !item.processed_status)) return 'specialist_gap';
  if(((row?.sources||[]).includes('sif_asin_signals') ||
      ((row?.sources||[]).includes('sif_competitor_gap') && row?.current_competitor_gap===true)) &&
    !row?.internal_evidence) return 'external_unverified';
  if(row?.internal_evidence) return 'internal_observed';
  return 'tracking_only';
}

export function adMetricSummary(action) {
  const count = value => value === null || value === undefined || value === '' ||
    !Number.isFinite(Number(value)) || Number(value) < 0 ? null : Number(value);
  const impressions=count(action?.impressions), clicks=count(action?.clicks);
  const spend=count(action?.spend??action?.spends), sales=count(action?.sales), orders=count(action?.orders);
  const ratio=(top,bottom) => top != null && bottom != null && bottom > 0 ? top/bottom : null;
  return {impressions,clicks,ctr:ratio(clicks,impressions),cpc:ratio(spend,clicks),
    acos:ratio(spend,sales),spend,sales,orders,cpa:ratio(spend,orders),cvr:ratio(orders,clicks)};
}

export function adExactMatchSummary(action) {
  const rows=action?.existing_exact_matches||[];
  const total={};
  for(const [target,source] of [['impressions','impressions'],['clicks','clicks'],
    ['spend','spends'],['sales','sales'],['orders','orders']]){
    const values=rows.map(row=>row[source]??(source==='spends'?row.spend:null))
      .filter(value=>value!==null&&value!==undefined&&value!==''&&
        Number.isFinite(Number(value))&&Number(value)>=0);
    total[target]=values.length?values.reduce((sum,value)=>sum+Number(value),0):null;
  }
  return adMetricSummary(total);
}

export function adSourceGroups(action) {
  const rows=action?.kind==='exact' ? action.source_scopes||[] : action?.source_rows||[];
  const grouped=new Map();
  for(const row of rows){
    const key=[row.profile_id||action.profile_id||'',row.campaign_id||'',row.ad_group_id||''].join('|');
    let group=grouped.get(key);
    if(!group){
      group={campaignId:String(row.campaign_id||''),campaignName:String(row.campaign_name||row.campaign_id||'—'),
        adGroupId:String(row.ad_group_id||''),adGroupName:String(row.ad_group_name||row.ad_group_id||'—'),
        impressions:0,clicks:0,spend:0,orders:0,sales:0,recordCount:0,matchTypes:[],
        relatedAsins:[],sharedGroup:false,defaultDestination:false};
      grouped.set(key,group);
    }
    for(const [target,source] of [['impressions','impressions'],['clicks','clicks'],['spend','spends'],
      ['orders','orders'],['sales','sales']]){
      const value=row[source]??(source==='spends'?row.spend:null);
      if(value!=null && Number.isFinite(Number(value)))group[target]+=Number(value);
    }
    const types=String(row.target_match_type||row.match_type||'').split('/').map(v=>v.trim()).filter(Boolean);
    for(const type of types)if(!group.matchTypes.includes(type))group.matchTypes.push(type);
    const ids=row.source_record_ids||((row.sources||[]).map(s=>s.record_id));
    group.recordCount+=Math.max(1,Array.isArray(ids)&&ids.length?ids.length:row.source_count||0);
    for(const asin of row.related_asins||[])if(!group.relatedAsins.includes(asin))group.relatedAsins.push(asin);
    group.sharedGroup ||= row.relation_type==='shared_group'||group.relatedAsins.length>1;
    group.defaultDestination ||= Boolean(row.selected_default_exact_destination);
  }
  return [...grouped.values()];
}

export function rankPresentation(digest, fallback) {
  const days=Number(digest?.days)||0;
  if(digest?.latest!=null && Number.isFinite(Number(digest.latest)) && Number(digest.latest)>0){
    const date=String(digest.latestDate||'').slice(5);
    return {kind:'absolute',label:`#${Number(digest.latest).toLocaleString('zh-CN')}`,
      detail:`${date?`${date} 末次`:''}绝对名次 · ${days}/14 天实测`,days};
  }
  const page=/^p\s*(\d+)\s*,\s*(\d+)\s*\/\s*(\d+)/i.exec(String(fallback||'').trim());
  if(page)return {kind:'page',label:`第 ${Number(page[1])} 页 · 第 ${Number(page[2])} 位`,
    shortLabel:`P${Number(page[1])} · ${Number(page[2])}`,
    detail:`SIF 页位快照 · 每页 ${Number(page[3])} 位；非绝对名次`,days};
  const compactPage=/^p\s*(\d+)\s*#\s*(\d+)$/i.exec(String(fallback||'').trim());
  if(compactPage)return {kind:'page',label:`第 ${Number(compactPage[1])} 页 · 第 ${Number(compactPage[2])} 位`,
    shortLabel:`P${Number(compactPage[1])} · ${Number(compactPage[2])}`,
    detail:'SIF 页位快照 · 每页位数未知；非绝对名次',days};
  return {kind:'missing',label:'未观测',detail:'没有可比的绝对名次或页位',days};
}

export function keywordBidReview(row, asOf) {
  const activeExact=(row?.actions||[]).some(action=>action.kind==='exact' &&
    action.processed_status==='already_exact_running');
  if(!activeExact)return null;
  const frozen={executable:false,bid:null};
  const coverage=rankCoverage(row,asOf);
  const naturalReady=coverage.naturalDays.every(days=>days>=5);
  const adReady=coverage.advertisingDays.every(days=>days>=5);
  if(!naturalReady&&!adReady&&
    ['source_failed','replay_missing','shape_mismatch','deferred_rank_budget'].includes(row?.rank_14d_state))
    return {...frozen,kind:'coverage_gap',title:'精准在投 · SIF 排名来源缺口',
      note:'本次排名来源未核实，不能依据空白排名调整竞价。'};
  const digest=rankDigest(row,asOf), natural=digest.natural, ad=digest.advertising;
  if(naturalReady && natural.latest<=20 && adReady && ad.latest>20)
    return {...frozen,kind:'ad_weak',title:'自然靠前 · 广告位靠后',
      note:'先核对预算、投放资格及精准目标级 ACOS/CPC；目标级效率合格后才考虑小幅竞价测试，不自动给出出价。'};
  if(naturalReady && natural.latest<=20 && !adReady)
    return {...frozen,kind:'ad_unmeasured',title:'自然可见 · 广告绝对名次不足',
      note:'可能已有广告页位快照或排名采集缺口；先核对精准目标是否正常展现、预算和竞价，不能直接认定没有广告位。'};
  if(adReady && ad.latest<=10 && naturalReady && natural.latest>30)
    return {...frozen,kind:'organic_weak',title:'广告靠前 · 自然承接偏弱',
      note:'先看目标级转化效率与自然相关性，不建议因广告位靠前继续加价；需要时另行诊断 Listing。'};
  if(adReady && ad.latest<=10 && !naturalReady)
    return {...frozen,kind:'organic_unmeasured',title:'广告靠前 · 自然名次待核',
      note:'自然绝对名次不足，页位快照不可与广告绝对名次直接比较；先守位并复核目标级效率。'};
  return {...frozen,kind:'monitor',title:'精准在投 · 持续观察',
    note:'自然/广告任一渠道需双周各至少 5 天绝对名次才进入差异判断；搜索词合并数据也不等于该精准目标的单独表现。'};
}

// A reading aid, not an executable ad action. Target-level changes remain in the specialist queue.
export function keywordRecommendation(row, asOf) {
  const result=(code,title,reason)=>({code,title,reason,scope:'advisory'});
  const actions=row?.actions||[];
  if(actions.some(a=>['negative','negative_asin'].includes(a.kind)&&a.reviewable))
    return result('stop_loss','止损复核','内部否词方案已达到专业复核门槛；先查看广告组证据。');
  if(actions.some(a=>a.kind==='exact'&&a.reviewable))
    return result('scale_exact','精准扩量','内部精准方案可审核；先确认是否已有在投或历史停投目标。');
  const targetReview=actions.find(a=>a.kind==='bid_review'&&a.reviewable&&a.target_id);
  if(targetReview){
    if(targetReview.direction==='consider_lower')
      return result('bid_lower_review','降价复核','已有可审核的精准目标降价方向；按目标级表现和预算核对后由运营确认。');
    if(targetReview.direction==='consider_raise')
      return result('bid_raise_review','提价测试','已有可审核的精准目标提价方向；先核预算与目标效率，不自动调整。');
    return result('bid_target_review','竞价复核','已有目标级专业判断；先看该目标证据，再决定守位或调整。');
  }
  const evidence=row?.internal_evidence||{};
  const clicks=Number(evidence.clicks)||0,orders=Number(evidence.orders)||0;
  const spend=Number(evidence.spend)||0,sales=Number(evidence.sales)||0;
  const coverage=rankCoverage(row,asOf),rank=rankDigest(row,asOf);
  const naturalReady=coverage.naturalDays.every(n=>n>=5);
  const adReady=coverage.advertisingDays.every(n=>n>=5);
  const acos=sales>0?spend/sales:null;
  if(clicks>=20&&spend>0&&(orders===0||acos!=null&&acos>0.30))
    return result('cost_review','控费复核','合并搜索词花费偏高；先下钻广告组与目标级数据，避免把整词直接否定。');
  const rankEnough=rank.natural.days>=5&&rank.advertising.days>=5;
  const rankCaveat=naturalReady&&adReady?'双周可比':'仅现有实测，双周覆盖不足';
  if(rankEnough&&rank.natural.latest<=20&&rank.advertising.latest>20)
    return result('ad_position_test','广告位试探',`${rankCaveat}：自然位靠前、广告位偏后；先核预算与精准目标效率。`);
  if(rankEnough&&rank.natural.latest>30&&rank.advertising.latest<=10)
    return result('organic_rebuild','自然承接',`${rankCaveat}：广告靠前、自然偏后；先复核自然承接，不继续盲目加价。`);
  if(rankEnough&&rank.natural.latest<=20&&rank.advertising.latest<=10&&orders>=2)
    return result('hold_position','守住双端词位',`${rankCaveat}：自然与广告均可见；先保留有效流量，不因名次好继续抬价。`);
  if(clicks>=20&&orders>=2&&sales>0&&spend/sales<=0.15)
    return result('protect_efficient','守住高效','领星合并搜索词转化有效；持续核对精准目标级表现，避免盲目扩价。');
  if(clicks>=20&&orders>=2&&acos!=null&&acos<=0.30)
    return result('protect_converting','守住转化','合并搜索词有订单且 ACOS 未超 30% 保本参考；复核目标级效率后再调价。');
  if((row?.sources||[]).includes('sif_competitor_gap')&&row?.current_competitor_gap===true)
    return result('trial_relevance','机会核验','竞品词只证明外部机会；先查本品相关性、在投状态和承接广告组。');
  return result('observe','持续观察','当前证据不足以提出广告操作；保留词位趋势和来源供下轮比较。');
}

// One advisory judgment may point to several distinct ad-group/target reviews.
// This never changes action eligibility or grants permission to write ads.
export function keywordDecision(row, asOf, options={}) {
  const unique=new Map();
  for(const action of row?.actions||[]){
    if(action?.action_key&&!unique.has(action.action_key))unique.set(action.action_key,action);
  }
  const actions=[...unique.values()];
  const active=actions.filter(action=>action.reviewable===true&&!action.processed_status);
  const scopes=[
    ['negative','否词',active.filter(action=>['negative','negative_asin'].includes(action.kind)),'组'],
    ['exact','精投',active.filter(action=>action.kind==='exact'),'组'],
    ['bid','调价',active.filter(action=>action.kind==='bid_review'&&action.target_id&&
      ['consider_raise','consider_lower'].includes(action.direction)),'目标'],
  ];
  const operations=scopes.filter(([, , items])=>items.length).map(([kind,label,items,unit])=>{
    const ids=new Set(items.map(action=>kind==='bid'?action.target_id:action.ad_group_id||action.action_key));
    return {kind,label,status:'review',countText:`${ids.size}${unit}`,
      actionKeys:items.map(action=>action.action_key),actions:items};
  });
  if(options.probeKey&&!actions.some(action=>action.kind==='exact')&&
     !operations.some(operation=>operation.kind==='exact')){
    operations.push({kind:'probe',label:'精投',status:'validation',countText:'',
      actionKeys:[options.probeKey],actions:[]});
  }
  const verdict=(code,title,reason)=>({code,title,reason,scope:'advisory'});
  const kinds=new Set(operations.map(operation=>operation.kind));
  if(kinds.size>1)return {verdict:verdict('split_handling','分组处理',
    '同词的不同广告组或精准目标需要不同处理；逐项核对，不能把单组结论套到整词。'),operations};
  if(kinds.has('negative'))return {verdict:verdict('stop_loss','局部止损',
    `只审核 ${operations[0].countText} 的否词建议；其他广告组的有效转化继续保留。`),operations};
  if(kinds.has('exact'))return {verdict:verdict('scale_exact','尝试扩量',
    '内部精准方案达到专业审核门槛；仍需核对历史目标、承接广告组和出价，不自动新增。'),operations};
  if(kinds.has('bid')){
    const directions=new Set(operations[0].actions.map(action=>action.direction));
    const title=directions.size>1?'分目标调价':directions.has('consider_lower')?'审慎降价':'小幅试价';
    return {verdict:verdict('bid_target_review',title,
      '只对列出的精准目标审核竞价方向；SIF 的 ASIN 排名是外部位置线索，不等于目标级转化归因。'),operations};
  }
  if(kinds.has('probe'))return {verdict:verdict('trial_relevance','尝试扩量',
    'SIF 外部词仅可先提交试投核验意向；没有内部搜索词记录，不代表没有在投或历史停投目标。'),operations};
  return {verdict:keywordRecommendation(row,asOf),operations};
}

export function parseKeywordBatch(raw) {
  const rows=[];let cells=[],cell='',quoted=false;
  for(let i=0;i<String(raw||'').length;i++){
    const char=raw[i];
    if(char==='"'&&quoted&&raw[i+1]==='"'){cell+='"';i++;continue}
    if(char==='"'){quoted=!quoted;continue}
    if(!quoted&&(char===','||char==='\t'||char===';')){
      cells.push(cell.trim());cell='';continue;
    }
    if(!quoted&&(char==='\n'||char==='\r')){
      cells.push(cell.trim());rows.push(cells);cells=[];cell='';
      if(char==='\r'&&raw[i+1]==='\n')i++;
      continue;
    }
    cell+=char;
  }
  cells.push(cell.trim());rows.push(cells);
  const errors=[],terms=[],seen=new Set();
  if(quoted)errors.push('CSV 引号没有闭合');
  const headers=['keyword','keywords','关键词','搜索词'];
  const first=rows.find(row=>row.some(value=>value));
  const column=first?.findIndex(value=>headers.includes(value.trim().toLocaleLowerCase()))??-1;
  const values=column>=0?rows.slice(rows.indexOf(first)+1).map(row=>row[column]||''):rows.flat();
  if(values.length>200)errors.push('一次最多导入 200 个词');
  for(const value of values){
    if(!value||/^(keyword|keywords|关键词|搜索词)$/i.test(value))continue;
    if(value.length>120||/^B[A-Z0-9]{9}$/i.test(value)||/^\d+(?:\.\d+)?$/.test(value)){
      errors.push(`无效关键词：${value.slice(0,24)}`);continue;
    }
    const key=value.replace(/\s+/g,' ').toLocaleLowerCase();
    if(!seen.has(key)){seen.add(key);terms.push(value.replace(/\s+/g,' '))}
  }
  if(!terms.length)errors.push('没有可导入的关键词');
  return {terms,errors};
}

export function probeActionKey(profileId,row) {
  return `sif-probe:${String(profileId)}:${String(row?.id||'')}`;
}

export function rankDigest(row, asOf) {
  const [start,end]=rankWindow(row,asOf);
  const summarize=channel=>{
    const points=(row?.rank_observations||[]).filter(point=>point.channel===channel &&
      point.state==='absolute_rank' && Number.isFinite(Number(point.rank)) && Number(point.rank)>0 &&
      point.observed_date>=start && point.observed_date<=end)
      .sort((a,b)=>String(a.observed_date).localeCompare(String(b.observed_date)));
    const unique=new Map(points.map(point=>[point.observed_date,Number(point.rank)]));
    const values=[...unique.values()];
    const first=values.at(0)??null,latest=values.at(-1)??null;
    return {first,latest,improvement:first!=null&&latest!=null?first-latest:null,
      best:values.length?Math.min(...values):null,worst:values.length?Math.max(...values):null,
      amplitude:values.length?Math.max(...values)-Math.min(...values):null,days:unique.size,
      latestDate:[...unique.keys()].at(-1)||null};
  };
  return {natural:summarize('natural'),advertising:summarize('advertising'),window:[start,end]};
}

export function globalActionQueue(actions, profileToSid, shop='all', kind='all') {
  const unique = new Map();
  for (const action of actions || []) {
    if (!action.action_key || (shop !== 'all' && String(profileToSid[action.profile_id]) !== String(shop))) continue;
    if(kind==='bid' ? action.kind!=='bid_review' : action.kind==='bid_review') continue;
    if (kind === 'processed' && !action.processed_status) continue;
    if (kind !== 'processed' && action.processed_status) continue;
    if (kind === 'gaps' && action.reviewable !== false) continue;
    if (kind !== 'gaps' && kind !== 'processed' && action.reviewable === false) continue;
    if (kind === 'negative' && !['negative','negative_asin'].includes(action.kind)) continue;
    if (kind === 'exact' && action.kind !== 'exact') continue;
    if (kind === 'observe' && action.kind !== 'observe') continue;
    unique.set(action.action_key, action);
  }
  return [...unique.values()].sort((a,b) => Number(Boolean(b.reviewable ?? b.executable))-Number(Boolean(a.reviewable ?? a.executable)) ||
    (Number(b.spend)||0)-(Number(a.spend)||0));
}

export function mergeKeywordRows(snapshot, live) {
  if (!live) return snapshot || [];
  const byId = new Map((snapshot || []).map(term => [term.id, term]));
  for (const term of live) byId.set(term.id, {...(byId.get(term.id)||{}), ...term});
  return [...byId.values()];
}

export function rankSeries(observations, start, end) {
  const byDate = new Map();
  for (const item of observations || []) {
    if (!item.observed_date || item.observed_date < start || item.observed_date > end) continue;
    const entry = byDate.get(item.observed_date) || {date:item.observed_date,natural:null,advertising:null,adDisplay:null};
    const absolute=item.state==='absolute_rank' && item.rank!==null && item.rank!==undefined &&
      Number.isFinite(Number(item.rank)) && Number(item.rank)>0;
    if (item.channel === 'natural' && absolute) entry.natural = Number(item.rank);
    if (item.channel === 'advertising') {
      if (absolute) entry.advertising = Number(item.rank);
      entry.adDisplay = item.display || null;
    }
    byDate.set(item.observed_date, entry);
  }
  const result = [];
  for (let time = Date.parse(`${start}T00:00:00Z`), last = Date.parse(`${end}T00:00:00Z`); time <= last; time += 86400000) {
    const day = new Date(time).toISOString().slice(0,10);
    result.push(byDate.get(day) || {date:day,natural:null,advertising:null,adDisplay:null});
  }
  return result;
}

export function rankWindow(row, asOf) {
  const stored = row?.rank_window;
  if (Array.isArray(stored) && stored.length === 2 &&
      stored.every(value => /^\d{4}-\d{2}-\d{2}$/.test(value))) return stored;
  const end = new Date(`${asOf}T00:00:00Z`);
  end.setUTCDate(end.getUTCDate() - 1);
  end.setUTCDate(end.getUTCDate() - (end.getUTCDay() - 6 + 7) % 7);
  const start = new Date(end);
  start.setUTCDate(start.getUTCDate() - 13);
  return [start.toISOString().slice(0,10), end.toISOString().slice(0,10)];
}

export function rankCoverage(row, asOf) {
  const [start,end] = rankWindow(row, asOf);
  const firstWeekEnd = new Date(`${start}T00:00:00Z`);
  firstWeekEnd.setUTCDate(firstWeekEnd.getUTCDate() + 6);
  const boundary = firstWeekEnd.toISOString().slice(0,10);
  const days = {natural:[new Set(),new Set()], advertising:[new Set(),new Set()]};
  for (const point of row?.rank_observations || []) {
    if (point.state !== 'absolute_rank' || !(Number(point.rank) > 0) ||
        point.observed_date < start || point.observed_date > end || !days[point.channel]) continue;
    days[point.channel][point.observed_date <= boundary ? 0 : 1].add(point.observed_date);
  }
  const naturalDays = days.natural.map(set => set.size);
  const advertisingDays = days.advertising.map(set => set.size);
  const twoWeek = [naturalDays,advertisingDays].some(counts => counts[0] >= 5 && counts[1] >= 5);
  const observedDays = Math.max(naturalDays[0]+naturalDays[1],
    advertisingDays[0]+advertisingDays[1]);
  return {twoWeek, observedDays, naturalDays, advertisingDays};
}

export function sortKeywordRows(rows, asOf) {
  return [...rows].sort((a,b) => {
    const aRank = rankCoverage(a, asOf), bRank = rankCoverage(b, asOf);
    return Number(Boolean(b.pinned))-Number(Boolean(a.pinned)) ||
      Number(bRank.twoWeek)-Number(aRank.twoWeek) || bRank.observedDays-aRank.observedDays ||
      (Number(b.sif_traffic_share)||0)-(Number(a.sif_traffic_share)||0) ||
      String(a.keyword||'').localeCompare(String(b.keyword||''));
  });
}

export function weekHoverText(week, selected, labels, formats = {}) {
  const metric = key => {
    const value = week[key];
    if (value == null || !Number.isFinite(Number(value))) return '—';
    if (formats[key] === 'pct') return `${(Number(value) * 100).toFixed(2)}%`;
    return Number(value).toLocaleString('zh-CN',{maximumFractionDigits:2});
  };
  return [week.label, ...selected.map(key => `${labels[key] || key} ${metric(key)}`)].join(' · ');
}

export function trafficComposition(week) {
  if (week?.quality !== 'measured') return null;
  const total=week.sessions_total, advertising=week.ad_clicks, natural=week.natural_sessions_est;
  if (![total,advertising,natural].every(value=>typeof value==='number'&&Number.isFinite(value)) ||
      total<=0 || advertising<0 || natural<0 || advertising>total ||
      Math.abs(total-advertising-natural)>0.01) return null;
  return {label:week.label,total,advertising,natural,
    naturalPct:natural/total,advertisingPct:advertising/total};
}

export function adSpendComposition(week) {
  if (week?.quality !== 'measured') return null;
  const total=week.ad_spend,sp=week.sp_spend,sb=week.sb_spend;
  if (![total,sp,sb].every(value=>typeof value==='number'&&Number.isFinite(value)) ||
      total<=0 || sp<0 || sb<0 || sp+sb>total+0.01) return null;
  const other=Math.max(0,total-sp-sb);
  return {total,sp,sb,other,spPct:sp/total,sbPct:sb/total,otherPct:other/total};
}

export function toggleKeywordPanel(previous, id, kind, focus=null) {
  const next={id,kind,focus:kind==='rank'?focus:null};
  return previous?.id===next.id && previous.kind===next.kind && previous.focus===next.focus
    ? null : next;
}

export function tooltipPosition({x,y,width,height,viewportWidth,viewportHeight,offset=12,margin=12}) {
  const wantedLeft=x+offset+width<=viewportWidth-margin ? x+offset : x-offset-width;
  const wantedTop=y+offset+height<=viewportHeight-margin ? y+offset : y-offset-height;
  return {
    left:Math.max(margin,Math.min(wantedLeft,viewportWidth-width-margin)),
    top:Math.max(margin,Math.min(wantedTop,viewportHeight-height-margin)),
  };
}

export function bindSingleClick(element, handler) {
  element.onclick=handler;
}
