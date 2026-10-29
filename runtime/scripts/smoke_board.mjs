/** Exercise the real generated board payload with the shipped UI script, offline. */
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';

const htmlPath=process.argv[2];
if(!htmlPath)throw new Error('usage: node scripts/smoke_board.mjs <board-ads-v6.html>');
const html=fs.readFileSync(htmlPath,'utf8');
const match=/<script id="board-data" type="application\/json">([\s\S]*?)<\/script>/.exec(html);
if(!match)throw new Error('board-data script missing');
const board=JSON.parse(match[1]);
const elements=new Map();
function element(id){
  if(!elements.has(id))elements.set(id,{innerHTML:'',textContent:'',value:'',hidden:false,
    addEventListener(){},setSelectionRange(){},focus(){}});
  return elements.get(id);
}
element('board-data').textContent=match[1];
const document={getElementById:element,querySelectorAll(){return []},querySelector(){return null},
  activeElement:null};
const window={B_REVIEW:null,B_SUPPLEMENTS:{},innerWidth:1440,innerHeight:900};
const root=path.resolve(import.meta.dirname,'..');
const model=fs.readFileSync(path.join(root,'web','model.mjs'),'utf8').replaceAll('export function ','function ');
const app=fs.readFileSync(path.join(root,'web','app.js'),'utf8')
  .replace(/  initialize\(\);\s*\}\)\(\);\s*$/, '  window.__smoke={state,render};\n  initialize();\n})();');
const pmcScript=board.inventory_batch?[...html.matchAll(/<script>([\s\S]*?)<\/script>/g)]
  .map(match=>match[1]).find(source=>source.includes('window.PmcEngine=')):null;
if(board.inventory_batch&&!pmcScript)throw new Error('PMC browser engine missing');
vm.runInNewContext(`${model}\n${pmcScript||''}\n${app}`,{document,window},{filename:'board-ui.js',timeout:30000});
const catalog=element('catalog').innerHTML;
const details=element('app').innerHTML;
if(!catalog.includes('product-row')||!details||!element('source-line').innerHTML){
  throw new Error('initial board view or source status did not render');
}
const tracked=Object.values(board.products||{}).find(product=>(product.keyword_state?.terms||[])
  .some(term=>(term.rank_observations||[]).some(point=>point.state==='absolute_rank')));
if(tracked){
  const term=tracked.keyword_state.terms.find(row=>(row.rank_observations||[])
    .some(point=>point.state==='absolute_rank'));
  Object.assign(window.__smoke.state,{selected:tracked.key,view:'product',domain:'growth',growthView:'rank',
    keywordFilter:'all',keywordLimit:1000,expanded:{id:term.id,kind:'rank',focus:'natural'}});
  window.__smoke.render();
  const keywordHtml=element('app').innerHTML;
  if(!keywordHtml.includes('rank-chart'))throw new Error('real rank curve did not render');
  if(!keywordHtml.includes('verdict-tag'))throw new Error('keyword decision did not render');
  if(keywordHtml.indexOf('competitor-panel')<keywordHtml.indexOf('radar-table'))
    throw new Error('competitor pool must follow the keyword tracker');
}
const bidProduct=Object.values(board.products||{}).find(product=>(product.actions||[])
  .some(action=>action.kind==='bid_review'));
if(bidProduct){
  Object.assign(window.__smoke.state,{selected:bidProduct.key,view:'product',domain:'growth',
    growthView:'ads',adFilter:'bid'});
  window.__smoke.render();
  if(!element('app').innerHTML.includes('bid-review-card'))throw new Error('target bid evidence did not render');
}
Object.assign(window.__smoke.state,{view:'queue',adFilter:'all'});
window.__smoke.render();
if(!element('app').innerHTML.includes('ad-action-card'))throw new Error('global ad queue did not render');
Object.assign(window.__smoke.state,{view:'product',domain:'listing',selected:Object.values(board.products||{})[0]?.key});
window.__smoke.render();
const listingHtml=element('app').innerHTML;
if(!listingHtml.includes('listing-health-panel')||!listingHtml.includes('listing-score'))throw new Error('Listing health panel did not render');
if(board.inventory_batch){
  Object.assign(window.__smoke.state,{view:'inventory-queue'});
  window.__smoke.render();
  if(!element('app').innerHTML.includes('库存待办'))throw new Error('inventory queue did not render');
  const target=Object.values(board.products).find(p=>p.inventory_pmc?.listingStatus===1);
  Object.assign(window.__smoke.state,{view:'product',domain:'inventory',selected:target.key});
  window.__smoke.render();
  if(!element('app').innerHTML.includes('pmc-timeline')||!element('app').innerHTML.includes('库存时间轴'))
    throw new Error('PMC product timeline did not render');
  const scenario=window.PmcEngine.analyzeInventoryRecord(target.inventory_pmc.basis,
    {asOf:target.inventory_pmc.asOf,scenarioMultiplier:1.5});
  if(!(scenario.forecast.daily>=target.inventory_pmc.forecast.daily))throw new Error('PMC scenario engine did not run');
}
console.log(JSON.stringify({run_id:board.run_id,products:Object.keys(board.products||{}).length,
  actions:(board.actions||[]).length,html_bytes:Buffer.byteLength(html),
  catalog_chars:catalog.length,details_chars:details.length,
  rank_curve_smoked:Boolean(tracked),bid_card_smoked:Boolean(bidProduct),global_queue_smoked:true,
  inventory_smoked:Boolean(board.inventory_batch),
  audit_only_payload_omitted:!('ad_keyword_targets' in board)&&!('keyword_snapshot' in board)}));
