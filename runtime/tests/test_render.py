import json
import re
import sys

import pytest

from b_ops.render import render_board
from scripts import render_board as render_script


def test_offline_board_embeds_new_batch_only_without_external_assets(tmp_path):
    path = tmp_path / "board.json"
    path.write_text(json.dumps({"run_id": "b-test", "products": {}, "coverage": {}, "status": {}}, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "board.html"
    render_board(path, out)
    html = out.read_text(encoding="utf-8")
    assert "库存与广告工作台" in html
    assert "b-test" in html
    assert "src=\"https" not in html
    assert "__APP__" not in html


def test_inventory_board_embeds_local_pmc_engine_for_offline_scenario_preview(tmp_path):
    path = tmp_path / "board.json"
    path.write_text(json.dumps({"run_id": "b-test", "products": {}, "coverage": {},
                                "status": {}, "inventory_batch": {"as_of": "2026-10-21"}}), encoding="utf-8")
    out = tmp_path / "board-pmc.html"
    render_board(path, out)
    html = out.read_text(encoding="utf-8")
    assert "window.PmcEngine" in html
    assert "function analyzeInventoryRecord(record, options = {})" in html
    assert "src=\"https" not in html


def test_offline_board_can_embed_only_a_matching_sif_supplement(tmp_path):
    board_path = tmp_path / "board.json"
    board_path.write_text(json.dumps({"run_id": "b-test", "products": {
        "5906|UK|B012345678": {"key": "5906|UK|B012345678", "sid": "5906", "asin": "B012345678"}},
        "coverage": {}, "status": {}}, ensure_ascii=False), encoding="utf-8")
    supplement_path = tmp_path / "summary.json"
    supplement = {"run_id": "b-test", "query_id": "sif-001", "sid": "5906", "asin": "B012345678",
                  "terms": [{"keyword": "kids scissors", "rank_observations": [{"rank": 8}]}]}
    supplement_path.write_text(json.dumps(supplement), encoding="utf-8")
    out = tmp_path / "board-sif.html"
    render_board(board_path, out, supplement_paths=[supplement_path])
    html = out.read_text(encoding="utf-8")
    assert 'window.B_SUPPLEMENTS={"5906|UK|B012345678":' in html
    assert '"query_id":"sif-001"' in html
    assert "manualSif:window.B_SUPPLEMENTS||{}" in html

    supplement["run_id"] = "b-other"
    supplement_path.write_text(json.dumps(supplement), encoding="utf-8")
    with pytest.raises(ValueError, match="supplement run"):
        render_board(board_path, out, supplement_paths=[supplement_path])


def test_v4_board_embeds_ad_evidence_and_rank_boundary_without_touching_v3(tmp_path):
    path = tmp_path / "board.json"
    payload = json.dumps({"run_id": "b-test", "products": {}, "actions": [],
                          "coverage": {}, "status": {}}, ensure_ascii=False)
    path.write_text(payload, encoding="utf-8")
    older = tmp_path / "board-ads-v3.html"
    older.write_text("preserved v3", encoding="utf-8")
    out = tmp_path / "board-ads-v4.html"
    render_board(path, out)
    html = out.read_text(encoding="utf-8")
    assert older.read_text(encoding="utf-8") == "preserved v3"
    assert 'function adMetricSummary(action)' in html
    assert 'function rankPresentation(digest, fallback)' in html
    assert '在投精准复核' in html
    assert '广告销售额' in html


def test_v5_html_omits_audit_only_duplicate_collections_but_keeps_full_board_json(tmp_path):
    path=tmp_path/'board.json'
    board={'run_id':'b-test','products':{'p':{'key':'p','name':'商品'}},'actions':[],
           'coverage':{},'status':{},'ad_keyword_targets':[{'target_id':'t1'}],
           'keyword_snapshot':{'p':{'terms':[{'keyword':'kids knife'}]}}}
    path.write_text(json.dumps(board,ensure_ascii=False),encoding='utf-8')
    out=tmp_path/'board-ads-v5.html'
    render_board(path,out)
    html=out.read_text(encoding='utf-8')
    embedded=json.loads(re.search(r'<script id="board-data" type="application/json">(.*?)</script>',
                             html,re.S).group(1))
    assert 'ad_keyword_targets' not in embedded
    assert 'keyword_snapshot' not in embedded
    assert embedded['products']==board['products']
    assert json.loads(path.read_text(encoding='utf-8'))==board


def test_v7_is_independent_and_embeds_only_decision_view_payload(tmp_path):
    path=tmp_path/'board.json'
    board={'run_id':'b-v7','products':{},'actions':[],'coverage':{},'status':{},
           'ad_keyword_targets':[{'target_id':'t1'}],
           'keyword_snapshot':{'p':{'terms':[{'keyword':'kids knife'}]}}}
    path.write_text(json.dumps(board,ensure_ascii=False),encoding='utf-8')
    old=tmp_path/'board-ads-v6.html'
    old.write_text('preserve V6',encoding='utf-8')
    out=tmp_path/'board-ads-v7.html'
    render_board(path,out)
    html=out.read_text(encoding='utf-8')
    embedded=json.loads(re.search(r'<script id="board-data" type="application/json">(.*?)</script>',
                             html,re.S).group(1))
    assert old.read_text(encoding='utf-8')=='preserve V6'
    assert 'decision-drawer' in html
    assert 'keyword-import-file' not in html
    assert 'ad_keyword_targets' not in embedded
    assert 'keyword_snapshot' not in embedded


def test_render_cli_defaults_to_v7_without_overwriting_v6(tmp_path, monkeypatch):
    run=tmp_path/'storage'/'runs'/'b-v7'
    run.mkdir(parents=True)
    (run/'board.json').write_text(json.dumps({'run_id':'b-v7','products':{},'coverage':{},'status':{}}),encoding='utf-8')
    (run/'board-ads-v6.html').write_text('old v6',encoding='utf-8')
    monkeypatch.setattr(render_script,'ROOT',tmp_path)
    monkeypatch.setattr(sys,'argv',['render_board.py','b-v7'])
    render_script.main()
    assert (run/'board-ads-v7.html').is_file()
    assert (run/'board-ads-v6.html').read_text(encoding='utf-8')=='old v6'
