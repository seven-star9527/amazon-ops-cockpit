import test from 'node:test';
import assert from 'node:assert/strict';
import {selectProducts, shortName, actionCount, keywordRows, globalActionQueue,
  mergeKeywordRows, rankSeries, weekHoverText} from '../web/model.mjs';
import * as model from '../web/model.mjs';

const products = [
  {key:'1|US|B012345678', asin:'B012345678', status:'1', name:'很长很长的中文产品名称需要省略显示但详情保留', issues:[{severity:'high',domain:'inventory'}], keyword_state:{terms:[{id:'a',keyword:'kids scissors'}]}},
  {key:'1|US|B098765432', asin:'B098765432', status:'1', name:'普通产品', issues:[], keyword_state:{terms:[]}},
  {key:'1|US|B011111111', asin:'B011111111', status:'0', name:'停售产品', issues:[{severity:'high'}], keyword_state:{terms:[]}},
];

test('three fixed catalog scopes use status and issues, not duplicate queues', () => {
  assert.deepEqual(selectProducts(products,'problem').map(p=>p.asin), ['B012345678']);
  assert.equal(selectProducts(products,'active').length, 2);
  assert.equal(selectProducts(products,'all').length, 3);
});

test('Chinese short label truncates only navigation, never product identity', () => {
  assert.ok(shortName(products[0].name, 12).endsWith('…'));
  assert.equal(products[0].name.includes('详情'), true);
});

test('shared action key counts once and keyword pool is one table', () => {
  assert.equal(actionCount([{action_key:'x',executable:true},{action_key:'x',executable:true}]),1);
  assert.equal(keywordRows(products[0]).length,1);
});

test('global queue filters a store while shared ASIN actions stay one row', () => {
  const actions=[{action_key:'a',profile_id:'p1',kind:'negative',affected_asins:['A','B']},
    {action_key:'a',profile_id:'p1',kind:'negative',affected_asins:['A','B']},
    {action_key:'b',profile_id:'p2',kind:'exact',affected_asins:['C']}];
  assert.deepEqual(globalActionQueue(actions,{p1:'s1',p2:'s2'},'s1','all').map(a=>a.action_key),['a']);
});

test('competitor gap stays external candidate and bid review has its own lane', () => {
  const gap={keyword:'kids knife',sources:['sif_competitor_gap'],current_competitor_gap:true,tracking:{state:'candidate'}};
  assert.equal(model.keywordLane(gap),'external_unverified');
  assert.deepEqual(model.filterKeywordRadar([gap],'opportunity'),[gap]);
  const oldGap={...gap,keyword:'adult chef knife',current_competitor_gap:false};
  assert.deepEqual(model.filterKeywordRadar([oldGap],'opportunity'),[]);
  const actions=[{action_key:'b1',profile_id:'p1',kind:'bid_review',reviewable:true},
    {action_key:'n1',profile_id:'p1',kind:'negative',reviewable:true}];
  assert.deepEqual(globalActionQueue(actions,{p1:'s1'},'s1','all').map(a=>a.action_key),['n1']);
  assert.deepEqual(globalActionQueue(actions,{p1:'s1'},'s1','bid').map(a=>a.action_key),['b1']);
});

test('keyword direction leads with a business judgment while never granting write permission', () => {
  const window=['2026-09-27','2026-10-10'];
  const days=['2026-09-27','2026-09-28','2026-09-29','2026-09-30','2026-10-01',
    '2026-10-04','2026-10-05','2026-10-06','2026-10-07','2026-10-08'];
  const observed=(natural,advertising)=>({rank_window:window,rank_observations:days.flatMap(date=>[
    {observed_date:date,channel:'natural',state:'absolute_rank',rank:natural},
    {observed_date:date,channel:'advertising',state:'absolute_rank',rank:advertising}] )});
  const decide=row=>model.keywordRecommendation(row,'2026-10-13');
  assert.equal(decide({actions:[{kind:'negative',reviewable:true}]}).code,'stop_loss');
  assert.equal(decide({actions:[{kind:'exact',reviewable:true}]}).code,'scale_exact');
  assert.equal(decide({actions:[{kind:'bid_review',reviewable:true,direction:'consider_lower',target_id:'t1'}],
    ...observed(7,36)}).code,'bid_lower_review');
  assert.equal(decide({...observed(7,36),internal_evidence:{clicks:50,orders:5,spend:20,sales:150}}).code,
    'ad_position_test');
  assert.equal(decide({...observed(42,4),internal_evidence:{clicks:100,orders:7,spend:30,sales:130}}).code,
    'organic_rebuild');
  const firstWeek=observed(7,28);firstWeek.rank_observations=firstWeek.rank_observations.slice(0,12);
  assert.equal(decide({...firstWeek,internal_evidence:{clicks:50,orders:5,spend:20,sales:150}}).code,
    'ad_position_test');
  assert.equal(decide({internal_evidence:{clicks:40,orders:4,spend:12,sales:100}}).code,
    'protect_efficient');
  assert.equal(decide({internal_evidence:{clicks:100,orders:20,spend:200,sales:1000}}).code,
    'protect_converting');
  assert.equal(decide({internal_evidence:{clicks:100,orders:5,spend:300,sales:500}}).code,
    'cost_review');
  assert.equal(decide({internal_evidence:{clicks:25,orders:0,spend:20,sales:0}}).code,
    'cost_review');
  assert.equal(decide({sources:['sif_competitor_gap'],current_competitor_gap:true,weekly_volume:900}).code,
    'trial_relevance');
  assert.equal(decide({sources:['sif_competitor_gap'],current_competitor_gap:false}).code,
    'observe');
  assert.equal(decide({...observed(7,36)}).scope,'advisory');
});

test('keyword decision keeps a reviewable group negative when a processed Exact is also present',()=>{
  const row={keyword:'kids cooking set',internal_evidence:{clicks:295,orders:17,spend:172.42,sales:382.92},
    actions:[
      {kind:'exact',action_key:'exact-old',processed_status:'already_exact_running',reviewable:false,ad_group_id:'g-good'},
      {kind:'negative',action_key:'negative-g-bad',processed_status:'',reviewable:true,ad_group_id:'g-bad',orders:0},
      {kind:'negative',action_key:'negative-g-bad',processed_status:'',reviewable:true,ad_group_id:'g-bad',orders:0},
      {kind:'bid_review',action_key:'bid-gap',reviewable:false,direction:'variant_rank_gap',target_id:'t1'},
    ]};
  const decision=model.keywordDecision(row,'2026-10-13');
  assert.equal(decision.verdict.title,'局部止损');
  assert.deepEqual(decision.operations.map(op=>[op.kind,op.label,op.countText,op.actions.map(a=>a.action_key)]),
    [['negative','否词','1组',['negative-g-bad']]]);
  assert.match(decision.verdict.reason,/广告组/);
  assert.doesNotMatch(decision.verdict.reason,/整词否定/);
});

test('keyword decision separates multiple scoped operations and never offers unsupported bid',()=>{
  const row={actions:[
    {kind:'negative',action_key:'n1',reviewable:true,ad_group_id:'g1'},
    {kind:'exact',action_key:'e1',reviewable:true,ad_group_id:'g2'},
    {kind:'bid_review',action_key:'b1',reviewable:true,direction:'consider_raise',target_id:'t1',ad_group_id:'g3'},
    {kind:'bid_review',action_key:'b2',reviewable:true,direction:'needs_rank',target_id:'t2',ad_group_id:'g3'},
  ]};
  const decision=model.keywordDecision(row,'2026-10-13');
  assert.equal(decision.verdict.title,'分组处理');
  assert.deepEqual(decision.operations.map(op=>op.label),['否词','精投','调价']);
  assert.deepEqual(decision.operations.find(op=>op.kind==='bid').actions.map(a=>a.target_id),['t1']);
  assert.equal(model.keywordDecision({actions:[row.actions[3]]},'2026-10-13').operations.length,0);
});

test('SIF-only exact intent remains a validation entry, not a specialist action',()=>{
  const row={keyword:'external candidate',sources:['sif_asin_signals'],weekly_volume:800,actions:[]};
  const decision=model.keywordDecision(row,'2026-10-13',{probeKey:'sif-probe:p1:k1'});
  assert.deepEqual(decision.operations.map(op=>[op.kind,op.label,op.status,op.actionKeys]),
    [['probe','精投','validation',['sif-probe:p1:k1']]]);
  assert.equal(model.keywordDecision(row,'2026-10-13').operations.length,0);
  assert.equal(model.keywordDecision({...row,actions:[{kind:'exact',action_key:'old',reviewable:false,
    processed_status:'already_exact_running'}]},'2026-10-13',{probeKey:'sif-probe:p1:k1'}).operations.length,0);
});

test('batch keyword preview accepts CSV/TXT, deduplicates, rejects ASIN and caps input',()=>{
  assert.deepEqual(model.parseKeywordBatch('keyword\n"kids knife set"\nKids  Knife Set\ntoddler kitchen tools').terms,
    ['kids knife set','toddler kitchen tools']);
  assert.deepEqual(model.parseKeywordBatch('kids knife,toddler knife').terms,
    ['kids knife','toddler knife']);
  assert.deepEqual(model.parseKeywordBatch('volume,keyword\n120,kids knife\n300,kids bowl').terms,
    ['kids knife','kids bowl']);
  assert.ok(model.parseKeywordBatch('kids knife\nB012345678').errors.length);
  assert.ok(model.parseKeywordBatch(Array.from({length:201},(_,i)=>`word ${i}`).join('\n')).errors.length);
});

test('Exact plans count as reviewable while source-processed rows leave the default queue', () => {
  const actions=[
    {action_key:'exact-plan',profile_id:'p1',kind:'exact',reviewable:true,executable:false,spend:15},
    {action_key:'processed',profile_id:'p1',kind:'negative',reviewable:false,executable:false,
      processed_status:'already_exact_negative',spend:30},
    {action_key:'gap',profile_id:'p1',kind:'exact',reviewable:false,executable:false,spend:40},
  ];
  assert.equal(actionCount(actions),1);
  assert.deepEqual(globalActionQueue(actions,{p1:'s1'},'s1','all').map(a=>a.action_key),['exact-plan']);
  assert.deepEqual(globalActionQueue(actions,{p1:'s1'},'s1','processed').map(a=>a.action_key),['processed']);
  assert.deepEqual(globalActionQueue(actions,{p1:'s1'},'s1','gaps').map(a=>a.action_key),['gap']);
});

test('live pending keyword merges with immutable snapshot without erasing evidence', () => {
  const board=[{id:'k1',keyword:'kids scissors',rank_observations:[{observed_date:'2026-10-12',rank:4}]}];
  const live=[{id:'k1',keyword:'kids scissors',tracking:{state:'active',pending:'remove'}},
    {id:'k2',keyword:'manual term',tracking:{state:'candidate',pending:'add'}}];
  const merged=mergeKeywordRows(board,live);
  assert.equal(merged[0].rank_observations.length,1);
  assert.equal(merged[0].tracking.pending,'remove');
  assert.equal(merged[1].keyword,'manual term');
});

test('rank series preserves missing days and original ad position', () => {
  const days=rankSeries([{observed_date:'2026-10-12',channel:'natural',rank:12,state:'absolute_rank'},
    {observed_date:'2026-10-12',channel:'advertising',rank:9,state:'absolute_rank',display:'p1,9/12'}], '2026-10-11','2026-10-12');
  assert.equal(days[0].natural,null);
  assert.equal(days[1].natural,12);
  assert.equal(days[1].advertising,9);
  assert.equal(days[1].adDisplay,'p1,9/12');
  const invalid=rankSeries([{observed_date:'2026-10-11',channel:'natural',rank:null,state:'absolute_rank'},
    {observed_date:'2026-10-12',channel:'advertising',rank:0,state:'absolute_rank'}],
    '2026-10-11','2026-10-12');
  assert.equal(invalid[0].natural,null);
  assert.equal(invalid[1].advertising,null);
});

test('rank display follows the two complete SIF weeks rather than trailing fourteen days', () => {
  assert.equal(typeof model.rankWindow, 'function');
  assert.deepEqual(model.rankWindow({}, '2026-10-13'), ['2026-09-27','2026-10-10']);
  assert.deepEqual(model.rankWindow({rank_window:['2026-09-20','2026-10-03']}, '2026-10-13'),
    ['2026-09-20','2026-10-03']);
});

test('keyword list surfaces genuine two-week curves without hiding missing tracked words', () => {
  assert.equal(typeof model.rankCoverage, 'function');
  assert.equal(typeof model.sortKeywordRows, 'function');
  const dates=['2026-09-27','2026-09-28','2026-09-29','2026-09-30','2026-10-01',
    '2026-10-04','2026-10-05','2026-10-06','2026-10-07','2026-10-08'];
  const complete={keyword:'ranked',rank_window:['2026-09-27','2026-10-10'],
    rank_observations:dates.map((date,i)=>({observed_date:date,channel:'natural',
      state:'absolute_rank',rank:20-i}))};
  const missing={keyword:'missing',rank_window:['2026-09-27','2026-10-10'],
    rank_observations:[{observed_date:'2026-10-08',channel:'natural',
      state:'reported_position',display:'p1,8/48'}]};
  assert.equal(model.rankCoverage(complete,'2026-10-13').twoWeek,true);
  assert.equal(model.rankCoverage(missing,'2026-10-13').twoWeek,false);
  assert.deepEqual(model.sortKeywordRows([missing,complete],'2026-10-13').map(row=>row.keyword),
    ['ranked','missing']);
  assert.deepEqual(model.sortKeywordRows([{...missing,pinned:1},complete],'2026-10-13')
    .map(row=>row.keyword),['missing','ranked']);
});

test('whole week hover includes every selected metric in original units', () => {
  assert.equal(weekHoverText({label:'W40',units:14,ad_spend:12.5}, ['units','ad_spend'],
    {units:'销量',ad_spend:'广告花费'}), 'W40 · 销量 14 · 广告花费 12.5');
});

test('ASIN click ring uses one measured week and refuses conflicting or missing inputs', () => {
  const valid={label:'W41',quality:'measured',sessions_total:2975,ad_clicks:1872,natural_sessions_est:1103};
  assert.deepEqual(model.trafficComposition(valid),{
    label:'W41',total:2975,advertising:1872,natural:1103,
    naturalPct:1103/2975,advertisingPct:1872/2975,
  });
  assert.equal(model.trafficComposition({...valid,quality:'missing'}),null);
  assert.equal(model.trafficComposition({...valid,ad_clicks:3000}),null);
  assert.equal(model.trafficComposition({...valid,natural_sessions_est:1104}),null);
  assert.equal(model.trafficComposition({...valid,sessions_total:0,ad_clicks:0,natural_sessions_est:0}),null);
});

test('ad spend composition reports only measured SP, SB and unclassified residual', () => {
  const valid={quality:'measured',ad_spend:786.12,sp_spend:551.53,sb_spend:77.41};
  const result=model.adSpendComposition(valid);
  assert.equal(result.total,786.12);
  assert.equal(result.sp,551.53);
  assert.equal(result.sb,77.41);
  assert.ok(Math.abs(result.other-157.18)<1e-9);
  assert.ok(Math.abs(result.spPct+result.sbPct+result.otherPct-1)<1e-9);
  assert.equal(model.adSpendComposition({...valid,sb_spend:null}),null);
  assert.equal(model.adSpendComposition({...valid,sp_spend:800}),null);
});

test('rank and Lingxing evidence are mutually exclusive while rank channel remains focusable', () => {
  const natural=model.toggleKeywordPanel(null,'term-1','rank','natural');
  assert.deepEqual(natural,{id:'term-1',kind:'rank',focus:'natural'});
  const advertising=model.toggleKeywordPanel(natural,'term-1','rank','advertising');
  assert.deepEqual(advertising,{id:'term-1',kind:'rank',focus:'advertising'});
  assert.equal(model.toggleKeywordPanel(advertising,'term-1','rank','advertising'),null);
  const internal=model.toggleKeywordPanel(natural,'term-1','internal');
  assert.deepEqual(internal,{id:'term-1',kind:'internal',focus:null});
  assert.deepEqual(model.toggleKeywordPanel(internal,'term-2','rank','natural'),
    {id:'term-2',kind:'rank',focus:'natural'});
});

test('tooltip flips and clamps when a weekly or rank point is at the viewport edge', () => {
  const corner=model.tooltipPosition({x:990,y:590,width:300,height:120,
    viewportWidth:1000,viewportHeight:600});
  assert.deepEqual(corner,{left:678,top:458});
  assert.deepEqual(model.tooltipPosition({x:10,y:10,width:300,height:120,
    viewportWidth:1000,viewportHeight:600}),{left:22,top:22});
  const narrow=model.tooltipPosition({x:315,y:200,width:450,height:80,
    viewportWidth:320,viewportHeight:400});
  assert.equal(narrow.left,12);
});

test('outer product tabs replace their click listener after an inner-view redraw', () => {
  const tab={onclick:null};
  let calls=0;
  model.bindSingleClick(tab,()=>{calls+=1});
  model.bindSingleClick(tab,()=>{calls+=1});
  tab.onclick();
  assert.equal(calls,1);
});

test('keyword radar excludes ASIN targets and separates SIF assets from internal-only queries', () => {
  const rows=[
    {keyword:'kids knife set',sources:['sif_asin_signals','lingxing_search_term'],tracking:{state:'active'}},
    {keyword:'little tikes',sources:['sif_asin_signals'],tracking:{state:'active'}},
    {keyword:'other term',sources:['lingxing_search_term'],tracking:{state:'candidate'}},
    {keyword:'B0FGTVP62B',sources:['lingxing_search_term'],tracking:{state:'candidate'}},
  ];
  assert.deepEqual(model.filterKeywordRadar(rows,'core').map(row=>row.keyword),['kids knife set','little tikes']);
  assert.deepEqual(model.filterKeywordRadar(rows,'all').map(row=>row.keyword),['kids knife set','little tikes','other term']);
  assert.deepEqual(model.filterKeywordRadar(rows,'internal').map(row=>row.keyword),['other term']);
});

test('rank digest uses only real absolute observations, reports change and gaps', () => {
  const row={rank_window:['2026-09-27','2026-10-10'],rank_observations:[
    {observed_date:'2026-09-27',channel:'natural',state:'absolute_rank',rank:15},
    {observed_date:'2026-09-28',channel:'advertising',state:'reported_position',display:'p2,4/12'},
    {observed_date:'2026-10-06',channel:'natural',state:'absolute_rank',rank:8},
    {observed_date:'2026-10-10',channel:'natural',state:'absolute_rank',rank:7},
  ]};
  const digest=model.rankDigest(row,'2026-10-13');
  assert.equal(digest.natural.latest,7);
  assert.equal(digest.natural.improvement,8);
  assert.equal(digest.natural.best,7);
  assert.equal(digest.natural.worst,15);
  assert.equal(digest.natural.days,3);
  assert.equal(digest.advertising.latest,null);
  assert.equal(digest.advertising.days,0);
});

test('external-only SIF terms require validation; existing specialist exact action is linked once', () => {
  const noInternal={id:'asset-1',keyword:'little tikes',sources:['sif_asin_signals'],
    tracking:{state:'active'},internal_evidence:null};
  assert.equal(model.keywordLane(noInternal),'external_unverified');
  const withAction={...noInternal,internal_evidence:{clicks:20,orders:3},
    actions:[{kind:'exact',action_key:'exact-1',reviewable:true}]};
  assert.equal(model.keywordLane(withAction),'specialist_exact');
  assert.equal(model.keywordActionKey(withAction),'exact-1');
  assert.equal(model.keywordLane({...withAction,actions:[{kind:'exact',action_key:'gap',reviewable:false,
    blocked_reason:'ambiguous_promoted_asin'}]}),'specialist_gap');
  assert.equal(model.probeActionKey('p1',noInternal),'sif-probe:p1:asset-1');
});

test('advertising summary ratios derive from merged raw totals, never average source ratios', () => {
  const result=model.adMetricSummary({impressions:1000,clicks:25,spend:20,orders:2,sales:100,
    source_scopes:[{ctr:.9,acos:.8},{ctr:.01,acos:.02}]});
  assert.deepEqual(result,{impressions:1000,clicks:25,ctr:.025,cpc:.8,acos:.2,
    spend:20,sales:100,orders:2,cpa:10,cvr:.08});
  const zero=model.adMetricSummary({impressions:0,clicks:0,spend:12,orders:0,sales:0});
  assert.equal(zero.ctr,null);
  assert.equal(zero.cpc,null);
  assert.equal(zero.acos,null);
  assert.equal(zero.cpa,null);
  assert.equal(zero.cvr,null);
});

test('advertising source drawer groups repeated campaign/ad-group records without losing totals', () => {
  const groups=model.adSourceGroups({kind:'negative',source_rows:[
    {campaign_id:'c1',campaign_name:'活动甲',ad_group_id:'g1',ad_group_name:'组甲',
      record_id:'r1',match_type:'broad',impressions:100,clicks:10,spends:5,orders:1,sales:20},
    {campaign_id:'c1',campaign_name:'活动甲',ad_group_id:'g1',ad_group_name:'组甲',
      record_id:'r2',match_type:'phrase',impressions:200,clicks:20,spends:8,orders:0,sales:0},
  ]});
  assert.equal(groups.length,1);
  assert.equal(groups[0].recordCount,2);
  assert.deepEqual(groups[0].matchTypes,['broad','phrase']);
  assert.deepEqual(model.adMetricSummary(groups[0]),{impressions:300,clicks:30,ctr:.1,
    cpc:13/30,acos:13/20,spend:13,sales:20,orders:1,cpa:13,cvr:1/30});
});

test('in-running Exact matches stay separate from non-Exact candidate source totals',()=>{
  const action={kind:'exact',clicks:180,spend:90,orders:9,sales:300,
    existing_exact_matches:[{record_id:'exact-1',campaign_id:'c2',ad_group_id:'g2',
      target_match_type:'exact',clicks:4,spends:2,orders:1,sales:20}]};
  assert.equal(model.adMetricSummary(action).clicks,180);
  assert.equal(model.adExactMatchSummary(action).clicks,4);
  assert.equal(model.adExactMatchSummary(action).acos,.1);
  assert.equal(model.adExactMatchSummary({...action,existing_exact_matches:[]}).clicks,null);
});

test('SIF page position remains page position, not a fabricated absolute rank', () => {
  assert.deepEqual(model.rankPresentation({latest:null,latestDate:null,days:0},'p2,7/48'),{
    kind:'page',label:'第 2 页 · 第 7 位',shortLabel:'P2 · 7',detail:'SIF 页位快照 · 每页 48 位；非绝对名次',days:0});
  assert.deepEqual(model.rankPresentation({latest:8,latestDate:'2026-10-10',days:11},'p1,9/48'),{
    kind:'absolute',label:'#8',detail:'10-10 末次绝对名次 · 11/14 天实测',days:11});
  assert.equal(model.rankPresentation({latest:null,days:0},'').label,'未观测');
  assert.deepEqual(model.rankPresentation({latest:null,days:0},'P2#4'),{
    kind:'page',label:'第 2 页 · 第 4 位',shortLabel:'P2 · 4',detail:'SIF 页位快照 · 每页位数未知；非绝对名次',days:0});
});

test('active Exact rank asymmetry yields conditional bid review, not a bid mutation', () => {
  const dates=['2026-09-27','2026-09-28','2026-09-29','2026-09-30','2026-10-01',
    '2026-10-04','2026-10-05','2026-10-06','2026-10-07','2026-10-08'];
  const base={rank_window:['2026-09-27','2026-10-10'],rank_14d_state:'verified',
    actions:[{kind:'exact',processed_status:'already_exact_running'}]};
  const natural=dates.map(date=>({observed_date:date,channel:'natural',state:'absolute_rank',rank:8}));
  const weakAd=dates.map(date=>({observed_date:date,channel:'advertising',state:'absolute_rank',rank:35}));
  const first=model.keywordBidReview({...base,rank_observations:[...natural,...weakAd]},'2026-10-13');
  assert.equal(first.kind,'ad_weak');
  assert.equal(first.executable,false);
  assert.equal(first.bid,null);
  assert.match(first.note,/目标级/);
  const strongAd=dates.map(date=>({observed_date:date,channel:'advertising',state:'absolute_rank',rank:3}));
  const weakNatural=dates.map(date=>({observed_date:date,channel:'natural',state:'absolute_rank',rank:60}));
  assert.equal(model.keywordBidReview({...base,rank_observations:[...weakNatural,...strongAd]},'2026-10-13').kind,'organic_weak');
  assert.equal(model.keywordBidReview({...base,rank_observations:natural,ad_rank_display:'p2,3/12'},'2026-10-13').kind,'ad_unmeasured');
  assert.equal(model.keywordBidReview({...base,rank_14d_state:'source_failed',rank_observations:[]},'2026-10-13').kind,'coverage_gap');
  assert.equal(model.keywordBidReview({...base,actions:[],rank_observations:[...natural,...weakAd]},'2026-10-13'),null);
  const secondWeekOnly=natural.filter(point=>point.observed_date>='2026-10-04');
  assert.equal(model.keywordBidReview({...base,rank_observations:[...secondWeekOnly,
    ...weakAd.filter(point=>point.observed_date>='2026-10-04')]},'2026-10-13').kind,'monitor');
  assert.equal(model.keywordBidReview({...base,rank_14d_state:'source_failed',
    rank_observations:[...natural,...weakAd]},'2026-10-13').kind,'ad_weak');
});

test('single-ASIN supplement overrides stale rank status and observations in either direction',()=>{
  const old=[{id:'k1',rank_14d_state:'verified',rank_observations:[{observed_date:'2026-09-27',channel:'natural',state:'absolute_rank',rank:8}]}];
  const fail=model.mergeKeywordRows(old,[{id:'k1',rank_14d_state:'source_failed',rank_observations:[]}]);
  assert.equal(fail[0].rank_14d_state,'source_failed');
  assert.equal(fail[0].rank_observations.length,0);
  const recovered=model.mergeKeywordRows([{...old[0],rank_14d_state:'source_failed'}],
    [{id:'k1',rank_14d_state:'verified',rank_observations:old[0].rank_observations}]);
  assert.equal(recovered[0].rank_14d_state,'verified');
});
