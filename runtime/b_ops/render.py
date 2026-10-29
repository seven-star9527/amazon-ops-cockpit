"""Build a standalone read-only SIF-inspired workbench from one B-line batch."""

from __future__ import annotations

import json
from pathlib import Path


WEB = Path(__file__).resolve().parents[1] / "web"
PMC_SRC = Path(__file__).resolve().parents[1] / "pmc" / "src"


def _pmc_browser_engine() -> str:
    """Bundle the supplied PMC modules into the offline board without external assets."""
    specs = (("PmcDemand", "demand-engine.mjs", "forecastDemand"),
             ("PmcTimeline", "timeline-engine.mjs",
              "normalizeInventoryLayers,buildConfirmedEvents,simulateInventoryTimeline,calculateCoverage"),
             ("PmcPlanning", "planning-engine.mjs", "buildSupplyPlan"))
    chunks = []
    for namespace, filename, exports in specs:
        source = (PMC_SRC / filename).read_text(encoding="utf-8")
        source = source.replace("export function ", "function ").replace("export const ", "const ")
        chunks.append(f"const {namespace}=(()=>{{\n{source}\nreturn {{{exports}}};\n}})();")
    inventory = (PMC_SRC / "inventory-engine.mjs").read_text(encoding="utf-8")
    inventory = inventory[inventory.index("const DAY_MS"):]
    inventory = inventory.replace("export function ", "function ").replace("export const ", "const ")
    prefix = ("const {forecastDemand:forecastDemandKernel}=PmcDemand;\n"
              "const {normalizeInventoryLayers,buildConfirmedEvents,simulateInventoryTimeline,calculateCoverage}=PmcTimeline;\n"
              "const {buildSupplyPlan}=PmcPlanning;\n")
    chunks.append(f"window.PmcEngine=(()=>{{\n{prefix}{inventory}\nreturn {{analyzeInventoryRecord,buildShipmentPlanView}};\n}})();")
    return "\n".join(chunks).replace("</script", "<\\/script")


def render_board(board_path: Path, output_path: Path,
                 *, supplement_paths: list[Path] | None = None) -> Path:
    board = json.loads(Path(board_path).read_text(encoding="utf-8"))
    if not str(board.get("run_id") or "").startswith("b-"):
        raise ValueError("B workbench requires a B-line run ID")
    template = (WEB / "index.html").read_text(encoding="utf-8")
    model = (WEB / "model.mjs").read_text(encoding="utf-8").replace("export function ", "function ")
    app = (WEB / "app.js").read_text(encoding="utf-8")
    css = (WEB / "style.css").read_text(encoding="utf-8")
    if board.get("inventory_batch"):
        css += "\n" + (WEB / "pmc.css").read_text(encoding="utf-8")
    css += "\n" + (WEB / "theme-light.css").read_text(encoding="utf-8")
    pmc_engine = _pmc_browser_engine() if board.get("inventory_batch") else ""
    # V5+ product/action rows already contain the operational evidence. Keep the
    # duplicate source-index collections in immutable board.json for audit,
    # not in the browser payload on every page load.
    view = dict(board)
    if board.get("ad_group_options"):
        view["ad_group_options"] = board["ad_group_options"]
    else:
        groups = {}
        for row in board.get("ad_keyword_targets") or []:
            if row.get("campaign_state") != "enabled" or row.get("ad_group_state") != "enabled":
                continue
            key = (str(row.get("profile_id")), str(row.get("campaign_id")), str(row.get("ad_group_id")))
            groups[key] = {"profile_id": key[0], "campaign_id": key[1],
                           "campaign_name": row.get("campaign_name") or key[1],
                           "ad_group_id": key[2], "ad_group_name": row.get("ad_group_name") or row.get("name") or "未命名广告组",
                           "portfolio_id": row.get("portfolio_id"), "portfolio_name": row.get("portfolio_name")}
        view["ad_group_options"] = list(groups.values())
    if Path(output_path).name.startswith(("board-ads-v5", "board-ads-v6", "board-ads-v7", "board-pmc")):
        view.pop("ad_keyword_targets", None)
        view.pop("keyword_snapshot", None)
    data = json.dumps(view, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    supplements = {}
    for path in supplement_paths or []:
        item = json.loads(Path(path).read_text(encoding="utf-8"))
        if item.get("run_id") != board["run_id"]:
            raise ValueError("supplement run does not match board")
        if not str(item.get("query_id") or "").startswith("sif-") or not isinstance(item.get("terms"), list):
            raise ValueError("invalid SIF supplement")
        matches = [product["key"] for product in board.get("products", {}).values()
                   if str(product.get("sid")) == str(item.get("sid"))
                   and product.get("asin") == item.get("asin")
                   and (not item.get("site") or product.get("site") == item["site"])]
        if len(matches) != 1:
            raise ValueError("supplement product is absent or ambiguous")
        previous = supplements.get(matches[0])
        if previous is None or str(item.get("queried_at") or "") > str(previous.get("queried_at") or ""):
            supplements[matches[0]] = item
    embedded = json.dumps(supplements, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    config = f"window.B_REVIEW=null;window.B_SUPPLEMENTS={embedded};"
    html = (template.replace("__STYLE__", css).replace("__DATA__", data).replace("__REVIEW__", config)
            .replace("__PMC_ENGINE__", pmc_engine)
            .replace("__MODEL__", model).replace("__APP__", app))
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    return output_path
