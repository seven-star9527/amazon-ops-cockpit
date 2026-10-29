(() => {
  const board = JSON.parse(document.getElementById('board-data').textContent);
  const products = Object.values(board.products || {});
  const state = {scope:'problem', shop:'all', query:'', selected:null, view:'product', domain:'growth', growthView:'rank', keywordSearch:'', expanded:null,expandedAction:null,
    keywordLimit:12, keywordFilter:'core', adLimit:40, adFilter:'all', queueLimit:60,bidLimit:20,bidFocus:null,weeklyOpen:false,
    metrics:new Set(['units','total_cvr','ad_cvr','return_rate']), review:{connected:false,version:0,items:{}},
    tracking:{version:0,byProduct:{}},manualSif:window.B_SUPPLEMENTS||{},manualSifLoading:false,
    keywordManageOpen:false,keywordImportText:'',keywordImportPreview:null,keywordImportProduct:null,bidRank:null,
    decisionDrawer:null,inventoryPreview:{},
    pmcTab:'ship',pmcTier:'all',pmcQuery:'',pmcChoice:{},pmcCustom:{},pmcEditor:{},
    pmcFeedback:{},pmcFromQueue:false,pmcRange:90,pmcPin:null,pmcPinProduct:null,pmcView:null,pmcHoverKey:null,
    pmcLibrary:null,pmcModal:null,pmcDraft:null,
    sidebarCollapsed:false,lastView:null,navOrigin:'catalog',theme:'dark'};
  let drawerReturnFocus=null;
  let verdictTipTrigger=null,verdictTipPinned=false;
  const metricLabels = {
    sales:'销售额', avg_price:'均价', units:'销量', daily_units:'日均销量',
    acoas:'ACoAS', acos:'ACOS', cpc:'CPC', ad_spend:'广告花费', impressions:'广告曝光',
    ad_clicks:'广告点击', ad_click_rate:'广告点击率', sessions_total:'总点击',
    natural_sessions_est:'自然点击', natural_order_share:'自然单占比', ad_order_share:'广告单占比',
    total_cvr:'总转化率', ad_cvr:'广告转化率', return_rate:'退货率'
  };
  const metricMeta = {
    sales:{axis:'value',format:'money',color:'#4f8ff7'},
    avg_price:{axis:'value',format:'money',color:'#d9a441'},
    units:{axis:'value',format:'int',color:'#25c4ad',bar:true},
    daily_units:{axis:'value',format:'decimal',color:'#65d6c0'},
    acoas:{axis:'percent',format:'pct',color:'#e2a33d'},
    acos:{axis:'percent',format:'pct',color:'#f06a6a'},
    cpc:{axis:'value',format:'money',color:'#c76ad6'},
    ad_spend:{axis:'value',format:'money',color:'#f28b5c'},
    impressions:{axis:'value',format:'int',color:'#9b8cff'},
    ad_clicks:{axis:'value',format:'int',color:'#f2b35c'},
    ad_click_rate:{axis:'percent',format:'pct',color:'#d58ae8'},
    sessions_total:{axis:'value',format:'int',color:'#6fa8dc'},
    natural_sessions_est:{axis:'value',format:'int',color:'#4fc3a1'},
    natural_order_share:{axis:'percent',format:'pct',color:'#38d6b0'},
    ad_order_share:{axis:'percent',format:'pct',color:'#b07de0'},
    total_cvr:{axis:'percent',format:'pct',color:'#38bdf8'},
    ad_cvr:{axis:'percent',format:'pct',color:'#a874ff'},
    return_rate:{axis:'percent',format:'pct',color:'#e58aa8'}
  };
  const DEFAULT_METRICS = ['units','total_cvr','ad_cvr','return_rate'];
  const colors = Object.fromEntries(Object.entries(metricMeta).map(([key,meta])=>[key,meta.color]));
  const evidenceLabels = {sellable:'FBA 可售',inbound_shipped:'已发在途',daily_units:'近四周日均销量',days_cover:'估算可售天数',age_181_plus:'181 天以上库存',excess_estimate:'预估冗余',storage_cost_next_month:'下月预估仓储费',clicks:'广告点击',spend:'广告花费',orders:'广告订单',sales:'广告销售额',acos:'广告 ACOS',baseline_cvr:'前三周总转化率',current_cvr:'本周总转化率',traffic_change:'总点击变化',week:'自然周',returns:'退货数',units:'销量',ratio:'退货/销量参考比',rating:'评分',reviews:'评论数'};
  const escapeHtml = v => String(v ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const fmt = (v,d=0) => v === null || v === undefined || Number.isNaN(Number(v)) ? '—' : Number(v).toLocaleString('zh-CN',{maximumFractionDigits:d});
  const pct = v => v === null || v === undefined ? '—' : `${(Number(v)*100).toFixed(1)}%`;
  const sevTag = issue => issue?.severity === 'critical' || issue?.severity === 'high' ? 'red' : issue?.severity === 'medium' ? 'amber' : 'muted';
  const tagName = domain => ({advertising:'广告',inventory:'库存',listing:'Listing'}[domain] || domain);
  const queueReasonLabels={below_sales_threshold:'销量未到自动查询门槛',sales_data_gap:'销量数据缺口，未自动查询',
    sif_call_budget:'本轮 SIF 配额排队',operator_priority:'运营优先',stable:'销量稳定',recent_growth:'近期增长'};
  const rankStateLabels={verified:'部分跟踪词跨两周有真实观测，并非全部日期齐全',partial:'部分词或日期有真实观测',no_rows:'没有可匹配的排名观测',
    no_campaign:'没有可查询的广告活动',no_core:'没有跟踪词',source_failed:'SIF 排名读取失败',
    replay_missing:'历史重放缺少排名源响应',deferred_rank_budget:'排名查询本轮延后',
    current_snapshot_only:'只有当前排名快照',shape_mismatch:'SIF 返回结构不符'};
  const activeProducts = () => products.filter(p => state.shop === 'all' || String(p.sid) === state.shop);
  const visibleProducts = () => selectProducts(activeProducts(), state.scope, state.query);
  const selectedProduct = () => products.find(p => p.key === state.selected);
  const localDate = iso => iso ? new Date(iso).toLocaleString('zh-CN',{dateStyle:'short',timeStyle:'short'}) : '—';
  const productProfile = product => Object.entries(board.profile_to_sid||{}).find(([,sid])=>String(sid)===String(product?.sid))?.[0]||null;
  const productKeywords = product => sortKeywordRows(mergeKeywordRows(
    mergeKeywordRows(keywordRows(product),state.manualSif[product.key]?.terms?.map(term=>({
      ...term,rank_14d_state:state.manualSif[product.key]?.rank_state||term.rank_14d_state||'no_rows'}))),
    state.tracking.byProduct[product.key]?.terms),board.as_of_date||board.fetched_at.slice(0,10));
  const probeRows = product => {
    if(board.status?.ads_diagnosis?.source_complete!==true||product.keyword_state?.sif_state!=='verified')return [];
    const frozenIds=new Set((product.keyword_state?.terms||[]).map(row=>row.id));
    return filterKeywordRadar(productKeywords(product),'opportunity')
      .filter(row=>row.id&&frozenIds.has(row.id)&&['active','candidate'].includes(row.tracking?.state)&&
        (row.current_competitor_gap===true||Number(row.weekly_volume)>0)&&
        !row.internal_evidence&&!row.actions?.some(a=>a.kind==='exact')&&
        !(row.keyword_targets||[]).some(t=>t.match_type==='exact'&&
          ['target_state','campaign_state','ad_group_state'].every(field=>t[field]==='enabled')));
  };

  function applyTheme() {
    const theme=state.theme==='light'?'light':'dark';
    if(document.documentElement)document.documentElement.dataset.theme=theme;
    const brand=document.getElementById('brand-theme');
    if(brand&&typeof brand.setAttribute==='function')brand.setAttribute('aria-label',theme==='light'?'切换到夜间主题':'切换到日间主题');
  }

  function initialize() {
    try{state.theme=(typeof localStorage!=='undefined'&&localStorage.getItem('amazon-ops-b-theme'))||'dark'}catch{state.theme='dark'}
    try{state.sidebarCollapsed=typeof localStorage!=='undefined'&&localStorage.getItem('amazon-ops-b-sidebar')==='collapsed'}catch{state.sidebarCollapsed=false}
    applyTheme();
    document.getElementById('brand-theme')?.addEventListener('click',()=>{const scroll=window.scrollY;state.pmcPin=null;state.theme=state.theme==='light'?'dark':'light';applyTheme();try{if(typeof localStorage!=='undefined')localStorage.setItem('amazon-ops-b-theme',state.theme)}catch{}render();window.scrollTo?.(0,scroll)});
    document.getElementById('sidebar-toggle')?.addEventListener('click',()=>{state.sidebarCollapsed=!state.sidebarCollapsed;try{if(typeof localStorage!=='undefined')localStorage.setItem('amazon-ops-b-sidebar',state.sidebarCollapsed?'collapsed':'expanded')}catch{}render()});
    document.querySelectorAll('.side-mode').forEach(el=>el.addEventListener('click',()=>{state.view=el.dataset.view;state.navOrigin=null;state.decisionDrawer=null;state.pmcFromQueue=false;render()}));
    document.addEventListener?.('click',event=>{
      const day=event.target?.closest?.('[data-pmc-day]');
      if(day){event.stopPropagation();pmcToggleDay(day.dataset.pmcSource||'timeline',Number(day.dataset.pmcDay),event);return}
      const ship=event.target?.closest?.('[data-pmc-ship]');
      if(ship){event.stopPropagation();pmcToggleShip(ship.dataset.pmcShip,event);return}
      if(event.target?.closest?.('[data-pmc-season-add]')){
        document.querySelector('.pmc-season-rows')?.insertAdjacentHTML('beforeend',pmcSeasonRow({from:'',to:'',multiplier:2}));
        pmcSyncSeasonMode();return;
      }
      if(event.target?.closest?.('[data-pmc-season-remove]')){
        event.target.closest('.pmc-season-row')?.remove();pmcSyncSeasonMode();
      }
    });
    document.addEventListener?.('pointermove',event=>{
      const chart=event.target?.closest?.('#pmc-timeline-chart');
      if(!chart||state.pmcPin)return;
      const band=event.target?.closest?.('.pmc-eta-band[data-pmc-ship]');
      if(band){pmcHoverShip(band.dataset.pmcShip,event);return}
      const day=event.target?.closest?.('[data-pmc-day][data-pmc-source="timeline"]');
      if(day){pmcHoverTimeline(Number(day.dataset.pmcDay),Number(day.dataset.pmcX),event);return}
      pmcHideHover();
    });
    document.addEventListener?.('pointerout',event=>{
      const chart=event.target?.closest?.('#pmc-timeline-chart');
      if(!chart||state.pmcPin)return;
      if(event.relatedTarget&&chart.contains(event.relatedTarget))return;
      pmcHideHover();
    });
    const shopMap = new Map(products.map(p=>[String(p.sid),p.shop]));
    document.getElementById('shop-filter').innerHTML = '<option value="all">全部店铺</option>' + [...shopMap].map(([sid,name])=>`<option value="${escapeHtml(sid)}">${escapeHtml(name)}</option>`).join('');
    document.getElementById('shop-filter').addEventListener('change', e => {state.shop=e.target.value;
      state.selected=activeProducts().find(p=>p.key===state.selected)?.key || activeProducts()[0]?.key || null;render();loadTracking(selectedProduct());loadSupplement(selectedProduct())});
    document.getElementById('product-search').addEventListener('input', e=>{state.query=e.target.value;renderCatalog()});
    document.getElementById('run-caption').textContent = board.inventory_batch ?
      `库存 ${board.inventory_batch.as_of} · 广告/Listing ${board.as_of_date}` :
      `数据截至 ${board.as_of_date||board.fetched_at.slice(0,10)}`;
    document.getElementById('coverage-badge').textContent = `${board.coverage?.problem ?? 0} 个问题 ASIN / ${board.coverage?.active ?? 0} 在售`;
    const lingxingTransport=board.status?.lingxing_transport;
    const sifTransport=board.status?.sif_transport;
    const provenance=['same_day_b_raw_resume_live','same_day_b_complete_extend_live'].includes(sifTransport?.state)?
      `领星同日原始响应重算 · SIF 同日复用 ${fmt(sifTransport.reused_calls)} 次 · 新查 ${fmt(sifTransport.live_calls)} 次`:
      lingxingTransport?.state==='same_day_b_raw_replay'?
        `领星同日重算 · SIF ${sifTransport?'同日重算':'本轮在线读取'}`:
      sifTransport?'SIF 同日重算 · 非本轮在线读取':'';
    const lx = board.status?.performance?.state === 'verified' ? '<span class="ok">领星数据已核对</span>' : '<span class="warn">领星部分缺口</span>';
    const sf = board.status?.sif?.state === 'verified' ? `<span class="ok">SIF 已连 · ${board.status.sif.successful_products}/${board.status.sif.total_active} 在售</span>` :
      `<span class="warn">SIF ${board.status?.sif?.successful_products||0}/${board.status?.sif?.total_active||0} 成功 · 部分延后</span>`;
    const adReady=board.status?.ads_diagnosis?.source_complete;
    const adRows=Object.entries(board.status||{}).filter(([key])=>key.startsWith('search_terms:')).reduce((sum,[,value])=>sum+(Number(value.rows)||0),0);
    const ads=adReady?`<span class="ok">广告搜索词 ${fmt(adRows)} 条 · 专业规则 ${escapeHtml((board.status.ads_diagnosis.specialist_sha256||'').slice(0,8))}</span>`:
      '<span class="warn">广告来源不完整 · 动作只读</span>';
    const sourceOkay=board.status?.performance?.state==='verified'&&adReady&&board.status?.sif?.state==='verified';
    const sourceCount=`SIF ${fmt(board.status?.sif?.successful_products||0)}/${fmt(board.status?.sif?.total_active||0)}`;
    const inventoryNote=board.inventory_batch?`<span class="ok">库存 ${escapeHtml(board.inventory_batch.as_of)} · ${fmt(board.inventory_batch.matched_products)} 个原有 ASIN 匹配</span><br>`:'';
    document.getElementById('source-line').innerHTML = `<details class="source-status"><summary class="${sourceOkay?'ok':'warn'}">${board.inventory_batch?'库存新批次 · 广告旧批次':sourceOkay?'来源已核对':'来源有缺口'} · ${sourceCount}</summary><div class="source-detail">${inventoryNote}${board.inventory_batch?.mixed_source_dates?`<span class="warn">广告/Listing 仍为 ${escapeHtml(board.as_of_date)}，不可与库存日期当作同日比较</span><br>`:''}${provenance?`<span class="warn">${escapeHtml(provenance)}</span><br>`:''}${lx} · ${ads}<br>${sf}<br><span>批次 ${escapeHtml(board.run_id)}</span></div></details>`;
    document.addEventListener?.('click',event=>{if(verdictTipPinned&&!event.target?.closest?.('[data-verdict-tip]'))hideVerdictTooltip(true)});
    document.addEventListener?.('keydown',event=>{if(event.key==='Escape'){hideVerdictTooltip(true);state.pmcPin=null;pmcHidePin()}});
    document.getElementById('review-mode').textContent = window.B_REVIEW ? (state.review.connected?'审核已连接':'审核未连接 · 只读') : '只读快照';
    const first = selectProducts(products,'problem')[0] || selectProducts(products,'active')[0] || products[0];
    state.selected = first?.key || null;
    document.addEventListener?.('keydown',event=>{if(event.key==='Escape'&&state.decisionDrawer)closeDecisionDrawer()});
    render();
    if(window.B_REVIEW){loadReview();if(first){loadTracking(first);loadSupplement(first)}}
  }

  async function loadSupplement(product){
    if(!window.B_REVIEW||!product)return;
    try{
      const response=await fetch(`/api/sif-supplement?sid=${encodeURIComponent(product.sid)}&asin=${encodeURIComponent(product.asin)}`,
        {headers:{'X-Local-Session':window.B_REVIEW.token}});
      if(!response.ok)throw new Error('supplement unavailable');
      const data=await response.json();
      if(data.query_id)state.manualSif[product.key]=data;
      if(state.selected===product.key)render();
    }catch{/* Immutable board remains usable without a supplement. */}
  }

  async function loadTracking(product){
    if(!window.B_REVIEW||!product)return;
    try{
      const response=await fetch(`/api/tracking?sid=${encodeURIComponent(product.sid)}&asin=${encodeURIComponent(product.asin)}`,
        {headers:{'X-Local-Session':window.B_REVIEW.token}});
      if(!response.ok)throw new Error('tracking unavailable');
      const data=await response.json();
      if(data.run_id!==board.run_id)throw new Error('stale tracking');
      state.tracking.version=data.version;state.tracking.byProduct[product.key]=data;
      if(state.selected===product.key)render();
    }catch{state.tracking.byProduct[product.key]={unavailable:true};if(state.selected===product.key)render()}
  }

  async function saveTracking(product,keyword,action){
    const live=state.tracking.byProduct[product.key];
    if(!window.B_REVIEW||!state.review.connected||live?.unavailable)return;
    const selected=action==='add'&&!keyword ? (window.prompt('添加下轮开始跟踪的关键词（一次一个）')||'').trim() : keyword;
    if(!selected)return;
    try{
      const response=await fetch('/api/tracking',{method:'POST',headers:{'Content-Type':'application/json','X-Local-Session':window.B_REVIEW.token},
        body:JSON.stringify({run_id:board.run_id,sid:product.sid,asin:product.asin,keyword:selected,action,
          expected_version:state.tracking.version})});
      if(response.status===409){await loadTracking(product);window.alert('跟踪词已在别处更新，请核对后重试。');return}
      if(!response.ok)throw new Error('save failed');
      await loadTracking(product);
    }catch{window.alert('跟踪变更未保存，请确认本批次审核服务仍在运行。')}
  }

  async function saveTrackingBulk(product){
    const preview=state.keywordImportPreview;
    if(!window.B_REVIEW||!state.review.connected||!preview||preview.errors.length||!preview.terms.length||
       state.keywordImportProduct!==product.key)return;
    try{
      const response=await fetch('/api/tracking/bulk',{method:'POST',headers:{'Content-Type':'application/json',
        'X-Local-Session':window.B_REVIEW.token},body:JSON.stringify({run_id:board.run_id,sid:product.sid,
          asin:product.asin,keywords:preview.terms,action:'add',expected_version:state.tracking.version})});
      if(response.status===409){await loadTracking(product);window.alert('词库已更新，请检查预览后重试。');return}
      if(!response.ok){const detail=await response.json().catch(()=>({}));throw new Error(detail.detail||'未保存')}
      state.keywordImportText='';state.keywordImportPreview=null;state.keywordImportProduct=null;
      await loadTracking(product);
    }catch(error){window.alert(`批量跟踪词未保存：${error.message}`)}
  }

  async function savePriority(product,active){
    if(!window.B_REVIEW||!state.review.connected)return;
    try{
      const response=await fetch('/api/sif-priority',{method:'POST',headers:{'Content-Type':'application/json','X-Local-Session':window.B_REVIEW.token},
        body:JSON.stringify({run_id:board.run_id,sid:product.sid,asin:product.asin,active,
          expected_version:state.tracking.version})});
      if(response.status===409){await loadTracking(product);window.alert('查询优先级已在别处更新，请核对后重试。');return}
      if(!response.ok)throw new Error('save failed');
      await loadTracking(product);
    }catch{window.alert('SIF 优先级未保存，请确认本批次审核服务仍在运行。')}
  }

  async function saveCompetitor(product,competitorAsin,action){
    const live=state.tracking.byProduct[product.key];
    if(!window.B_REVIEW||!state.review.connected||live?.unavailable)return;
    const selected=action==='add'&&!competitorAsin?
      (window.prompt('添加下轮开始跟踪的竞品 ASIN（同父体最多查询 3 个）')||'').trim().toUpperCase():competitorAsin;
    if(!selected)return;
    if(!/^B0[A-Z0-9]{8}$/.test(selected)){window.alert('请输入有效的 B0 开头 10 位 ASIN。');return}
    try{
      const response=await fetch('/api/competitors',{method:'POST',headers:{'Content-Type':'application/json',
        'X-Local-Session':window.B_REVIEW.token},body:JSON.stringify({run_id:board.run_id,sid:product.sid,
          asin:product.asin,competitor_asin:selected,action,expected_version:state.tracking.version})});
      if(response.status===409){await loadTracking(product);window.alert('竞品池已在别处更新，请核对后重试。');return}
      if(!response.ok)throw new Error('save failed');
      await loadTracking(product);
    }catch{window.alert('竞品变更未保存，请确认本批次审核服务仍在运行。')}
  }

  async function querySif(product){
    if(!window.B_REVIEW?.sif_available||state.manualSifLoading)return;
    state.manualSifLoading=true;refreshDomain();
    try{
      const response=await fetch('/api/sif-query',{method:'POST',headers:{'Content-Type':'application/json',
        'X-Local-Session':window.B_REVIEW.token},body:JSON.stringify({run_id:board.run_id,sid:product.sid,asin:product.asin})});
      if(!response.ok)throw new Error('sif query failed');
      state.manualSif[product.key]=await response.json();
      await loadTracking(product);
    }catch{window.alert('本品 SIF 查询未完成；旧批次数据不变。请检查 SIF 授权或稍后重试。')}
    finally{state.manualSifLoading=false;if(state.selected===product.key)render()}
  }

  async function loadReview(){
    try{
      const response=await fetch('/api/decisions',{headers:{'X-Local-Session':window.B_REVIEW.token}});
      if(!response.ok)throw new Error('review unavailable');
      const data=await response.json();
      if(data.run_id!==board.run_id)throw new Error('stale review service');
      state.review={connected:true,version:data.version,items:data.items||{}};
      const mode=document.getElementById('review-mode');
      if(mode)mode.textContent='审核已连接';
      render();
    }catch{
      state.review.connected=false;
      const mode=document.getElementById('review-mode');
      if(mode)mode.textContent='审核未连接 · 只读';
      render();
    }
    render();
  }

  async function saveReview(actionKey,profileId,value){
    if(!window.B_REVIEW || !state.review.connected)return;
    if(state.view==='queue'&&state.shop==='all'){window.alert('请先选择一家店铺，再保存广告审核意见。');return}
    const isProbe=actionKey.startsWith('sif-probe:');
    const note=isProbe&&value==='accept' ? (window.prompt('说明该词与本品的相关性、为何值得试投。这里只保存核验意向；当前投放状态、承接广告组和出价尚未验证。')||'').trim() :
      value==='modify' ? (window.prompt('写下要更改的建议与理由（只保存审核意见，不直接执行）')||'').trim() : '';
    if(isProbe&&value==='accept'&&note.length<8){window.alert('请写出至少 8 字的本品相关性或试投理由。');return}
    if(value==='modify'&&!note)return;
    const action=(board.actions||[]).find(item=>item.action_key===actionKey);
    let bid=null;
    if((value==='accept'||value==='modify')&&['exact','bid_review'].includes(action?.kind)){
      const input=Array.from(document.querySelectorAll('[data-review-bid]')).find(el=>el.dataset.reviewBid===actionKey);
      if(!input){window.alert('没有找到出价输入框，请刷新面板后重试。');return}
      bid=Number(input.value);
      if(!Number.isFinite(bid)||bid<=0||bid>1000){window.alert('出价必须为大于 0 且不超过 1000 的数字。');return}
    }
    try{
      if(action?.kind==='exact'&&(value==='accept'||value==='modify')){
        const select=Array.from(document.querySelectorAll('[data-exact-target]')).find(el=>el.dataset.exactTarget===actionKey);
        if(!select||!select.value){window.alert('请选择精准投放的承接广告组。');return}
        const [campaignId,adGroupId]=select.value.split('|');
        action._targetCampaignId=campaignId;action._targetAdGroupId=adGroupId;
      }
      const response=await fetch('/api/decisions',{method:'POST',headers:{'Content-Type':'application/json','X-Local-Session':window.B_REVIEW.token},
        body:JSON.stringify({run_id:board.run_id,action_key:actionKey,profile_id:profileId,value,note,bid,
          target_campaign_id:action?._targetCampaignId||null,target_ad_group_id:action?._targetAdGroupId||null,
          expected_version:state.review.version})});
      if(response.status===409){await loadReview();window.alert('其他窗口已更新审核意见，请核对后重试。');return}
      if(!response.ok)throw new Error('save failed');
      const saved=await response.json();state.review.version=saved.version;state.review.items[actionKey]=saved;render();
    }catch{state.review.connected=false;render();window.alert('审核服务连接中断，未保存意见。请重新打开本批次服务。')}
  }

  function renderCatalog() {
    const base = activeProducts();
    const counts = {problem:selectProducts(base,'problem').length,active:selectProducts(base,'active').length,all:base.length};
    document.getElementById('catalog-tabs').innerHTML = [['problem','问题 ASIN'],['active','在售 ASIN'],['all','所有 ASIN']].map(([key,label])=>
      `<button type="button" data-scope="${key}" class="${state.scope===key?'active':''}" aria-pressed="${state.scope===key}">${label}<b>${counts[key]}</b></button>`).join('');
    const rows = visibleProducts();
    document.getElementById('catalog').innerHTML = rows.length ? rows.map(product => {
      const issues = (product.issues||[]).filter(issue=>issue.severity!=='gap');
      const tags = [...new Map(issues.map(i=>[i.domain,i])).values()].slice(0,2);
      return `<button type="button" class="product-row ${state.selected===product.key?'active':''}" data-product="${escapeHtml(product.key)}" aria-current="${state.selected===product.key?'true':'false'}">
        <span class="product-name" title="${escapeHtml(product.name)}">${escapeHtml(shortName(product.name,30))}</span>
        <span class="product-sub"><span>${escapeHtml(product.asin)}</span><span>${escapeHtml(product.shop)}</span></span>
        <span class="tag-row">${tags.map(i=>`<span class="tag ${sevTag(i)}">${tagName(i.domain)} · ${escapeHtml(i.title)}</span>`).join('')}
        ${!tags.length ? `<span class="tag ${product.status==='1'?'teal':'muted'}">${product.status==='1'?'暂无需处理':'非在售'}</span>`:''}
        ${(product.issues||[]).some(i=>i.severity==='gap')?'<span class="tag blue">数据缺口</span>':''}</span></button>`;
    }).join('') : '<div class="empty">没有匹配的产品</div>';
    document.querySelectorAll('[data-scope]').forEach(el=>el.addEventListener('click',()=>{state.scope=el.dataset.scope;renderCatalog()}));
    document.querySelectorAll('[data-product]').forEach(el=>el.addEventListener('click',()=>{
      state.selected=el.dataset.product;state.view='product';state.navOrigin='catalog';state.domain='growth';state.growthView='rank';state.expanded=null;state.decisionDrawer=null;state.adLimit=40;state.pmcFromQueue=false;render();
      loadTracking(selectedProduct());
      loadSupplement(selectedProduct());
    }));
  }

  function render() {
    hideVerdictTooltip(true);
    document.querySelector('.shell')?.classList.toggle('is-collapsed',state.sidebarCollapsed);
    const toggle=document.getElementById('sidebar-toggle');
    if(toggle){toggle.textContent=state.sidebarCollapsed?'»':'«';if(typeof toggle.setAttribute==='function')toggle.setAttribute('aria-label',state.sidebarCollapsed?'展开商品目录':'收起商品目录')}
    renderCatalog();
    const originLabel=state.navOrigin==='inventory-queue'?'库存待办':state.navOrigin==='queue'?'广告待办':'商品目录';
    const modeLabels={product:'单品诊断',queue:'广告待办','inventory-queue':'库存待办'};
    const viewSwitch=document.getElementById('view-switch');
    viewSwitch.classList?.toggle('product-breadcrumb',state.view==='product');
    viewSwitch.innerHTML = state.view==='product'?
      `<button type="button" class="view-back" data-view-back>← ${originLabel}</button>`:
      `<span class="view-current">${modeLabels[state.view]||''}</span>`;
    document.querySelectorAll('.side-mode').forEach(el=>el.classList.toggle('active',el.dataset.view===state.view));
    const inventoryMode=document.querySelector('.side-mode[data-view="inventory-queue"]');
    if(inventoryMode)inventoryMode.hidden=!board.inventory_batch;
    document.querySelectorAll('[data-view-back]').forEach(el=>el.addEventListener('click',()=>{
      if(state.navOrigin==='catalog'){state.sidebarCollapsed=false;render();return}
      state.view=state.navOrigin||'product';state.decisionDrawer=null;state.pmcFromQueue=false;render()
    }));
    document.getElementById('app')?.classList?.toggle('is-product-view',state.view==='product');
    if(state.view==='queue'){document.getElementById('app').innerHTML=globalQueueContent();bindContent();renderDecisionDrawer();return}
    if(state.view==='inventory-queue'){document.getElementById('app').innerHTML=inventoryQueueContent();bindContent();renderDecisionDrawer();return}
    const product = selectedProduct();
    if (!product) {document.getElementById('app').innerHTML='<div class="empty"><strong>本批次没有可展示的 ASIN</strong>请核对领星授权和 Listing 数据。</div>';renderDecisionDrawer();return}
    const priority = (product.issues||[]).find(i=>i.severity!=='gap');
    const liveActions = (product.actions||[]).filter(a=>a.reviewable ?? a.executable);
    const profile=productProfile(product);
    const probeSelected=profile?probeRows(product).filter(row=>state.review.items[probeActionKey(profile,row)]?.value==='accept').length:0;
    const latest = product.weeks?.at(-1) || {};
    const pace=product.sales_pace?.actual_daily_units_28d;
    const cover=product.stock?.sellable!=null && pace>0 ? Number(product.stock.sellable)/pace : null;
    const url = product.url?.startsWith('https://') ? product.url : `https://www.amazon.com/dp/${product.asin}`;
    const summary = priority ? priority.hypothesis || priority.title : '当前未发现满足阈值的明确问题；可继续查看关键词与完整指标。';
    const coreTerms=filterKeywordRadar(productKeywords(product),'core');
    const rankedTerms=coreTerms.filter(row=>rankCoverage(row,row.rank_as_of_date||board.as_of_date).twoWeek).length;
    const internalTerms=coreTerms.filter(row=>row.internal_evidence).length;
    const negativeActions=(product.actions||[]).filter(a=>['negative','negative_asin'].includes(a.kind)&&a.reviewable).length;
    const exactActions=(product.actions||[]).filter(a=>a.kind==='exact'&&a.reviewable).length;
    const heroTitle=priority?priority.title:'当前无高优先级问题';
    const heroSummary=summary;
    const heroMetrics=[['销量',`${fmt(latest.units)} 件`],['总点击',fmt(latest.sessions_total)],['FBA 可售',`${fmt(product.stock?.sellable)} 件`],['估算可售天数',fmt(cover,1)],['待确认广告动作',actionCount(liveActions)]];
    const overview=state.domain==='growth'?growthOverview(product,{url,latest,coreTerms,rankedTerms,internalTerms,negativeActions,exactActions,probeSelected}):'';
    const productOverviewHeader=productHeader(product,url);
    document.getElementById('app').innerHTML = `
      ${productOverviewHeader}
      <nav class="product-tabs" aria-label="产品分析板块">${[['growth','广告'],['inventory','库存'],['listing','Listing']].map(([key,label])=>{
        const count=key==='growth'&&(liveActions.length||probeSelected)?actionCount(liveActions)+probeSelected:0;
        return `<button type="button" data-domain="${key}" class="${state.domain===key?'active':''}" aria-pressed="${state.domain===key}"><span>${label}</span>${count?`<b class="tab-count">${count}</b>`:''}</button>`;
      }).join('')}</nav>
      <div id="product-overview">${overview}</div>
      <div id="domain-content">${domainContent(product)}</div>`;
    bindContent();
    renderDecisionDrawer();
  }

  function globalQueueContent(){
    const source=(board.actions||[]).filter(action=>!['observe','bid_review'].includes(action.kind));
    const all=globalActionQueue(source,board.profile_to_sid||{},state.shop,'all');
    const filtered=globalActionQueue(source,board.profile_to_sid||{},state.shop,state.adFilter);
    const negative=all.filter(action=>['negative','negative_asin'].includes(action.kind)).length;
    const exact=all.filter(action=>action.kind==='exact').length;
    const processed=globalActionQueue(source,board.profile_to_sid||{},state.shop,'processed').length;
    const gaps=globalActionQueue(source,board.profile_to_sid||{},state.shop,'gaps').length;
    const bidItems=bidReviewItems(null);
    const selectedProbes=products.filter(product=>state.shop==='all'||String(product.sid)===state.shop)
      .flatMap(product=>{const profile=productProfile(product);return probeRows(product)
        .filter(row=>state.review.items[probeActionKey(profile,row)]?.value==='accept')
        .map(row=>({product,row,profile,key:probeActionKey(profile,row),decision:state.review.items[probeActionKey(profile,row)]}))});
    return `<section class="queue-intro"><span class="eyebrow">同一动作只审核一次 · 专业规则</span><h2>广告待办</h2><p>否词按广告组；精准投放按产品与词合成一条方案。打开“依据”可见全部来源组和已处理证据。全部店铺可浏览，保存意见请先选一家店铺。</p>
      <div class="queue-summary"><span>专业待复核 <b>${all.length}</b></span><span>否词 <b>${negative}</b></span><span>精准方案 <b>${exact}</b></span><span>目标竞价可审 <b>${bidItems.filter(item=>item.action.reviewable).length}</b> / 记录 ${bidItems.length}</span><span>外部试投待核 <b>${selectedProbes.length}</b></span></div></section>
      <section class="panel"><div class="panel-title"><div><h3>建议与证据</h3><p>接受后保存意见；由智能体生成冻结写回批次，并单独确认执行。</p></div><span class="pill">${state.shop==='all'?'全部店铺 · 只读':escapeHtml(products.find(p=>String(p.sid)===state.shop)?.shop||state.shop)}</span></div>
      <div class="chart-controls ads-filters">${[['all','专业待处理'],['negative','否词'],['exact','精投'],['bid','调价'],['probe',`外部试投待核 ${selectedProbes.length}`],['processed','已处理'],['gaps',`待补证据 ${gaps}`]].map(([key,label])=>`<button type="button" data-ad-filter="${key}" class="${state.adFilter===key?'active':''}">${label}</button>`).join('')}</div>
      ${state.adFilter==='bid'?bidReviewContent(bidItems):state.adFilter==='probe'?(selectedProbes.length?`<div class="probe-intro"><strong>这是运营选择的核验意向，不是可执行的精准投放批次</strong><span>运营复核须核查活跃目标、可承接广告组和出价；如已有相同精准，则取消重复投放。</span></div><div class="table-wrap"><table><thead><tr><th>店铺 · 产品</th><th>SIF 关键词</th><th>周量</th><th>运营理由</th><th>进入单品</th></tr></thead><tbody>${selectedProbes.map(({product,row,decision})=>`<tr><td>${escapeHtml(product.shop)}<br><span class="muted">${escapeHtml(product.asin)}</span></td><td><strong>${escapeHtml(row.keyword)}</strong></td><td>${fmt(row.weekly_volume)}</td><td>${escapeHtml(decision.note)}</td><td><button type="button" class="action-link" data-open-keyword-product="${escapeHtml(product.key)}" data-open-keyword="${escapeHtml(row.id)}">查看排名与来源 ↗</button></td></tr>`).join('')}</tbody></table></div>`:'<div class="empty"><strong>尚未选入外部试投核验词</strong>到单品“关键词雷达”勾选相关词；不能把没有内部搜索词记录当作未投放证据。</div>'):
      filtered.length?`<div class="ad-action-list">${filtered.slice(0,state.queueLimit).map(action=>adActionRow(action,true)).join('')}</div>
        ${filtered.length>state.queueLimit?`<button class="more" data-more="queue">继续显示（剩余 ${filtered.length-state.queueLimit}）</button>`:''}`:
        '<div class="empty"><strong>当前筛选下没有广告待办</strong>这不是全部广告活动无问题；可切换店铺或查看单品依据。</div>'}
      <p class="footnote">单品与总览共用同一审核编号。共享广告组花费不拆给多个 ASIN；历史批次和离线 HTML 只读。</p></section>`;
  }

  function productImageUrl(product) {
    const content=product.content||{}, external=product.listing_external||{};
    // The ERP row can carry the parent/default variant image. Prefer the
    // child-ASIN front-end image from the SellerSprite supplement when present.
    const raw=external.image_url||content.main_image_url||'';
    return raw ? String(raw).replace(/\._[A-Z0-9]+_\.(jpg|jpeg|png)(\?.*)?$/i,'._SL300_.$1') : '';
  }

  function productHeader(product,url) {
    const image=productImageUrl(product);
    const initial=escapeHtml(String(product.name||product.asin||'?').trim().slice(0,1)||'?');
    const asOf=board.inventory_batch?.as_of||board.as_of_date||'';
    const rating=product.rating==null?'':`<span>评分 ${fmt(product.rating,1)}</span>`;
    const reviews=product.reviews==null?'':`<span>评论 ${fmt(product.reviews)}</span>`;
    return `<section class="product-header">
      <div class="product-header-main">
        <div class="product-thumb ${image?'':'no-image'}">${image?`<img src="${escapeHtml(image)}" alt="${escapeHtml(product.name||product.asin||'产品主图')}" loading="eager" referrerpolicy="no-referrer" onerror="this.parentElement.classList.add('no-image');this.remove()">`:''}<span>${initial}</span></div>
        <div class="product-header-copy">
          <span class="eyebrow">${escapeHtml(product.shop)} · ${escapeHtml(product.site)} · ${product.status==='1'?'在售':'非在售'}</span>
          <h2>${escapeHtml(product.name||product.asin)}</h2>
          <div class="product-header-meta"><span>${escapeHtml(product.asin)}</span><span>MSKU ${Object.keys(product.skus||{}).length} 个</span>${rating}${reviews}<span>数据 ${escapeHtml(asOf)}</span><a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">打开 Amazon Listing ↗</a></div>
        </div>
      </div>
    </section>`;
  }

  function growthOverview(product, context) {
    const {url,latest,coreTerms,rankedTerms,internalTerms,negativeActions,exactActions,probeSelected}=context;
    const traffic=trafficComposition(latest);
    const spend=adSpendComposition(latest);
    const ring=traffic?`<div class="growth-donut" style="--natural:${(traffic.naturalPct*100).toFixed(2)}%" role="img" aria-label="${escapeHtml(traffic.label)} 自然点击估算 ${pct(traffic.naturalPct)}，广告点击 ${pct(traffic.advertisingPct)}"><div><strong>${pct(traffic.naturalPct)}</strong><small>自然点击估算</small></div></div>`:
      '<div class="growth-donut unavailable" role="img" aria-label="同周点击口径不足，无法计算自然与广告构成"><div><strong>—</strong><small>口径待补</small></div></div>';
    const clickLegend=traffic?`<div class="growth-legend"><span><i class="natural-dot"></i>自然估算 <b>${pct(traffic.naturalPct)}</b></span><span><i class="ad-dot"></i>广告点击 <b>${pct(traffic.advertisingPct)}</b></span></div><p class="growth-source">${escapeHtml(traffic.label)} · 总点击 ${fmt(traffic.total)} − 广告点击 ${fmt(traffic.advertising)} = 自然估算 ${fmt(traffic.natural)}</p>`:
      '<p class="growth-source">最近完整周总点击与广告点击缺失或口径冲突，不绘制估算比例。</p>';
    const spendBar=spend?`<div class="spend-bar" role="img" aria-label="广告花费结构：SP ${pct(spend.spPct)}，SB ${pct(spend.sbPct)}，其他或未拆分 ${pct(spend.otherPct)}"><i class="sp" style="width:${(spend.spPct*100).toFixed(2)}%"></i><i class="sb" style="width:${(spend.sbPct*100).toFixed(2)}%"></i><i class="other" style="width:${(spend.otherPct*100).toFixed(2)}%"></i></div><div class="spend-legend"><span>SP <b>${pct(spend.spPct)}</b></span><span>SB <b>${pct(spend.sbPct)}</b></span><span>其他/未拆分 <b>${pct(spend.otherPct)}</b></span></div>`:
      '<p class="growth-source">广告花费分型不完整，暂不显示 SP/SB 比例。</p>';
    return `<section class="growth-overview" aria-label="ASIN 关键词与广告概况"><div class="growth-main"><div class="growth-main-grid solo"><div class="growth-composition"><div class="growth-composition-head"><span>同周点击构成 · 运营估算</span><small>${escapeHtml(latest.label||'最近完整周')}</small></div><div class="growth-traffic">${ring}<div>${clickLegend}<div class="growth-composition-head spend-head"><span>广告花费结构</span><small>非曝光占比</small></div>${spendBar}</div></div></div></div>
        <div class="growth-kpis"><div><small>上周销量</small><strong>${fmt(latest.units)}</strong><span>${escapeHtml(latest.label||'无周报表')} · 件</span></div><div><small>核心跟踪词</small><strong>${coreTerms.length}</strong><span>${rankedTerms} 个有双周有效曲线</span></div><div><small>领星匹配词</small><strong>${internalTerms}</strong><span>点击可下钻广告组来源</span></div></div></div>
      <aside class="growth-decisions"><div class="growth-decision"><small>排名窗口</small><strong>${rankedTerms} / ${coreTerms.length} 词双周有据</strong><p>自然与广告名次分别点开；断线仍按缺口呈现。</p></div><div class="growth-decision amber"><small>广告复核</small><strong>${negativeActions} 否词 · ${exactActions} 精准方案</strong><p>按同一专业动作审核；另有 ${probeSelected} 个 SIF 外部词待核试投。</p></div></aside></section>`;
  }

  function domainContent(product) {
    switch(state.domain){
      case 'inventory':return inventoryContent(product);
      case 'listing':return listingContent(product);
      default:return growthContent(product);
    }
  }

  function growthContent(product) {
    const actions=(product.actions||[]).filter(a=>a.reviewable&&!a.processed_status);
    return `<div class="growth-switch" role="group" aria-label="关键词与广告工作区"><div><strong>先看词位与表现，再决定广告动作</strong><small>同一词与同一专业动作在两处共用，不重复生成建议。</small></div><div class="growth-switch-buttons">${[['rank','词位跟踪'],['ads',`广告审核${actions.length?` · ${actionCount(actions)}`:''}`]].map(([key,label])=>`<button type="button" data-growth-view="${key}" class="${state.growthView===key?'active':''}" aria-pressed="${state.growthView===key}">${label}</button>`).join('')}</div></div>
      ${state.growthView==='ads'?advertisingContent(product):keywordContent(product)}
      `;
  }

  function issueCard(issue) {
    const evidence = Object.entries(issue.evidence||{}).filter(([key])=>!['weeks'].includes(key))
      .map(([key,value])=>`${escapeHtml(evidenceLabels[key]||key)} ${escapeHtml(value === null ? '—' : ['acos','baseline_cvr','current_cvr','traffic_change','ratio'].includes(key)?pct(value):typeof value==='number'?fmt(value,2):value)}`).join(' · ');
    const severity = ({critical:'紧急',high:'优先',medium:'复核',low:'观察',gap:'缺口'})[issue.severity]||'复核';
    return `<article class="issue ${escapeHtml(issue.severity)}"><div class="rail"></div><div class="issue-body"><div class="issue-head"><h4>${escapeHtml(issue.title)}</h4><span class="pill ${issue.severity==='high'||issue.severity==='critical'?'danger':'warn'}">${severity}</span></div>
      <p>${escapeHtml(issue.hypothesis||'')}</p><div class="evidence">依据：${evidence || '请查看来源数据'}</div>
      ${issue.gaps?.length?`<div class="evidence">尚缺：${escapeHtml(issue.gaps.join('、'))}</div>`:''}
      ${issue.next_step?`<div class="next">下一步：${escapeHtml(issue.next_step)}</div>`:''}</div></article>`;
  }

  function keywordContent(product) {
    const live=state.tracking.byProduct[product.key];
    const manual=state.manualSif[product.key];
    const all=productKeywords(product);
    const query = state.keywordSearch.trim().toLowerCase();
    const scoped=filterKeywordRadar(all,state.keywordFilter);
    const filtered=query?scoped.filter(row=>row.keyword.toLowerCase().includes(query)):scoped;
    const rows = filtered.slice(0,state.keywordLimit);
    const coreCount=filterKeywordRadar(all,'core').length;
    const rankedCount=filterKeywordRadar(all,'core').filter(row=>rankCoverage(row,row.rank_as_of_date||board.as_of_date).twoWeek).length;
    const intentCount=probeRows(product).length;
    const pendingCount=all.filter(row=>row.tracking?.pending).length;
    const rankPeriod=manual?.rank_window||board.periods?.sif_rank;
    const rankPeriodText=Array.isArray(rankPeriod)&&rankPeriod.length===2?
      `${rankPeriod[0]}—${rankPeriod[1]}`:'最近两个完整 SIF 周';
    const stateText = product.keyword_state?.sif_state === 'verified' ? 'SIF 本次已返回关键词' :
      product.keyword_state?.sif_state === 'no_rows' ? 'SIF 本次未返回本品关键词' :
      product.keyword_state?.sif_state === 'not_queued' ? 'SIF 本轮未排入查询' :
      product.keyword_state?.sif_state === 'not_queried' ? 'SIF 本批次未查询本品' :
      product.keyword_state?.sif_state === 'replay_missing' ? '历史重放缺少本品 SIF 源响应' :
      product.keyword_state?.sif_state === 'deferred_after_repeated_failures' ? 'SIF 连续失败后延后，本品未查询' : 'SIF 本次读取失败';
    const priority=live?.sif_priority;
    const priorityText=priority?.pending==null?(priority?.active?'已设为查询优先':'下轮优先查询'):(priority.pending?'下轮加入优先':'下轮取消优先');
    return `<section class="panel keyword-workbench"><div class="panel-title"><div><span class="eyebrow">SIF EXTERNAL × LINGXING ACTUAL</span><h3>关键词雷达</h3><p>外部词库决定看哪些词；排名判断位置，领星搜索词验证真实表现，专业规则决定广告动作。</p></div><span class="pill">${escapeHtml(rankPeriodText)}</span></div>
      <div class="radar-summary"><div><small>SIF 跟踪词</small><strong>${coreCount}</strong><span>${escapeHtml(manual?`单品补查 ${localDate(manual.queried_at)}`:stateText)}</span></div><div><small>双周有据</small><strong>${rankedCount}</strong><span>至少每周 5 个真实日</span></div><div><small>外部独有 · 待核</small><strong>${intentCount}</strong><span>没有内部记录 ≠ 没有投放</span></div></div>
      <div class="keyword-overview"><span>${escapeHtml(rankStateLabels[manual?.rank_state||product.keyword_state?.rank_14d_state]||'尚未取得完整观测')}</span><span>外部来源：本品 SIF 词位 + 有界竞品机会；内部来源：领星广告搜索词与目标报表</span>${product.keyword_state?.sif_queue_reason?`<span>${escapeHtml(queueReasonLabels[product.keyword_state.sif_queue_reason]||product.keyword_state.sif_queue_reason)}</span>`:''}${pendingCount?`<span>${pendingCount} 项词库变更待下轮生效</span>`:''}</div>
      <div class="keyword-toolbar"><div class="chart-controls">${[['core','核心跟踪'],['opportunity','外部待核'],['internal','仅内部搜索词'],['all','全部词']].map(([key,label])=>`<button type="button" data-keyword-filter="${key}" class="${state.keywordFilter===key?'active':''}">${label}</button>`).join('')}</div><input id="keyword-search" class="control" type="search" placeholder="搜索关键词" value="${escapeHtml(state.keywordSearch)}"></div>
      ${window.B_REVIEW?`<div class="keyword-actions"><button type="button" data-keyword-manage>管理跟踪词${pendingCount?` · ${pendingCount} 项待生效`:''}</button><button type="button" data-sif-priority="${priority?.active?0:1}" ${state.review.connected&&!live?.unavailable?'':'disabled'}>${escapeHtml(priorityText)}</button><button type="button" data-sif-query ${window.B_REVIEW.sif_available&&!state.manualSifLoading?'':'disabled'}>${state.manualSifLoading?'正在查询 SIF…':'单独查询本 ASIN'}</button></div>${state.keywordManageOpen?trackingManagePanel(product,all,live):''}`:''}
      ${rows.length?`<div class="table-wrap"><table class="radar-table"><thead><tr><th>核心词</th><th>SIF 周需求</th><th>本品贡献</th><th>14 日自然 / 广告位</th><th>领星内部表现</th><th>判断与操作</th></tr></thead><tbody>
      ${rows.map(row=>keywordRowHtml(row,product)).join('')}</tbody></table></div>`:'<div class="empty"><strong>此筛选下暂无关键词</strong>可以切换词池或单品补查；不以空白冒充“排名为零”。</div>'}
      ${filtered.length>rows.length?`<button class="more" data-more="keywords">继续显示（剩余 ${filtered.length-rows.length}）</button>`:''}
      ${competitorPanel(product,live)}
      <p class="footnote">双周有效＝同一渠道每周至少 5 个真实日，不代表 14 天无缺口；广告页位原文不会伪装成绝对名次。内部搜索词属于广告组，共享组不拆成单品销售贡献。“外部待核”仅是 SIF 发现，不是已证实未投放。${window.B_REVIEW?'词库与试投意向仅保存本地，不自动写回领星。':'离线 HTML 为本批次只读快照。'}</p></section>
      <details class="disclosure"><summary>数据边界与完整来源</summary><p>本页源数据来自本批次领星 MCP 与已授权 SIF MCP。广告搜索词属于广告组，多 ASIN 共用时花费与订单不拆分。自然点击为同周总点击减广告点击的运营估算；若口径冲突即置缺。利润权限未开放，不推断保本。</p></details>`;
  }

  function trackingManagePanel(product,all,live){
    if(state.keywordImportProduct&&state.keywordImportProduct!==product.key){
      state.keywordImportText='';state.keywordImportPreview=null;state.keywordImportProduct=null;
    }
    const ready=state.review.connected&&!live?.unavailable;
    const tracked=all.filter(row=>row.tracking?.state==='active'||row.tracking?.pending).sort((a,b)=>
      Number(Boolean(b.tracking?.pending))-Number(Boolean(a.tracking?.pending))||a.keyword.localeCompare(b.keyword));
    const preview=state.keywordImportPreview;
    return `<div class="tracking-manager"><div class="tracking-manager-head"><strong>本品核心词库 · ${tracked.length} 词</strong><small>仅影响本店铺 / 本 ASIN；增减与查询优先在下一次完整刷新生效，历史排名不删除。</small></div>
      <div class="tracking-import"><label for="keyword-import-text">批量粘贴关键词（逐行或粘贴表格列，最多 200 词）</label><textarea id="keyword-import-text" rows="3" placeholder="kids knife set&#10;toddler kitchen tools">${escapeHtml(state.keywordImportText)}</textarea><div class="tracking-import-actions"><button type="button" data-keyword-preview>预览去重</button>${preview&&!preview.errors.length?`<button type="button" data-keyword-commit ${ready?'':'disabled'}>确认下轮加入 ${preview.terms.length} 词</button>`:''}</div>
      ${preview?`<div class="tracking-preview ${preview.errors.length?'invalid':''}">${preview.errors.length?escapeHtml(preview.errors.join('；')):`去重后 ${preview.terms.length} 词：${escapeHtml(preview.terms.slice(0,12).join('、'))}${preview.terms.length>12?'…':''}`}</div>`:''}</div>
      <div class="tracking-current">${tracked.length?tracked.map(row=>{const tr=row.tracking||{};const operation=tr.pending?'cancel':tr.state==='active'?'remove':'add';return `<div><span><strong>${escapeHtml(row.keyword)}</strong><small>${tr.pending?`待下轮${tr.pending==='add'?'加入':'移除'}`:'持续跟踪'}</small></span><button type="button" data-tracking="${operation}" data-term="${escapeHtml(row.keyword)}" ${ready?'':'disabled'}>${tr.pending?'撤回':tr.state==='active'?'下轮移出':'下轮加入'}</button></div>`}).join(''):'<p class="muted">目前没有持续跟踪词。</p>'}</div></div>`;
  }

  function competitorPanel(product,live){
    const source=product.keyword_state?.competitor_discovery||{};
    const entries=live?.competitors||product.keyword_state?.competitors||[];
    const candidates=source.candidates||[];
    const selected=candidates.filter(row=>row.selected).slice(0,3);
    const rejected=candidates.filter(row=>!row.selected);
    const active=entries.filter(row=>row.active).length;
    const pending=entries.filter(row=>row.pending).length;
    const status={verified:'本轮已查询',partial:'部分竞品查询失败',no_competitors:'未发现可用竞品',
      replay_missing:'重放缺少竞品源响应',source_failed:'SIF 竞品查询失败',no_seed:'本品未取得种子词'}[source.state]||
      '本轮未进入有界竞品查询';
    const discoveryNote=source.discovery_state==='source_failed'?'；自动发现失败，已保存的竞品仍单独复核':
      source.discovery_state==='replay_missing'?'；自动发现原始响应缺失，已保存的竞品仍单独复核':
      source.discovery_state==='no_seed'&&source.competitors?.length?'；无本品种子词，仅复核已保存竞品':'';
    const card=row=>{const registered=entries.find(item=>item.asin===row.asin)||{};
      const activeNow=Boolean(registered.active);const pendingState=registered.pending;
      const monthly=row.monthly_orders==null?'月购未返回':`${row.monthly_orders} 月购`;
      const currency=({UK:'£',US:'$',DE:'€',FR:'€',IT:'€',ES:'€',JP:'¥'})[product.site]||'';
      return `<article class="competitor-card"><div class="competitor-identity">${row.image_url?`<img src="${escapeHtml(row.image_url)}" alt="" loading="lazy" referrerpolicy="no-referrer">`:''}<div><small>${row.source==='operator'?'运营维护':'SIF 发现 · 意图初筛'}</small><strong><a href="https://www.amazon.${product.site==='UK'?'co.uk':'com'}/dp/${escapeHtml(row.asin)}" target="_blank" rel="noopener noreferrer">${escapeHtml(row.asin)} ↗</a></strong><span>${escapeHtml(row.brand||'品牌未返回')} · ${row.price==null?'价格未返回':`${currency}${fmt(row.price,2)}`} · ${row.rating==null?'评分未返回':`${escapeHtml(row.rating)}★`} · ${row.reviews==null?'评论未返回':`${escapeHtml(row.reviews)}评`} · ${escapeHtml(monthly)}</span><p>${escapeHtml(row.title||'SIF 本轮未返回商品标题')}</p></div></div><div class="competitor-card-foot"><span>${escapeHtml(row.relevance_reason||'运营维护，需人工核验商品相关性')}</span>${window.B_REVIEW&&state.review.connected?`<button type="button" data-competitor="${activeNow?'remove':'add'}" data-competitor-asin="${escapeHtml(row.asin)}">${pendingState?'待下轮变更':activeNow?'下轮移除':'下轮加入'}</button>`:''}</div></article>`};
    return `<details class="disclosure competitor-panel"><summary>竞品机会池 · 本轮 ${selected.length} 个初筛可比${pending?` · ${pending} 项下轮变更`:''}</summary>
      <div class="competitor-panel-body"><p class="muted">${escapeHtml(status+discoveryNote)}${source.seed?` · 发现词「${escapeHtml(source.seed)}」`:''}。同店铺、同父体共用竞品池；一次发现最多 10 个，用一批商品资料初筛，最多查询 3 个竞品关键词。候选不自动加入核心词库。</p>
      ${selected.length?`<div class="competitor-cards">${selected.map(card).join('')}</div>`:
        entries.length?`<div class="competitor-list">${entries.map(row=>`<div><strong>${escapeHtml(row.asin)}</strong><span>${row.origin==='operator'?'运营维护':'历史自动发现'} · ${row.active?'启用':'停用'}${row.pending?` · 下轮${row.pending==='add'?'加入':'移除'}`:''}</span>${window.B_REVIEW&&state.review.connected?`<button type="button" data-competitor="${row.active?'remove':'add'}" data-competitor-asin="${escapeHtml(row.asin)}">${row.active?'下轮移除':'下轮加入'}</button>`:''}</div>`).join('')}</div>`:'<p class="data-gap">本轮没有通过相关性初筛的竞品；可手动维护，下一次刷新生效。</p>'}
      ${rejected.length?`<details class="disclosure"><summary>另有 ${rejected.length} 个未纳入自动查询的候选 · 查看原因</summary><div class="competitor-rejected">${rejected.map(row=>`<div><strong>${escapeHtml(row.asin)}</strong><span>${escapeHtml(row.title||'商品资料未返回')}</span><em>${escapeHtml(row.relevance_reason||'超出本轮 3 个查询名额')}</em></div>`).join('')}</div></details>`:''}
      ${window.B_REVIEW?`<button type="button" data-competitor="add" data-competitor-asin="" ${state.review.connected&&!live?.unavailable?'':'disabled'}>＋ 手动维护竞品 ASIN</button>`:''}</div></details>`;
  }

  function keywordRowHtml(row,product) {
    const internal=row.internal_evidence;
    const digest=rankDigest(row,row.rank_as_of_date||board.as_of_date||board.fetched_at.slice(0,10));
    const profile=productProfile(product);
    const probeReady=profile&&probeRows(product).some(item=>item.id===row.id);
    const probeKey=probeReady?probeActionKey(profile,row):null;
    const track=row.tracking||{};
    const decision=keywordDecision(row,row.rank_as_of_date||board.as_of_date||board.fetched_at.slice(0,10),
      {probeKey});
    const acos=internal?.spend!=null&&internal?.sales>0?internal.spend/internal.sales:null;
    const matching=internal?.match_types?.filter(v=>['exact','phrase','broad'].includes(String(v).toLowerCase()))
      .map(v=>({exact:'精准',phrase:'词组',broad:'广泛'}[String(v).toLowerCase()]));
    const matchText=matching?.length?[...new Set(matching)].join(' / '):'仅搜索词表现';
    const expanded=state.expanded?.id===row.id?state.expanded:null;
    return `<tr class="radar-row compact-keyword"><td><strong class="keyword-name">${escapeHtml(row.keyword)}</strong>${track.pending?`<small class="keyword-pending">下轮${track.pending==='add'?'加入':'移出'}</small>`:''}</td>
      <td><strong class="radar-number">${fmt(row.weekly_volume)}</strong><small>${row.aba_rank!=null?`ABA ${fmt(row.aba_rank)}`:'ABA 未返回'}</small></td>
      <td class="sif-contribution"><strong>${pct(row.sif_traffic_share)}</strong><small>SIF 近 7 日估算</small></td>
      <td><div class="rank-pair"><button type="button" class="rank-trigger ${expanded?.kind==='rank'&&expanded.focus==='natural'?'active':''}" data-keyword-rank="${escapeHtml(row.id)}" data-rank-focus="natural" aria-expanded="${expanded?.kind==='rank'&&expanded.focus==='natural'}" aria-label="查看 ${escapeHtml(row.keyword)} 的 14 天自然排名曲线">${rankBrief('自然',digest.natural,row.natural_rank_display)}</button><button type="button" class="rank-trigger ${expanded?.kind==='rank'&&expanded.focus==='advertising'?'active':''}" data-keyword-rank="${escapeHtml(row.id)}" data-rank-focus="advertising" aria-expanded="${expanded?.kind==='rank'&&expanded.focus==='advertising'}" aria-label="查看 ${escapeHtml(row.keyword)} 的 14 天广告排名曲线">${rankBrief('广告',digest.advertising,row.ad_rank_display)}</button></div></td>
      <td>${internal?`<button type="button" class="internal-trigger ${expanded?.kind==='internal'?'active':''}" data-keyword-internal="${escapeHtml(row.id)}" aria-expanded="${expanded?.kind==='internal'}" aria-label="查看 ${escapeHtml(row.keyword)} 的领星活动与广告组数据"><strong>${fmt(internal.clicks)} 点击 · ${fmt(internal.orders)} 单</strong><small>花费 ${fmt(internal.spend,2)} · ACOS ${pct(acos)}</small><em>${escapeHtml(matchText)} · 看广告组 ↗</em></button>`:'<span class="data-gap">无可归属内部表现</span>'}</td>
      <td><div class="keyword-decision"><button type="button" class="verdict-tag ${escapeHtml(decision.verdict.code)}" data-verdict-tip="${escapeHtml(row.id)}" aria-describedby="verdict-tip" aria-expanded="false" aria-label="${escapeHtml(row.keyword)}：${escapeHtml(decision.verdict.title)}，查看判断原因">${escapeHtml(decision.verdict.title)}</button>${decision.operations.length?`<div class="keyword-ops">${decision.operations.map(op=>`<button type="button" data-decision-open="${escapeHtml(row.id)}" data-decision-pane="${escapeHtml(op.kind)}" aria-label="${escapeHtml(row.keyword)}：${escapeHtml(op.label)}${op.countText?`，${escapeHtml(op.countText)}`:''}">${escapeHtml(op.label)}${op.countText?`<small>${escapeHtml(op.countText)}</small>`:''}</button>`).join('')}</div>`:''}</div></td></tr>
      ${expanded?`<tr class="expanded-row"><td colspan="6">${expanded.kind==='rank'?keywordRankDetail(row,expanded.focus):keywordInternalDetail(row)}</td></tr>`:''}`;
  }

  function rankBrief(label,digest,fallback){
    const presentation=rankPresentation(digest,fallback);
    const snapshot=rankPresentation({latest:null,days:0},fallback);
    const change=presentation.kind==='absolute'&&digest.improvement!=null?`<em class="${digest.improvement>0?'up':digest.improvement<0?'down':''}">${digest.improvement>0?'↑':digest.improvement<0?'↓':'→'}${fmt(Math.abs(digest.improvement))}</em>`:'';
    return `<span class="rank-brief ${presentation.kind}"><span>${label}</span><strong>${escapeHtml(presentation.shortLabel||presentation.label)}</strong>${change}<small>${escapeHtml(presentation.detail)}</small>${presentation.kind==='absolute'&&snapshot.kind==='page'?`<small class="rank-snapshot">本次快照 ${escapeHtml(snapshot.shortLabel||snapshot.label)}</small>`:''}</span>`;
  }

  function keywordRankDetail(row,focus) {
    const digest=rankDigest(row,row.rank_as_of_date||board.as_of_date||board.fetched_at.slice(0,10));
    const tracking=row.tracking||{};
    const canEdit=window.B_REVIEW&&state.review.connected&&!state.tracking.byProduct[selectedProduct().key]?.unavailable;
    const trackAction=tracking.pending?'cancel':tracking.state==='active'?'remove':'add';
    const trackLabel=tracking.pending?'撤回下轮变更':tracking.state==='active'?'下轮移出跟踪':'下轮加入跟踪';
    return `<div class="keyword-detail"><div class="detail-head"><div><span class="eyebrow">14-DAY RANK WINDOW · ${focus==='natural'?'自然排名':'SP 广告排名'}</span><strong>${escapeHtml(row.keyword)}</strong><small>${escapeHtml(digest.window.join(' → '))}</small></div>${canEdit?`<button type="button" data-tracking="${trackAction}" data-term="${escapeHtml(row.keyword)}">${trackLabel}</button>`:''}</div>
      <div class="keyword-market-facts"><span>周需求 <b>${fmt(row.weekly_volume)}</b>${row.volume_period?` · 周起 ${escapeHtml(row.volume_period)}`:''}</span><span>ABA 热词排名 <b>${fmt(row.aba_rank)}</b></span><span>本品词流量贡献 <b>${pct(row.sif_traffic_share)}</b> · SIF 近 7 日估算</span>${row.sif_natural_ratio!=null?`<span>SIF 自然流量占比 <b>${pct(row.sif_natural_ratio)}</b></span>`:''}${row.sif_top3_click_share!=null?`<span>SIF 前三点击占比 <b>${pct(row.sif_top3_click_share)}</b></span>`:''}${row.sif_top3_conversion_share!=null?`<span>SIF 前三转化占比 <b>${pct(row.sif_top3_conversion_share)}</b></span>`:''}${row.sif_cpc_median!=null?`<span>SIF 市场 CPC 中位数 <b>${fmt(row.sif_cpc_median,2)}</b></span>`:''}</div>
      <div class="rank-cards">${[['natural','自然位',row.natural_rank_display],['advertising','SP 广告位',row.ad_rank_display]].map(([key,label,fallback])=>{const d=digest[key],presentation=rankPresentation(d,fallback),snapshot=rankPresentation({latest:null,days:0},fallback);return `<div><small>${label}</small><strong>${escapeHtml(presentation.label)}${presentation.kind==='absolute'&&d.improvement!=null?` <em class="${d.improvement>0?'up':d.improvement<0?'down':''}">${d.improvement>0?'↑':d.improvement<0?'↓':'→'}${fmt(Math.abs(d.improvement))}</em>`:''}</strong><span>${escapeHtml(presentation.detail)}</span>${presentation.kind==='absolute'&&snapshot.kind==='page'?`<span>本次快照 ${escapeHtml(snapshot.label)}（另一口径）</span>`:''}<span>${presentation.kind==='absolute'?`最好 #${fmt(d.best)} · 最差 #${fmt(d.worst)} · 波幅 ${fmt(d.amplitude)}`:'页位不参加绝对名次波动计算'}</span></div>`}).join('')}</div>
      <div class="rank-legend"><span>● 自然名次</span><span>● 广告绝对名次</span><small>越靠上＝名次越好；断线＝当天未观测。悬停日期可同时查看两种名次。</small></div>
      <div class="rank-chart">${rankChart(row,focus)}</div><details class="disclosure"><summary>逐日数据与缺口 · 14 天</summary><div class="rank-days">${rankDays(row)}</div></details><p class="footnote">周需求、近 7 日流量贡献与双周词位是不同时间窗，不互相换算。曲线只画真实绝对名次 #；第 X 页·第 Y 位是 SIF 页位，不能与 # 直接换算或算涨跌。</p></div>`;
  }

  function keywordInternalDetail(row) {
    const internal=row.internal_evidence||{};
    const sources=internal.sources||[];
    return `<div class="keyword-detail"><div class="detail-head"><div><span class="eyebrow">LINGXING SEARCH TERM EVIDENCE</span><strong>${escapeHtml(row.keyword)}</strong><small>广告搜索词归属广告组；共享组不拆成单品贡献</small></div></div>
      <div class="internal-summary"><span>点击 <b>${fmt(internal.clicks)}</b></span><span>花费 <b>${fmt(internal.spend,2)}</b></span><span>订单 <b>${fmt(internal.orders)}</b></span><span>广告销售额 <b>${fmt(internal.sales,2)}</b></span></div>
      ${sources.length?`<div class="table-wrap"><table><thead><tr><th>活动 / 广告组</th><th>匹配</th><th>点击</th><th>花费</th><th>订单</th><th>销售额</th><th>归属</th></tr></thead><tbody>${sources.map(s=>`<tr><td>${escapeHtml(s.campaign_name||s.campaign_id)}<br><span class="muted">${escapeHtml(s.ad_group_name||s.ad_group_id)}</span></td><td>${escapeHtml(s.match_type||'—')}</td><td>${fmt(s.clicks)}</td><td>${fmt(s.spend,2)}</td><td>${fmt(s.orders)}</td><td>${fmt(s.sales,2)}</td><td>${s.shared_group?'共享组 · 不按 ASIN 拆分':'本品广告组'}</td></tr>`).join('')}</tbody></table></div>`:'<p class="muted">本批次没有可归属的领星广告组记录；不能据此判断该词绝无投放。</p>'}</div>`;
  }

  function verdictTooltipHtml(row,product){
    const profile=productProfile(product);
    const probeKey=profile&&probeRows(product).some(item=>item.id===row.id)?probeActionKey(profile,row):null;
    const decision=keywordDecision(row,row.rank_as_of_date||board.as_of_date||board.fetched_at.slice(0,10),{probeKey});
    const scope=decision.operations.length?`<small>处理范围：${decision.operations.map(op=>`${escapeHtml(op.label)} ${escapeHtml(op.countText||'待核验')}`).join(' · ')}；逐项点击操作按钮复核。</small>`:'';
    return `<strong>${escapeHtml(decision.verdict.title)}</strong><p>${escapeHtml(decision.verdict.reason)}</p>${scope}`;
  }

  function verdictTooltipPosition(anchor,size,viewport){
    const edge=8,gap=8;
    const width=Math.min(size.width,viewport.width-edge*2);
    const height=Math.min(size.height,viewport.height-edge*2);
    let left=anchor.left-width-gap;
    if(left<edge)left=anchor.right+gap;
    left=Math.max(edge,Math.min(left,viewport.width-width-edge));
    const top=Math.max(edge,Math.min(anchor.top,viewport.height-height-edge));
    return {left,top};
  }

  function hideVerdictTooltip(force=false){
    if(verdictTipPinned&&!force)return;
    const tip=document.getElementById('verdict-tip');
    if(tip)tip.hidden=true;
    verdictTipTrigger?.setAttribute?.('aria-expanded','false');
    verdictTipTrigger=null;verdictTipPinned=false;
  }

  function showVerdictTooltip(trigger,pinned=false){
    const product=selectedProduct();
    const row=product&&productKeywords(product).find(item=>item.id===trigger.dataset.verdictTip);
    const tip=document.getElementById('verdict-tip');
    if(!row||!tip)return;
    if(verdictTipTrigger!==trigger)hideVerdictTooltip(true);
    verdictTipTrigger=trigger;verdictTipPinned=pinned;
    tip.innerHTML=verdictTooltipHtml(row,product);tip.hidden=false;
    trigger.setAttribute('aria-expanded','true');
    const size=tip.getBoundingClientRect();
    const position=verdictTooltipPosition(trigger.getBoundingClientRect(),size,
      {width:window.innerWidth,height:window.innerHeight});
    tip.style.left=`${position.left}px`;tip.style.top=`${position.top}px`;
  }

  function decisionDrawerHtml(row,product,pane='why') {
    const profile=productProfile(product);
    const probeKey=profile&&probeRows(product).some(item=>item.id===row.id)?probeActionKey(profile,row):null;
    const decision=keywordDecision(row,row.rank_as_of_date||board.as_of_date||board.fetched_at.slice(0,10),{probeKey});
    const operation=decision.operations.find(item=>item.kind===pane);
    const activePane=operation?pane:'why';
    const rank=rankDigest(row,row.rank_as_of_date||board.as_of_date||board.fetched_at.slice(0,10));
    const internal=row.internal_evidence;
    const acos=internal?.sales>0?internal.spend/internal.sales:null;
    const facts=`<div class="decision-facts"><div><small>SIF 周需求 / ABA</small><strong>${fmt(row.weekly_volume)} / ${fmt(row.aba_rank)}</strong><span>${row.volume_period?`周起 ${escapeHtml(row.volume_period)}`:'周需求期未返回'}</span></div><div><small>本品词流量贡献</small><strong>${pct(row.sif_traffic_share)}</strong><span>SIF 近 7 日估算；非获流率</span></div><div><small>自然 / 广告末次实测</small><strong>${escapeHtml(rankPresentation(rank.natural,row.natural_rank_display).label)} / ${escapeHtml(rankPresentation(rank.advertising,row.ad_rank_display).label)}</strong><span>${rank.natural.days} / ${rank.advertising.days} 个有效日</span></div><div><small>领星搜索词合并表现</small><strong>${internal?`${fmt(internal.clicks)} 点击 · ${fmt(internal.orders)} 单`:'暂无归属记录'}</strong><span>${internal?`花费 ${fmt(internal.spend,2)} · ACOS ${pct(acos)}`:'无记录不等于未投放'}</span></div></div>`;
    const why=`<section class="decision-drawer-section"><h4>${escapeHtml(decision.verdict.title)}</h4><p class="decision-reason">${escapeHtml(decision.verdict.reason)}</p>${facts}
      ${decision.operations.length?`<div class="decision-scope"><strong>对应处理对象</strong>${decision.operations.map(op=>`<div><span>${escapeHtml(op.label)}${op.countText?` · ${escapeHtml(op.countText)}`:''}</span><small>${op.kind==='probe'?'外部试投仅待核验':op.actions.map(action=>action.kind==='bid_review'?`目标 ${action.query||'未取得'}`:`${action.campaign_name||action.campaign_id||'活动未取得'} / ${action.ad_group_name||action.ad_group_id||'组未取得'}`).join('；')}</small></div>`).join('')}</div>`:'<p class="decision-no-action">当前没有可提交审核的广告动作；保留排名和内部表现继续观察。</p>'}
      <details class="disclosure"><summary>来源与口径</summary><p>SIF 来源：${escapeHtml((row.sources||[]).join(' / ')||'未标注')}；周需求、近 7 日贡献和两个完整 SIF 周的排名不在同一时间窗。领星搜索词期间：${escapeHtml((board.periods?.search_terms||[]).join(' → ')||'未返回')}。搜索词花费与订单属于广告组，同父体子 ASIN 不重复归因；目标报表缺行不能证明从未投放。</p></details></section>`;
    const probe=operation?.kind==='probe'?`<section class="decision-drawer-section"><h4>精投 · 试投核验</h4><p class="decision-reason">这是 SIF 外部词的核验意向，不是已确认的精准投放方案。没有内部搜索词记录，不代表广告后台没有启用、暂停或历史目标。</p>${facts}<div class="decision-checks"><span>① 运营确认本品相关性</span><span>② 复核领星活跃及历史精准目标</span><span>③ 确认承接广告组与基础出价</span></div>${window.B_REVIEW&&state.review.connected?`<button type="button" class="probe-toggle ${state.review.items[probeKey]?.value==='accept'?'selected':''}" data-probe="${escapeHtml(probeKey)}" data-profile="${escapeHtml(profile)}" data-probe-value="${state.review.items[probeKey]?.value==='accept'?'reject':'accept'}">${state.review.items[probeKey]?.value==='accept'?'☑ 已保存核验意向 · 点击撤回':'加入试投核验'}</button>`:'<span class="pill">只读快照 · 请在审核服务保存意向</span>'}</section>`:'';
    const actionList=operation&&operation.kind!=='probe'?`<section class="decision-drawer-section"><h4>${escapeHtml(operation.label)} · ${escapeHtml(operation.countText)}</h4><p class="decision-reason">${operation.kind==='bid'?'按目标 ID 审核基础竞价；接受后保存目标出价，由智能体生成写回批次。':operation.kind==='exact'?'逐组审核精准方案；接受后保存承接广告组和出价，由智能体生成写回批次。':'否词落在列出的 SP 广告组；共享变体只审核一次，点击接受也不会立即写回。'}</p>${operation.actions.map(decisionActionCard).join('')}</section>`:'';
    return `<div class="decision-backdrop" data-decision-close></div><aside class="decision-drawer" role="dialog" aria-modal="true" aria-label="${escapeHtml(row.keyword)} 的判断与操作"><div class="decision-drawer-head"><div><span class="eyebrow">关键词判断 · ${escapeHtml(product.shop)}</span><h3>${escapeHtml(row.keyword)}</h3><small>${escapeHtml(product.name)} · ${escapeHtml(product.asin)}</small></div><button type="button" class="decision-close" data-decision-close aria-label="关闭判断与操作">×</button></div><nav class="decision-drawer-nav" aria-label="判断与操作详情"><button type="button" data-decision-tab="why" class="${activePane==='why'?'active':''}">判断依据</button>${decision.operations.map(op=>`<button type="button" data-decision-tab="${escapeHtml(op.kind)}" class="${activePane===op.kind?'active':''}">${escapeHtml(op.label)}${op.countText?` <small>${escapeHtml(op.countText)}</small>`:''}</button>`).join('')}</nav><div class="decision-drawer-body">${activePane==='why'?why:operation?.kind==='probe'?probe:actionList}</div><footer>审核意见与广告待办共用同一动作键；页面按钮不直接写回领星。</footer></aside>`;
  }

  function decisionActionCard(action){
    const bid=action.kind==='bid_review';
    const evidence=action.bid_evidence||{};
    const groups=adSourceGroups(action);
    const destination=action.kind==='exact'&&action.exact_plan?.target_ad_group_id?
      `${action.exact_plan.target_campaign_name||action.campaign_name||'活动未取得'} / ${action.exact_plan.target_ad_group_name||action.ad_group_name||'组未取得'}`:
      `${action.campaign_name||action.campaign_id||'活动未取得'} / ${action.ad_group_name||action.ad_group_id||'组未取得'}`;
    return `<article class="decision-action-card ${['exact','bid_review'].includes(action.kind)?'has-complex-review':''}" data-action-row="${escapeHtml(action.action_key)}"><div class="decision-action-head"><div><small>${bid?'调价目标':action.kind==='exact'?'精准承接组':'否词广告组'}</small><strong>${escapeHtml(destination)}</strong>${action.portfolio_name?`<small class="decision-target-meta">广告组合 · ${escapeHtml(action.portfolio_name)}</small>`:''}</div><span class="pill ${action.reviewable||action.kind==='exact'?'action':'warn'}">${action.reviewable?'可审核':action.kind==='exact'?'需选承接组':'证据待补'}</span></div>
      <p>${escapeHtml(action.reason||'本批次没有返回判断理由')}</p><div class="ad-metric-grid" aria-label="该处理对象的领星指标">${adMetricTiles(adMetricSummary(action))}</div>
      ${bid?`<div class="decision-bid-facts"><span>基础竞价 <b>${fmt(evidence.base_bid,2)}</b></span><span>实际 CPC <b>${fmt(adMetricSummary(action).cpc,2)}</b></span><span>活动日预算 <b>${fmt(evidence.budget,2)}</b></span><span>策略 <b>${escapeHtml(evidence.bidding_strategy||'未取得')}</b></span>${action.effective_bid_ceiling!=null?`<span>配置理论上限 <b>${fmt(action.effective_bid_ceiling,2)}</b> · 非实际 CPC</span>`:''}</div>`:''}
      ${action.kind==='exact'?`<div class="decision-bid-facts"><span>方案参考出价 <b>${fmt(action.suggested_bid,2)}</b> · 需运营确认</span><span>历史目标状态仍须复核</span></div>`:''}
      ${(action.affected_asins||[]).length>1?`<small class="decision-affected">关联子 ASIN ${escapeHtml(action.affected_asins.join(' / '))} · 组级数值不拆分</small>`:''}
      ${groups.length?`<details class="disclosure"><summary>查看 ${groups.length} 个来源广告组</summary><div class="decision-source-list">${groups.map(group=>`<div><strong>${escapeHtml(group.campaignName)} / ${escapeHtml(group.adGroupName)}</strong><span>${fmt(group.clicks)} 点击 · ${fmt(group.orders)} 单 · 花费 ${fmt(group.spend,2)}</span></div>`).join('')}</div></details>`:''}
      <div class="decision-review"><small>运营意见</small>${reviewControl(action)}</div></article>`;
  }

  function renderDecisionDrawer(){
    const root=document.getElementById('decision-drawer');
    if(!root)return;
    const context=state.decisionDrawer;
    const product=context&&products.find(item=>item.key===context.productKey);
    const row=product&&productKeywords(product).find(item=>item.id===context.keywordId);
    if(!context||!product||!row||state.view!=='product'||state.domain!=='growth'||state.growthView!=='rank'){
      root.hidden=true;root.innerHTML='';document.body?.classList?.remove('decision-open');return;
    }
    root.innerHTML=decisionDrawerHtml(row,product,context.pane);
    root.hidden=false;document.body?.classList?.add('decision-open');
    root.querySelectorAll?.('[data-decision-close]').forEach(el=>el.addEventListener('click',closeDecisionDrawer));
    root.querySelectorAll?.('[data-decision-tab]').forEach(el=>el.addEventListener('click',()=>{
      state.decisionDrawer.pane=el.dataset.decisionTab;renderDecisionDrawer()}));
    root.querySelectorAll?.('[data-review]').forEach(el=>el.addEventListener('click',()=>saveReview(el.dataset.action,el.dataset.profile,el.dataset.review)));
    root.querySelectorAll?.('[data-probe]').forEach(el=>el.addEventListener('click',()=>saveReview(el.dataset.probe,el.dataset.profile,el.dataset.probeValue)));
  }

  function openDecisionDrawer(rowId,pane,trigger){
    hideVerdictTooltip(true);
    const product=selectedProduct();
    if(!product||!productKeywords(product).some(row=>row.id===rowId))return;
    drawerReturnFocus=trigger;state.decisionDrawer={productKey:product.key,keywordId:rowId,pane};
    renderDecisionDrawer();document.getElementById('decision-drawer')?.querySelector?.('[data-decision-close]')?.focus?.();
  }

  function closeDecisionDrawer(){
    state.decisionDrawer=null;renderDecisionDrawer();
    if(drawerReturnFocus?.isConnected)drawerReturnFocus.focus();
    drawerReturnFocus=null;
  }

  function rankChart(row,focus){
    const [start,end]=rankWindow(row,row.rank_as_of_date||board.as_of_date||board.fetched_at.slice(0,10));
    const series=rankSeries(row.rank_observations||[],start,end);
    const observed=series.flatMap(day=>[day.natural,day.advertising]).filter(v=>v!=null&&Number.isFinite(v));
    if(!observed.length)return '<div class="empty"><strong>暂无可绘制的绝对排名</strong>自然/广告页位原文及缺口仍可在下方逐日查看；页位不伪装成名次曲线。</div>';
    const width=800,height=216,left=46,right=20,top=20,bottom=32;
    const best=Math.min(...observed),worst=Math.max(...observed),span=Math.max(1,worst-best);
    const x=i=>left+i*(width-left-right)/(series.length-1);
    const y=v=>top+(v-best)/span*(height-top-bottom);
    const draw=(key,color)=>{let path='',previous=false;const points=[];series.forEach((day,i)=>{const value=day[key];if(value==null){previous=false;return}path+=`${previous?'L':'M'}${x(i).toFixed(1)},${y(value).toFixed(1)} `;previous=true;
      points.push(`<circle cx="${x(i)}" cy="${y(value)}" r="4.5" fill="${color}" stroke="#071b24" stroke-width="2"/>`)});return `<g opacity="${focus===key?'1':'.38'}"><path d="${path}" fill="none" stroke="${color}" stroke-width="${focus===key?'3.6':'2.5'}" stroke-linecap="round" stroke-linejoin="round"/>${points.join('')}</g>`};
    const grid=Array.from({length:5},(_,i)=>{const value=best+span*i/4,yy=y(value);return `<line x1="${left}" x2="${width-right}" y1="${yy}" y2="${yy}" stroke="#294651" stroke-dasharray="${i===0||i===4?'0':'3 5'}"/><text x="${left-10}" y="${yy+4}" text-anchor="end" fill="#8caab0" font-size="11">${fmt(value)}</text>`}).join('');
    const labels=series.filter((_,i)=>i===0||i===3||i===6||i===10||i===13).map(day=>{const i=series.indexOf(day);return `<text x="${x(i)}" y="${height-8}" text-anchor="middle" fill="#849da1" font-size="11">${day.date.slice(5)}</text>`}).join('');
    const hitWidth=(width-left-right)/(series.length-1);
    const hits=series.map((day,i)=>{const page=rankPresentation({latest:null,days:0},day.adDisplay);return `<rect class="rank-hit" x="${x(i)-hitWidth/2}" y="${top}" width="${hitWidth}" height="${height-top-bottom}" fill="transparent" data-label="${escapeHtml(day.date)} · 自然 ${day.natural!=null?`#${fmt(day.natural)}`:'未观测'} · SP 广告 ${day.advertising!=null?`#${fmt(day.advertising)}`:escapeHtml(page.kind==='page'?page.label:day.adDisplay||'未观测')}"/>`}).join('');
    return `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="最近两个完整 SIF 周自然与广告绝对名次；悬停任意日期可同时查看两种名次，断线代表缺口">${grid}${draw('natural','#46dec8')}${draw('advertising','#ffbd68')}${hits}${labels}</svg>`;
  }

  function rankDays(row){
    const [start]=rankWindow(row,row.rank_as_of_date||board.as_of_date||board.fetched_at.slice(0,10));
    const observations=new Map((row.rank_observations||[]).filter(v=>v.state==='absolute_rank'||v.state==='reported_position')
      .map(v=>{const page=rankPresentation({latest:null,days:0},v.display);return [`${v.observed_date}|${v.channel}`,
        v.state==='absolute_rank'?`#${fmt(v.rank)}`:page.kind==='page'?page.label:(v.display||'—')]}));
    return Array.from({length:14},(_,i)=>{const day=new Date(`${start}T00:00:00Z`);day.setUTCDate(day.getUTCDate()+i);const date=day.toISOString().slice(0,10);
      const natural=observations.get(`${date}|natural`),ad=observations.get(`${date}|advertising`);
      return `<span class="rank-day ${natural||ad?'measured':''}" title="${date} · 自然 ${escapeHtml(natural||'缺')} / 广告位 ${escapeHtml(ad||'缺')}"><small>${date.slice(5)}</small><b>${escapeHtml(natural||'—')}</b><em>${escapeHtml(ad||'—')}</em></span>`}).join('');
  }

  function observationTable(rows,product){
    return `<div class="table-wrap ad-observation-table"><table><thead><tr><th>产品</th><th>广告组合</th><th>活动</th><th>广告组</th><th>搜索词</th><th>原因</th><th>花费</th></tr></thead><tbody>${rows.map(a=>`<tr><td>${escapeHtml(product.name||product.asin)}</td><td>${escapeHtml(a.portfolio_name||'未解析')}</td><td>${escapeHtml(a.campaign_name||'未解析')}</td><td>${escapeHtml(a.ad_group_name||'未解析')}</td><td><strong>${escapeHtml(a.query)}</strong></td><td>${escapeHtml(a.reason)}</td><td>${fmt(a.spend,2)}</td></tr>`).join('')}</tbody></table></div>`;
  }

  function advertisingContent(product) {
    const actions = product.actions || [];
    const issues = (product.issues||[]).filter(i=>i.domain==='advertising');
    const pending=actions.filter(a=>!['observe','bid_review'].includes(a.kind)&&!a.processed_status);
    const processed=actions.filter(a=>!['observe','bid_review'].includes(a.kind)&&a.processed_status);
    const observing=actions.filter(a=>a.kind==='observe');
    const gaps=pending.filter(a=>!a.reviewable);
    const filtered=(state.adFilter==='observe'?observing:state.adFilter==='processed'?processed:state.adFilter==='gaps'?gaps:state.adFilter==='all'?pending:
      pending.filter(a=>state.adFilter==='negative'?a.kind==='negative'||a.kind==='negative_asin':a.kind==='exact'))
      .sort((a,b)=>Number(Boolean(b.reviewable))-Number(Boolean(a.reviewable))||(Number(b.spend)||0)-(Number(a.spend)||0));
    const probes=probeRows(product),profile=productProfile(product);
    const bidItems=bidReviewItems(product);
    const selectedProbes=probes.filter(row=>state.review.items[probeActionKey(profile,row)]?.value==='accept');
    return `<section class="panel ads-workbench"><div class="panel-title"><div><span class="eyebrow">INTERNAL SEARCH TERMS × EXTERNAL OPPORTUNITY</span><h3>广告决策中心</h3><p>内部否词/精准按专业规则的对象与门槛审核；外部词先核验相关性和当前投放，不凭空估计转化。</p></div><span class="pill action">${actionCount(actions)} 个专业待办</span></div>
      <div class="ad-summary" role="group" aria-label="广告处置摘要，点击筛选">
        ${[['all','专业待办',pending.length,'count-all'],
           ['negative','否词复核',pending.filter(a=>a.kind==='negative'||a.kind==='negative_asin').length,'count-negative'],
           ['exact','精准方案',pending.filter(a=>a.kind==='exact').length,'count-exact'],
           ['bid','调价可审',bidItems.filter(item=>item.action.reviewable).length,'count-bid'],
           ['observe','观察池',observing.length,'count-observe'],
           ['probe','外部核验',selectedProbes.length,'count-probe'],
           ['processed','已处理',processed.length,'count-processed'],
           ['gaps','待补证据',gaps.length,'count-gaps']]
          .map(([key,label,value,cls])=>`<button type="button" class="ad-summary-chip ${state.adFilter===key?'active':''}" data-ad-filter="${key}" aria-pressed="${state.adFilter===key}"><span>${label}</span><b class="${cls}">${value}</b></button>`).join('')}
      </div>
      <details class="disclosure ad-reading-guide"><summary>？ 审核口径与限制</summary><p>每行的 10 项参数由本动作来源行先合并、再计算 CTR/CPC/ACOS/CPA/CVR，不平均比例。搜索词与否词动作落在广告组，关联多个变体也不拆分花费与订单。点击“判断依据”查看专业规则结论、活动/组原始汇总和历史精准状态；保存运营意见不等于写回广告。</p></details>
      ${state.adFilter==='observe'?`<div class="ad-observation-head"><strong>观察池 · ${observing.length}</strong><span>只读；需要动作时回到对应待办筛选。</span></div>${observing.length?observationTable(observing,product):'<div class="empty"><strong>当前没有观察词</strong>可回专业待办查看明确动作。</div>'}`
        :state.adFilter==='bid'?bidReviewContent(bidItems):state.adFilter==='probe'?`<div class="probe-intro"><strong>从 SIF 发现到精准试投，先过三道门</strong><span>① 商品相关性由运营确认　② 领星活跃精准投放目标复核　③ 承接广告组与出价复核</span><small>第 ②、③ 项本批次尚无完整目标清单，加入核验不等于可写回。</small></div>${probes.length?`<div class="table-wrap"><table><thead><tr><th>外部关键词</th><th>SIF 当前周</th><th>排名线索</th><th>运营核验意向</th></tr></thead><tbody>${probes.map(row=>{const key=probeActionKey(profile,row),decision=state.review.items[key],digest=rankDigest(row,row.rank_as_of_date||board.as_of_date);return `<tr><td><strong>${escapeHtml(row.keyword)}</strong><br><span class="muted">SIF 本品词库 · 无可归属内部搜索词记录</span></td><td>${fmt(row.weekly_volume)}</td><td>自然 ${escapeHtml(rankPresentation(digest.natural,row.natural_rank_display).label)}<br>广告 ${escapeHtml(rankPresentation(digest.advertising,row.ad_rank_display).label)}</td><td><button type="button" class="probe-toggle ${decision?.value==='accept'?'selected':''}" data-probe="${escapeHtml(key)}" data-profile="${escapeHtml(profile)}" data-probe-value="${decision?.value==='accept'?'reject':'accept'}" ${state.review.connected?'':'disabled'}>${decision?.value==='accept'?'☑ 已加入核验':'☐ 加入试投核验'}</button>${decision?.note?`<small class="probe-note">理由：${escapeHtml(decision.note)}</small>`:''}</td></tr>`}).join('')}</tbody></table></div>`:'<div class="empty"><strong>此 ASIN 没有符合本批次条件的外部独有词</strong>不是 SIF 没有机会词；只是已取词库中没有可直接列入此核验池的词。</div>'}`:
      filtered.length?`<div class="ad-action-list">${filtered.slice(0,state.adLimit).map(a=>adActionRow(a,false)).join('')}</div>${filtered.length>state.adLimit?`<button class="more" data-more="ads">继续显示（剩余 ${filtered.length-state.adLimit}）</button>`:''}`:'<div class="empty"><strong>当前筛选下没有专业广告动作</strong>可切换“外部试投核验”或回关键词雷达查看证据。</div>'}
      <p class="footnote">${window.B_REVIEW?(state.review.connected?'审核已连接。意见会保存，但不会自动写回领星。':'审核未连接；页面保持只读，请重开同批次服务。'):'只读快照。运营确认须在本批次审核服务保存。'} 否词执行仍需冻结批次复核；精准方案和 SIF 外部试投意向当前均不具备自动写回资格。</p></section>`;
  }

  function bidReviewItems(product){
    const source=product?.actions||board.actions||[];
    const unique=new Map();
    for(const action of source){
      if(action.kind!=='bid_review'||!action.action_key||unique.has(action.action_key))continue;
      const sid=board.profile_to_sid?.[action.profile_id];
      const owner=product||products.find(p=>String(p.sid)===String(sid)&&action.affected_asins?.includes(p.asin));
      if(!owner||state.shop!=='all'&&String(owner.sid)!==state.shop)continue;
      const row=productKeywords(owner).find(item=>item.normalized===action.normalized_keyword);
      unique.set(action.action_key,{action,product:owner,row});
    }
    return [...unique.values()].sort((a,b)=>Number(b.action.action_key===state.bidFocus)-Number(a.action.action_key===state.bidFocus)||
      Number(Boolean(b.action.reviewable))-Number(Boolean(a.action.reviewable))||
      (Number(b.action.spend)||0)-(Number(a.action.spend)||0));
  }

  function bidDirectionLabel(direction){
    return ({consider_raise:'可考虑小幅上调',consider_lower:'可考虑降低',hold_visibility:'广告已可见 · 守位',
      hold_organic:'自然靠前 · 先守位',hold_for_review:'继续观察',needs_rank:'排名证据不足',
      needs_budget:'预算证据不足',needs_rank_and_budget:'排名与预算待补',budget_first:'先核预算 · 不直接加价',
      variant_rank_gap:'变体词位不全',variant_rank_conflict:'变体词位方向冲突',
      conflict_negative:'与否词建议冲突'})[direction]||'待核对';
  }

  function bidReviewContent(items){
    if(!items.length)return '<div class="empty"><strong>本批次没有可关联的精准目标报表行</strong>这不是“没有精准投放”；报表可能缺少零点击或停投目标。</div>';
    const visible=items.slice(0,state.bidLimit);
    const ready=items.filter(({action})=>action.reviewable).length;
    return `<div class="bid-review-intro"><strong>按关键词/商品目标复核竞价；排名只作外部位置线索</strong><span>领星目标级表现与活动预算、竞价策略配对后给方向。SIF ASIN 排名不归因于某个广告目标；无充分证据时只读。接受后保存目标出价，由智能体生成写回批次。</span></div>
      <p class="bid-list-count">${fmt(ready)} 个可审核 · ${fmt(items.length-ready)} 个只读待补证据 · 已显示 ${fmt(visible.length)} / ${fmt(items.length)}</p>
      <div class="bid-review-list">${visible.map(({action,product,row})=>{
        const evidence=action.bid_evidence||{},rank=action.rank_evidence||{};
        const boost=evidence.placement_adjustments||{};
        const placement=Object.entries(boost).map(([name,value])=>`${name==='placementTop'?'Top':name==='placementRestOfSearch'?'其余搜索位':name==='placementProductPage'?'商品页':name} +${fmt(value)}%`).join(' · ')||'未取得';
        const adRank=rank.advertising_latest!=null?`#${fmt(rank.advertising_latest)}`:rank.advertising_page_latest?`第 ${fmt(rank.advertising_page_latest)} 页`:'未观测';
        const rankScope=rank.review_basis==='directional'?'方向性词位线索 · 非完整双周曲线':'';
        const ceilingLabel=action.effective_bid_ceiling!=null?'目标基础竞价 / 仅降低策略下最高位置出价':'目标基础竞价 / 位置竞价上限不可推算';
        return `<article data-action-row="${escapeHtml(action.action_key)}" class="bid-review-card has-complex-review"><div class="bid-review-head"><div><small>${escapeHtml(product.shop)} · ${escapeHtml((action.affected_asins||[]).join(' / '))}${(action.affected_asins||[]).length>1?' · 共享组不拆分':''}</small><strong>${escapeHtml(action.query)}</strong></div><span class="pill ${action.direction==='consider_raise'||action.direction==='consider_lower'?'warn':''}">${escapeHtml(bidDirectionLabel(action.direction))}</span></div>
          <div class="bid-review-facts"><span>自然 ${rank.natural_latest!=null?`#${fmt(rank.natural_latest)}`:'未观测'}</span><span>SP 广告 ${adRank}</span><span>${rank.natural_week_days&&rank.advertising_week_days?`自然 ${rank.natural_week_days.map(day=>fmt(day)).join('+')} 天 · 广告 ${rank.advertising_week_days.map(day=>fmt(day)).join('+')} 天`:`两渠道覆盖待核 · ${fmt(rank.observed_days)} / 14 天`}</span><span>目标级 ACOS ${pct(action.acos)}</span>${rankScope?`<span>${rankScope}</span>`:''}</div>
          ${(action.affected_asins||[]).length>1?`<details class="disclosure"><summary>查看 ${action.affected_asins.length} 个关联变体的各自排名</summary><div class="bid-review-facts">${action.affected_asins.map(asin=>{const child=rank.children?.[asin]||{};return `<span>${escapeHtml(asin)} · 自然 ${child.natural_latest!=null?`#${fmt(child.natural_latest)}`:'缺'} · 广告 ${child.advertising_latest!=null?`#${fmt(child.advertising_latest)}`:child.advertising_page_latest?`第 ${fmt(child.advertising_page_latest)} 页`:'缺'} · ${fmt(child.observed_days)}/14 天</span>`}).join('')}</div></details>`:''}
          <div class="ad-metric-grid" aria-label="领星精准目标报表指标">${adMetricTiles(adMetricSummary(action))}</div>
          <div class="bid-source-comparison"><div><small>${ceilingLabel}</small><strong>${fmt(evidence.base_bid,2)} / ${fmt(action.effective_bid_ceiling,2)}</strong><span>${escapeHtml(evidence.bidding_strategy||'策略未取得')} · ${escapeHtml(placement)}</span></div><div><small>活动日预算 / 实际 CPC</small><strong>${fmt(evidence.budget,2)} / ${fmt(adMetricSummary(action).cpc,2)}</strong><span>目标 ${escapeHtml(action.query||'未取得')} · 活动 ${escapeHtml(action.campaign_name||action.campaign_id)} / 组 ${escapeHtml(action.ad_group_name||'未命名广告组')}</span>${action.budget_utilization_proxy!=null?`<span>14 日花费占日预算合计约 ${pct(action.budget_utilization_proxy)}；非逐日预算耗尽证明</span>`:''}</div></div>
          <p>${escapeHtml(action.reason)}${action.reviewable?' 方向可供运营复核，目标价须手动确认。':' 当前缺口不足以生成可审核调价方案。'}</p>
          <div class="bid-review-links">${row?`<button type="button" class="action-link" data-bid-rank="${escapeHtml(action.action_key)}" aria-expanded="${state.bidRank===action.action_key}">${state.bidRank===action.action_key?'收起 14 天排名':'看 14 天排名'}</button>`:''}</div>${reviewControl(action,!(state.view==='queue'&&state.shop==='all'))}
          ${state.bidRank===action.action_key?`<div class="bid-rank-inline"><div class="bid-rank-head"><strong>14 天排名 · ${escapeHtml(action.query)}</strong><button type="button" class="action-link" data-bid-rank-close>收起</button></div>${row?keywordRankDetail(row,'natural'):'<div class="empty">该类目词没有可展开的排名曲线</div>'}</div>`:''}
          <details class="disclosure"><summary>数据口径与风险</summary><p>目标表现来自领星 SP 关键词目标报表 ${escapeHtml((board.periods?.sif_rank||[]).join(' → '))}；活动预算与出价策略来自同期间活动报表。报告缺行不证明目标不存在。SIF 排名按 ASIN 观察，非该目标的直接转化归因。位置加价显示的是配置上限，不等于实际 CPC；若分时/动态策略未核实，则不显示最高位置出价。</p></details></article>`;
      }).join('')}</div>${visible.length<items.length?'<button type="button" class="more-button" data-more="bid">继续显示 20 条</button>':''}`;
  }

  function adActionRow(action,global){
    const sid=board.profile_to_sid?.[action.profile_id];
    const target=products.find(p=>String(p.sid)===String(sid)&&action.affected_asins?.includes(p.asin));
    const shop=target?.shop||products.find(p=>String(p.sid)===String(sid))?.shop||String(sid||'未知店铺');
    const label=({negative:'搜索词精准否定',negative_asin:'ASIN 精准否定',exact:'精准投放方案'})[action.kind]||'观察';
    const status=action.processed_status==='already_exact_negative'?'已否定':action.processed_status==='already_exact_running'?'已有在投精准':
      action.reviewable?'待运营确认':'证据待补';
    const groups=adSourceGroups(action);
    const exactMatches=action.kind==='exact'&&action.processed_status==='already_exact_running'?
      action.existing_exact_matches||[]:[];
    const metricTiles=adMetricTiles(adMetricSummary(action));
    const sourceTable=groups.length?`<div class="ad-source-scroll"><table><thead><tr><th>活动 / 广告组</th><th>匹配 · 原始记录</th><th>曝光</th><th>点击</th><th>CTR</th><th>实际 CPC</th><th>ACOS</th><th>花费</th><th>广告销售额</th><th>广告订单</th><th>CPA</th><th>CVR</th></tr></thead><tbody>${groups.map(group=>{const m=adMetricSummary(group);return `<tr><td><strong>${escapeHtml(group.campaignName)}</strong><br><span class="muted">${escapeHtml(group.adGroupName)}</span>${group.defaultDestination?'<br><span class="pill action">默认承接</span>':''}${group.sharedGroup?'<br><span class="pill warn">共享组</span>':''}</td><td>${escapeHtml(group.matchTypes.join(' / ')||'—')}<br><span class="muted">${fmt(group.recordCount)} 条记录</span></td><td>${fmt(m.impressions)}</td><td>${fmt(m.clicks)}</td><td>${m.ctr==null?'无曝光':pct(m.ctr)}</td><td>${m.cpc==null?'无点击':fmt(m.cpc,2)}</td><td>${m.acos==null?'无销售':pct(m.acos)}</td><td>${fmt(m.spend,2)}</td><td>${fmt(m.sales,2)}</td><td>${fmt(m.orders)}</td><td>${m.cpa==null?'无订单':fmt(m.cpa,2)}</td><td>${m.cvr==null?'无点击':pct(m.cvr)}</td></tr>`}).join('')}</tbody></table></div>`:'<p class="muted">来源行未返回；请核对批次原始记录。</p>';
    const exactTable=exactMatches.length?`<div class="ad-source-scroll"><table><thead><tr><th>在投精准活动 / 广告组</th><th>目标 / 状态</th><th>当前竞价</th><th>曝光</th><th>点击</th><th>花费</th><th>广告销售额</th><th>广告订单</th><th>ACOS</th></tr></thead><tbody>${exactMatches.map(match=>{const m=adMetricSummary(match);return `<tr><td><strong>${escapeHtml(match.campaign_name||match.campaign_id||'—')}</strong><br>${escapeHtml(match.ad_group_name||match.ad_group_id||'—')}</td><td>${escapeHtml(match.targeting_text||match.query||action.query)}<br><span class="muted">${escapeHtml(match.target_state||'状态未返回')}</span></td><td>${fmt(match.bid,2)}</td><td>${fmt(m.impressions)}</td><td>${fmt(m.clicks)}</td><td>${fmt(m.spend,2)}</td><td>${fmt(m.sales,2)}</td><td>${fmt(m.orders)}</td><td>${m.acos==null?'无销售':pct(m.acos)}</td></tr>`}).join('')}</tbody></table></div>`:'<p class="data-gap">本批次未保留在投精准匹配来源明细；须重跑专业诊断后再复核。</p>';
    const plan=action.kind!=='exact'?'':action.processed_status==='already_exact_running'?`<p class="ad-plan">已核实在投精准目标，不重复新增。${action.exact_match_source==='keyword_target_report'?'下表为本批次目标级报表；竞价建议请到“在投精准复核”。':'下表是搜索词匹配线索，不等于完整目标级表现。'}</p>`:
      `<p class="ad-plan">精准方案：${action.exact_plan?.target_ad_group_id?`默认承接 ${escapeHtml(action.exact_plan.target_campaign_name||action.campaign_name)} / ${escapeHtml(action.exact_plan.target_ad_group_name||action.ad_group_name)}；`:''}建议出价 ${fmt(action.suggested_bid,2)} 来自合并实际 CPC。新增前须核查全量精准目标及历史停投原因；本批次搜索词未命中在投，不等于从未投放。当前仅保存方案，不写回。</p>`;
    const asins=action.affected_asins||[];
    const scopeText=asins.length>1?`${escapeHtml(asins.slice(0,2).join(' / '))}${asins.length>2?` 等 ${asins.length} 个 ASIN`:''}`:escapeHtml(asins[0]||'未归属产品');
    return `<article data-action-row="${escapeHtml(action.action_key)}" class="ad-action-card ${action.processed_status?'ad-processed':''} ${['exact','bid_review'].includes(action.kind)?'has-complex-review':''}"><div class="ad-action-top"><div class="ad-action-identity"><span class="ad-kind">${escapeHtml(label)} · ${escapeHtml(status)}</span><strong>${escapeHtml(action.query)}</strong><small>${escapeHtml(shop)} · ${scopeText}</small>${global&&target?`<button class="text-link" data-open-product="${escapeHtml(target.key)}">进入关联单品 ↗</button>`:''}</div>
      <div class="ad-metric-block"><div class="ad-metric-grid" aria-label="该动作合并来源后的广告指标">${metricTiles}</div></div><div class="ad-action-review"><span class="ad-column-label">运营意见</span>${reviewControl(action,!(global&&state.shop==='all'))}</div></div>
      <details class="ad-evidence" ${state.expandedAction===action.action_key?'open':''}><summary>判断依据与活动明细 · ${fmt(groups.length)} 组${exactMatches.length?` · ${fmt(exactMatches.length)} 条精准目标`:''}</summary><div class="ad-evidence-body"><p class="ad-evidence-note">${escapeHtml(action.reason)}${action.reference_cpa==null?'':` · 参考 CPA ${fmt(action.reference_cpa,2)}`}</p>${plan}<div class="ad-source-label">${action.kind==='exact'?'非精准候选搜索词来源':'广告组搜索词来源'}</div>${sourceTable}${action.processed_status==='already_exact_running'?`<div class="ad-source-label">${action.exact_match_source==='keyword_target_report'?'领星精准目标报表':'已在投精准匹配搜索词（非完整目标表现）'}</div>${exactTable}`:''}${asins.length>1?`<p class="ad-evidence-note">关联 ASIN：${escapeHtml(asins.join(' / '))}；共享广告组的花费、订单和销售额不按产品拆分。</p>`:''}</div></details></article>`;
  }

  function adMetricTiles(m){
    const items=[['曝光',fmt(m.impressions)],['点击',fmt(m.clicks)],['CTR',m.ctr==null?'无曝光':pct(m.ctr)],
      ['实际 CPC',m.cpc==null?'无点击':fmt(m.cpc,2)],['ACOS',m.acos==null?'无销售':pct(m.acos)],
      ['花费',fmt(m.spend,2)],['广告销售额',fmt(m.sales,2)],['广告订单',fmt(m.orders)],
      ['CPA',m.cpa==null?'无订单':fmt(m.cpa,2)],['CVR',m.cvr==null?'无点击':pct(m.cvr)]];
    return items.map(([label,value])=>`<div class="ad-metric"><small>${escapeHtml(label)}</small><strong>${escapeHtml(value)}</strong></div>`).join('');
  }

  function exactTargets(action){
    const all=(board.ad_group_options||[]).filter(row=>String(row.profile_id)===String(action.profile_id));
    const source=`${action.campaign_id}|${action.ad_group_id}`;
    const sourceOption=all.find(row=>`${row.campaign_id}|${row.ad_group_id}`===source);
    const portfolio=action.portfolio_id||sourceOption?.portfolio_id||'';
    const rows=all.filter(row=>row.campaign_state==='enabled'&&row.ad_group_state==='enabled'&&(!portfolio||String(row.portfolio_id)===String(portfolio)));
    const seen=new Set(),out=[];
    const sourceRow=sourceOption||{campaign_id:action.campaign_id,campaign_name:action.campaign_name||action.campaign_id,ad_group_id:action.ad_group_id,ad_group_name:action.ad_group_name||'未命名广告组',portfolio_id:portfolio,portfolio_name:action.portfolio_name};
    if(action.campaign_id&&action.ad_group_id&&(sourceRow.campaign_state==='enabled'||!sourceRow.campaign_state)){out.push({...sourceRow,is_source:true});seen.add(source)}
    for(const row of rows){const key=`${row.campaign_id}|${row.ad_group_id}`;if(!seen.has(key)){seen.add(key);out.push(row)}}
    return out;
  }

  function exactTargetSelect(action){
    const options=exactTargets(action);
    if(!options.length)return '';
    const saved=state.review.items[action.action_key];
    const selected=`${saved?.target_campaign_id||''}|${saved?.target_ad_group_id||''}`;
    return `<label class="exact-target"><span>承接组</span><select data-exact-target="${escapeHtml(action.action_key)}">${options.map((row,index)=>{const value=`${row.campaign_id}|${row.ad_group_id}`;const active=selected?value===selected:index===0;const label=`${row.campaign_name} / ${row.ad_group_name}${row.is_source?' · 原广告组':''}`;return `<option value="${escapeHtml(value)}" title="${escapeHtml(label)}" ${active?'selected':''}>${escapeHtml(label)}</option>`}).join('')}</select></label>`;
  }

  function reviewControl(action,shopReady=true){
    const decision=state.review.items[action.action_key];
    const current=decision?({accept:'已接受',reject:'已拒绝',observe:'继续观察',modify:'已更改',executed:'已执行'}[decision.value]||decision.value):'未审核';
    if(action.processed_status)return `<span class="pill">${escapeHtml(current==='未审核'?'来源已处理':current)}</span>`;
    if(decision?.value==='executed'){
      const oldBid=action.bid_evidence?.base_bid;
      const done=action.kind==='bid_review'
        ? `已执行 · ${oldBid==null?'原价未取得':`£${Number(oldBid).toFixed(2)} → £${Number(decision.bid).toFixed(2)}`}`
        : action.kind==='exact'
          ? `已执行 · 新增精准 £${Number(decision.bid).toFixed(2)}`
          : '已执行 · 新增否定';
      return `<span class="pill action">${escapeHtml(done)}</span>`;
    }
    const exactReady=action.kind==='exact'&&exactTargets(action).length>0;
    if(!action.reviewable&&!exactReady)return `<span class="pill warn">${escapeHtml(action.blocked_reason||'证据待补')} · 只读</span>`;
    if(!shopReady)return `<span class="pill">选单店铺后审核</span>`;
    if(!window.B_REVIEW||!state.review.connected)return `<span class="pill">${current} · 只读</span>`;
    const confirmed=decision?.value==='accept';
    const bidValue=decision?.bid??action.suggested_bid??action.bid_evidence?.base_bid??'';
    const oldBid=action.bid_evidence?.base_bid;
    const bidLabel=action.kind==='bid_review'
      ? (oldBid==null?'目标竞价（原价未取得）':`原价 £${Number(oldBid).toFixed(2)} → 新价`)
      : '新增精准 · 出价';
    const bidInput=['exact','bid_review'].includes(action.kind)?`<label class="review-bid"><span>${escapeHtml(bidLabel)}</span><input type="number" min="0.01" max="1000" step="0.01" data-review-bid="${escapeHtml(action.action_key)}" value="${bidValue===''?'':Number(bidValue).toFixed(2)}"></label>`:'';
    const form=action.kind==='exact'?`<div class="review-form">${exactTargetSelect(action)}${bidInput}</div>`
      :action.kind==='bid_review'?`<div class="review-form bid-form">${bidInput}</div>`:'';
    return `<div class="review-cell">${form}<div class="review-actions"><span class="pill ${confirmed?'action':''}">${confirmed?'已确认 · 待写回':current}${decision?.bid?` · ${fmt(decision.bid,2)}`:''}</span><div class="review-buttons">
      <button class="review-btn review-accept ${decision?.value==='accept'?'is-active':''}" aria-pressed="${decision?.value==='accept'}" data-review="accept" data-action="${escapeHtml(action.action_key)}" data-profile="${escapeHtml(action.profile_id)}">接受</button>
      <button class="review-btn review-reject ${decision?.value==='reject'?'is-active':''}" aria-pressed="${decision?.value==='reject'}" data-review="reject" data-action="${escapeHtml(action.action_key)}" data-profile="${escapeHtml(action.profile_id)}">拒绝</button>
      <button class="review-btn review-observe ${decision?.value==='observe'?'is-active':''}" aria-pressed="${decision?.value==='observe'}" data-review="observe" data-action="${escapeHtml(action.action_key)}" data-profile="${escapeHtml(action.profile_id)}">观察</button>
      <button class="review-btn review-modify ${decision?.value==='modify'?'is-active':''}" aria-pressed="${decision?.value==='modify'}" data-review="modify" data-action="${escapeHtml(action.action_key)}" data-profile="${escapeHtml(action.profile_id)}">更改</button></div></div></div>`;
  }

  // ---------- PMC inventory cockpit ----------
  const PMC_TABS = {
    ship:{eyebrow:'SHIP',title:'本周发货',head:['产品 / ASIN','断货区间','风险金额','可执行发货','走法','到仓 / 剩余']},
    buy:{eyebrow:'BUY',title:'本周采购',head:['产品 / ASIN','建议采','金额','首单下单','首单到货','本地参考','口径']},
    risk:{eyebrow:'RISK',title:'断货风险',head:['产品 / ASIN','断货区间','断货天数','风险金额','下一批供应']},
    aged:{eyebrow:'AGED',title:'超龄清理',head:['产品 / ASIN','>90 天件数','占用金额','占超龄金额','建议']}
  };
  const PMC_PRESET_LABELS = {base:'基准（自动）',default:'默认情景',peak:'旺季 +30%',conservative:'保守 -15%',delay:'物流延误 +14 天',custom:'自定义试算'};
  const PMC_TIER_ORDER = {P0:0,P1:1,P2:2};
  const PMC_RISK_LABEL = {critical:'断货风险',warning:'发货 / 货源待复核',procurement:'采购时点待复核',overstock:'冗余待处理',healthy:'健康'};
  function pmcConfidenceLabel(value) { return ({high:'高',medium:'中',low:'低'})[value]||value||'低'; }

  function pmcMoney(value) {
    const number=Number(value||0);
    return number ? `£${Math.round(number).toLocaleString('zh-CN')}` : '—';
  }
  function pmcDate(value) {
    if(!value)return '—';
    const text=String(value).slice(0,10).split('-');
    return text.length===3?`${text[1]}/${text[2]}`:String(value);
  }
  function pmcFullDate(value) { return value?String(value).slice(0,10):'—'; }
  function pmcDaysBetween(first,second) {
    if(!first||!second)return null;
    return Math.round((new Date(`${String(second).slice(0,10)}T00:00:00Z`)-new Date(`${String(first).slice(0,10)}T00:00:00Z`))/86400000);
  }
  function pmcIsoWeek(value) {
    if(!value)return '—';
    const date=new Date(`${String(value).slice(0,10)}T00:00:00Z`);
    const target=new Date(date.valueOf());
    target.setUTCDate(target.getUTCDate()-((date.getUTCDay()+6)%7)+3);
    const firstThursday=new Date(Date.UTC(target.getUTCFullYear(),0,4));
    return `W${String(1+Math.round((target.getTime()-firstThursday.getTime())/604800000)).padStart(2,'0')}`;
  }
  function pmcTier(product) {
    const tier=product.inventory_pmc?.basis?.priorityTier||'P2';
    return PMC_TIER_ORDER[tier]===undefined?'P2':tier;
  }
  function pmcRisk(product) { return product.inventory_pmc?.risk||'healthy'; }
  function pmcRiskText(product) { return PMC_RISK_LABEL[pmcRisk(product)]||'库存观察'; }
  function pmcIsActive(product) { return Number(product.inventory_pmc?.listingStatus)===1; }
  function pmcShipmentView(pmc) {
    const batches=pmc?.shipmentBatches||[];
    const plan=pmc?.shipmentPlan;
    const annotate=batch=>{
      const fundedQty=Number(batch.fundedQty??batch.shipNowQty??batch.executableQty??0);
      const needQty=Number(batch.needQty??batch.suggestedQty??0);
      const immediate=String(batch.dispatchDate||'').slice(0,10)===String(pmc?.asOf||'').slice(0,10)&&fundedQty>0;
      return {
        ...batch,
        fundedQty,
        remainingQty:Math.max(0,Number(batch.remainingQty??(needQty-fundedQty))),
        phase:batch.phase||(immediate?'immediate':fundedQty>0?'planned':'unavailable'),
        funding:batch.funding||(Number(batch.purchaseQty)>0?'purchase':'local'),
        actionableNow:Boolean(batch.actionableNow??immediate),
        needQty,
        shipNowQty:fundedQty
      };
    };
    const bySequence=new Map(batches.map(batch=>[Number(batch.sequence),annotate(batch)]));
    let immediate=null;
    if(plan&&plan.immediate!==null&&plan.immediate!==undefined){
      immediate=bySequence.get(Number(plan.immediate))||null;
    }else if(!plan){
      const first=batches[0];
      if(first&&(first.actionableNow||Number(first.fundedQty??first.executableQty)>0))immediate=bySequence.get(Number(first.sequence))||null;
    }
    if(immediate&&!immediate.actionableNow)immediate={...immediate,phase:'immediate',actionableNow:true};
    let planned=[];
    if(plan&&Array.isArray(plan.planned)){
      planned=plan.planned.map(sequence=>bySequence.get(Number(sequence))).filter(Boolean);
    }else{
      planned=batches
        .filter(batch=>!immediate||Number(batch.sequence)!==Number(immediate.sequence))
        .filter(batch=>batch.phase==='planned'||Number(batch.executableQty)>0)
        .map(annotate);
    }
    planned=planned.filter(batch=>Number(batch.shipNowQty)>0);
    return {immediate,planned,next:immediate||planned[0]||null,batches:batches.map(annotate)};
  }
  function pmcFunded(batch){ return Number(batch?.fundedQty??batch?.shipNowQty??batch?.executableQty??0); }
  function pmcFundedShipments(pmc) { return pmcShipmentView(pmc).batches.filter(batch=>pmcFunded(batch)>0); }
  function pmcPlannedShipments(pmc) { return pmcShipmentView(pmc).planned; }
  function pmcFirstShip(pmc) { return pmcShipmentView(pmc).immediate; }
  function pmcFirstBuy(pmc) { return (pmc.purchaseBatches||[]).find(row=>Number(row.suggestedQty)>0)||null; }
  function pmcUnshippableNeed(pmc) { return pmcShipmentView(pmc).batches.find(row=>Number(row.needQty)>0&&Number(row.shipNowQty)<=0)||null; }
  function pmcStockoutText(pmc) {
    const start=pmc.timeline?.stockoutDate;
    const days=Number(pmc.timeline?.stockoutDays)||0;
    return start?`${pmcDate(start)} 起${days?` · ${fmt(days)} 天`:''}`:'测算期内无';
  }
  function pmcLane(mode) {
    const cls=mode==='海运'?'sea':mode==='空运'?'air':'truck';
    return `<span class="pmc-lane ${cls}">${escapeHtml(mode||'待定')}</span>`;
  }
  function pmcLocalReference(pmc) {
    const parts=pmc.calc?.localParts||{};
    return Number(parts.local||0)+Number(parts.overseas||0)+Number(parts.procurementOpen||0);
  }
  function pmcQualityItems(items,single=false) {
    const eta=board.inventory_batch?.metadata?.etaFile||{};
    const confirmed=items.filter(p=>Number(p.inventory_pmc?.timeline?.confirmedQty)>0).length;
    const confirmedQty=items.reduce((sum,p)=>sum+Number(p.inventory_pmc?.timeline?.confirmedQty||0),0);
    const unknown=items.filter(p=>Number(p.inventory_pmc?.timeline?.unknownEtaQty)>0).length;
    const unknownQty=items.reduce((sum,p)=>sum+Number(p.inventory_pmc?.timeline?.unknownEtaQty||0),0);
    const defaultLead=items.filter(p=>(p.inventory_pmc?.dataGaps||[]).some(text=>String(text).includes('采购天数'))).length;
    return [
      {text:single?`确认 ETA ${fmt(confirmedQty)} 件`:`确认 ETA ${fmt(confirmed)} 个 ASIN`,tone:confirmed?'good':'danger',title:'只有带货件号且 ETA 在未来的在途才进入时间轴'},
      {text:single?`未知 ETA ${fmt(unknownQty)} 件`:`未知 ETA ${fmt(unknown)} 个`,tone:unknown?'warn':'good',title:'在途有数量但缺可靠 ETA，不用于推迟断货日'},
      {text:`采购默认 ${fmt(defaultLead)} 个`,tone:defaultLead?'warn':'good',title:'领星未维护采购天数，暂用 40 天默认值'},
      {text:eta.status==='loaded'?'ETA 台账已读取':'ETA 台账缺失',tone:eta.status==='loaded'?'good':'danger',title:eta.sourceName||'FBA货件.xlsx'}
    ];
  }
  function pmcQualityChips(items,single=false) {
    return pmcQualityItems(items,single).map(item=>`<span class="pmc-chip ${item.tone}" title="${escapeHtml(item.title)}">${escapeHtml(item.text)}</span>`).join('');
  }

  function pmcActiveProducts() {
    return products.filter(product=>product.inventory_pmc&&pmcIsActive(product)&&
      (state.shop==='all'||String(product.sid)===state.shop));
  }
  function pmcSearchProducts(items) {
    const query=state.pmcQuery.trim().toLowerCase();
    if(!query)return items;
    return items.filter(product=>{
      const pmc=product.inventory_pmc;
      const haystack=[product.name,product.asin,product.shop,pmc?.title,pmc?.basis?.sku,pmc?.basis?.msku,
        ...(pmc?.basis?.skus||[]),...(pmc?.basis?.mskus||[])].join(' ').toLowerCase();
      return haystack.includes(query);
    });
  }
  function pmcQueueCounts(items) {
    return {
      ship:items.filter(product=>Boolean(pmcFirstShip(product.inventory_pmc))).length,
      buy:items.filter(product=>Boolean(pmcFirstBuy(product.inventory_pmc))).length,
      risk:items.filter(product=>Boolean(product.inventory_pmc?.timeline?.stockoutDate)).length,
      aged:items.filter(product=>Number(product.inventory_pmc?.calc?.agedQty)>0).length
    };
  }
  function pmcQueueItems(items,tab) {
    const tier=state.pmcTier;
    const filtered=items.filter(product=>tier==='all'||pmcTier(product)===tier);
    const chosen=filtered.filter(product=>{
      const pmc=product.inventory_pmc;
      if(tab==='ship')return Boolean(pmcFirstShip(pmc));
      if(tab==='buy')return Boolean(pmcFirstBuy(pmc));
      if(tab==='risk')return Boolean(pmc?.timeline?.stockoutDate);
      if(tab==='aged')return Number(pmc?.calc?.agedQty)>0;
      return false;
    });
    const rank=product=>PMC_TIER_ORDER[pmcTier(product)]??2;
    return chosen.sort((a,b)=>{
      const tierDelta=rank(a)-rank(b);
      if(tierDelta)return tierDelta;
      if(tab==='aged')return Number(b.inventory_pmc?.calc?.agedValue||0)-Number(a.inventory_pmc?.calc?.agedValue||0);
      if(tab==='buy')return Number(pmcFirstBuy(b.inventory_pmc)?.suggestedQty||0)-Number(pmcFirstBuy(a.inventory_pmc)?.suggestedQty||0);
      const riskDelta=Number(b.inventory_pmc?.calc?.lossAmount||0)-Number(a.inventory_pmc?.calc?.lossAmount||0);
      if(riskDelta)return riskDelta;
      const dateA=String(a.inventory_pmc?.timeline?.stockoutDate||'9999-12-31');
      const dateB=String(b.inventory_pmc?.timeline?.stockoutDate||'9999-12-31');
      return dateA.localeCompare(dateB);
    });
  }
  function pmcSummary(items) {
    const stockouts=items.filter(product=>product.inventory_pmc?.timeline?.stockoutDate).length;
    const ships=items.filter(product=>Boolean(pmcFirstShip(product.inventory_pmc)));
    const buys=items.filter(product=>Boolean(pmcFirstBuy(product.inventory_pmc)));
    const shipExecutable=ships.reduce((sum,product)=>sum+pmcFunded(pmcFirstShip(product.inventory_pmc)),0);
    const buyQty=buys.reduce((sum,product)=>sum+Number(pmcFirstBuy(product.inventory_pmc)?.suggestedQty||0),0);
    const buyValue=buys.reduce((sum,product)=>sum+Number(pmcFirstBuy(product.inventory_pmc)?.suggestedQty||0)*Number(product.inventory_pmc?.basis?.price||0),0);
    const riskValue=items.reduce((sum,product)=>sum+Number(product.inventory_pmc?.calc?.lossAmount||0),0);
    const agedValue=items.reduce((sum,product)=>sum+Number(product.inventory_pmc?.calc?.agedValue||0),0);
    return `<div class="pmc-summary-line"><span><b>${fmt(items.length)}</b> 在售</span><span><b class="pmc-danger">${fmt(stockouts)}</b> 会断</span><span>本周发 <b>${fmt(ships.length)}</b> 个 / <b>${fmt(shipExecutable)}</b> 件可执行</span><span>本周采 <b>${fmt(buys.length)}</b> 个 / <b>${fmt(buyQty)}</b> 件<small>${pmcMoney(buyValue)}</small></span><span>断货风险 <b class="pmc-danger">${pmcMoney(riskValue)}</b></span><span>超龄占用 <b class="pmc-warn">${pmcMoney(agedValue)}</b></span></div>`;
  }

  function pmcQueueRow(product,tab,totalAgedValue) {
    const pmc=product.inventory_pmc;
    const firstShip=pmcFirstShip(pmc);
    const firstBuy=pmcFirstBuy(pmc);
    const tier=pmcTier(product);
    const choice=state.pmcChoice[product.key];
    const scenario=choice&&choice!=='base'?`<span class="pmc-chip warn">${escapeHtml(PMC_PRESET_LABELS[choice]||'情景')}</span>`:'';
    const mark=escapeHtml(pmc?.basis?.imageMark||'A');
    const name=escapeHtml(shortName(product.name||pmc?.title||product.asin,26));
    const productCell=`<div class="pmc-product"><span class="pmc-mark">${mark}</span><span class="pmc-product-text"><strong>${name}</strong><small>${escapeHtml(product.asin)} · ${escapeHtml(product.shop)}</small></span><span class="pmc-tier ${tier.toLowerCase()}">${tier}</span>${scenario}</div>`;
    if(tab==='ship'){
      const gap=pmc?.timeline?.stockoutDate;
      const urgent=gap?((pmcDaysBetween(board.inventory_batch?.as_of,gap)??999)<=7):false;
      return `<tr data-pmc-open="${escapeHtml(product.key)}" tabindex="0"><td>${productCell}</td><td class="${urgent?'pmc-urgent':''}">${escapeHtml(pmcStockoutText(pmc))}${urgent?' · 急':''}</td><td class="pmc-money">${pmcMoney(pmc?.calc?.lossAmount)}</td><td class="pmc-number"><strong>${fmt(pmcFunded(firstShip))}</strong><small>可执行</small></td><td>${pmcLane(firstShip?.mode)}</td><td>${escapeHtml(pmcFullDate(firstShip?.arrivalDate))}<small>${Number(firstShip?.projectedAfterArrival)<0?`仍缺 ${fmt(-Number(firstShip?.projectedAfterArrival))}`:`剩余 ${fmt(firstShip?.projectedAfterArrival)}`}</small></td></tr>`;
    }
    if(tab==='buy'){
      const amount=Number(firstBuy?.suggestedQty||0)*Number(pmc?.basis?.price||0);
      const reference=pmcLocalReference(pmc);
      return `<tr data-pmc-open="${escapeHtml(product.key)}" tabindex="0"><td>${productCell}</td><td class="pmc-number"><strong>${fmt(firstBuy?.suggestedQty)}</strong></td><td class="pmc-money">${pmcMoney(amount)}</td><td>${escapeHtml(pmcFullDate(firstBuy?.orderDate))}${firstBuy?.late?' <span class="pmc-danger">已晚</span>':''}</td><td>${escapeHtml(pmcFullDate(firstBuy?.expectedReadyDate))}</td><td class="pmc-number">${fmt(reference)}</td><td><span class="pmc-chip">保守</span></td></tr>`;
    }
    if(tab==='risk'){
      const days=Number(pmc?.timeline?.stockoutDays)||0;
      const next=pmcFirstShip(pmc)||pmcPlannedShipments(pmc)[0];
      return `<tr data-pmc-open="${escapeHtml(product.key)}" tabindex="0"><td>${productCell}</td><td>${escapeHtml(pmcStockoutText(pmc))}</td><td class="pmc-number">${fmt(days)}</td><td class="pmc-money">${pmcMoney(pmc?.calc?.lossAmount)}</td><td>${next?`${escapeHtml(pmcFullDate(next.arrivalDate))} · ${fmt(pmcFunded(next))} 件`:(pmc?.timeline?.nextEta?`ETA ${escapeHtml(pmcFullDate(pmc.timeline.nextEta))}`:'未确认')}</td></tr>`;
    }
    const agedQty=Number(pmc?.calc?.agedQty||0);
    const agedValue=Number(pmc?.calc?.agedValue||0);
    const share=totalAgedValue>0?agedValue/totalAgedValue:0;
    return `<tr data-pmc-open="${escapeHtml(product.key)}" tabindex="0"><td>${productCell}</td><td class="pmc-number">${fmt(agedQty)}</td><td class="pmc-money">${pmcMoney(agedValue)}</td><td class="pmc-number">${pct(share)}</td><td>停止补货，降价清理或移除</td></tr>`;
  }

  function inventoryQueueContent() {
    const all=pmcSearchProducts(pmcActiveProducts());
    const counts=pmcQueueCounts(all);
    const tab=PMC_TABS[state.pmcTab]?state.pmcTab:'ship';
    const items=pmcQueueItems(all,tab);
    const totalAgedValue=all.reduce((sum,product)=>sum+Number(product.inventory_pmc?.calc?.agedValue||0),0);
    const meta=PMC_TABS[tab];
    return `<section class="pmc-queue-head">
      <div class="pmc-queue-title"><div><span class="eyebrow">库存 · ${escapeHtml(board.inventory_batch?.as_of||'')}</span><h2>库存待办</h2><p>先处理会断的、要发的、要采的；每条进入单品库存，看需求、时间轴和情景对比。当前只形成方案，不自动建货件或采购单。发货只列本地可执行量；“本周发货/采购”按每个 ASIN 的首批动作排序，不等于都在这 7 天发出。</p></div><div class="pmc-queue-actions"><button type="button" class="pmc-quiet-button" data-pmc-export-csv>导出当前列表</button></div></div>
      ${pmcSummary(all)}
      <div class="pmc-quality-line"><span class="pmc-quality-label">数据质量</span>${pmcQualityChips(all)}</div>
      <div class="pmc-action-tabs">${Object.entries(PMC_TABS).map(([key,entry])=>`<button type="button" data-pmc-tab="${key}" class="${tab===key?'active':''}" aria-pressed="${tab===key}">${entry.title}<b>${fmt(counts[key])}</b></button>`).join('')}</div>
      <div class="pmc-queue-filters"><label class="pmc-search"><span>⌕</span><input data-pmc-search type="search" placeholder="搜索 ASIN / SKU / 产品名" value="${escapeHtml(state.pmcQuery)}"></label><div class="pmc-tier-filter">${[['all','全部'],['P0','P0'],['P1','P1'],['P2','P2']].map(([key,label])=>`<button type="button" data-pmc-tier="${key}" class="${state.pmcTier===key?'active':''}">${label}</button>`).join('')}</div><span class="pmc-filter-note">按 P0 → P1 → P2，再按风险金额排序</span></div>
    </section>
    <section class="panel pmc-queue-panel"><div class="pmc-panel-head"><div><span class="eyebrow">${meta.eyebrow}</span><h3>${meta.title}</h3></div><span class="pmc-count">${fmt(items.length)} 个 ASIN</span></div><div class="table-wrap"><table class="pmc-queue-table"><thead><tr>${meta.head.map(head=>`<th>${head}</th>`).join('')}</tr></thead><tbody>${items.length?items.map(product=>pmcQueueRow(product,tab,totalAgedValue)).join(''):`<tr><td colspan="${meta.head.length}"><div class="pmc-empty"><strong>当前筛选下没有需要处理的 ASIN</strong><span>${all.length?'可以切换 Tab 或放宽 P0/P1/P2；也可以搜索其他 ASIN。':'当前店铺或搜索条件没有匹配；回到商品目录或清除搜索。'}</span><div class="pmc-empty-links">${Object.entries(PMC_TABS).filter(([key])=>key!==tab&&counts[key]).map(([key,entry])=>`<button type="button" data-pmc-tab="${key}">${entry.title} · ${fmt(counts[key])}</button>`).join('')}</div></div></td></tr>`}</tbody></table></div></section>`;
  }

  // ---------- single-ASIN PMC cockpit ----------
  function pmcDefaultScenario(pmc) {
    const list=pmc?.basis?.scenarios||[];
    return list.find(item=>item.id===pmc.activeScenarioId)||list.find(item=>item.isDefault)||null;
  }
  function pmcNormalizeParams(params) {
    const out={...(params||{})};
    if(out.scenarioMultiplier!==undefined&&out.demandMultiplier===undefined)out.demandMultiplier=out.scenarioMultiplier;
    if(out.expressTransitDays!==undefined&&out.expressDays===undefined)out.expressDays=out.expressTransitDays;
    delete out.scenarioMultiplier;delete out.expressTransitDays;delete out.cadenceDays;
    return out;
  }
  function pmcScenarioParams(product,pmc,choice) {
    if(String(choice||'').startsWith('lib:')){
      const scenario=pmcLibraryScenario(String(choice).slice(4));
      return scenario&&pmcScenarioAllowed(scenario,product)?pmcNormalizeParams(scenario.params||{}):{};
    }
    if(choice==='default'){
      const scenario=pmcDefaultScenario(pmc);
      return pmcNormalizeParams(scenario?.params||{});
    }
    if(choice==='peak')return {demandMultiplier:1.3};
    if(choice==='conservative')return {demandMultiplier:0.85};
    if(choice==='delay')return {transitDays:Number(pmc.policy?.transitDays||60)+14,expressDays:Number(pmc.policy?.expressTransitDays||30)+14};
    if(choice==='custom')return {...(state.pmcCustom[product.key]||{})};
    return {};
  }
  function pmcEngineParams(params) {
    const out={...(params||{})};
    if(out.demandMultiplier!==undefined){out.scenarioMultiplier=out.demandMultiplier;delete out.demandMultiplier;}
    if(out.expressDays!==undefined){out.expressTransitDays=out.expressDays;delete out.expressDays;}
    delete out.cadenceDays;
    if(Array.isArray(out.seasonal)&&out.seasonal.length)delete out.scenarioMultiplier;
    return out;
  }
  function pmcAnalyze(product,params) {
    const source=product.inventory_pmc?.basis;
    if(!source||!window.PmcEngine?.analyzeInventoryRecord)return null;
    try{
      return window.PmcEngine.analyzeInventoryRecord(source,{asOf:product.inventory_pmc.asOf,...pmcEngineParams(params)});
    }catch{return null}
  }
  function pmcScenarioMeta(params) {
    const bits=[];
    if(Array.isArray(params.seasonal)&&params.seasonal.length){
      bits.push(params.seasonal.map(row=>`${String(row.from).slice(5)}~${String(row.to).slice(5)} ×${fmt(row.multiplier,2)}`).join('、'));
    }else if(params.demandMultiplier!==undefined&&Number(params.demandMultiplier)!==1){
      bits.push(`日均 ×${fmt(params.demandMultiplier,2)}`);
    }
    if(params.transitDays)bits.push(`海运 ${fmt(params.transitDays)} 天`);
    if(params.expressDays)bits.push(`卡航 ${fmt(params.expressDays)} 天`);
    if(params.airTransitDays)bits.push(`空运 ${fmt(params.airTransitDays)} 天`);
    if(params.purchaseLeadDays!==undefined)bits.push(`采购 ${fmt(params.purchaseLeadDays)} 天`);
    if(params.safetyDays!==undefined)bits.push(`安全 ${fmt(params.safetyDays)} 天`);
    if(Number(params.minShipQty)>0)bits.push(`最低起运 ${fmt(params.minShipQty)} 件`);
    if(params.cartonQty)bits.push(`${fmt(params.cartonQty)} 件/箱`);
    if(params.moq)bits.push(`起订 ${fmt(params.moq)} 件`);
    if(params.minShipQty)bits.push(`最低起运 ${fmt(params.minShipQty)} 件`);
    if(params.localAvailable!==undefined&&params.localAvailable!==null)bits.push(`本地可用 ${fmt(params.localAvailable)} 件`);
    return bits.join(' · ')||'按当前算法自动计算';
  }
  const PMC_LIBRARY_KEY='amazon-ops-b-pmc-library-v1';
  function pmcLibraryData() {
    if(state.pmcLibrary&&Array.isArray(state.pmcLibrary.scenarios))return state.pmcLibrary;
    let stored=null;
    try{stored=typeof localStorage==='undefined'?null:JSON.parse(localStorage.getItem(PMC_LIBRARY_KEY)||'null')}catch{stored=null}
    state.pmcLibrary=stored&&Array.isArray(stored.scenarios)?stored:{version:1,scenarios:[]};
    return state.pmcLibrary;
  }
  function pmcLibrarySave() {
    try{if(typeof localStorage!=='undefined')localStorage.setItem(PMC_LIBRARY_KEY,JSON.stringify(pmcLibraryData()))}catch{/* file:// may block storage */}
  }
  function pmcScenarioAllowed(scenario,product) {
    return (scenario.allowed||[]).some(item=>String(item.sid||item.storeId||item.store)===String(product.sid)&&String(item.asin).toUpperCase()===String(product.asin).toUpperCase());
  }
  function pmcLibraryScenario(id) {
    return pmcLibraryData().scenarios.find(scenario=>String(scenario.id)===String(id))||null;
  }
  function pmcScenarioOptions(product,pmc) {
    const options=[['base','基准（自动）']];
    for(const scenario of pmcLibraryData().scenarios){
      if(pmcScenarioAllowed(scenario,product))options.push([`lib:${scenario.id}`,`自定义 · ${scenario.name}`]);
    }
    if(state.pmcCustom[product.key])options.push(['custom','自定义试算（未保存）']);
    return options;
  }

  function pmcTargetAt(item,dateText) {
    // Mirror the engine: safety-stock demand + one batch (max(minShip, 7 days)).
    const safety=Number(item.policy?.safetyDays??item.calc?.safetyDays??15);
    const minShip=Number(item.calc?.minShipQty||0);
    const demandAt=item.forecast?.demandAt;
    const dailyAt=date=>demandAt?Number(demandAt(date)||0):Number(item.forecast?.daily||0);
    let safetyDemand=0;
    for(let offset=1;offset<=safety;offset+=1){
      const date=new Date(`${String(dateText).slice(0,10)}T00:00:00Z`);
      date.setUTCDate(date.getUTCDate()+offset);
      safetyDemand+=dailyAt(date.toISOString().slice(0,10));
    }
    const batch=Math.max(minShip,7*dailyAt(String(dateText).slice(0,10)));
    return Math.ceil(safetyDemand+batch);
  }
  function pmcChartColors() {
    if(state.theme==='light')return {
      segFar:'#e7efe9',segMid:'#e1ebf1',segRecent:'#f4e5d2',segStroke:'#c6d8cf',segStroke2:'#c2d6df',segStroke3:'#dfc6a4',
      muted:'#7b8a86',axis:'#7b8a86',tick2:'#a6b0ad',
      avg:'#8fa39c',recent:'#d08a5a',bar:'#0f7469',constrained:'#e8b4a8',
      mean:'#da5c43',teal:'#0f7469',blue:'#466b83',amber:'#b67824',coral:'#c0503f',
      base:'#9aa8a3',gap:'#fbe6df',planGap:'#f2b8ad',hatch:'#c4776b',gapText:'#8b3a2f',targetText:'#8d641f',grid:'#e3e9e4',
      text:'#33564e',cursor:'#173d38',zero:'#da5c43',planArea:'#e4edf3',stockArea:'#dff2ed',halo:'#fffefa'
    };
    return {
      segFar:'#153a45',segMid:'#1a4650',segRecent:'#2d443b',segStroke:'#2d5b65',segStroke2:'#326470',segStroke3:'#4b6352',
      muted:'#86a8ab',axis:'#86a8ab',tick2:'#5f858b',
      avg:'#64868b',recent:'#e5b66b',bar:'#42c7b1',constrained:'#e5b66b',
      mean:'#e5b66b',teal:'#42c7b1',blue:'#78aade',amber:'#e5b66b',coral:'#f17673',
      base:'#8aa7ac',gap:'#3b2529',planGap:'#4a2b2e',hatch:'#8e4f4c',gapText:'#f3d6d1',targetText:'#f0d7a0',grid:'#2b4d57',
      text:'#86a8ab',cursor:'#42c7b1',zero:'#f17673',planArea:'#78aade',stockArea:'#42c7b1',halo:'#0b222d'
    };
  }
  function pmcDemandSvg(item) {
    const c=pmcChartColors();
    const days=(item.forecast?.dailySeries||[]).slice(-60);
    if(!days.length)return '<div class="pmc-empty">没有逐日需求样本。</div>';
    const values=days.map(day=>Math.max(0,Number(day.sales)||0));
    const width=920,height=176,left=44,right=902,top=24,bottom=138;
    const max=Math.max(1,Number(item.forecast?.daily||0),...values);
    const slot=(right-left)/Math.max(1,values.length);
    const yOf=value=>bottom-value/max*(bottom-top);
    const segments=[
      {key:'far',from:0,to:Math.max(0,values.length-30),label:'60 天均值',color:c.segFar,stroke:c.segStroke},
      {key:'middle',from:Math.max(0,values.length-30),to:Math.max(0,values.length-7),label:'30 天均值',color:c.segMid,stroke:c.segStroke2},
      {key:'recent',from:Math.max(0,values.length-7),to:values.length,label:'近 7 天',color:c.segRecent,stroke:c.segStroke3}
    ];
    const background=segments.map(segment=>{
      const x1=left+segment.from*slot;
      const x2=left+Math.min(segment.to,values.length)*slot;
      const average=item.forecast?.segments?.[segment.key]??0;
      return `<rect x="${x1.toFixed(1)}" y="${top}" width="${Math.max(0,x2-x1).toFixed(1)}" height="${bottom-top}" fill="${segment.color}" stroke="${segment.stroke}" stroke-width="1"/><text x="${(x1+5).toFixed(1)}" y="${top-8}" font-size="9" fill="${c.muted}">${segment.label} ${fmt(average)}</text>`;
    }).join('');
    const averages=[['far',0],['middle',Math.max(0,values.length-30)],['recent',Math.max(0,values.length-7)]].map(([key,from])=>{
      const average=item.forecast?.segments?.[key]??0;
      return `<line x1="${(left+from*slot).toFixed(1)}" y1="${yOf(average).toFixed(1)}" x2="${right}" y2="${yOf(average).toFixed(1)}" stroke="${key==='recent'?c.recent:c.avg}" stroke-dasharray="4 4" opacity=".9"/>`;
    }).join('');
    const bars=values.map((value,index)=>{
      const day=days[index]||{};
      const barHeight=Math.max(0,bottom-yOf(value));
      const label=`${day.date||''} · 销量 ${fmt(value)} · FBA 可售 ${fmt(day.fbaSellable)} · 收货中 ${fmt(day.inboundReceiving)}${day.constrained?' · 库存约束日':''}`;
      return `<rect class="pmc-bar ${day.constrained?'constrained':''}" x="${(left+index*slot+1).toFixed(1)}" y="${(bottom-barHeight).toFixed(1)}" width="${Math.max(1,slot-2).toFixed(1)}" height="${barHeight.toFixed(1)}" rx="2" fill="${day.constrained?c.constrained:c.bar}" opacity="${day.constrained?.45:.86}"/><rect class="pmc-day-hit" data-pmc-day="${index}" data-pmc-source="demand" x="${(left+index*slot).toFixed(1)}" y="${top}" width="${Math.max(1,slot).toFixed(1)}" height="${bottom-top}" fill="transparent" data-pmc-x="${(left+index*slot+slot/2).toFixed(1)}" aria-label="${escapeHtml(label)}"></rect>`;
    }).join('');
    return `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="近 60 天销量与 7/30/60 天均值"><defs><linearGradient id="pmcDaily" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${c.mean}" stop-opacity=".95"/><stop offset="1" stop-color="${c.mean}" stop-opacity=".15"/></linearGradient></defs>${background}${averages}${bars}<line x1="${left}" y1="${yOf(item.forecast.daily).toFixed(1)}" x2="${right}" y2="${yOf(item.forecast.daily).toFixed(1)}" stroke="url(#pmcDaily)" stroke-width="1.5" stroke-dasharray="5 4"/><text x="${right}" y="${(yOf(item.forecast.daily)-5).toFixed(1)}" text-anchor="end" font-size="9" fill="${c.mean}">日均 ${fmt(item.forecast.daily)}</text><text x="${left}" y="${height-8}" font-size="9" fill="${c.axis}">${escapeHtml(days[0]?.date||'')}</text><text x="${right}" y="${height-8}" text-anchor="end" font-size="9" fill="${c.axis}">${escapeHtml(days[days.length-1]?.date||'')}</text><line class="pmc-cursor demand-cursor" x1="${left}" y1="${top}" x2="${left}" y2="${bottom}" stroke="${c.cursor}" stroke-width="1.2" opacity="0"/></svg>`;
  }
  function pmcWeightsHtml(item) {
    const f=item.forecast||{};
    const labels={recent:'近 7 天',middle:'30 天',far:'60 天'};
    return `<div class="pmc-weights">${['recent','middle','far'].map(key=>{
      const weight=Math.round(Number(f.weights?.[key]||0)*100);
      return `<span class="pmc-weight ${key}" style="flex:${Math.max(1,weight)}"><b>${labels[key]} ${weight}%</b><small>${fmt(f.segments?.[key])}/天</small></span>`;
    }).join('')}</div>`;
  }
  function pmcTimelineSvg(base,current,limit=180) {
    const c=pmcChartColors();
    const span=Math.max(60,Math.min(241,Number(limit)||90));
    const points=(current.timeline?.points||[]).slice(0,span);
    const planPoints=(current.plannedTimeline?.points||[]).slice(0,span);
    if(points.length<2)return '<div class="pmc-empty">库存时间轴没有足够观测点。</div>';
    const confirmedEvents=(current.timeline?.events||[]).slice(0,8);
    const visibleEnd=String(points[points.length-1]?.date||'').slice(0,10);
    const plannedEvents=pmcFundedShipments(current).filter(event=>String(event.dispatchDate||'').slice(0,10)<=visibleEnd).slice(0,8);
    const bandTop=8, confirmedStep=11, plannedStep=10;
    const planBase=bandTop+Math.max(1,confirmedEvents.length)*confirmedStep+6;
    const top=planBase+Math.max(0,plannedEvents.length)*plannedStep+8;
    const bottom=Math.max(top+230,306);
    const height=bottom+64;
    const width=920,left=50,right=902;
    const targetCurve=points.map(point=>pmcTargetAt(current,point.date));
    const observedMax=Math.max(1,Number(current.calc?.targetFba||0),Number(current.calc?.targetPeak||0),...points.map(point=>Number(point.stock)||0),...planPoints.map(point=>Number(point.stock)||0),...targetCurve);
    const max=observedMax*1.08;
    const x=index=>left+index*(right-left)/Math.max(1,points.length-1);
    const y=value=>bottom-Math.max(0,Number(value)||0)/max*(bottom-top);
    const poly=rows=>rows.map((point,index)=>`${x(index).toFixed(1)},${y(point.stock).toFixed(1)}`).join(' ');
    const indexForDate=date=>{
      const found=points.findIndex(point=>String(point.date).slice(0,10)>=String(date).slice(0,10));
      return found<0?points.length-1:found;
    };
    const gapLabel=(text,startX,endX,labelY,fill)=>{
      const width=Math.max(78,String(text).length*10.5+14);
      const cx=(startX+endX)/2;
      return `<g><rect x="${(cx-width/2).toFixed(1)}" y="${(labelY-12).toFixed(1)}" width="${width.toFixed(1)}" height="16" rx="4" fill="${c.halo}" opacity=".88"/><text x="${cx.toFixed(1)}" y="${labelY.toFixed(1)}" text-anchor="middle" font-size="9" fill="${fill}">${text}</text></g>`;
    };
    const gapRects=(gaps,kind)=>{
      return (gaps||[]).slice(0,4).map(gap=>{
        const start=indexForDate(gap.start);
        const end=gap.end?indexForDate(gap.end):points.length-1;
        const x1=x(start),x2=x(end),width=Math.max(2,x2-x1);
        if(kind==='base'){
          return `<rect class="pmc-gap-base" x="${x1.toFixed(1)}" y="${top}" width="${width.toFixed(1)}" height="${bottom-top}" fill="${c.gap}" opacity=".9"/>${width>110?gapLabel(`不补货断 ${fmt(gap.days)} 天`,x1,x2,bottom-12,c.gapText):''}`;
        }
        return `<rect class="pmc-gap-plan" x="${x1.toFixed(1)}" y="${top}" width="${width.toFixed(1)}" height="${bottom-top}" fill="${c.planGap}" opacity=".2"/><rect x="${x1.toFixed(1)}" y="${top}" width="${width.toFixed(1)}" height="${bottom-top}" fill="url(#pmcPlanHatch)" opacity=".85"/>${width>110?gapLabel(`计划后仍断 ${fmt(gap.days)} 天`,x1,x2,bottom-32,c.gapText):''}`;
      }).join('');
    };
    const gaps=gapRects(base.timeline?.stockoutIntervals,'base');
    const planGaps=gapRects(current.plannedTimeline?.stockoutIntervals,'plan');
    const tickStep=span<=90?7:span<=180?14:21;
    const tickIndexes=[];
    for(let index=0;index<points.length;index+=tickStep)tickIndexes.push(index);
    if(tickIndexes[tickIndexes.length-1]!==points.length-1)tickIndexes.push(points.length-1);
    const tickLines=tickIndexes.map(index=>`<line x1="${x(index).toFixed(1)}" y1="${top}" x2="${x(index).toFixed(1)}" y2="${bottom}" stroke="${c.grid}" stroke-dasharray="2 6" opacity=".42"/>`).join('');
    const ticks=tickIndexes.map(index=>`<text x="${x(index).toFixed(1)}" y="${bottom+16}" text-anchor="middle" font-size="9" fill="${c.axis}">${pmcIsoWeek(points[index].date)}</text><text x="${x(index).toFixed(1)}" y="${bottom+27}" text-anchor="middle" font-size="8" fill="${c.tick2}">${escapeHtml(String(points[index].date).slice(5))}</text>`).join('');
    const grid=[0,.5,1].map(fraction=>`<line x1="${left}" y1="${y(max*fraction).toFixed(1)}" x2="${right}" y2="${y(max*fraction).toFixed(1)}" stroke="${c.grid}" stroke-dasharray="3 5"/><text x="${left-7}" y="${(y(max*fraction)+3).toFixed(1)}" text-anchor="end" font-size="8" fill="${c.axis}">${fmt(Math.round(max*fraction))}</text>`).join('');
    const confirmedBands=confirmedEvents.map((event,index)=>{
      const start=indexForDate(event.etaStart||event.etaEnd||event.date);
      const end=indexForDate(event.etaEnd||event.date);
      const yBand=bandTop+index*confirmedStep;
      const cx=x(end),cy=yBand+4;
      return `<rect class="pmc-eta-band" data-pmc-ship="${escapeHtml(event.shipment||event.id||`ETA-${index+1}`)}" data-pmc-x="${((x(start)+x(end))/2).toFixed(1)}" data-pmc-start="${x(start).toFixed(1)}" data-pmc-end="${x(end).toFixed(1)}" x="${x(start).toFixed(1)}" y="${yBand.toFixed(1)}" width="${Math.max(4,x(end)-x(start)).toFixed(1)}" height="8" rx="4" fill="${c.teal}" opacity=".82"/><circle cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="3.5" fill="${c.teal}"/><line x1="${cx.toFixed(1)}" y1="${(cy+4).toFixed(1)}" x2="${cx.toFixed(1)}" y2="${bottom}" stroke="${c.grid}" stroke-dasharray="2 5" opacity=".55"/><text x="${cx.toFixed(1)}" y="${(yBand-3).toFixed(1)}" text-anchor="middle" font-size="8" fill="${c.teal}">${fmt(event.qty)}</text>`;
    }).join('');
    const plannedBands=plannedEvents.map((event,index)=>{
      const start=indexForDate(event.dispatchDate);
      const end=indexForDate(event.arrivalDate);
      const yBand=planBase+index*plannedStep;
      const laneColor=event.mode==='海运'?c.teal:event.mode==='空运'?c.coral:c.amber;
      const cx=x(end),cy=yBand+4;
      const future=event.phase==='planned';
      const label=event.phase==='immediate'?'今日发':future?(event.funding==='purchase'?'采购齐套后':'后续批次'):'计划';
      return `<rect class="pmc-eta-band planned${future?' future':''}" data-pmc-ship="PLAN-${event.sequence}" data-pmc-x="${((x(start)+x(end))/2).toFixed(1)}" data-pmc-start="${x(start).toFixed(1)}" data-pmc-end="${x(end).toFixed(1)}" x="${x(start).toFixed(1)}" y="${yBand.toFixed(1)}" width="${Math.max(4,x(end)-x(start)).toFixed(1)}" height="7" rx="3.5" fill="${laneColor}" opacity="${future?.62:.72}" stroke="${laneColor}" stroke-width="1.2" stroke-dasharray="4 3"/><circle cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="3.5" fill="${laneColor}"/><line x1="${cx.toFixed(1)}" y1="${(cy+4).toFixed(1)}" x2="${cx.toFixed(1)}" y2="${bottom}" stroke="${c.grid}" stroke-dasharray="2 5" opacity=".55"/><text x="${(x(start)>(right-40)?(right-2):x(start)).toFixed(1)}" y="${(yBand-3).toFixed(1)}" text-anchor="${x(start)>(right-40)?'end':'start'}" font-size="8" fill="${laneColor}">${pmcIsoWeek(event.dispatchDate)}</text><text x="${(x(end)>(right-28)?(right-2):x(end)).toFixed(1)}" y="${(yBand-3).toFixed(1)}" text-anchor="end" font-size="8" fill="${laneColor}">${fmt(event.shipNowQty??event.fundedQty??0)}</text>`;
    }).join('');
    const bands=confirmedBands+plannedBands;
    const targetPeakValue=Math.max(...targetCurve);
    const targetPeakIndex=targetCurve.indexOf(targetPeakValue);
    const targetText=(xPos,yPos,text,anchor='end')=>`<text x="${xPos.toFixed(1)}" y="${yPos.toFixed(1)}" text-anchor="${anchor}" font-size="9" fill="${c.targetText}" stroke="${c.halo}" stroke-width="3" paint-order="stroke">${text}</text>`;
    const targetLabel=targetText(right,y(current.calc?.targetFba||0)-5,`目标 ${fmt(current.calc?.targetFba)}`)+ (Math.abs(targetPeakValue-Number(current.calc?.targetFba||0))>1?targetText(Math.min(right-4,Math.max(left+4,x(targetPeakIndex))),y(targetPeakValue)-5,`峰值目标 ${fmt(Math.ceil(targetPeakValue))}`,'middle'):'');
    const hits=points.map((point,index)=>{
      const label=`${point.date} · 不补货 ${fmt(point.stock)} 件 · 按方案 ${fmt(planPoints[index]?.stock)} 件 · 目标 ${fmt(Math.round(targetCurve[index]))}${point.arrivalQty?` · 到货 ${fmt(point.arrivalQty)} 件`:''}`;
      return `<rect class="pmc-day-hit" data-pmc-day="${index}" data-pmc-source="timeline" x="${Math.max(left,x(index)-((right-left)/Math.max(1,points.length-1))/2).toFixed(1)}" y="${top}" width="${((right-left)/Math.max(1,points.length-1)+1).toFixed(1)}" height="${bottom-top}" fill="transparent" data-pmc-x="${x(index).toFixed(1)}" aria-label="${escapeHtml(label)}"/>`;
    }).join('');
    return `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="库存投影、目标与 ETA 时间轴"><defs><pattern id="pmcPlanHatch" width="9" height="9" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="9" stroke="${c.hatch}" stroke-width="2.2" opacity=".8"/></pattern></defs>${gaps}${planGaps}${tickLines}${bands}${grid}<polyline points="${points.map((point,index)=>`${x(index).toFixed(1)},${y(targetCurve[index]).toFixed(1)}`).join(' ')}" fill="none" stroke="${c.halo}" stroke-width="4.2" stroke-dasharray="5 4"/><polyline class="pmc-target" points="${points.map((point,index)=>`${x(index).toFixed(1)},${y(targetCurve[index]).toFixed(1)}`).join(' ')}" fill="none" stroke="${c.targetText}" stroke-width="1.6" stroke-dasharray="5 4"/><polyline points="${poly(planPoints)}" fill="none" stroke="${c.halo}" stroke-width="5" stroke-dasharray="6 4"/><polyline class="pmc-line-plan" points="${poly(planPoints)}" fill="none" stroke="${c.blue}" stroke-width="2.3" stroke-dasharray="6 4"/><polyline points="${poly(points)}" fill="none" stroke="${c.halo}" stroke-width="6"/><polyline class="pmc-line-current" points="${poly(points)}" fill="none" stroke="${c.teal}" stroke-width="3.1"/><line x1="${left}" y1="${y(0)}" x2="${right}" y2="${y(0)}" stroke="${c.zero}" stroke-dasharray="4 5" opacity=".55"/>${targetLabel}${ticks}${hits}<line class="pmc-cursor chart-cursor" x1="${left}" y1="${top}" x2="${left}" y2="${bottom}" stroke="${c.cursor}" stroke-width="1.2" opacity="0"/></svg>`;
  }
  function pmcTipRow(label,value) {
    return `<div><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`;
  }
  function pmcDemandTip(current,index) {
    const day=(current.forecast?.dailySeries||[]).slice(-60)[index];
    if(!day)return '';
    const segment=index<30?'60 天基线':index<53?'30 天窗口':'近 7 天';
    return `<b>${escapeHtml(day.date||'')}</b>${pmcTipRow('当日销量',fmt(day.sales))}${pmcTipRow('FBA 可售',fmt(day.fbaSellable))}${pmcTipRow('收货中',fmt(day.inboundReceiving))}${pmcTipRow('所属区间',segment)}${day.constrained?'<div class="tip-warn">库存约束日，已从均值中剔除</div>':''}`;
  }
  function pmcTimelineShips(current,date) {
    const confirmed=(current.timeline?.events||[]).filter(event=>String(event.etaEnd||'').slice(0,10)===String(date).slice(0,10)).map(event=>({id:event.shipment||event.id,line:`ETA ${pmcFullDate(event.etaStart)} ~ ${pmcFullDate(event.etaEnd)}`,qty:event.qty}));
    const planned=pmcFundedShipments(current).filter(batch=>String(batch.arrivalDate||'').slice(0,10)===String(date).slice(0,10)).map(batch=>({id:`建议第 ${batch.sequence} 批`,line:`${batch.phase==='planned'?(batch.funding==='purchase'?'采购齐套后':'后续批次'):'计划'} · ${pmcIsoWeek(batch.dispatchDate)} 发 → ${pmcIsoWeek(batch.arrivalDate)} 到 · ${batch.mode||''} ${fmt(batch.transitDays)} 天`,qty:batch.shipNowQty}));
    return [...confirmed,...planned].slice(0,4);
  }
  function pmcTimelineTip(current,index) {
    const point=current.timeline?.points?.[index];
    const plan=current.plannedTimeline?.points?.[index];
    if(!point)return '';
    const target=Math.round(pmcTargetAt(current,point.date));
    const ships=pmcTimelineShips(current,point.date);
    const shipRows=ships.map(ship=>`<div class="tip-ship"><b>${escapeHtml(ship.id)}</b><span>${escapeHtml(ship.line)} · ${fmt(ship.qty)} 件</span></div>`).join('');
    return `<b>${pmcIsoWeek(point.date)} · ${escapeHtml(point.date||'')}</b>${pmcTipRow('日销',fmt(current.forecast?.demandAt?current.forecast.demandAt(point.date):current.forecast?.daily))}${pmcTipRow('期末库存',fmt(Math.max(0,Number(point.stock)||0)))}${pmcTipRow('确认到仓',point.arrivalQty?`+${fmt(point.arrivalQty)}`:'—')}${pmcTipRow('当日目标',fmt(target))}${pmcTipRow('距目标',fmt(Math.round((Number(point.stock)||0)-target)))}${pmcTipRow('建议发货后',fmt(Math.max(0,Number(plan?.stock)||0)))}${pmcTipRow('建议后距目标',fmt(Math.round(Math.max(0,Number(plan?.stock)||0)-target)))}${shipRows?`<div class="tip-ships">${shipRows}</div>`:''}`;
  }
  function pmcShipTip(current,id) {
    const event=(current.timeline?.events||[]).find(item=>String(item.shipment||item.id)===String(id));
    if(event){
      const point=(current.timeline?.points||[]).find(item=>String(item.date).slice(0,10)===String(event.etaEnd||'').slice(0,10));
      return `<b>${escapeHtml(event.shipment||event.id)}</b>${pmcTipRow('到仓日',pmcFullDate(event.etaEnd))}${pmcTipRow('ETA 窗口',`${pmcFullDate(event.etaStart)} ~ ${pmcFullDate(event.etaEnd)}`)}${pmcTipRow('数量',`${fmt(event.qty)} 件`)}${pmcTipRow('状态',event.status||'在途')}${point?pmcTipRow('当日期末',fmt(Math.max(0,Number(point.stock)||0))):''}`;
    }
    const batch=pmcFundedShipments(current).find(item=>`PLAN-${item.sequence}`===String(id));
    if(!batch)return '';
    const point=(current.timeline?.points||[]).find(item=>String(item.date).slice(0,10)===String(batch.arrivalDate||'').slice(0,10));
    const future=batch.phase==='planned';
    return `<b>建议第 ${batch.sequence} 批</b>${pmcTipRow('发出日',pmcFullDate(batch.dispatchDate))}${pmcTipRow('到仓日',pmcFullDate(batch.arrivalDate))}${pmcTipRow('时效',`${batch.mode||''} ${fmt(batch.transitDays)} 天`)}${pmcTipRow('发货量',`${fmt(batch.shipNowQty??batch.fundedQty??batch.executableQty)} 件`)}${pmcTipRow('状态',future?(batch.funding==='purchase'?'采购齐套后':'后续批次'):'计划在途')}${point?pmcTipRow('当日期末',fmt(Math.max(0,Number(point.stock)||0))):''}`;
  }
  function pmcHoverTip(html,key,event) {
    const current=state.pmcView?.current;
    const wrap=document.getElementById('pmc-timeline-chart');
    const tip=document.getElementById('pmc-timeline-tip');
    if(!current||!wrap||!tip||!html)return;
    if(state.pmcHoverKey===key&&!tip.hidden)return;
    tip.innerHTML=html;
    tip.hidden=false;
    pmcPlaceTip(wrap,tip,event);
    state.pmcHoverKey=key;
  }
  function pmcPointIndexAtEvent(current,event) {
    const wrap=document.getElementById('pmc-timeline-chart');
    const svg=wrap?.querySelector('svg');
    const rect=svg?.getBoundingClientRect();
    const points=(current.timeline?.points||[]).slice(0,Math.max(60,Math.min(241,Number(state.pmcRange)||90)+1));
    if(!rect||!event||points.length<2)return 0;
    let svgX=null;
    if(event.clientX>=rect.left&&event.clientX<=rect.right)svgX=(event.clientX-rect.left)/Math.max(1,rect.width)*920;
    if(svgX===null){const anchor=Number(event.target?.dataset?.pmcStart||event.target?.dataset?.pmcX);if(Number.isFinite(anchor))svgX=anchor}
    if(svgX===null)return 0;
    const index=Math.round((svgX-50)/Math.max(1,902-50)*(points.length-1));
    return Math.max(0,Math.min(points.length-1,index));
  }
  function pmcHoverShip(id,event,indexArg=null) {
    const current=state.pmcView?.current;
    if(!current)return;
    const batch=pmcFundedShipments(current).find(item=>`PLAN-${item.sequence}`===String(id))
      ||(current.timeline?.events||[]).find(item=>String(item.shipment||item.id)===String(id));
    const index=indexArg!==null&&indexArg!==undefined&&Number.isFinite(Number(indexArg))?Number(indexArg):pmcPointIndexAtEvent(current,event);
    const tip=pmcTimelineTip(current,index);
    if(!tip)return;
    let shipLine='';
    if(batch){
      const shipId=batch.shipment||batch.id||`PLAN-${batch.sequence}`;
      const dispatch=batch.dispatchDate||batch.etaStart||'';
      const arrival=batch.arrivalDate||batch.etaEnd||batch.date||'';
      const qty=batch.fundedQty??batch.shipNowQty??batch.executableQty??batch.qty??0;
      shipLine=`<div class="tip-ship"><b>${escapeHtml(shipId)}</b><span>${escapeHtml(pmcFullDate(dispatch))} 发 · ${escapeHtml(pmcFullDate(arrival))} 到 · ${fmt(qty)} 件</span></div>`;
    }
    const html=shipLine?`${tip}<div class="tip-ships">${shipLine}</div>`:tip;
    pmcHoverTip(html,`ship:${id}:${index}`,event);
    const wrap=document.getElementById('pmc-timeline-chart');
    const cursor=wrap?.querySelector('.pmc-cursor');
    if(cursor&&wrap){
      const svg=wrap.querySelector('svg');
      const rect=svg?.getBoundingClientRect();
      let x=event?.target?.dataset?.pmcX;
      if(event&&rect&&event.clientX>=rect.left&&event.clientX<=rect.right)x=((event.clientX-rect.left)/Math.max(1,rect.width)*920).toFixed(1);
      if(x){cursor.setAttribute('x1',x);cursor.setAttribute('x2',x);cursor.setAttribute('opacity','.55')}
    }
  }
  function pmcHoverTimeline(index,x,event) {
    const current=state.pmcView?.current;
    const wrap=document.getElementById('pmc-timeline-chart');
    if(!current||!wrap)return;
    const html=pmcTimelineTip(current,index);
    if(!html)return;
    pmcHoverTip(html,`day:${index}`,event);
    const cursor=wrap.querySelector('.pmc-cursor');
    if(cursor){cursor.setAttribute('x1',x);cursor.setAttribute('x2',x);cursor.setAttribute('opacity','.55')}
  }
  function pmcHideHover() {
    if(state.pmcPin)return;
    state.pmcHoverKey=null;
    const tip=document.getElementById('pmc-timeline-tip');
    if(tip){tip.hidden=true;tip.innerHTML=''}
    const cursor=document.querySelector('#pmc-timeline-chart .pmc-cursor');
    if(cursor)cursor.setAttribute('opacity','0');
  }
  function pmcHidePin() {
    state.pmcHoverKey=null;
    document.querySelectorAll('.pmc-pin-tip').forEach(tip=>{tip.hidden=true;tip.innerHTML=''});
    document.querySelectorAll('.pmc-cursor').forEach(cursor=>cursor.setAttribute('opacity','0'));
    document.querySelectorAll('#pmc-arrival tr[data-pmc-ship]').forEach(row=>row.classList.remove('selected'));
  }
  function pmcPlaceTip(wrap,tip,event) {
    const rect=wrap.getBoundingClientRect();
    const inChart=event?.target&&wrap.contains(event.target);
    const x=inChart?event.clientX-rect.left:Math.max(12,rect.width-230);
    const y=inChart?event.clientY-rect.top:12;
    tip.hidden=false;
    const width=tip.offsetWidth,height=tip.offsetHeight;
    let left=x+14;
    if(left+width>rect.width-8)left=x-width-14;
    let top=y+14;
    if(top+height>rect.height-8)top=y-height-14;
    tip.style.left=`${Math.max(4,left)}px`;
    tip.style.top=`${Math.max(4,top)}px`;
  }
  function pmcShowPin(pin,event) {
    const current=state.pmcView?.current;
    if(!current)return;
    const source=pin.kind==='ship'?'timeline':pin.source;
    const wrap=document.getElementById(source==='demand'?'pmc-demand-chart':'pmc-timeline-chart');
    const tip=document.getElementById(source==='demand'?'pmc-demand-tip':'pmc-timeline-tip');
    if(!wrap||!tip)return;
    document.querySelectorAll('.pmc-pin-tip').forEach(node=>{node.hidden=true;node.innerHTML=''});
    const html=pin.kind==='ship'?pmcShipTip(current,pin.id):(source==='demand'?pmcDemandTip(current,pin.index):pmcTimelineTip(current,pin.index));
    if(!html)return;
    tip.innerHTML=html;
    pmcPlaceTip(wrap,tip,event);
    const cursor=wrap.querySelector('.pmc-cursor');
    if(cursor){
      const svg=wrap.querySelector('svg');
      const rect=svg?.getBoundingClientRect();
      let x=null;
      if(event&&rect&&event.clientX>=rect.left&&event.clientX<=rect.right){
        x=((event.clientX-rect.left)/Math.max(1,rect.width)*920).toFixed(1);
      }
      if(!x)x=event?.target?.dataset?.pmcX;
      if(x){cursor.setAttribute('x1',x);cursor.setAttribute('x2',x);cursor.setAttribute('opacity','1')}
    }
    document.querySelectorAll('#pmc-arrival tr[data-pmc-ship]').forEach(row=>row.classList.toggle('selected',pin.kind==='ship'&&pin.id===row.dataset.pmcShip));
  }
  function pmcToggleDay(source,index,event) {
    const same=state.pmcPin?.kind==='day'&&state.pmcPin.source===source&&state.pmcPin.index===index;
    if(same){state.pmcPin=null;pmcHidePin();return}
    state.pmcPin={kind:'day',source,index};pmcShowPin(state.pmcPin,event);
  }
  function pmcToggleShip(id,event) {
    const same=state.pmcPin?.kind==='ship'&&state.pmcPin.id===id;
    if(same){state.pmcPin=null;pmcHidePin();return}
    state.pmcPin={kind:'ship',id};pmcShowPin(state.pmcPin,event);
  }

  function pmcHero(product,pmc,base,current,choice) {
    const firstShip=pmcFirstShip(current);
    const firstBuy=pmcFirstBuy(current);
    const bridge=current.bridgePlan||{};
    const bridgeGap=Number(bridge.uncoveredDays||0);
    const need=pmcUnshippableNeed(current);
    const risk=current.risk||pmcRisk(product);
    const eta=board.inventory_batch?.metadata?.etaFile||{};
    const decision=current.decision?.conclusion||current.nextAction||'库存方案待复核';
    const stockoutDate=current.timeline?.stockoutDate;
    const headline=stockoutDate
      ? `预计 ${escapeHtml(pmcFullDate(stockoutDate))} 断货${bridgeGap?` · 断档 ${fmt(bridgeGap)} 天`:''}`
      : String(decision).split('；')[0];
    const summary=current.timeline?.nextEta
      ? `下一票 ${escapeHtml(pmcFullDate(current.timeline.nextEta))} 到${bridge.arrivalDate?`；今天发最快 ${escapeHtml(pmcFullDate(bridge.arrivalDate))} 到`:''}${bridgeGap?'，赶不上':''}`
      : '';
    const futureShip=pmcPlannedShipments(current).find(batch=>batch.sequence!==(firstShip?.sequence||-1))||null;
    let nextTitle='当前不需要发货';
    let nextDetail='测算期内没有达到策略阈值的发货批次';
    if(firstShip){
      nextTitle=`发 ${fmt(pmcFunded(firstShip))} 件 · ${escapeHtml(firstShip.mode||'待定')}`;
      nextDetail=`${escapeHtml(pmcFullDate(firstShip.dispatchDate))} 发出 · ${escapeHtml(pmcFullDate(firstShip.arrivalDate))} 到仓`;
    }else if(firstBuy){
      nextTitle=`本地无货，先采购 ${fmt(firstBuy.suggestedQty)} 件`;
      nextDetail=`${escapeHtml(pmcFullDate(firstBuy.orderDate))} 下单 · ${escapeHtml(pmcFullDate(firstBuy.expectedReadyDate))} 齐套${futureShip?`；齐套后 ${escapeHtml(pmcFullDate(futureShip.dispatchDate))} 发 ${fmt(pmcFunded(futureShip))} 件，${escapeHtml(pmcFullDate(futureShip.arrivalDate))} 到仓`:'；齐套后再排发货'}${firstBuy.late?' · <b class="pmc-danger">采购已晚</b>':''}`;
    }else if(futureShip){
      nextTitle='本地无货，采购后补发';
      nextDetail=`后续批次 ${escapeHtml(pmcFullDate(futureShip.dispatchDate))} 发 ${fmt(pmcFunded(futureShip))} 件 · ${escapeHtml(pmcFullDate(futureShip.arrivalDate))} 到仓；不是立刻可发`;
    }else if(current.timeline?.nextEta){
      nextTitle='新发赶不上';
      nextDetail=`下一票 ${escapeHtml(pmcFullDate(current.timeline.nextEta))} 到 ${fmt(current.timeline.confirmedQty)} 件；建议催提前或改空运`;
    }else if(Number(current.calc?.gapFba||0)>0){
      nextTitle='本地无货，需调拨/采购';
      nextDetail=`理论补货缺口 ${fmt(need?.suggestedQty??current.calc?.gapFba)} 件；当前没有可执行货源`;
    }
    return `<section class="pmc-decision ${risk==='critical'?'critical':''}">
      <div class="pmc-decision-main"><div class="pmc-decision-kicker"><span class="pmc-chip ${risk==='critical'?'danger':risk==='overstock'?'warn':'good'}">${escapeHtml(pmcRiskText(product))}</span><span class="pmc-chip">${escapeHtml(pmcConfidenceLabel(current.forecast?.confidence))}置信度 · 有效 ${fmt(current.forecast?.effectiveDays)}/60 天</span><span class="pmc-chip">库存 ${escapeHtml(board.inventory_batch?.as_of||'')}</span></div><h3>${escapeHtml(headline)}</h3>${summary?`<p class="pmc-decision-summary">${summary}</p>`:''}<div class="pmc-decision-tags"><span>ETA 台账 ${escapeHtml(eta.status==='loaded'?'已读取':'缺失')}</span><span>确认在途 ${fmt(current.timeline?.confirmedQty)} 件</span><span>未知 ETA ${fmt(current.timeline?.unknownEtaQty)} 件</span>${choice!=='base'?`<span class="pmc-warn">情景：${escapeHtml(PMC_PRESET_LABELS[choice]||'自定义')}</span>`:''}</div></div>
      <div class="pmc-decision-next"><small>下一步</small><strong>${nextTitle}</strong><span>${nextDetail}</span>${firstShip&&firstBuy?`<span>采购 ${fmt(firstBuy.suggestedQty)} 件 · ${escapeHtml(pmcFullDate(firstBuy.orderDate))} 下单</span>`:''}${bridgeGap?`<span class="pmc-danger">即使按首批救急，仍断 ${fmt(bridgeGap)} 天</span>`:''}</div>
    </section>`;
  }

  function pmcEditorValues(pmc,params) {
    const policy=pmc.policy||{};
    return {
      demandPct:Math.round(Number(params.demandMultiplier??1)*100),
      transitDays:params.transitDays??policy.transitDays??60,
      expressDays:params.expressDays??policy.expressTransitDays??30,
      airTransitDays:params.airTransitDays??0,
      purchaseLeadDays:params.purchaseLeadDays??policy.purchaseLeadDays??40,
      safetyDays:params.safetyDays??policy.safetyDays??15,
      cartonQty:params.cartonQty??0,
      moq:params.moq??0,
      minShipQty:params.minShipQty??0,
      localAvailable:params.localAvailable??'',
      seasonal:Array.isArray(params.seasonal)?params.seasonal:[]
    };
  }
  function pmcSeasonRow(row={}) {
    return `<div class="pmc-season-row"><input type="date" class="pmc-season-from" value="${escapeHtml(row.from||'')}"><span>~</span><input type="date" class="pmc-season-to" value="${escapeHtml(row.to||'')}"><div class="pmc-input"><input type="number" class="pmc-season-mult" min="50" max="1000" step="10" value="${Math.round(Number(row.multiplier||2)*100)}"><em>%</em></div><button type="button" data-pmc-season-remove aria-label="删除区间">×</button></div>`;
  }
  function pmcEditorHtml(product,pmc,params) {
    const values=pmcEditorValues(pmc,params);
    const hasSeason=values.seasonal.length>0;
    const field=(name,label,value,unit,min,max,step='1',disabled=false)=>`<label class="pmc-field ${disabled?'disabled':''}"><span>${label}</span><div class="pmc-input"><input data-pmc-param="${name}" type="number" min="${min}" max="${max}" step="${step}" value="${escapeHtml(value)}" ${disabled?'disabled':''}><em>${unit}</em></div></label>`;
    return `<div id="pmc-editor" class="pmc-editor"><div class="pmc-editor-head"><div><strong>情景参数</strong><span>改完点“应用试算”；曲线、发货、采购和目标会一起重算。这里只做本地预览，不写领星。</span></div><div class="pmc-editor-actions"><button type="button" class="pmc-primary-button" data-pmc-apply>应用试算</button><button type="button" class="pmc-quiet-button" data-pmc-save>保存为方案</button><button type="button" class="pmc-quiet-button" data-pmc-export>导出 JSON</button></div></div>
      <div class="pmc-editor-grid">
        <fieldset><legend>需求</legend>${field('demandPct','日均倍数',values.demandPct,'%',30,1000,'5',hasSeason)}${hasSeason?'<p class="pmc-field-note">已启用季节区间，常数倍数不生效。</p>':''}</fieldset>
        <fieldset><legend>运输</legend>${field('transitDays','海运',values.transitDays,'天',10,120)}${field('expressDays','卡航',values.expressDays,'天',5,90)}${field('airTransitDays','空运',values.airTransitDays,'天',0,30)}</fieldset>
        <fieldset><legend>采购</legend>${field('purchaseLeadDays','采购周期',values.purchaseLeadDays,'天',0,180)}${field('moq','最低起订量',values.moq,'件',0,100000)}${field('cartonQty','装箱数量',values.cartonQty,'件/箱',0,10000)}</fieldset>
        <fieldset><legend>发货</legend>${field('safetyDays','安全库存',values.safetyDays,'天',0,60)}${field('minShipQty','最低起运量',values.minShipQty,'件',0,100000)}<p class="pmc-field-note">发货频率由断货日和最低起运量自动推导，不再手填；最低起运量越高，目标库存越高。</p></fieldset>
        <fieldset><legend>本地</legend>${field('localAvailable','本地实际可用',values.localAvailable,'件',0,1000000,'1')}<p class="pmc-field-note">不填 = 用领星本地库存；覆盖只影响发货可行性，不减少采购建议。</p></fieldset>
      </div>
      <div class="pmc-season-block"><div class="pmc-season-head"><span>季节区间倍数（区间内按倍数，区间外 ×1；有区间时常数倍数不生效）</span><button type="button" class="pmc-quiet-button" data-pmc-season-add>+ 加区间</button></div><div class="pmc-season-rows">${values.seasonal.map(pmcSeasonRow).join('')}</div></div>
      <p class="pmc-editor-hint">保存为方案会进入本浏览器的方案库，可选择允许使用的 ASIN；导出 JSON 可供技能情景库合并。保存动作不是领星写回。</p></div>`;
  }
  function pmcScenarioBar(product,pmc,current,choice,params) {
    const options=pmcScenarioOptions(product,pmc);
    const selected=options.some(([key])=>key===choice)?choice:'base';
    const editorOpen=Boolean(state.pmcEditor[product.key]);
    const feedback=state.pmcFeedback[product.key]||'';
    return `<section class="pmc-scenario-shell"><div class="pmc-scenario-bar ${choice!=='base'?'active':''}"><div class="pmc-scenario-main"><span class="pmc-scenario-kicker">情景</span><select class="pmc-scenario-select" data-pmc-scenario-select>${options.map(([key,label])=>`<option value="${key}" ${selected===key?'selected':''}>${escapeHtml(label)}</option>`).join('')}</select><span class="pmc-scenario-meta">${escapeHtml(pmcScenarioMeta(params))}</span></div><div class="pmc-scenario-actions"><button type="button" class="pmc-quiet-button" data-pmc-edit>${editorOpen?'收起编辑':'编辑情景'}</button><button type="button" class="pmc-quiet-button" data-pmc-open-library>方案库</button><button type="button" class="pmc-quiet-button" data-pmc-reset ${choice==='base'?'disabled':''}>恢复基准</button><button type="button" class="pmc-quiet-button" data-pmc-export>导出方案</button></div></div>${editorOpen?pmcEditorHtml(product,pmc,params):''}${feedback?`<p class="pmc-feedback">${escapeHtml(feedback)}</p>`:''}</section>`;
  }
  function pmcModalHtml(product,pmc) {
    if(!state.pmcModal)return '';
    const draft=state.pmcDraft||{name:'',scope:'current',selected:[product.key],search:''};
    if(state.pmcModal==='save'){
      const candidates=products.filter(item=>item.inventory_pmc);
      const parentAsin=product.parent_asin||pmc?.basis?.parent_asin||product.asin;
      const parentCount=candidates.filter(item=>(item.parent_asin||item.inventory_pmc?.basis?.parent_asin||item.asin)===parentAsin).length;
      const rows=candidates.map(item=>`<label class="pmc-asin-row" data-pmc-asin-row data-search="${escapeHtml([item.name,item.asin,item.shop].join(' ').toLowerCase())}"><input type="checkbox" data-pmc-asin value="${escapeHtml(item.key)}" ${draft.selected?.includes(item.key)?'checked':''}><span><b>${escapeHtml(shortName(item.name,26))}</b><small>${escapeHtml(item.asin)} · ${escapeHtml(item.shop)}</small></span></label>`).join('');
      return `<div class="pmc-modal-backdrop"><section class="pmc-modal" role="dialog" aria-modal="true" aria-label="保存方案"><div class="pmc-modal-head"><div><strong>保存为方案</strong><span>自由命名，并选择允许使用它的 ASIN；保存到本浏览器方案库。</span></div><button type="button" data-pmc-modal-close aria-label="关闭">×</button></div><label class="pmc-modal-field"><span>方案名称</span><input data-pmc-save-name type="text" maxlength="60" value="${escapeHtml(draft.name||'')}" placeholder="例如：旺季保守补货"></label><div class="pmc-scope-tabs">${[['current','仅当前 ASIN'],['parent',`同父体 ASIN · ${fmt(parentCount)} 个`],['manual','手动选择']].map(([key,label])=>`<button type="button" data-pmc-scope="${key}" class="${draft.scope===key?'active':''}">${label}</button>`).join('')}</div>${draft.scope==='manual'?`<div class="pmc-modal-search"><input data-pmc-save-search type="search" placeholder="搜索 ASIN / SKU / 产品名" value="${escapeHtml(draft.search||'')}"></div><div class="pmc-asin-list">${rows}</div>`:`<p class="pmc-modal-note">${draft.scope==='parent'?`将允许同父体 ${escapeHtml(parentAsin)} 下的 ${fmt(parentCount)} 个店铺-ASIN 使用；当前 ASIN 一定包含。`:'只允许当前店铺-ASIN 使用；之后可在方案库里修改范围。'}</p>`}<div class="pmc-modal-actions"><button type="button" class="pmc-quiet-button" data-pmc-modal-close>取消</button><button type="button" class="pmc-primary-button" data-pmc-save-confirm>保存方案</button></div><p class="pmc-modal-error" id="pmc-modal-error"></p></section></div>`;
    }
    if(state.pmcModal==='library'){
      const scenarios=pmcLibraryData().scenarios;
      return `<div class="pmc-modal-backdrop"><section class="pmc-modal pmc-library-modal" role="dialog" aria-modal="true" aria-label="方案库"><div class="pmc-modal-head"><div><strong>方案库</strong><span>已保存 ${fmt(scenarios.length)} 个方案；只在本浏览器保留，导出 JSON 后可合并到技能情景库。</span></div><button type="button" data-pmc-modal-close aria-label="关闭">×</button></div><div class="pmc-library-list">${scenarios.length?scenarios.map(scenario=>{const allowed=pmcScenarioAllowed(scenario,product);return `<div class="pmc-library-row"><div><strong>${escapeHtml(scenario.name)}</strong><small>${escapeHtml(pmcScenarioMeta(scenario.params))}</small><span>${fmt((scenario.allowed||[]).length)} 个允许 ASIN${allowed?' · 含当前':''}</span></div><div class="pmc-library-actions"><button type="button" class="pmc-quiet-button" data-pmc-lib-apply="${escapeHtml(scenario.id)}" ${allowed?'':'disabled'}>${allowed?'应用':'未授权当前'}</button><button type="button" class="pmc-danger-link" data-pmc-lib-delete="${escapeHtml(scenario.id)}">删除</button></div></div>`}).join(''):'<p class="pmc-empty-line">还没有保存的自定义方案。先在“编辑情景”里调参数，再点“保存为方案”。</p>'}</div><div class="pmc-modal-actions"><button type="button" class="pmc-quiet-button" data-pmc-lib-export>导出方案库 JSON</button><button type="button" class="pmc-quiet-button" data-pmc-modal-close>关闭</button></div></section></div>`;
    }
    return '';
  }
  function pmcOpenSave(product,pmc,params) {
    state.pmcDraft={name:'',scope:'current',selected:[product.key],search:'',params};
    state.pmcModal='save';state.pmcEditor[product.key]=false;pmcRefresh(product);
  }
  function pmcCreateScenario(product) {
    const name=document.querySelector('[data-pmc-save-name]')?.value.trim()||'';
    const error=document.getElementById('pmc-modal-error');
    const fail=message=>{if(error)error.textContent=message};
    if(!name||name.length>60){fail('请填写 1–60 字的方案名称');return}
    const library=pmcLibraryData();
    if(library.scenarios.some(item=>String(item.name).toLowerCase()===name.toLowerCase())){fail('方案名称已存在，请换一个');return}
    const scope=document.querySelector('[data-pmc-scope].active')?.dataset.pmcScope||state.pmcDraft?.scope||'current';
    const parentAsin=product.parent_asin||product.inventory_pmc?.basis?.parent_asin||product.asin;
    let allowed;
    if(scope==='current')allowed=[product];
    else if(scope==='parent')allowed=products.filter(item=>item.inventory_pmc&&((item.parent_asin||item.inventory_pmc?.basis?.parent_asin||item.asin)===parentAsin));
    else{
      const keys=new Set([...document.querySelectorAll('[data-pmc-asin]:checked')].map(input=>input.value));
      allowed=products.filter(item=>keys.has(item.key));
    }
    if(!allowed.length){fail('至少选择一个允许使用的 ASIN');return}
    const params=state.pmcDraft?.params||{};
    const scenario={id:`pmc-${Date.now()}`,name,params,allowed:allowed.map(item=>({sid:String(item.sid),store:item.shop,asin:item.asin})),createdAt:new Date().toISOString(),updatedAt:new Date().toISOString()};
    library.scenarios.push(scenario);
    pmcLibrarySave();
    state.pmcChoice[product.key]=`lib:${scenario.id}`;
    state.pmcModal=null;state.pmcFeedback[product.key]=`方案「${name}」已保存，并应用到当前 ASIN。`;
    pmcRefresh(product);
  }
  function pmcExportLibrary() {
    const data=pmcLibraryData();
    pmcDownload('pmc-scenario-library.json',JSON.stringify({version:1,exportedAt:new Date().toISOString(),scenarios:data.scenarios},null,2),'application/json');
  }

  function pmcKpis(base,current) {
    const firstShip=pmcFirstShip(current);
    const safetyDays=Number(current.calc?.safetyDays??current.policy?.safetyDays??15);
    const targetDays=Number(current.calc?.targetDays||22);
    const batchDays=Math.max(0,targetDays-safetyDays);
    const gap=current.timeline?.stockoutIntervals?.[0];
    const stockoutDays=Number(current.calc?.stockoutDuration??current.timeline?.stockoutDays??0);
    const openGap=Boolean(gap&&(gap.open||!gap.end));
    const riskNote=stockoutDays>0
      ?`${openGap?'断货至计划期末':'首个断货'} ${fmt(stockoutDays)} 天 · 近30天日均营收`
      :'测算期内无断货';
    const cards=[
      ['FBA 可售',fmt(current.inventoryLayers?.sellable),'不含接收中/在途'],
      ['基线断货日',escapeHtml(current.timeline?.stockoutDate||'未见'),'未知 ETA 不计入'],
      ['预测日均',`${fmt(current.forecast?.daily,1)} 件`,'近 7/30/60 天加权'],
      ['FBA 目标',fmt(current.calc?.targetFba),`覆盖 ${fmt(targetDays)} 天 = 安全 ${fmt(safetyDays)} + 补货 ${fmt(batchDays)} · 峰值 ${fmt(current.calc?.targetPeak)}`],
      ['断货营收影响',pmcMoney(current.calc?.lossAmount),riskNote]
    ];
    return `<section class="pmc-kpis pmc-kpis-five">${cards.map(([label,value,note])=>`<div class="pmc-stat"><small>${label}</small><strong>${value}</strong><span>${note}</span></div>`).join('')}</section>`;
  }
  function pmcQualityHtml(product,pmc) {
    const gaps=[...new Set([...(pmc.dataGaps||[]),...(pmc.basis?.dataGaps||[])])];
    const eta=board.inventory_batch?.metadata?.etaFile||{};
    return `<section class="pmc-quality-panel ${Number(pmc.timeline?.confirmedQty)>0?'':'warn'}"><div class="pmc-quality-panel-title"><span>数据质量</span>${pmcQualityChips([product],true)}</div>${Number(pmc.timeline?.confirmedQty)===0?'<p class="pmc-quality-alert"><b>本次没有确认 ETA。</b> 断货日只按 FBA 可售推算，可能偏早；在途有数量但缺可靠 ETA，不进入时间轴。</p>':''}<details class="pmc-disclosure"><summary>查看缺口与来源（${fmt(gaps.length)} 项）</summary><ul>${gaps.length?gaps.map(gap=>`<li>${escapeHtml(gap)}</li>`).join(''):'<li>关键字段完整。</li>'}</ul><p class="pmc-source-note">库存批次 ${escapeHtml(board.inventory_batch?.as_of||'')} · 广告/Listing ${escapeHtml(board.as_of_date||'')} · ETA 文件 ${escapeHtml(eta.lastUpdatedAt||eta.sourceName||'—')} · 库存与广告不按同日因果合并。</p></details></section>`;
  }
  function pmcDemandPanel(current) {
    const f=current.forecast||{};
    const momentum={accelerating:'加速',steady:'平稳',decelerating:'减速'}[f.momentum]||'';
    const stateLabel={growth:'增长',decline:'下降',stable:'稳定',volatile:'波动',limited:'样本少'}[f.state]||f.state||'—';
    const formula=`近 7 天 ${fmt(f.segments?.recent)} × ${Math.round(Number(f.weights?.recent||0)*100)}% + 30 天 ${fmt(f.segments?.middle)} × ${Math.round(Number(f.weights?.middle||0)*100)}% + 60 天 ${fmt(f.segments?.far)} × ${Math.round(Number(f.weights?.far||0)*100)}% = <b>${fmt(f.daily)}</b> 件/天`;
    return `<section class="panel pmc-chart-panel pmc-demand-panel"><div class="pmc-panel-head"><div><span class="eyebrow">DEMAND</span><h3>卖多快</h3></div><span class="pmc-headline">${fmt(f.daily)} 件/天<small>${escapeHtml(stateLabel)}${momentum?` · ${momentum}`:''} · ${escapeHtml(pmcConfidenceLabel(f.confidence))}置信</small></span></div><p class="pmc-formula">${formula}　·　有效 ${fmt(f.effectiveDays)} 天${Number(f.constrainedDays)?`，剔除 ${fmt(f.constrainedDays)} 个库存约束日`:''}${f.fallbackUsed?'，样本不足按最近有效日均回退':''}${f.seasonalActive?'，曲线已计入季节区间':''}</p><div class="pmc-chart pmc-demand-chart" id="pmc-demand-chart">${pmcDemandSvg(current)}<div class="pmc-pin-tip" id="pmc-demand-tip" hidden></div></div>${pmcWeightsHtml(current)}<p class="pmc-chart-note">柱 = 逐日销量；库存约束日用浅珊瑚标记，已从均值中剔除。点击柱子固定，再点取消。</p></section>`;
  }
  function pmcTimelinePanel(base,current,choice) {
    const firstShip=pmcFirstShip(current);
    const second=pmcFundedShipments(current).filter(batch=>batch.sequence!==(firstShip?.sequence||-1))[0];
    const baseGap=base.timeline?.stockoutIntervals?.[0];
    const planGap=current.plannedTimeline?.stockoutIntervals?.[0];
    const bridge=current.bridgePlan||{};
    const local=current.calc?.localOverride??current.calc?.sourceAvailable??0;
    const future=pmcFundedShipments(current).find(batch=>batch.sequence!==(firstShip?.sequence||-1))||null;
    const range=Math.max(60,Number(state.pmcRange)||90);
    const status=baseGap?`不行动：${pmcDate(baseGap.start)} 起断货${baseGap.end?`，持续 ${fmt(baseGap.days)} 天`:'，测算期内未恢复'}`:'不行动：测算期内不断货';
    const planStatus=planGap?`全计划后仍有断档 ${pmcDate(planGap.start)} → ${pmcDate(planGap.end)}`:'全计划后测算期内不断货';
    const zoom=`<div class="pmc-zoom" role="group" aria-label="时间轴缩放"><button type="button" data-pmc-zoom="-15" aria-label="缩小窗口">−</button><span id="pmc-range-label">${fmt(range)} 天</span><button type="button" data-pmc-zoom="15" aria-label="放大窗口">+</button><button type="button" data-pmc-zoom="reset">重置</button></div>`;
    const minShipQty=Number(current.calc?.minShipQty||0);
    const minShipDays=Number(current.forecast?.daily)>0?minShipQty/Number(current.forecast.daily):0;
    const minShipNote=minShipQty>0&&minShipDays>30?`<p class="pmc-plan-warning">最低起运量 ${fmt(minShipQty)} 件 ≈ ${fmt(minShipDays,1)} 天需求，超过 30 天；批次会偏少，建议核对起运量。</p>`:'';
    return `<section class="panel pmc-chart-panel pmc-timeline-panel"><div class="pmc-panel-head"><div><span class="eyebrow">TIMELINE</span><h3>什么时候断、什么时候到</h3></div><div class="pmc-timeline-head-right"><span class="pmc-headline ${baseGap?'danger':''}">${escapeHtml(status)}<small>${escapeHtml(planStatus)}</small></span>${zoom}</div></div><div class="pmc-legend"><span><i class="pmc-legend-line confirmed"></i>确认在途</span><span><i class="pmc-legend-line planned"></i>建议发货后</span><span><i class="pmc-legend-line target"></i>目标</span><span><i class="pmc-legend-gap base"></i>不补货会断</span><span><i class="pmc-legend-gap plan"></i>按建议仍断</span><span class="pmc-legend-hint">悬停查看 · 点击锁定</span></div><div class="pmc-chart pmc-timeline-chart" id="pmc-timeline-chart">${pmcTimelineSvg(base,current,range)}<div class="pmc-pin-tip" id="pmc-timeline-tip" hidden></div></div><div class="pmc-timeline-facts"><div><span>当前可售</span><strong>${fmt(current.inventoryLayers?.sellable)}</strong></div><div><span>首批救急后</span><strong>${bridge.actionable?`${fmt(bridge.gapDays)} 天缺口 / ${fmt(bridge.uncoveredDays)} 天未覆盖`:'不适用'}</strong></div><div><span>下一确认 ETA</span><strong>${current.timeline?.nextEta?`${escapeHtml(pmcFullDate(current.timeline.nextEta))}`:'未确认'}</strong></div><div><span>目标 / 计划期</span><strong>当前 ${fmt(current.calc?.targetFba)} · 峰值 ${fmt(current.calc?.targetPeak)} (${escapeHtml(pmcDate(current.calc?.targetPeakDate))})</strong></div></div><p class="pmc-plan-note">${firstShip?`立刻可发 ${fmt(pmcFunded(firstShip))} 件 ${escapeHtml(pmcFullDate(firstShip.dispatchDate))} 发出（${escapeHtml(firstShip.mode||'待定')}），${escapeHtml(pmcFullDate(firstShip.arrivalDate))} 到仓${second?`；下一批 ${fmt(pmcFunded(second))} 件 ${escapeHtml(pmcFullDate(second.arrivalDate))} 到仓`:''}。本地可发 ${fmt(local)} 件；采购 ${fmt(current.policy?.purchaseLeadDays)} 天 + 运输 ${fmt(firstShip?.transitDays)} 天。`:(future?`本地可发 0 件；后续按采购周期推算：${escapeHtml(pmcFullDate(future.dispatchDate))} 发 ${fmt(pmcFunded(future))} 件，${escapeHtml(pmcFullDate(future.arrivalDate))} 到仓（采购 ${fmt(current.policy?.purchaseLeadDays)} 天 + 运输 ${fmt(future.transitDays)} 天）。`:(current.timeline?.nextEta?`没有新增发货批次；下一票 ${escapeHtml(pmcFullDate(current.timeline.nextEta))} 到 ${fmt(current.timeline.confirmedQty)} 件，建议催提前或改空运。`:'当前没有可执行发货批次。'))}${minShipNote}</p><p class="pmc-chart-note">图表窗口 ${fmt(range)} 天；下表计划覆盖 ${fmt(current.calc?.horizonDays)} 天。窗口外仍有后续批次时，以下方周计划为准；图中最多显示 8 条计划色条。</p></section>`;
  }
  function pmcSetRange(next) {
    state.pmcRange=Math.max(60,Math.min(240,Number(next)||90));
    state.pmcPin=null;
    const view=state.pmcView;
    const chart=document.getElementById('pmc-timeline-chart');
    if(!chart||!view)return;
    chart.innerHTML=pmcTimelineSvg(view.base,view.current,state.pmcRange)+'<div class="pmc-pin-tip" id="pmc-timeline-tip" hidden></div>';
    const label=document.getElementById('pmc-range-label');
    if(label)label.textContent=`${fmt(state.pmcRange)} 天`;
  }
  function pmcActionCard(current) {
    const firstShip=pmcFirstShip(current),firstBuy=pmcFirstBuy(current),bridge=current.bridgePlan||{};
    const need=pmcUnshippableNeed(current);
    return `<section class="panel pmc-side-card pmc-side-action"><div class="pmc-side-head"><span>本周动作</span><span class="pmc-chip">仅方案</span></div>${firstShip?`<div class="pmc-side-block"><small>发货 · 可执行</small><strong>${fmt(pmcFunded(firstShip))} 件</strong><p>${escapeHtml(pmcFullDate(firstShip.dispatchDate))} · ${escapeHtml(firstShip.mode||'待定')} → ${escapeHtml(pmcFullDate(firstShip.arrivalDate))}</p>${bridge.uncoveredDays?`<p class="pmc-warn">首批救急后仍断 ${fmt(bridge.uncoveredDays)} 天</p>`:''}</div>`:`<div class="pmc-side-block"><small>发货</small><strong>${firstBuy?'本地无货，先采购':(current.timeline?.nextEta?'新发赶不上':'当前不需要发货')}</strong><p>${firstBuy?`理论补货缺口 ${fmt(need?.suggestedQty??firstBuy.suggestedQty)} 件；采购齐套后再排发货。`:(current.timeline?.nextEta?`下一票 ${escapeHtml(pmcFullDate(current.timeline.nextEta))} 到 ${fmt(current.timeline.confirmedQty)} 件；建议催提前或改空运。`:(Number(current.calc?.gapFba||0)>0?'有缺口，但当前没有可执行货源。':'测算期内不需要发货。'))}</p></div>`}${firstBuy?`<div class="pmc-side-block"><small>采购</small><strong>${fmt(firstBuy.suggestedQty)} 件</strong><p>${escapeHtml(pmcFullDate(firstBuy.orderDate))} 下单 · ${escapeHtml(pmcFullDate(firstBuy.expectedReadyDate))} 齐套${firstBuy.late?' · <span class="pmc-danger">已晚</span>':''}</p></div>`:''}<p class="pmc-side-foot">所有数量是本地模拟，不创建货件或采购单。</p></section>`;
  }
  function pmcLayerCard(current) {
    const layers=current.inventoryLayers||{},calc=current.calc||{};
    const items=[
      ['FBA 可售',fmt(layers.sellable),'计入基线'],
      ['确认在途',fmt(calc.fbaParts?.confirmedInbound),'带 ETA 才计入'],
      ['未知 ETA',fmt(current.timeline?.unknownEtaQty),'不推迟断货日'],
      ['本地 + 海外',fmt(Number(calc.localParts?.local||0)+Number(calc.localParts?.overseas||0)),'发货源'],
      ['采购未结',fmt(calc.localParts?.procurementOpen),'无到货日'],
      ['客户预留',fmt(layers.reservedCustomerOrders),'FBA 内占用']
    ];
    return `<section class="panel pmc-side-card"><div class="pmc-side-head"><span>库存分层</span><span class="pmc-chip">领星 + 货件</span></div><div class="pmc-layer-grid">${items.map(([label,value,note])=>`<div><small>${label}</small><strong>${value}</strong><span>${note}</span></div>`).join('')}</div>${current.stockAllocation?`<p class="pmc-side-foot">共享 SKU ${escapeHtml(current.stockAllocation.sku)}：本店按近 30 天销量分摊 ${pct(current.stockAllocation.share)}；只用于计划参考。</p>`:''}</section>`;
  }
  function pmcEtaCard(current) {
    const eta=board.inventory_batch?.metadata?.etaFile||{};
    const recon=current.etaReconciliation||{};
    const api=current.basis?.supplyEvidence||current.supplyEvidence;
    const apiRows=api?.items||[];
    const apiGaps=apiRows.filter(item=>item.state!=='verified').length;
    const read=api?api.state==='verified':eta.status==='loaded';
    const label=api?(read?'API 已读取':'API 已读 · ETA 待补'):(read?'已读取':'缺失');
    const source=api
      ? `领星 API：${apiRows.length} 个货件，${apiGaps} 个到仓日期待复核${api.source_response_time?` · 来源响应 ${escapeHtml(api.source_response_time)}`:''}`
      : `货件文件 ${escapeHtml(eta.sourceName||'未提供')}${eta.lastUpdatedAt?` · 更新 ${escapeHtml(eta.lastUpdatedAt)}`:''}`;
    return `<section class="panel pmc-side-card"><div class="pmc-side-head"><span>ETA 与来源</span><span class="pmc-chip ${read?'good':'danger'}">${label}</span></div><div class="pmc-eta-grid"><div><small>确认在途</small><strong>${fmt(current.timeline?.confirmedQty)}</strong></div><div><small>未知 ETA</small><strong>${fmt(current.timeline?.unknownEtaQty)}</strong></div><div><small>台账 / 实时</small><strong>${fmt(recon.ledgerQty)} / ${fmt(recon.liveQty)}</strong></div><div><small>提示</small><strong>${(api?apiGaps>0:eta.reminder)?'有':'无'}</strong></div></div><p class="pmc-side-foot">${source}。缺失或过期 ETA 的在途只做提示，不进入确认曲线。</p></section>`;
  }
  function pmcConfidenceCard(current) {
    const dims=current.confidenceDimensions;
    if(!dims)return '';
    const labels={high:'高',medium:'中',low:'低'};
    const rows=[['需求','demand'],['时间轴','timeline'],['执行','execution']].map(([label,key])=>{
      const item=dims[key]||{level:'low',reasons:[],impact:''};
      return `<div class="pmc-confidence-row"><span>${label}</span><b class="${item.level}">${labels[item.level]||item.level}</b><small>${escapeHtml((item.reasons||[]).slice(0,2).join('；')||'—')}</small></div>`;
    }).join('');
    return `<section class="panel pmc-side-card"><div class="pmc-side-head"><span>置信度</span><span class="pmc-chip">只读</span></div>${rows}</section>`;
  }

  function pmcShipmentSchedulePanel(current) {
    const batches=pmcFundedShipments(current).slice(0,6);
    if(!batches.length)return '';
    const rows=batches.map(batch=>{
      const funded=pmcFunded(batch);
      const carton=Number(batch.cartonQty)>0?Math.floor(funded/Number(batch.cartonQty)):0;
      const remaining=Number(batch.remainingQty||0);
      const purchase=batch.funding==='purchase'&&batch.purchaseReadyDate?`<small>采购 ${escapeHtml(pmcFullDate(batch.purchaseReadyDate))} 到</small>`:'';
      const rest=remaining>0?`<small>剩余 ${fmt(remaining)} 由后续</small>`:'';
      return `<tr><td><strong>第 ${batch.sequence} 批 · ${pmcIsoWeek(batch.dispatchDate)}</strong></td><td>${escapeHtml(pmcFullDate(batch.dispatchDate))}</td><td>${pmcLane(batch.mode)} ${fmt(batch.transitDays)} 天</td><td>${escapeHtml(pmcFullDate(batch.arrivalDate))}</td><td><strong>${batch.phase==='immediate'?'发':'待发'} ${fmt(funded)}</strong>${carton?` · ${fmt(carton)} 箱`:''}${purchase}${rest}</td><td>${fmt(Math.round(Number(batch.projectedAfterArrival)||0))}</td></tr>`;
    }).join('');
    return `<section class="panel pmc-list-panel" id="pmc-shipment-schedule"><div class="pmc-panel-head"><div><span class="eyebrow">PLAN</span><h3>要发多少</h3></div><span class="pmc-count">补到 FBA 目标</span></div><div class="table-wrap"><table><thead><tr><th>批次</th><th>发出</th><th>走法</th><th>到仓</th><th>发货</th><th>到仓后库存</th></tr></thead><tbody>${rows}</tbody></table></div><p class="pmc-chart-note">只显示前 6 批；“待发”是采购齐套或未来周发货，不等于今天可发；剩余量由后续批次承接。</p></section>`;
  }
  function pmcWeeklyPanel(current) {
    const batches=pmcFundedShipments(current);
    if(!batches.length)return `<section class="panel pmc-list-panel" id="pmc-weekly"><div class="pmc-panel-head"><div><span class="eyebrow">WEEKLY</span><h3>按周发货计划</h3></div></div><p class="pmc-empty-line">${Number(current.timeline?.confirmedQty)>0?`没有新增发货批次；已有确认在途 ${fmt(current.timeline.confirmedQty)} 件，见下方到仓日程。`:'测算期内没有建议发货批次。'}</p></section>`;
    const groups=new Map();
    batches.forEach(batch=>{
      const week=pmcIsoWeek(batch.dispatchDate);
      const key=`${week}|${batch.dispatchDate}`;
      if(!groups.has(key))groups.set(key,{week,dispatch:batch.dispatchDate,qty:0,exec:0,cartons:0,lanes:new Set(),arrivals:new Set(),short:0,rescue:false,timingGap:false,purchase:false});
      const group=groups.get(key);
      group.qty+=pmcFunded(batch);
      group.exec+=pmcFunded(batch);
      group.cartons+=Number(batch.cartonQty)>0?Math.floor(pmcFunded(batch)/Number(batch.cartonQty)):0;
      group.lanes.add(batch.mode||'—');
      group.arrivals.add(batch.arrivalDate);
      if(batch.rescue)group.rescue=true;
      if(batch.timingGap)group.timingGap=true;
      if(batch.funding==='purchase')group.purchase=true;
    });
    const rows=[...groups.values()].sort((a,b)=>a.dispatch.localeCompare(b.dispatch));
    const totalExec=rows.reduce((sum,row)=>sum+row.exec,0);
    const table=rows=>`<div class="table-wrap"><table><thead><tr><th>周次</th><th>发出</th><th>渠道</th><th class="pmc-number">发货量</th><th>到仓</th><th>状态</th></tr></thead><tbody>${rows.map(row=>`<tr><td><strong>${row.week}</strong>${row.week===pmcIsoWeek(board.inventory_batch?.as_of)?' · 本周':''}</td><td>${escapeHtml(pmcFullDate(row.dispatch))}</td><td>${[...row.lanes].map(lane=>pmcLane(lane)).join(' ')}</td><td class="pmc-number">${fmt(row.exec)}${row.cartons?`<small> · ${fmt(row.cartons)} 箱</small>`:''}</td><td>${[...row.arrivals].map(date=>`${pmcIsoWeek(date)} · ${escapeHtml(pmcFullDate(date))}`).join(' / ')}</td><td>${row.rescue?'<span class="pmc-warn">救急</span>':row.timingGap?'<span class="pmc-danger">晚到</span>':row.purchase?'采购齐套':'计划'}</td></tr>`).join('')}</tbody></table></div>`;
    const visible=rows.slice(0,8);
    const rest=rows.slice(8);
    return `<section class="panel pmc-list-panel" id="pmc-weekly"><div class="pmc-panel-head"><div><span class="eyebrow">WEEKLY</span><h3>按周发货计划</h3></div><span class="pmc-count">${fmt(rows.length)} 周 · 可执行 ${fmt(totalExec)} 件</span></div>${table(visible)}${rest.length?`<details class="pmc-week-all"><summary>展开其余 ${fmt(rest.length)} 周（至 ${escapeHtml(pmcFullDate(current.calc?.horizonEnd))}）</summary>${table(rest)}</details>`:''}<p class="pmc-chart-note">先显示前 8 周；计划覆盖至 ${escapeHtml(pmcFullDate(current.calc?.horizonEnd))}（${fmt(current.calc?.horizonDays)} 天）。只列已由本地/采购覆盖的计划批次。</p></section>`;
  }
  function pmcArrivalPanel(current) {
    const confirmed=(current.timeline?.events||[]).map(event=>({date:event.etaEnd,dispatch:'',id:event.shipment||event.id||'在途',shipId:event.shipment||event.id||'',qty:event.qty,exec:null,start:event.etaStart,end:event.etaEnd,status:event.status||'在途',planned:false,lane:''}));
    const planned=pmcFundedShipments(current).slice(0,8).map(batch=>({date:batch.arrivalDate,dispatch:batch.dispatchDate,id:`建议第 ${batch.sequence} 批`,shipId:`PLAN-${batch.sequence}`,qty:pmcFunded(batch),exec:pmcFunded(batch),start:batch.dispatchDate,end:batch.arrivalDate,status:`${batch.mode||''} ${batch.transitDays||''} 天`,planned:true,future:batch.phase==='planned',immediate:batch.phase==='immediate',funding:batch.funding,lane:batch.mode}));
    const rows=[...confirmed,...planned].filter(row=>row.date).sort((a,b)=>String(a.date).localeCompare(String(b.date)));
    return `<section class="panel pmc-list-panel" id="pmc-arrival"><div class="pmc-panel-head"><div><span class="eyebrow">ARRIVAL</span><h3>到仓日程</h3></div><span class="pmc-count">${fmt(rows.length)} 条</span></div>${rows.length?`<div class="table-wrap"><table><thead><tr><th>发出</th><th>到仓</th><th>货件 / 批次</th><th class="pmc-number">发货量</th><th>时效 / ETA</th><th>状态</th></tr></thead><tbody>${rows.map(row=>`<tr class="${row.planned?'planned':''} ${state.pmcPin?.kind==='ship'&&state.pmcPin.id===row.shipId?'selected':''}" data-pmc-ship="${escapeHtml(row.shipId)}"><td>${row.planned?`${pmcIsoWeek(row.dispatch)} · ${escapeHtml(pmcFullDate(row.dispatch))}`:'—'}</td><td>${pmcIsoWeek(row.date)} · ${escapeHtml(pmcFullDate(row.date))}</td><td>${escapeHtml(row.id)}</td><td class="pmc-number">${fmt(row.qty)}</td><td>${row.planned?pmcLane(row.lane):`${escapeHtml(pmcFullDate(row.start))} ~ ${escapeHtml(pmcFullDate(row.end))}`}</td><td>${row.planned?(row.immediate?'今日发':row.funding==='purchase'?'采购齐套后':'计划在途'):escapeHtml(row.status)}</td></tr>`).join('')}</tbody></table></div>`:`<p class="pmc-empty-line">没有已确认在途；${fmt(current.timeline?.unknownEtaQty)} 件在途缺 ETA，未计入时间轴。</p>`}</section>`;
  }
  function pmcPurchasePanel(current) {
    const purchases=(current.purchaseBatches||[]).filter(batch=>Number(batch.suggestedQty)>0).slice(0,8);
    const gap=Number(current.calc?.gapFba||0);
    const first=purchases[0];
    return `<section class="panel pmc-list-panel" id="pmc-purchase"><div class="pmc-panel-head"><div><span class="eyebrow">PURCHASE</span><h3>采购台账</h3></div><span class="pmc-count">${first?`首单 ${escapeHtml(pmcFullDate(first.orderDate))}`:'测算期无采购'}</span></div>${purchases.length?`<div class="table-wrap"><table><thead><tr><th>下单</th><th>批次</th><th class="pmc-number">建议采</th><th>齐套</th><th>状态</th></tr></thead><tbody>${purchases.map(batch=>`<tr><td>${pmcIsoWeek(batch.orderDate)} · ${escapeHtml(pmcFullDate(batch.orderDate))}</td><td>第 ${batch.batchSequence??batch.sequence} 批${batch.dispatchDate?`<small> · ${pmcIsoWeek(batch.dispatchDate)} ${escapeHtml(pmcFullDate(batch.dispatchDate))} 发</small>`:''}</td><td class="pmc-number">${fmt(batch.suggestedQty)}${batch.cartons?`<small> · ${fmt(batch.cartons)} 箱</small>`:''}</td><td>${pmcIsoWeek(batch.expectedReadyDate)} · ${escapeHtml(pmcFullDate(batch.expectedReadyDate))}</td><td>${batch.late?'<span class="pmc-danger">已晚于目标发货日</span>':'计划内'}</td></tr>`).join('')}</tbody></table></div>`:`<p class="pmc-empty-line">${gap>0?'有缺口，但当前没有可执行采购批次：采购已错过目标发货日，或源头库存不足。':'测算期内没有需要采购的批次。'}</p>`}<p class="pmc-chart-note">保守口径：本地、海外和采购未结只作参考，不抵扣建议采购量；不自动生成采购单。</p></section>`;
  }
  function pmcEvidencePanel(product,current) {
    const gaps=[...new Set([...(current.dataGaps||[]),...(current.basis?.dataGaps||[])])];
    const chain=(current.evidenceChain||[]).slice(0,10);
    const cross=current.lingxingCrosscheck||{};
    const suggestion=current.lingxingSuggestion||{};
    return `<section class="panel pmc-evidence-panel"><details class="pmc-disclosure"><summary>依据与口径：库存分层 / ETA / 置信度 / 来源</summary><div class="pmc-evidence-cards">${pmcActionCard(current)}${pmcLayerCard(current)}${pmcEtaCard(current)}${pmcConfidenceCard(current)}</div><div class="pmc-evidence-chain">${chain.map((step,index)=>`<div><span>${String(index+1).padStart(2,'0')}</span><div><strong>${escapeHtml(step.stage||'')}</strong><p>${escapeHtml(step.fact||'')}</p><small>${escapeHtml(step.source||'')}</small></div></div>`).join('')}</div><div class="pmc-evidence-grid"><div><h4>来源缺口</h4><ul>${gaps.length?gaps.map(gap=>`<li>${escapeHtml(gap)}</li>`).join(''):'<li>关键字段完整。</li>'}</ul></div><div><h4>领星对照</h4><dl>${cross.officialDaily?`<dt>领星日均</dt><dd>${fmt(cross.officialDaily)} 件</dd><dt>本工具日均</dt><dd>${fmt(current.forecast?.daily)} 件</dd><dt>日均偏差</dt><dd>${fmt(cross.dailyVariancePct)}%</dd><dt>领星断货日</dt><dd>${escapeHtml(cross.lingxingStockoutDate||suggestion.stockoutDate||'—')}</dd><dt>本工具断货日</dt><dd>${escapeHtml(current.timeline?.stockoutDate||'测算期内无')}</dd>`:'<dt>领星原生建议</dt><dd>该店铺-ASIN 无记录</dd>'}</dl></div></div><p class="pmc-source-note">库存 ${escapeHtml(board.inventory_batch?.as_of||'')}；广告/Listing ${escapeHtml(board.as_of_date||'')}。库存结论不与广告/Listing 结论做同日因果合并。</p></details></section>`;
  }

  function inventoryContent(product) {
    const source=product.inventory_pmc;
    if(!source)return `<section class="panel pmc-missing"><h3>此 ASIN 未匹配本次库存批次</h3><p>库存 ${escapeHtml(board.inventory_batch?.as_of||'—')} 与店铺 + 子 ASIN 精确匹配；不能拿旧库存或别店同 ASIN 补位。广告/Listing 仍可查看各自原批次。</p></section>`;
    if(state.pmcPinProduct!==product.key){state.pmcPin=null;state.pmcPinProduct=product.key}
    let choice=state.pmcChoice[product.key]||'base';
    if(!['base','custom'].includes(choice)&&!String(choice).startsWith('lib:'))choice='base';
    if(choice==='custom'&&!state.pmcCustom[product.key])choice='base';
    if(String(choice).startsWith('lib:')){const saved=pmcLibraryScenario(String(choice).slice(4));if(!saved||!pmcScenarioAllowed(saved,product))choice='base';}
    if(choice==='default'&&!pmcDefaultScenario(source))choice='base';
    const params=pmcScenarioParams(product,source,choice);
    // Current plan uses the scenario parameters. The comparison baseline is the same
    // demand scenario with no new shipments, so the two lines are directly comparable.
    const current=pmcAnalyze(product,params)||source;
    // The engine's own timeline is the no-action projection (confirmed inbound only).
    // Reuse it for the "不行动" status instead of running a second analysis pass.
    const base=current;
    state.pmcView={base,current,choice};
    return `<div class="pmc-backbar">${state.pmcFromQueue?'<button type="button" class="pmc-quiet-button" data-pmc-back>← 返回库存待办</button>':'<span class="pmc-back-hint">单品库存 · 决策驾驶舱</span>'}<span class="pmc-source-date">库存 ${escapeHtml(board.inventory_batch?.as_of||'')} · 广告/Listing ${escapeHtml(board.as_of_date||'')}</span></div>${pmcHero(product,source,base,current,choice)}${pmcScenarioBar(product,source,current,choice,params)}${pmcKpis(base,current)}${pmcQualityHtml(product,source)}<div class="pmc-cockpit"><div class="pmc-cockpit-main">${pmcDemandPanel(current)}${pmcTimelinePanel(base,current,choice)}</div></div>${pmcShipmentSchedulePanel(current)}${pmcWeeklyPanel(current)}${pmcArrivalPanel(current)}${pmcPurchasePanel(current)}${pmcEvidencePanel(product,current)}${pmcModalHtml(product,source)}`;
  }

  function pmcSyncSeasonMode() {
    const root=document.getElementById('pmc-editor');
    if(!root||typeof root.querySelectorAll!=='function')return;
    const hasSeason=root.querySelectorAll('.pmc-season-row').length>0;
    const demand=root.querySelector('[data-pmc-param="demandPct"]');
    if(demand){demand.disabled=hasSeason;demand.closest('.pmc-field')?.classList.toggle('disabled',hasSeason)}
  }
  function pmcReadEditor() {
    const root=document.getElementById('pmc-editor');
    if(!root)throw new Error('情景编辑器未打开');
    const raw=name=>root.querySelector(`[data-pmc-param="${name}"]`)?.value?.trim()??'';
    const number=(name,min,max,required=false)=>{
      const text=raw(name);
      if(!text){if(required)throw new Error(`请填写 ${name}`);return null}
      const value=Number(text);
      if(!Number.isFinite(value)||value<min||value>max)throw new Error(`${name} 超出 ${min}..${max}`);
      return value;
    };
    const seasonal=[...root.querySelectorAll('.pmc-season-row')].map(row=>{
      const from=row.querySelector('.pmc-season-from')?.value||'';
      const to=row.querySelector('.pmc-season-to')?.value||'';
      const multiplier=Number(row.querySelector('.pmc-season-mult')?.value||0)/100;
      if(!from&&!to&&!multiplier)return null;
      if(!from||!to)throw new Error('季节区间需要完整开始/结束日期');
      if(from>to)throw new Error('季节区间开始日期晚于结束日期');
      if(!(multiplier>=.5&&multiplier<=10))throw new Error('季节倍数需在 50%..1000%');
      return {from,to,multiplier};
    }).filter(Boolean);
    const params={};
    if(seasonal.length)params.seasonal=seasonal;
    else params.demandMultiplier=number('demandPct',30,1000,true)/100;
    params.transitDays=number('transitDays',10,120,true);
    params.expressDays=number('expressDays',5,90,true);
    params.airTransitDays=number('airTransitDays',0,30)??0;
    params.purchaseLeadDays=number('purchaseLeadDays',0,180,true);
    params.safetyDays=number('safetyDays',0,60,true);
    params.cartonQty=number('cartonQty',0,10000)??0;
    params.moq=number('moq',0,100000)??0;
    params.minShipQty=number('minShipQty',0,100000)??0;
    const local=raw('localAvailable');
    if(local!=='')params.localAvailable=number('localAvailable',0,1000000,true);
    return params;
  }
  function pmcRefresh(product) {
    state.pmcPin=null;
    const scroll=window.scrollY;
    const active=document.activeElement;
    const field=active?.dataset?.pmcParam;
    const selection=field&&active.selectionStart!=null?active.selectionStart:null;
    const content=document.getElementById('domain-content');
    if(!content)return;
    content.innerHTML=inventoryContent(product);
    bindContent();
    pmcHidePin();
    if(field){
      const next=content.querySelector(`[data-pmc-param="${field}"]`);
      if(next){next.focus();if(selection!=null)next.setSelectionRange(selection,selection)}
    }
    window.scrollTo(0,scroll);
  }
  function pmcDownload(name,text,type) {
    const blob=new Blob([text],{type:type||'application/json'});
    const url=URL.createObjectURL(blob);
    const anchor=document.createElement('a');
    anchor.href=url;anchor.download=name;
    document.body.appendChild(anchor);anchor.click();anchor.remove();
    setTimeout(()=>URL.revokeObjectURL(url),1200);
  }
  function pmcExportScenario() {
    const product=selectedProduct();
    if(!product)return;
    let params=pmcScenarioParams(product,product.inventory_pmc,state.pmcChoice[product.key]||'base');
    try{if(state.pmcEditor[product.key])params=pmcReadEditor()}catch(error){state.pmcFeedback[product.key]=error.message;pmcRefresh(product);return}
    const payload={version:1,scenarios:[{id:`pmc-${product.asin}-${Date.now()}`,name:'自定义方案',store:product.inventory_pmc.store,asin:product.asin,isDefault:true,params}]};
    pmcDownload(`pmc-scenario-${product.asin}.json`,JSON.stringify(payload,null,2),'application/json');
    state.pmcFeedback[product.key]='方案已导出。合并到技能情景库后，下轮重跑生效。';
    pmcRefresh(product);
  }
  function pmcExportCsv() {
    const all=pmcSearchProducts(pmcActiveProducts());
    const tab=PMC_TABS[state.pmcTab]?state.pmcTab:'ship';
    const items=pmcQueueItems(all,tab);
    const cell=value=>`"${String(value??'').replaceAll('"','""')}"`;
    let header;let body;
    if(tab==='ship'){
      header=['店铺','ASIN','品名','分级','断货区间','风险金额','可执行发货','走法','到仓','到仓后库存'];
      body=items.map(product=>{const pmc=product.inventory_pmc,ship=pmcFirstShip(pmc);return [product.shop,product.asin,product.name,pmcTier(product),pmcStockoutText(pmc),Math.round(Number(pmc.calc?.lossAmount||0)),Math.round(pmcFunded(ship)),ship?.mode||'',ship?.arrivalDate||'',Math.round(Number(ship?.projectedAfterArrival||0))]});
    }else if(tab==='buy'){
      header=['店铺','ASIN','品名','分级','建议采','金额','首单下单','首单到货','本地参考'];
      body=items.map(product=>{const pmc=product.inventory_pmc,buy=pmcFirstBuy(pmc);return [product.shop,product.asin,product.name,pmcTier(product),Math.round(Number(buy?.suggestedQty||0)),Math.round(Number(buy?.suggestedQty||0)*Number(pmc.basis?.price||0)),buy?.orderDate||'',buy?.expectedReadyDate||'',Math.round(pmcLocalReference(pmc))]});
    }else if(tab==='risk'){
      header=['店铺','ASIN','品名','分级','断货日','断货天数','风险金额','下一批供应'];
      body=items.map(product=>{const pmc=product.inventory_pmc,ship=pmcFirstShip(pmc);return [product.shop,product.asin,product.name,pmcTier(product),pmc.timeline?.stockoutDate||'',Math.round(Number(pmc.timeline?.stockoutDays||0)),Math.round(Number(pmc.calc?.lossAmount||0)),ship?`${ship.arrivalDate} ${pmcFunded(ship)}`:(pmc.timeline?.nextEta||'')]});
    }else{
      header=['店铺','ASIN','品名','分级','>90天件数','占用金额'];
      body=items.map(product=>{const pmc=product.inventory_pmc;return [product.shop,product.asin,product.name,pmcTier(product),Math.round(Number(pmc.calc?.agedQty||0)),Math.round(Number(pmc.calc?.agedValue||0))]});
    }
    const csv=['\uFEFF'+[header,...body].map(row=>row.map(cell).join(',')).join('\r\n')];
    pmcDownload(`PMC_${tab}_${board.inventory_batch?.as_of||''}.csv`,csv.join(''),'text/csv;charset=utf-8');
  }
  function bindPmc() {
    const product=selectedProduct();

    document.querySelector('[data-pmc-open-library]')?.addEventListener('click',()=>{
      if(!product)return;state.pmcModal='library';pmcRefresh(product);
    });
    document.querySelector('[data-pmc-save]')?.addEventListener('click',()=>{
      if(!product)return;
      try{pmcOpenSave(product,product.inventory_pmc,pmcReadEditor())}catch(error){state.pmcFeedback[product.key]=error.message;pmcRefresh(product)}
    });
    document.querySelectorAll('[data-pmc-modal-close]').forEach(el=>el.addEventListener('click',()=>{state.pmcModal=null;if(product)pmcRefresh(product)}));
    document.querySelectorAll('[data-pmc-scope]').forEach(el=>el.addEventListener('click',()=>{
      if(!state.pmcDraft)return;state.pmcDraft.name=document.querySelector('[data-pmc-save-name]')?.value||state.pmcDraft.name;
      state.pmcDraft.scope=el.dataset.pmcScope;if(product)pmcRefresh(product);
    }));
    document.querySelector('[data-pmc-save-name]')?.addEventListener('input',event=>{if(state.pmcDraft)state.pmcDraft.name=event.target.value});
    document.querySelector('[data-pmc-save-search]')?.addEventListener('input',event=>{
      if(state.pmcDraft)state.pmcDraft.search=event.target.value;
      const query=event.target.value.trim().toLowerCase();
      document.querySelectorAll('[data-pmc-asin-row]').forEach(row=>{row.hidden=Boolean(query)&&!String(row.dataset.search||'').includes(query)});
    });
    document.querySelector('[data-pmc-save-confirm]')?.addEventListener('click',()=>{if(product)pmcCreateScenario(product)});
    document.querySelectorAll('[data-pmc-lib-apply]').forEach(el=>el.addEventListener('click',()=>{
      if(!product)return;const scenario=pmcLibraryScenario(el.dataset.pmcLibApply);
      if(!scenario||!pmcScenarioAllowed(scenario,product))return;
      state.pmcChoice[product.key]=`lib:${scenario.id}`;state.pmcModal=null;state.pmcEditor[product.key]=false;
      state.pmcFeedback[product.key]=`已应用方案「${scenario.name}」。`;pmcRefresh(product);
    }));
    document.querySelectorAll('[data-pmc-lib-delete]').forEach(el=>el.addEventListener('click',()=>{
      const library=pmcLibraryData();library.scenarios=library.scenarios.filter(item=>String(item.id)!==String(el.dataset.pmcLibDelete));pmcLibrarySave();
      if(product){state.pmcFeedback[product.key]='方案已从本地方案库删除。';pmcRefresh(product)}
    }));
    document.querySelector('[data-pmc-lib-export]')?.addEventListener('click',pmcExportLibrary);
    document.querySelectorAll('[data-pmc-tab]').forEach(el=>el.addEventListener('click',()=>{state.pmcTab=el.dataset.pmcTab;render()}));
    document.querySelectorAll('[data-pmc-tier]').forEach(el=>el.addEventListener('click',()=>{state.pmcTier=el.dataset.pmcTier;render()}));
    document.querySelector('[data-pmc-export-csv]')?.addEventListener('click',pmcExportCsv);
    document.querySelector('[data-pmc-search]')?.addEventListener('input',event=>{
      const value=event.target.value;state.pmcQuery=value;render();
      const next=document.querySelector('[data-pmc-search]');next?.focus();next?.setSelectionRange(value.length,value.length);
    });
    document.querySelectorAll('[data-pmc-open]').forEach(row=>{
      const open=()=>{const key=row.dataset.pmcOpen;if(!key)return;state.selected=key;state.view='product';state.navOrigin='inventory-queue';state.domain='inventory';state.pmcFromQueue=true;state.decisionDrawer=null;render();window.scrollTo?.(0,0)};
      row.addEventListener('click',open);
      row.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();open()}});
    });
    document.querySelector('[data-pmc-back]')?.addEventListener('click',()=>{state.view='inventory-queue';state.pmcFromQueue=false;render()});
    document.querySelector('[data-pmc-scenario-select]')?.addEventListener('change',event=>{
      if(!product)return;state.pmcChoice[product.key]=event.target.value;state.pmcFeedback[product.key]='';state.pmcEditor[product.key]=false;pmcRefresh(product);
    });
    document.querySelector('[data-pmc-edit]')?.addEventListener('click',()=>{
      if(!product)return;state.pmcEditor[product.key]=!state.pmcEditor[product.key];pmcRefresh(product);
    });
    document.querySelector('[data-pmc-reset]')?.addEventListener('click',()=>{
      if(!product)return;state.pmcChoice[product.key]='base';delete state.pmcCustom[product.key];state.pmcFeedback[product.key]='已恢复基准。';pmcRefresh(product);
    });
    document.querySelectorAll('[data-pmc-zoom]').forEach(el=>el.addEventListener('click',()=>{
      const value=el.dataset.pmcZoom;
      pmcSetRange(value==='reset'?90:state.pmcRange+Number(value||0));
    }));
    document.querySelector('[data-pmc-apply]')?.addEventListener('click',()=>{
      if(!product)return;
      try{
        const params=pmcReadEditor();
        state.pmcCustom[product.key]=params;state.pmcChoice[product.key]='custom';state.pmcEditor[product.key]=false;state.pmcFeedback[product.key]='已应用试算；图表、发货、采购和目标一起重算。';
        pmcRefresh(product);
      }catch(error){state.pmcFeedback[product.key]=error.message;pmcRefresh(product)}
    });
    document.querySelector('[data-pmc-export]')?.addEventListener('click',pmcExportScenario);
    pmcSyncSeasonMode();
  }

  function listingCvrSummary(product) {
    const weeks=(product.weeks||[]).filter(w=>w.quality==='measured'&&w.sessions_total!=null&&w.orders!=null);
    if(weeks.length<4)return {state:'insufficient'};
    const recent=weeks.at(-1),baseline=weeks.slice(-4,-1);
    const sessions=Number(recent.sessions_total)||0,orders=Number(recent.orders)||0;
    const priorSessions=baseline.reduce((n,w)=>n+(Number(w.sessions_total)||0),0);
    const priorOrders=baseline.reduce((n,w)=>n+(Number(w.orders)||0),0);
    if(sessions<50||priorSessions<150||priorOrders<10)return {state:'low_sample',week:recent.label,sessions,orders,current:sessions?orders/sessions:null,baseline:priorSessions?priorOrders/priorSessions:null};
    const current=orders/sessions,prior=priorOrders/priorSessions;
    const weeklyTraffic=priorSessions/3;
    return {state:'measured',week:recent.label,current,baseline:prior,sessions,orders,traffic:weeklyTraffic?sessions/weeklyTraffic-1:null};
  }

  function listingCheck(state,label,value,detail,source,action) {
    return {state,label,value,detail,source,action};
  }

  function listingChecks(product) {
    const content=product.content||{};
    const external=product.listing_external||{};
    const features=Array.isArray(external.features)?external.features:(Array.isArray(content.bullets)?content.bullets:null);
    const title=content.title||external.title;
    const mainImage=external.image_url||content.main_image_url;
    const rating=product.rating??external.rating;
    const reviews=product.reviews??external.ratings;
    const returns=product.return_analysis;
    const checks=[];
    checks.push(listingCheck(title==null?'unverified':String(title).trim()?'pass':'fail','标题',String(title||'').slice(0,42),String(title||'').trim()?'已取得标题':'标题为空，需补标题',content.source==='erp_listing'?'领星':'来源','补全标题后复核前台展示'));
    checks.push(listingCheck(mainImage==null?'unverified':/^https:\/\//.test(mainImage)?'pass':'fail','主图',mainImage?'已取得':'',mainImage?'已取得主图 URL':'主图为空或 URL 无效',external.image_url?'卖家精灵':'领星','补全主图并检查前台展示'));
    checks.push(listingCheck(features==null?'unverified':features.length===0?'fail':features.length<5?'warn':'pass','五点',features==null?'未核验':`${fmt(features.length)}/5 条`,features==null?'卖家精灵未返回五点，需补查后才能判定':features.length===0?'五点为空，需补齐':features.length<5?'五点不足 5 条，建议补齐':`已取得 ${fmt(features.length)} 条五点`,external.features?'卖家精灵':'未核验','补齐 5 条五点后复核页面承诺'));
    const lowStars=Array.isArray(external.reviews)?external.reviews.length:0;
    let ratingState='unverified',ratingDetail='评分未返回';
    if(rating!=null){
      if(reviews!=null&&Number(reviews)>=20&&Number(rating)<3.8){ratingState='warn';ratingDetail=`评分 ${fmt(rating,1)}，低于 3.8；需结合低星评论核对`;}
      else if(reviews!=null&&Number(reviews)<20){ratingState='pass';ratingDetail=`评分 ${fmt(rating,1)} · 评论 ${fmt(reviews)} 条，样本少`;}
      else {ratingState='pass';ratingDetail=`评分 ${fmt(rating,1)} · ${fmt(reviews)} 条评论`;}
      if(lowStars)ratingDetail+=` · 低星样本 ${fmt(lowStars)} 条`;
    }
    checks.push(listingCheck(ratingState,'评分',rating==null?'未核验':`${fmt(rating,1)} ★`,ratingDetail,'领星','核对低星评论与退货原因'));
    let returnState='unverified',returnDetail='本轮没有正式退货分析';
    if(returns&&returns.rate!=null){
      const rate=Number(returns.rate),prior=returns.prior_rate==null?null:Number(returns.prior_rate),count=Number(returns.returns||0);
      const jumped=prior!=null&&rate-prior>=.02&&rate>=Math.max(prior*1.5,.05);
      if(count>=5&&(jumped||prior==null&&rate>=.1)){returnState='warn';returnDetail=`近30天 ${pct(rate)} · 上期 ${prior==null?'—':pct(prior)} · ${fmt(count)} 件`;}
      else {returnState='pass';returnDetail=`近30天 ${pct(rate)} · 上期 ${prior==null?'—':pct(prior)} · ${fmt(count)} 件`;}
    }
    checks.push(listingCheck(returnState,'退货',returns&&returns.rate!=null?pct(returns.rate):'未核验',returnDetail,'领星','核对退货原因与页面承诺'));
    return {checks,external,content};
  }

  function listingCheckMark(state) {
    return state==='pass'?'✓':state==='warn'?'!':state==='observe'?'○':'?';
  }

  function listingReviewCard(product) {
    const external=product.listing_external||{};
    const reviews=Array.isArray(external.reviews)?external.reviews:[];
    const low=reviews.filter(row=>Number(row.star)<=3);
    const themes=[
      {name:'包装/破损',pattern:/bent|broken|damage|dented|arrived|packag|包装|破损|压|碎/i,suggestion:'先核对包装与到货状态，不先改主图'},
      {name:'尺寸/适配',pattern:/size|fit|small|large|short|long|尺寸|大小|太小|太大|不适/i,suggestion:'补尺寸表/对比图，核对页面尺寸承诺'},
      {name:'质量/材质',pattern:/quality|material|cheap|flimsy|sturdy|质量|材质|做工/i,suggestion:'转产品或供应链核对，不能只改文案'},
      {name:'颜色/变体',pattern:/color|colour|different|wrong item|颜色|色差|变体|发错/i,suggestion:'核对父子变体图、标题和发货 SKU'},
      {name:'描述不符',pattern:/description|not as|expect|misleading|描述|不符|预期/i,suggestion:'改五点/图片/A+ 的承诺，避免夸大'},
      {name:'物流/客服',pattern:/shipping|delivery|late|service|物流|配送|客服|到货/i,suggestion:'转履约/客服处理，不是 Listing 页面问题'}
    ];
    const grouped=new Map();
    for(const row of low){
      const text=`${row.title||''} ${row.content||''}`;
      const theme=themes.find(item=>item.pattern.test(text))||{name:'其他',suggestion:'逐条核对评论原文'};
      if(!grouped.has(theme.name))grouped.set(theme.name,{...theme,items:[]});
      grouped.get(theme.name).items.push(row);
    }
    const groups=[...grouped.values()].sort((a,b)=>b.items.length-a.items.length).slice(0,3);
    const sample=low.length;
    return `<section class="panel listing-review-panel"><div class="panel-title"><div><span class="listing-kicker">VOICE OF CUSTOMER</span><h3>差评与建议</h3><p>评分、评论和本次低星样本放在一起。</p></div><span class="listing-review-count">低星样本 ${fmt(sample)} 条</span></div>
      <div class="listing-review-summary"><span>评分 <b>${fmt(product.rating,1)} ★</b></span><span>评论 <b>${fmt(product.reviews)}</b></span><span>退货 <b>${product.return_analysis?.rate!=null?pct(product.return_analysis.rate):'未核验'}</b></span><span>${external.source==='sellersprite_mcp'?`补查于 ${escapeHtml((external.collected_at||'').slice(0,10))}`:'卖家精灵评论未补查'}</span></div>
      ${groups.length?`<div class="listing-review-themes">${groups.map(g=>`<article class="listing-review-theme"><div><strong>${escapeHtml(g.name)}</strong><em>${fmt(g.items.length)} 条</em></div>${g.items.slice(0,2).map(item=>`<blockquote>${escapeHtml(item.title||item.content||'无标题')}${item.star?`<small>${fmt(item.star)}★</small>`:''}</blockquote>`).join('')}<p>建议：${escapeHtml(g.suggestion)}</p></article>`).join('')}</div>`:`<p class="listing-review-empty">${external.reviews?'本次返回中没有 1–3 星样本':'卖家精灵未返回评论样本'}</p>`}
      <p class="listing-method">评论主题按本次返回的低星样本归纳；样本量见右上角。</p></section>`;
  }

  function listingTrafficCard(product,cvr) {
    const traffic=product.listing_insights?.traffic;
    const natural=Number(traffic?.natural_ratio)||0,ad=Number(traffic?.ad_ratio)||0;
    const sp=Number(traffic?.sp_ratio)||0,rec=Number(traffic?.recommend_ratio)||0,sbv=Number(traffic?.sbv_ratio)||0;
    const seg=(ratio)=>Math.max(0,Math.min(100,ratio*100));
    const segments=traffic?[
      {label:'自然',pct:seg(natural),cls:'natural'},
      {label:'SP',pct:seg(sp*ad),cls:'sp'},
      {label:'SP 推荐',pct:seg(rec*ad),cls:'rec'},
      {label:'SBV',pct:seg(sbv*ad),cls:'sbv'}
    ]:[];
    const cvrText=cvr.state==='measured'?pct(cvr.current):cvr.state==='low_sample'?'样本不足':'周数据不足';
    const baseline=cvr.state==='measured'?pct(cvr.baseline):'—';
    const trafficText=cvr.state==='measured'&&cvr.traffic!=null?`${cvr.traffic>=0?'+':''}${pct(cvr.traffic)}`:'—';
    const sources=Array.isArray(traffic?.recommend_sources)?traffic.recommend_sources.slice(0,3):[];
    return `<section class="panel listing-traffic-panel"><div class="panel-title"><div><span class="listing-kicker">CONVERSION & TRAFFIC</span><h3>转化与流量</h3><p>CVR 来自领星订单/总点击；流量构成来自 SIF 流量分，两者不混算。</p></div><span class="listing-source-pill">${traffic?`SIF · ${escapeHtml(String(traffic.data_notice||'').replace(/^Data updated through /,'数据截至 ').replace(/ \(refreshes daily, 1-day delay\)$/,''))}`:'SIF 未接入'}</span></div>
      <div class="listing-traffic-grid">
        <div class="listing-cvr-block"><div class="listing-cvr-big"><strong>${escapeHtml(cvrText)}</strong><small>总 CVR</small></div><div class="listing-cvr-compare"><span>前三周 ${baseline}</span><span>点击 ${trafficText}</span><span>价格 ${product.price==null?'—':`${escapeHtml(product.currency||'')}${fmt(product.price,2)}`}</span><span>FBA ${fmt(product.stock?.sellable)}</span></div><div class="listing-cvr-bars">${(product.weeks||[]).slice(-8).map(w=>{const measured=w.quality==='measured'&&w.sessions_total>0&&w.orders!=null;const v=measured?w.orders/w.sessions_total:0;return `<i class="${measured?'':'missing'}" style="height:${Math.max(3,Math.min(100,v*600))}%" data-label="${escapeHtml(w.label||'')} ${measured?pct(v):'缺口'}"></i>`}).join('')}</div><div class="listing-cvr-axis"><span>近 8 周</span><button type="button" class="listing-link" data-listing-weekly>完整周趋势 ↗</button></div></div>
        <div class="listing-traffic-block">${traffic?`<div class="listing-traffic-head"><strong>SIF 流量分构成</strong><span>近 ${fmt(traffic.days)} 天</span></div><div class="listing-traffic-bar">${segments.map(s=>`<i class="${s.cls}" style="width:${s.pct.toFixed(2)}%"></i>`).join('')}</div><div class="listing-traffic-legend">${segments.map(s=>`<span><i class="${s.cls}"></i>${s.label} <b>${s.pct.toFixed(1)}%</b></span>`).join('')}</div><div class="listing-traffic-sources"><small>推荐流量来源</small>${sources.length?sources.map(s=>`<span>${escapeHtml(s.name)} <b>${pct(s.ratio)}</b></span>`).join(''):'<span>未返回</span>'}</div>`:`<div class="listing-traffic-empty">SIF 流量结构未接入；CVR 仍可用。</div>`}</div>
      </div></section>`;
  }

  function listingContent(product) {
    const {checks,external,content}=listingChecks(product);
    const total=checks.length,passed=checks.filter(c=>c.state==='pass').length,warned=checks.filter(c=>['warn','fail'].includes(c.state)).length,unknown=checks.filter(c=>c.state==='unverified').length;
    const overall=warned?'warn':unknown?'unverified':passed===total?'pass':'warn';
    const badge=overall==='pass'?`巡检通过 · ${passed}/${total}`:overall==='unverified'?`${passed}/${total} 通过 · ${unknown} 未核验`:`${passed}/${total} 通过 · ${warned} 项待看`;
    const cvr=listingCvrSummary(product);
    const source=external.source==='sellersprite_mcp'?`领星 + 卖家精灵 · ${escapeHtml(external.collected_at||'')}`:'领星商品资料';
    return `<section class="panel listing-health-panel"><div class="panel-title"><div><span class="listing-kicker">LISTING · 巡检</span><h3>Listing 健康检查</h3><p>五项都可点击；通过项收起，未核验和异常项展开证据。</p></div><div class="listing-score ${overall}" style="--score:${Math.round(passed/total*100)}"><strong>${passed}/${total}</strong><small>${overall==='pass'?'通过':overall==='unverified'?'未核验':'待看'}</small></div></div>
      <div class="listing-health-strip"><span class="listing-health-badge ${overall}">${overall==='pass'?'✓':overall==='unverified'?'?':'!'} ${escapeHtml(badge)}</span><span class="listing-health-source">${source}</span></div>
      <div class="listing-check-grid">${checks.map(c=>`<details class="listing-check ${c.state}"><summary><div><small>${escapeHtml(c.label)}</small><strong>${escapeHtml(c.value||'—')}</strong></div><span>${listingCheckMark(c.state)}</span></summary><div class="listing-check-body"><p>${escapeHtml(c.detail)}</p><small>来源：${escapeHtml(c.source)}</small>${c.action?`<p class="listing-action">下一步：${escapeHtml(c.action)}</p>`:''}</div></details>`).join('')}</div>
      <p class="listing-method">判定口径：标题/主图领星优先，SellerSprite 子 ASIN 图补充；五点由卖家精灵补查；退货来自领星近 30 天退货分析；CVR 不参与通过/不通过评分；图片组/A+ 未取得时不纳入评分。</p>${content.title?`<details class="listing-snapshot"><summary>查看标题与主图快照</summary><div class="listing-snapshot-body">${/^https:\/\//.test(content.main_image_url||'')?`<img src="${escapeHtml(content.main_image_url)}" alt="已取得的主图快照" loading="lazy">`:''}<div><small>领星商品资料 · ${escapeHtml(board.as_of_date||'')}</small><p>${escapeHtml(content.title)}</p><small>仅核对来源字段，不能据此确认副图、A+ 或前台实际展示。</small></div></div></details>`:''}
    </section>${listingTrafficCard(product,cvr)}${listingReviewCard(product)}${weeklyDisclosure(product)}`;
  }

  function metricText(key,value) {
    if(value==null||!Number.isFinite(Number(value)))return '—';
    const meta=metricMeta[key]||{};
    if(meta.format==='pct')return pct(Number(value));
    if(meta.format==='money')return fmt(Number(value),2);
    if(meta.format==='int')return fmt(Number(value));
    return fmt(Number(value),2);
  }

  function weeklyChartPanel(product) {
    const selected=[...state.metrics].filter(key=>metricMeta[key]);
    return `<section class="panel"><div class="panel-title"><div><h3>完整周趋势 · 自选指标</h3><p>8 个完整 ISO 周；默认销量 + 总转化率 + 广告转化率 + 退货率。数量/金额只选一个主指标，百分比可多选。</p></div><div class="weekly-head-actions"><span class="pill">${product.weeks?.length||0} 周</span><button type="button" class="listing-link" data-metric-reset>重置</button></div></div>
      <div class="chart-controls">${Object.entries(metricLabels).map(([key,label])=>`<button type="button" data-metric="${key}" class="${state.metrics.has(key)?'active':''}" aria-pressed="${state.metrics.has(key)}">${label}</button>`).join('')}</div>
      <div class="chart-box" id="weekly-chart">${trendSvg(product.weeks||[])}</div>
      <div class="weekly-legend">${selected.map(key=>{const last=[...(product.weeks||[])].reverse().find(row=>row[key]!=null);return `<span><i style="background:${metricMeta[key].color}"></i>${metricLabels[key]}${last?` <b>${escapeHtml(metricText(key,last[key]))}</b>`:''}</span>`}).join('')}</div>
      <p class="chart-caption">周口径：领星商品表现。柱为销量，折线为百分比；坐标轴左数量/金额，右百分比。悬停读真实值；无报表行断线，不自动视为 0。</p>
      <details class="disclosure"><summary>展开已选指标的全部 8 周数据与来源</summary><div class="table-wrap"><table><thead><tr><th>ISO 周</th>${selected.map(key=>`<th>${metricLabels[key]}</th>`).join('')}<th>来源状态</th></tr></thead><tbody>${(product.weeks||[]).map(w=>`<tr><td>${escapeHtml(w.label)}</td>${selected.map(key=>`<td>${escapeHtml(metricText(key,w[key]))}</td>`).join('')}<td>${w.quality==='measured'?'已取得':'缺口'}</td></tr>`).join('')}</tbody></table></div></details></section>`;
  }

  function weeklyDisclosure(product){
    return `<details class="disclosure aux-chart" data-weekly ${state.weeklyOpen?'open':''}><summary>完整周产品指标 · 需要时展开自选图表</summary>${weeklyChartPanel(product)}</details>`;
  }

  function trendSvg(weeks) {
    if(!weeks.length)return '<div class="empty">没有完整周数据</div>';
    const selected=[...state.metrics].filter(key=>metricMeta[key]);
    if(!selected.length)return '<div class="empty">请选择至少一个指标</div>';
    const valueKeys=selected.filter(key=>metricMeta[key].axis==='value');
    const pctKeys=selected.filter(key=>metricMeta[key].axis==='percent');
    const valueOf=(week,key)=>week[key]==null||!Number.isFinite(Number(week[key]))?null:Number(week[key]);
    const values=selected.flatMap(key=>weeks.map(week=>valueOf(week,key)).filter(value=>value!=null));
    const leftMax=valueKeys.length?Math.max(1,...weeks.flatMap(week=>valueKeys.map(key=>valueOf(week,key)).filter(value=>value!=null))):1;
    const rightMax=pctKeys.length?Math.max(.01,...weeks.flatMap(week=>pctKeys.map(key=>valueOf(week,key)).filter(value=>value!=null))):.01;
    const niceMax=value=>{const v=Math.max(value,0.0001);const power=10**Math.floor(Math.log10(v));return Math.ceil(v/power*2)/2*power};
    const leftCeiling=niceMax(leftMax),rightCeiling=niceMax(rightMax*1.15);
    const width=960,height=290,left=60,right=pctKeys.length?58:20,top=24,bottom=34;
    const plotW=width-left-right,plotH=height-top-bottom;
    const x=i=>left+(weeks.length===1?plotW/2:i*plotW/(weeks.length-1));
    const yLeft=v=>top+plotH-v/leftCeiling*plotH;
    const yRight=v=>top+plotH-v/rightCeiling*plotH;
    const grids=[0,.5,1].map(part=>{
      const y=top+plotH*(1-part);
      return `<line x1="${left}" x2="${width-right}" y1="${y}" y2="${y}" stroke="#2b4650" stroke-dasharray="3 5"/>`;
    }).join('');
    const leftLabels=valueKeys.length?[0,.5,1].map(part=>`<text x="${left-8}" y="${top+plotH*(1-part)+3}" text-anchor="end" fill="#8db3b5" font-size="10">${fmt(leftCeiling*part)}</text>`).join(''):'';
    const rightLabels=pctKeys.length?[0,.5,1].map(part=>`<text x="${width-right+8}" y="${top+plotH*(1-part)+3}" fill="#c9a9cf" font-size="10">${pct(rightCeiling*part)}</text>`).join(''):'';
    const axisLabels=`${valueKeys.length?`<text x="${left}" y="13" fill="#8db3b5" font-size="9">数量 / 金额</text>`:''}${pctKeys.length?`<text x="${width-right}" y="13" text-anchor="end" fill="#c9a9cf" font-size="9">百分比</text>`:''}`;
    const labels=weeks.map((week,index)=>`<text x="${x(index)}" y="${height-9}" text-anchor="middle" fill="#93b6b8" font-size="10">${escapeHtml(week.label)}</text>`).join('');
    const series=selected.map(key=>{
      const meta=metricMeta[key];
      const y=meta.axis==='percent'?yRight:yLeft;
      const vals=weeks.map(week=>valueOf(week,key));
      if(meta.bar){
        const barWidth=Math.min(24,plotW/Math.max(weeks.length,1)*.46);
        return vals.map((value,index)=>value==null?'':`<rect x="${x(index)-barWidth/2}" y="${y(value)}" width="${barWidth}" height="${top+plotH-y(value)}" rx="3" fill="${meta.color}" opacity=".72"/>`).join('');
      }
      let path='',connected=false;
      vals.forEach((value,index)=>{if(value==null){connected=false;return}path+=`${connected?'L':'M'}${x(index).toFixed(1)},${y(value).toFixed(1)} `;connected=true});
      const dots=vals.map((value,index)=>value==null?'':`<circle cx="${x(index)}" cy="${y(value)}" r="3.5" fill="${meta.color}" stroke="#0d2530" stroke-width="1.5"/>`).join('');
      return `<path d="${path}" fill="none" stroke="${meta.color}" stroke-width="2.4" stroke-linejoin="round"/>${dots}`;
    }).join('');
    const step=plotW/Math.max(weeks.length-1,1);
    const formats=Object.fromEntries(selected.map(key=>[key,metricMeta[key].format]));
    const hits=weeks.map((week,index)=>`<rect class="week-hit" x="${Math.max(left,x(index)-step/2)}" y="${top}" width="${Math.min(step,width-right-Math.max(left,x(index)-step/2))}" height="${plotH}" fill="transparent" data-label="${escapeHtml(weekHoverText(week,selected,metricLabels,formats))}" data-tooltip="${escapeHtml(JSON.stringify({title:week.label,rows:selected.map(key=>({label:metricLabels[key],value:metricText(key,week[key]),color:metricMeta[key].color}))}))}"/>`).join('');
    return `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="完整自然周各指标走势图；悬停任意一周可见所有所选指标真实值">${grids}${axisLabels}${leftLabels}${rightLabels}${series}${hits}${labels}</svg>`;
  }

  function bindContent() {
    document.querySelector('[data-weekly]')?.addEventListener('toggle',event=>{state.weeklyOpen=event.currentTarget.open});
    document.querySelectorAll('[data-domain]').forEach(el=>bindSingleClick(el,()=>{state.domain=el.dataset.domain;state.expanded=null;state.decisionDrawer=null;render()}));
    document.querySelectorAll('[data-growth-view]').forEach(el=>el.addEventListener('click',()=>{state.growthView=el.dataset.growthView;state.expanded=null;state.decisionDrawer=null;refreshDomain()}));
    document.querySelectorAll('#app [data-review]').forEach(el=>el.addEventListener('click',()=>saveReview(el.dataset.action,el.dataset.profile,el.dataset.review)));
    document.querySelectorAll('[data-ad-filter]').forEach(el=>el.addEventListener('click',()=>{state.adFilter=el.dataset.adFilter;state.adLimit=40;state.queueLimit=60;state.bidLimit=20;state.bidFocus=null;
      if(state.view==='queue')render();else refreshDomain()}));
    document.querySelector('[data-more="ads"]')?.addEventListener('click',()=>{state.adLimit+=40;refreshDomain()});
    document.querySelector('[data-more="queue"]')?.addEventListener('click',()=>{state.queueLimit+=60;render()});
    document.querySelector('[data-more="bid"]')?.addEventListener('click',()=>{state.bidLimit+=20;
      if(state.view==='queue')render();else refreshDomain()});
    document.querySelectorAll('[data-open-product]').forEach(el=>el.addEventListener('click',()=>{state.selected=el.dataset.openProduct;
      state.view='product';state.navOrigin='queue';state.domain='growth';state.growthView='ads';state.adFilter='all';render();loadTracking(selectedProduct());loadSupplement(selectedProduct())}));
    document.querySelectorAll('[data-open-inventory]').forEach(el=>el.addEventListener('click',()=>{
      state.selected=el.dataset.openInventory;state.view='product';state.navOrigin='inventory-queue';state.domain='inventory';render();
      window.scrollTo?.({top:0,behavior:'smooth'});
    }));
    document.querySelector('[data-pmc-preview]')?.addEventListener('click',()=>{
      const product=selectedProduct(), feedback=document.getElementById('pmc-scenario-feedback');
      if(!window.PmcEngine?.analyzeInventoryRecord){feedback.textContent='库存引擎未加载，未执行预览。';return}
      const params={};let invalid=false;
      document.querySelectorAll('[data-pmc-param]').forEach(input=>{
        if(input.value.trim()==='')return;
        const value=Number(input.value);if(!Number.isFinite(value)||value<Number(input.min||0)||value>Number(input.max||Infinity))invalid=true;
        else params[input.dataset.pmcParam]=value;
      });
      if(invalid){feedback.textContent='参数超出范围，未执行预览。';return}
      try{const source=product.inventory_pmc;
        state.inventoryPreview[product.key]={...window.PmcEngine.analyzeInventoryRecord(source.basis,{asOf:source.asOf,...params}),asOf:source.asOf,basis:source.basis};
        refreshDomain();
      }catch(error){feedback.textContent=`预览未生成：${error?.message||'计算错误'}`}
    });
    document.querySelector('[data-pmc-reset]')?.addEventListener('click',()=>{delete state.inventoryPreview[selectedProduct().key];refreshDomain()});
    document.querySelector('[data-pmc-copy]')?.addEventListener('click',()=>{
      const product=selectedProduct(), params={};
      document.querySelectorAll('[data-pmc-param]').forEach(input=>{if(input.value.trim()!=='')params[input.dataset.pmcParam]=Number(input.value)});
      const draft={store:product.inventory_pmc.store,asin:product.asin,name:'运营情景',params};
      const feedback=document.getElementById('pmc-scenario-feedback');
      feedback.innerHTML=`<span>复制以下 JSON 到技能情景库，再重跑库存批次：</span><textarea readonly rows="5">${escapeHtml(JSON.stringify(draft,null,2))}</textarea>`;
      feedback.querySelector('textarea')?.select();
    });
    document.querySelectorAll('[data-bid-rank]').forEach(el=>el.addEventListener('click',()=>{
      state.bidRank=state.bidRank===el.dataset.bidRank?null:el.dataset.bidRank;refreshDomain();
      const row=document.querySelector(`[data-action-row="${el.dataset.bidRank}"]`);setTimeout(()=>row?.scrollIntoView({block:'center',behavior:'smooth'}),0);
    }));
    document.querySelectorAll('[data-bid-rank-close]').forEach(el=>el.addEventListener('click',()=>{state.bidRank=null;refreshDomain()}));
    document.querySelectorAll('[data-open-keyword-product]').forEach(el=>el.addEventListener('click',()=>{
      state.selected=el.dataset.openKeywordProduct;state.view='product';state.domain='growth';state.growthView='rank';
      state.keywordFilter='all';state.keywordLimit=1000;state.expanded={id:el.dataset.openKeyword,kind:'rank',focus:'natural'};
      render();loadTracking(selectedProduct());loadSupplement(selectedProduct());
    }));
    document.getElementById('keyword-search')?.addEventListener('input',e=>{state.keywordSearch=e.target.value;state.keywordLimit=12;refreshDomain()});
    document.querySelectorAll('[data-keyword-filter]').forEach(el=>el.addEventListener('click',()=>{state.keywordFilter=el.dataset.keywordFilter;state.keywordLimit=12;state.expanded=null;refreshDomain()}));
    document.querySelector('[data-keyword-manage]')?.addEventListener('click',()=>{state.keywordManageOpen=!state.keywordManageOpen;refreshDomain()});
    document.querySelector('#keyword-import-text')?.addEventListener('input',event=>{
      state.keywordImportText=event.target.value;state.keywordImportProduct=selectedProduct().key;
      state.keywordImportPreview=null;document.querySelector('[data-keyword-commit]')?.setAttribute('disabled','');
    });
    document.querySelector('[data-keyword-preview]')?.addEventListener('click',()=>{
      state.keywordImportText=document.querySelector('#keyword-import-text')?.value||'';
      state.keywordImportProduct=selectedProduct().key;
      state.keywordImportPreview=parseKeywordBatch(state.keywordImportText);refreshDomain();
    });
    document.querySelector('[data-keyword-commit]')?.addEventListener('click',()=>saveTrackingBulk(selectedProduct()));
    document.querySelectorAll('[data-tracking]').forEach(el=>el.addEventListener('click',()=>saveTracking(selectedProduct(),el.dataset.term,el.dataset.tracking)));
    document.querySelector('[data-sif-priority]')?.addEventListener('click',el=>savePriority(selectedProduct(),el.dataset.sifPriority==='1'));
    document.querySelector('[data-sif-query]')?.addEventListener('click',()=>querySif(selectedProduct()));
    document.querySelectorAll('[data-competitor]').forEach(el=>el.addEventListener('click',()=>
      saveCompetitor(selectedProduct(),el.dataset.competitorAsin,el.dataset.competitor)));
    document.querySelectorAll('[data-keyword-rank]').forEach(el=>el.addEventListener('click',()=>{state.expanded=toggleKeywordPanel(state.expanded,el.dataset.keywordRank,'rank',el.dataset.rankFocus);refreshDomain()}));
    document.querySelectorAll('[data-keyword-internal]').forEach(el=>el.addEventListener('click',()=>{state.expanded=toggleKeywordPanel(state.expanded,el.dataset.keywordInternal,'internal');refreshDomain()}));
    document.querySelectorAll('#app [data-probe]').forEach(el=>el.addEventListener('click',()=>saveReview(el.dataset.probe,el.dataset.profile,el.dataset.probeValue)));
    document.querySelectorAll('#app [data-verdict-tip]').forEach(el=>{
      el.addEventListener('mouseenter',()=>showVerdictTooltip(el));
      el.addEventListener('mouseleave',()=>hideVerdictTooltip());
      el.addEventListener('focus',()=>showVerdictTooltip(el,verdictTipPinned&&verdictTipTrigger===el));
      el.addEventListener('blur',()=>hideVerdictTooltip());
      el.addEventListener('click',event=>{event.stopPropagation();
        if(verdictTipPinned&&verdictTipTrigger===el)hideVerdictTooltip(true);
        else showVerdictTooltip(el,true)});
    });
    document.querySelectorAll('#app [data-decision-open]').forEach(el=>el.addEventListener('click',()=>openDecisionDrawer(el.dataset.decisionOpen,el.dataset.decisionPane,el)));
    document.querySelectorAll('[data-jump-action]').forEach(el=>el.addEventListener('click',()=>{
      const action=(board.actions||[]).find(item=>item.action_key===el.dataset.jumpAction);
      if(!action)return;
      state.domain='growth';state.growthView='ads';state.adFilter=action.kind==='bid_review'?'bid':
        action.processed_status?'processed':!action.reviewable?'gaps':action.kind==='exact'?'exact':'negative';
      state.adLimit=1000;if(action.kind==='bid_review'){state.bidLimit=20;state.bidFocus=action.action_key}state.expandedAction=action.action_key;
      render();const row=[...document.querySelectorAll('[data-action-row]')].find(item=>item.dataset.actionRow===action.action_key);
      row?.scrollIntoView({block:'center',behavior:'smooth'});
    }));
    document.querySelector('[data-more="keywords"]')?.addEventListener('click',()=>{state.keywordLimit+=24;refreshDomain()});
    document.querySelectorAll('[data-metric]').forEach(el=>el.addEventListener('click',()=>{
      const key=el.dataset.metric,meta=metricMeta[key];
      if(!meta)return;
      if(state.metrics.has(key))state.metrics.delete(key);
      else {
        if(meta.axis==='value')[...state.metrics].forEach(old=>{if(metricMeta[old]?.axis==='value')state.metrics.delete(old)});
        if(state.metrics.size<8)state.metrics.add(key);
      }
      refreshDomain();
    }));
    document.querySelector('[data-metric-reset]')?.addEventListener('click',()=>{state.metrics=new Set(DEFAULT_METRICS);refreshDomain()});
    document.querySelectorAll('[data-listing-weekly]').forEach(el=>el.addEventListener('click',()=>{
      state.weeklyOpen=true;refreshDomain();
      setTimeout(()=>document.querySelector('[data-weekly]')?.scrollIntoView({block:'center',behavior:'smooth'}),0);
    }));
    document.querySelectorAll('.chart-point,.week-hit,.rank-hit,.pmc-hit').forEach(el=>{
      el.addEventListener('pointermove',event=>{const tip=document.getElementById('hover-tip');
        let data=null;try{data=el.dataset.tooltip?JSON.parse(el.dataset.tooltip):null}catch{data=null}
        if(data){tip.className='hover-tip tip-card';tip.innerHTML=`<div class="tip-title">${escapeHtml(data.title)}</div><div class="tip-grid">${data.rows.map(row=>`<span><i style="background:${row.color}"></i>${escapeHtml(row.label)}</span><strong>${escapeHtml(row.value)}</strong>`).join('')}</div>`}
        else{tip.className='hover-tip';tip.textContent=el.dataset.label}
        tip.hidden=false;
        const size=tip.getBoundingClientRect();const position=tooltipPosition({x:event.clientX,y:event.clientY,width:size.width,height:size.height,
          viewportWidth:window.innerWidth,viewportHeight:window.innerHeight});
        tip.style.left=`${position.left}px`;tip.style.top=`${position.top}px`});
      el.addEventListener('pointerleave',()=>{const tip=document.getElementById('hover-tip');tip.hidden=true;tip.className='hover-tip'});
    });
    bindPmc();
  }

  function refreshDomain(){
    hideVerdictTooltip(true);
    const input=document.getElementById('keyword-search');const focus=input===document.activeElement;const cursor=focus?input.selectionStart:null;
    document.getElementById('domain-content').innerHTML=domainContent(selectedProduct());bindContent();renderDecisionDrawer();
    if(focus){const next=document.getElementById('keyword-search');next?.focus();next?.setSelectionRange(cursor,cursor)}
  }
  initialize();
})();
