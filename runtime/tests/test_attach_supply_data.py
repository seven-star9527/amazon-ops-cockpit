import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import attach_supply_data as module


def inputs(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    for name in ("snapshot", "supply", "details", "board"):
        (source / f"{name}.json").write_text(json.dumps({"products": {}, "kind": name}))
    enriched = {"metadata": {"supplyApi": {"schema": "test"}}}
    monkeypatch.setattr(module, "reconcile_fba", lambda s, d, **kw: s)
    monkeypatch.setattr(module, "apply_supply", lambda *args, **kw: enriched)
    monkeypatch.setattr(module, "apply_details", lambda s, d, **kw: s)
    monkeypatch.setattr(module, "fuse_board", lambda b, p: b)
    return dict(snapshot_path=source / "snapshot.json", supply_path=source / "supply.json",
                details_path=source / "details.json", board_path=source / "board.json",
                output_dir=tmp_path / "output", allowed_sids=[1])


def test_details_input_cannot_be_overwritten_by_projection(tmp_path, monkeypatch):
    args = inputs(tmp_path, monkeypatch)
    args["output_dir"].mkdir()
    source = args["output_dir"] / "inventory-projection.json"
    source.write_text('{"kind":"details"}')
    args["details_path"] = source
    with pytest.raises(ValueError, match="overwrite"):
        module.attach(**args)
    assert source.read_text() == '{"kind":"details"}'


@pytest.mark.parametrize("stage", ["calculate", "render"])
def test_build_failure_keeps_last_successful_artifacts(tmp_path, monkeypatch, stage):
    args = inputs(tmp_path, monkeypatch)
    out = args["output_dir"]
    out.mkdir()
    names = ["inventory-snapshot.json", "inventory-projection.json", "board-pmc.json", "board-pmc.html"]
    for name in names:
        (out / name).write_text("previous " + name)

    def calculate(command, **kw):
        if stage == "calculate":
            raise RuntimeError("calculation failed")
        Path(command[-1]).write_text("{}")

    def render(*args):
        raise RuntimeError("render failed")

    monkeypatch.setattr(module.subprocess, "run", calculate)
    monkeypatch.setattr(module, "render_board", render)
    with pytest.raises(RuntimeError):
        module.attach(**args)
    assert all((out / name).read_text() == "previous " + name for name in names)
    assert not list(out.glob(".supply-build-*"))
