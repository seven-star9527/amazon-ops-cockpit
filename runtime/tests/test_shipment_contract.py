from pathlib import Path
import re


def test_ui_reads_shipment_plan_through_one_view():
    app = (Path(__file__).resolve().parents[1] / "web" / "app.js").read_text(encoding="utf-8")
    assert "function pmcShipmentView" in app
    assert "shipmentBatches.find" not in app
    assert app.count("shipmentBatches") == 1, "UI must not bypass pmcShipmentView with raw shipmentBatches access"


def test_projection_keeps_named_shipment_plan():
    source = (Path(__file__).resolve().parents[1] / "pmc" / "scripts" / "analyze_snapshot.mjs").read_text(encoding="utf-8")
    assert re.search(r"const projectedPlan\s*=", source)
    assert re.search(r"shipmentPlan\s*:\s*projectedPlan", source)
