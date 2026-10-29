import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

function createView(board) {
  const elements=new Map();
  const element=id=>{
    if(!elements.has(id))elements.set(id,{innerHTML:'',textContent:'',value:'',hidden:false,
      addEventListener(){},setSelectionRange(){},focus(){}});
    return elements.get(id);
  };
  element('board-data').textContent=JSON.stringify(board);
  const document={getElementById:element,querySelectorAll(){return []},querySelector(){return null},activeElement:null};
  const window={B_REVIEW:null,B_SUPPLEMENTS:{},innerWidth:1400,innerHeight:900};
  const model=fs.readFileSync(new URL('../web/model.mjs',import.meta.url),'utf8').replaceAll('export function ','function ');
  const app=fs.readFileSync(new URL('../web/app.js',import.meta.url),'utf8')
    .replace(/  initialize\(\);\s*\}\)\(\);\s*$/, '  window.__test={pmcSupplyFacts,pmcEtaCard,state,adActionRow,keywordRowHtml,bidReviewContent,bidReviewItems,competitorPanel,productKeywords,trackingManagePanel,decisionDrawerHtml:typeof decisionDrawerHtml==="function"?decisionDrawerHtml:null,verdictTooltipHtml:typeof verdictTooltipHtml==="function"?verdictTooltipHtml:null,verdictTooltipPosition:typeof verdictTooltipPosition==="function"?verdictTooltipPosition:null};\n  initialize();\n})();');
  vm.runInNewContext(`${model}\n${app}`,{document,window}, {filename:'board-app.js'});
  return {...window.__test,element};
}

const action={action_key:'a1',kind:'exact',query:'kids knife set',normalized_keyword:'kids knife set',
  profile_id:'p1',affected_asins:['B012345678'],reviewable:true,processed_status:'',
  reason:'非精准词至少 2 单，ACOS 不高于 30%',source_count:2,
  impressions:500,clicks:25,spend:12.5,sales:50,orders:2,reference_cpa:8,
  source_scopes:[{profile_id:'p1',campaign_id:'c1',campaign_name:'活动甲',ad_group_id:'g1',ad_group_name:'组甲',
    impressions:500,clicks:25,spends:12.5,sales:50,orders:2,source_record_ids:['r1','r2'],
    target_match_type:'phrase',related_asins:['B012345678']}],
  exact_plan:{object_type:'keyword',target_ad_group_id:'g1',target_campaign_name:'活动甲',target_ad_group_name:'组甲'}};
const product={key:'s1|UK|B012345678',sid:'s1',site:'UK',asin:'B012345678',shop:'示例-UK',
  name:'儿童刀具套装',status:'1',issues:[],stock:{},skus:{},weeks:[],actions:[action],
  keyword_state:{terms:[]}};
const board={run_id:'b-test',as_of_date:'2026-10-13',fetched_at:'2026-10-13T00:00:00Z',
  products:{[product.key]:product},profile_to_sid:{p1:'s1'},actions:[action],coverage:{},status:{}};

test('advertising action is one concise card with ten aggregate metrics and grouped source drawer',()=>{
  const app=createView(board);
  const html=app.adActionRow(action,false);
  assert.match(html,/ad-action-card/);
  for(const label of ['曝光','点击','CTR','实际 CPC','ACOS','花费','广告销售额','广告订单','CPA','CVR'])
    assert.match(html,new RegExp(label));
  assert.match(html,/判断依据与活动明细 · 1 组/);
  assert.match(html,/2 条记录/);
  assert.match(html,/活动甲/);
  assert.match(html,/组甲/);
  assert.equal((html.match(/活动甲/g)||[]).length,2); // target plan + detailed source only
  assert.doesNotMatch(html,/承接广告组<\/th>/);
});

test('in-running Exact keyword explains rank asymmetry without inventing an actionable bid',()=>{
  const dates=['2026-09-27','2026-09-28','2026-09-29','2026-09-30','2026-10-01',
    '2026-10-04','2026-10-05','2026-10-06','2026-10-07','2026-10-08'];
  const row={id:'k1',keyword:'kids knife set',normalized:'kids knife set',sources:['sif_asin_signals'],
    rank_window:['2026-09-27','2026-10-10'],rank_14d_state:'verified',
    natural_rank_display:'p1,8/48',ad_rank_display:'p3,1/12',
    rank_observations:[...dates.map(date=>({observed_date:date,channel:'natural',state:'absolute_rank',rank:8})),
      ...dates.map(date=>({observed_date:date,channel:'advertising',state:'absolute_rank',rank:35}))],
    actions:[{...action,processed_status:'already_exact_running',reviewable:false}]};
  const app=createView(board);
  const html=app.keywordRowHtml(row,product);
  assert.match(html,/广告位试探/);
  assert.match(html,/#8/);
  assert.match(html,/本次快照 P1 · 8/);
  assert.doesNotMatch(html,/查看证据缺口|data-decision-pane="bid"/);
  assert.doesNotMatch(html,/自然位靠前、广告位偏后/); // long reasoning is in the decision detail
  assert.doesNotMatch(html,/自动加价/);
  const processed=app.adActionRow({...action,processed_status:'already_exact_running',reviewable:false},false);
  assert.match(processed,/不重复新增/);
  assert.doesNotMatch(processed,/建议出价/);
});

test('keyword row presents useful SIF metrics and one compact judgment/action cell',()=>{
  const row={id:'k1',keyword:'kids cooking set',normalized:'kids cooking set',
    sources:['sif_asin_signals'],weekly_volume:1645,aba_rank:46067,sif_traffic_share:.0525,
    volume_period:'2026-10-04',tracking:{state:'active'},
    internal_evidence:{clicks:295,orders:17,spend:172.42,sales:382.92},
    actions:[{kind:'exact',action_key:'old-exact',reviewable:false,processed_status:'already_exact_running'},
      {kind:'negative',action_key:'negative-g1',reviewable:true,ad_group_id:'g1',orders:0}]};
  const app=createView(board);
  const html=app.keywordRowHtml(row,product);
  assert.match(html,/ABA 46,067/);
  assert.match(html,/5\.3%/);
  assert.match(html,/SIF 近 7 日估算/);
  assert.match(html,/data-verdict-tip="k1"/);
  assert.doesNotMatch(html,/data-decision-pane="why"/);
  assert.match(html,/局部止损/);
  assert.match(html,/data-decision-pane="negative"/);
  assert.match(html,/否词/);
  assert.doesNotMatch(html,/data-decision-pane="exact"|查看证据缺口|进入专业审核/);
  assert.doesNotMatch(html,/周起 2026-10-04|持续跟踪|SIF 本品<\/span>/);
  assert.doesNotMatch(html,/其他广告组的有效转化继续保留/);
});

test('rank expansion uses already-returned SIF market estimates without confusing them with Lingxing CPC',()=>{
  const row={id:'k-market',keyword:'kids cooking set',normalized:'kids cooking set',
    weekly_volume:1645,aba_rank:46067,sif_traffic_share:.0525,sif_natural_ratio:.16,
    sif_top3_click_share:.35,sif_top3_conversion_share:.27,sif_cpc_median:.17,
    rank_observations:[],rank_window:['2026-09-27','2026-10-10'],tracking:{state:'active'}};
  const app=createView(board);
  app.state.expanded={id:row.id,kind:'rank',focus:'natural'};
  const html=app.keywordRowHtml(row,product);
  assert.match(html,/SIF 自然流量占比[^<]*<b>16\.0%<\/b>/);
  assert.match(html,/SIF 前三点击占比[^<]*<b>35\.0%<\/b>/);
  assert.match(html,/SIF 前三转化占比[^<]*<b>27\.0%<\/b>/);
  assert.match(html,/SIF 市场 CPC 中位数[^<]*<b>0\.17<\/b>/);
  assert.doesNotMatch(html,/竞争难度|实际 CPC 0\.17/);
});

test('judgment tooltip is concise and scoped operation keeps the original action key',()=>{
  const negative={kind:'negative',action_key:'negative-g1',profile_id:'p1',query:'kids cooking set',
    campaign_id:'c1',campaign_name:'活动甲',ad_group_id:'g1',ad_group_name:'组甲',
    reviewable:true,clicks:13,orders:0,spend:7.92,sales:0,reason:'该组无单达到参考 CPA',
    affected_asins:['B012345678'],source_rows:[]};
  const row={id:'k1',keyword:'kids cooking set',normalized:'kids cooking set',
    sources:['sif_asin_signals'],weekly_volume:1645,aba_rank:46067,sif_traffic_share:.0525,
    internal_evidence:{clicks:295,orders:17,spend:172.42,sales:382.92},actions:[negative]};
  const app=createView({...board,actions:[negative],products:{[product.key]:{...product,actions:[negative],keyword_state:{terms:[row]}}}});
  const why=app.verdictTooltipHtml(row,product);
  const operation=app.decisionDrawerHtml(row,product,'negative');
  assert.match(why,/局部止损/);
  assert.match(why,/其他广告组的有效转化继续保留/);
  assert.doesNotMatch(why,/decision-facts|SIF 周需求|领星搜索词合并表现|来源与口径/);
  assert.match(operation,/negative-g1/);
  assert.match(operation,/该组无单达到参考 CPA/);
  assert.match(operation,/接受/);
  assert.doesNotMatch(operation,/data-jump-action/);
});

test('judgment tooltip placement stays inside viewport at the right and bottom edges',()=>{
  const app=createView(board);
  const place=app.verdictTooltipPosition({left:1160,right:1210,top:790,bottom:816},{width:320,height:130},{width:1200,height:820});
  assert.ok(place.left>=8&&place.left+320<=1192);
  assert.ok(place.top>=8&&place.top+130<=812);
  assert.ok(place.left<1160);
});

test('paste manager retains bulk preview and individual removals but has no file selector',()=>{
  const app=createView(board);
  const row={id:'k1',keyword:'kids knife set',normalized:'kids knife set',tracking:{state:'active'}};
  const full=app.trackingManagePanel(product,[row],{});
  assert.match(full,/批量粘贴/);
  assert.match(full,/预览去重/);
  assert.doesNotMatch(full,/keyword-import-file|type="file"|上传 CSV/);
  assert.match(full,/下轮移出/);
});

test('running Exact review labels candidate and matched Exact evidence independently',()=>{
  const existing={...action,processed_status:'already_exact_running',reviewable:false,
    clicks:180,orders:9,spend:90,source_scopes:[{...action.source_scopes[0],clicks:180,orders:9,spends:90}],
    existing_exact_matches:[{record_id:'exact-1',campaign_id:'c2',campaign_name:'精准活动',
      ad_group_id:'g2',ad_group_name:'精准组',target_id:'t2',target_match_type:'exact',
      target_state:'enabled',bid:.6,impressions:80,clicks:4,spends:2,orders:1,sales:20}]};
  const app=createView(board);
  const detail=app.adActionRow(existing,false);
  assert.match(detail,/非精准候选搜索词来源/);
  assert.match(detail,/已在投精准匹配搜索词/);
  assert.match(detail,/精准活动/);
  assert.match(detail,/精准组/);
  assert.doesNotMatch(detail,/t2/);
  assert.match(detail,/不等于完整目标级表现/);
});

test('legacy single-ASIN supplement status overrides the frozen batch status',()=>{
  const app=createView(board);
  const withTerm={...product,keyword_state:{terms:[{id:'k1',keyword:'kids knife set',
    rank_14d_state:'verified',rank_observations:[{observed_date:'2026-09-27',channel:'natural',state:'absolute_rank',rank:8}]}]}};
  app.state.manualSif[product.key]={rank_state:'source_failed',terms:[{id:'k1',rank_observations:[]}]};
  const merged=app.productKeywords(withTerm)[0];
  assert.equal(merged.rank_14d_state,'source_failed');
  assert.equal(merged.rank_observations.length,0);
});

test('V6 competitor disclosure separates historical candidates from current verified cards',()=>{
  const app=createView(board);
  const html=app.competitorPanel({...product,keyword_state:{competitor_discovery:{state:'verified',seed:'kids knife'},
    competitors:[{asin:'B0CHXTHK7N',origin:'sif_serp_discovery',active:1,pending:null}]}},null);
  assert.match(html,/<details class="disclosure competitor-panel">/);
  assert.match(html,/历史自动发现/);
  assert.match(html,/B0CHXTHK7N/);
  assert.match(html,/候选不自动加入核心词库/);
});

test('V5 bid card uses target report metrics, settings, and ASIN rank separately',()=>{
  const bid={action_key:'bid-target|p1|c1|g1|t1',kind:'bid_review',profile_id:'p1',
    campaign_id:'c1',campaign_name:'精准活动',ad_group_id:'g1',ad_group_name:'精准组',
    target_id:'t1',query:'kids knife set',affected_asins:['B012345678'],direction:'consider_raise',
    reviewable:true,spend:10,clicks:20,orders:2,sales:50,impressions:1000,acos:.2,
    bid_evidence:{target_id:'t1',base_bid:.5,budget:30,bidding_strategy:'legacyForSales',
      placement_adjustments:{placementTop:100}},effective_bid_ceiling:1,
    rank_evidence:{natural_latest:30,advertising_page_latest:2,observed_days:12,
      natural_week_days:[6,6],advertising_week_days:[5,6],
      attribution:'asin_external_not_target',children:{B012345678:{state:'verified'}}},
    reason:'目标级表现与外部词位交叉复核'};
  const app=createView(board);
  const html=app.bidReviewContent([{action:bid,product,row:null}]);
  for(const label of ['曝光','点击','CTR','实际 CPC','ACOS','花费','广告销售额','广告订单','CPA','CVR'])
    assert.match(html,new RegExp(label));
  assert.match(html,/目标 kids knife set/);
  assert.doesNotMatch(html,/目标 ID/);
  assert.match(html,/第 2 页/);
  assert.match(html,/自然 6\+6 天 · 广告 5\+6 天/);
  assert.match(html,/仅降低策略下最高位置出价/);
  assert.match(html,/SIF 排名按 ASIN 观察/);
  const budgetHtml=app.bidReviewContent([{action:{...bid,direction:'budget_first',reviewable:false,
    budget_utilization_proxy:.93},product,row:null}]);
  assert.match(budgetHtml,/先核预算/);
  assert.match(budgetHtml,/14 日花费占日预算合计约 93.0%/);
});

test('large bid evidence queue is paged and does not render hundreds of cards at once',()=>{
  const app=createView(board);
  const items=Array.from({length:65},(_,index)=>({
    action:{action_key:`bid-${index}`,query:`term-${index}`,direction:'needs_rank',reviewable:false,
      profile_id:'p1',target_id:`t-${index}`,affected_asins:['B012345678'],rank_evidence:{},bid_evidence:{}},
    product,row:null}));
  const html=app.bidReviewContent(items);
  assert.equal((html.match(/class="bid-review-card/g)||[]).length,20);
  assert.match(html,/已显示 20 \/ 65/);
  assert.match(html,/0 个可审核/);
  assert.match(html,/data-more="bid"/);
  app.state.bidLimit=40;
  assert.equal((app.bidReviewContent(items).match(/class="bid-review-card/g)||[]).length,40);
});

test('directional bid review labels partial ranking and never invents a dynamic-bid ceiling',()=>{
  const bid={action_key:'bid-target|p1|c1|g1|t2',kind:'bid_review',profile_id:'p1',
    campaign_id:'c1',ad_group_id:'g1',target_id:'t2',query:'kids tablet',
    affected_asins:['B012345678'],direction:'consider_lower',reviewable:true,
    spend:40,clicks:20,orders:2,sales:80,acos:.5,reason:'目标级效率偏弱',
    bid_evidence:{target_id:'t2',base_bid:.5,budget:30,bidding_strategy:'autoForSales',
      placement_adjustments:{}},effective_bid_ceiling:null,
    rank_evidence:{state:'insufficient_days',review_basis:'directional',reference_asin:'B012345678',
      observed_days:4,natural_week_days:[0,0],advertising_week_days:[1,3],
      advertising_latest:17,children:{B012345678:{advertising_latest:17,observed_days:4}}}};
  const html=createView(board).bidReviewContent([{action:bid,product,row:null}]);
  assert.match(html,/方向性词位线索/);
  assert.match(html,/非完整双周曲线/);
  assert.match(html,/位置竞价上限不可推算/);
  assert.doesNotMatch(html,/仅降低策略下最高位置出价/);
});

test('same-day Lingxing replay plus resumed live SIF is labeled precisely',()=>{
  const mixed=createView({...board,status:{
    performance:{state:'verified'},ads_diagnosis:{source_complete:true},
    lingxing_transport:{state:'same_day_b_raw_replay',source_run_id:'b-20261014-raw'},
    sif_transport:{state:'same_day_b_raw_resume_live',source_run_id:'b-20261014-partial',
      reused_calls:12,live_calls:25},sif:{state:'partial',successful_products:25,total_active:65}}});
  const caption=mixed.element('source-line').innerHTML;
  assert.match(caption,/<summary[^>]*>[^<]*来源有缺口/);
  assert.match(caption,/<div class="source-detail">/);
  assert.match(caption,/领星同日原始响应重算/);
  assert.match(caption,/SIF 同日复用 12 次 · 新查 25 次/);
  assert.doesNotMatch(caption,/非今日实采/);
});

test('sidebar uses compact provenance disclosure instead of fixed introduction',()=>{
  const shell=fs.readFileSync(new URL('../web/index.html',import.meta.url),'utf8');
  assert.doesNotMatch(shell,/class="side-intro"/);
  assert.match(shell,/id="verdict-tip"/);
  const app=createView(board);
  assert.match(app.element('source-line').innerHTML,/<summary[^>]*>[^<]*来源有缺口/);
  assert.equal(app.element('run-caption').textContent,'数据截至 2026-10-13');
});


test('API ETA evidence is displayed without pretending it came from a shipment workbook', () => {
  const view=createView(board);
  const html=view.pmcEtaCard({basis:{supplyEvidence:{state:'partial',source_response_time:'2026-10-29 14:36:00',items:[{state:'overdue_eta'},{state:'missing_eta'}]}}});
  assert.match(html,/API 已读 · ETA 待补/);
  assert.match(html,/2 个货件，2 个到仓日期待复核/);
  assert.doesNotMatch(html,/货件文件/);
  assert.match(html,/缺失或过期 ETA/);
});


test('supply drawer separates actual receipt, estimates, components and escapes source fields',()=>{
  const view=createView(board);
  const html=view.pmcSupplyFacts({purchaseEvidence:{window_start:'2026-01-01',window_end:'2026-10-29',state:'complete_window',allocation:'shared_sku_reference_only',items:[],component_items:[],product_rules:[{sku:'<img src=x>',carton_qty:0,moq:0,components:[]}],receipts:[{order_sn:'CR1',actual_qty:40,actual_time:'2026-10-23 18:50:10',expected_date:'2026-11-03'}]},fbaShipmentEvidence:[]});
  assert.match(html,/2026-10-23 18:50:10（实际）/);
  assert.match(html,/2026-11-03（预计）/);
  assert.match(html,/不按 ASIN 重复汇总/);
  assert.match(html,/不再次增加当前库存/);
  assert.match(html,/源值 0，待确认/);
  assert.doesNotMatch(html,/<img src=x>/);
});
