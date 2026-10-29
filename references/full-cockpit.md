# Full Cockpit

## Layout

```text
amazon-ops-cockpit/
  SKILL.md
  scripts/run_cockpit.py
  references/
  runtime/                    # copied runtime code, no storage
```

`runtime/` is optional if `AMAZON_OPS_RUNTIME` points to an existing runtime.

## Check

```powershell
python scripts/run_cockpit.py --check
```

It reports:

- runtime path;
- Python/Node availability;
- complete board path;
- whether the board and state database exist.

## Serve

```powershell
python scripts/run_cockpit.py --serve
```

Full board only. It calls:

```text
runtime/scripts/serve_pmc.py
```

Never calls `scripts/run_analysis.py` or `dashboard_server.py`.

## Data prerequisites

The code package intentionally has no `storage/`.

To build a full board from a fresh data set:

```text
1. Lingxing same-day source capture -> pmc_sources/<date>/
2. ETA/shipment workbook
3. B-line ad/listing base board
4. python pmc/scripts/build_board.py \
     --sources <source_dir> \
     --shipments <eta.xlsx> \
     --base <base-board.json> \
     --output-dir <output_dir>
5. python runtime/scripts/serve_pmc.py \
     --board <output_dir>/board-pmc.json \
     --state <state.sqlite3>
```

`refresh.py` alone produces a B-line ad batch, not the PMC inventory layer. Do not call that the complete cockpit.

## UI invariants

- product tabs: 广告 / 库存 / Listing;
- one ad summary row, no duplicate bottom filters;
- keyword panel keeps latest natural/SP rank and hidden trend;
- no fake rank when SIF has no observation.

## Writeback

Panel save is business authorization for ordinary batches. The unified executor is:

```text
runtime/scripts/run_ad_writeback.py --execute-saved
```

Item failures do not stop the rest; only batch-level schema/identity/digest errors hard-stop.
