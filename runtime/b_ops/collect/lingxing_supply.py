"""Read-only FBA ETA adapter. Authentication stays in the host's API client."""
from __future__ import annotations

import copy
import datetime as dt
import math
import re

SOURCE_PATH = "/erp/sc/routing/fbaSug/asin/getSourceList"
DISPATCH_PATH = "/erp/sc/routing/storage/shipment/getInboundShipmentList"
READ_PATHS = frozenset({SOURCE_PATH, DISPATCH_PATH})
SCHEMA = "lingxing-supply.v1"


class SupplyError(ValueError):
    pass


def _qty(value):
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        number = float(value)
        return int(number) if math.isfinite(number) and number >= 0 and number.is_integer() else None
    except (ValueError, TypeError):
        return None


def _date(value):
    try:
        return dt.date.fromisoformat(str(value)[:10]).isoformat()
    except ValueError:
        return None


def _rows(response, key):
    if not isinstance(response, dict) or response.get("code") != 0 or response.get("success") is False:
        raise SupplyError("API_BUSINESS_ERROR")
    data = response.get("data")
    if not isinstance(data, dict) or not isinstance(data.get(key), list):
        raise SupplyError("API_SHAPE_ERROR")
    rows = data[key]
    if any(not isinstance(row, dict) for row in rows):
        raise SupplyError("API_ROW_ERROR")
    total = data.get("total", response.get("total"))
    # getSourceList has no paging contract and returns top-level total=0 even
    # for non-empty source_list. Only dispatch list totals describe page rows.
    if key == "list" and total is not None and _qty(total) != len(rows):
        raise SupplyError("API_INCOMPLETE_PAGE")
    return rows


def _eta(sid, asin, shipment_id, dispatches, as_of):
    matches = []
    for order in dispatches:
        relations = order.get("relate_list")
        if not isinstance(relations, list):
            raise SupplyError("API_RELATION_SHAPE_ERROR")
        exact = [r for r in relations if isinstance(r, dict)
                 and str(r.get("sid")) == sid and str(r.get("asin", "")).upper() == asin
                 and str(r.get("shipment_id")) == shipment_id]
        if exact:
            matches.append((str(order.get("shipment_sn") or ""), _date(order.get("expected_arrival_date")), str(order.get("status"))))
    matches = sorted(set(matches), key=str)
    if len(matches) != 1 or not matches[0][0]:
        return None, None, "ambiguous_dispatch" if matches else "unmatched_dispatch"
    sn, eta, status = matches[0]
    if status != "1":
        return sn, eta, {"-1": "waiting_pick", "0": "waiting_dispatch", "2": "completed", "3": "void"}.get(status, "unknown_status")
    if not eta:
        return sn, None, "missing_eta"
    return sn, eta, "overdue_eta" if eta < as_of else "verified"


def collect_supply(read_api, *, targets, allowed_sids, as_of, max_calls=100, shipment_rows=()):
    """Host supplies trusted current store grants and a signed POST callable.

    No retries, scheduling, or arbitrary API paths. Call budget counts adapter
    invocations; the host must also meter any transport retries. A response may
    contain other shops; only exact scoped relations leave this adapter.
    """
    if _date(as_of) != as_of:
        raise SupplyError("INVALID_AS_OF")
    allowed = {str(s) for s in allowed_sids if str(s).isdigit() and int(s) > 0}
    pairs = sorted({(str(sid), str(asin).upper()) for sid, asin in targets})
    if not pairs or not allowed or any(s not in allowed or not re.fullmatch(r"B[A-Z0-9]{9}", a) for s, a in pairs):
        raise SupplyError("STORE_SCOPE_DENIED")
    if any(str(r.get("sid")) not in allowed for r in shipment_rows):
        raise SupplyError("STORE_SCOPE_DENIED")
    if isinstance(max_calls, bool) or not isinstance(max_calls, int) or max_calls < 1:
        raise SupplyError("INVALID_CALL_BUDGET")
    calls, dispatch_cache = 0, {}

    def call(path, body):
        nonlocal calls
        if path not in READ_PATHS:
            raise SupplyError("NON_READ_PATH")
        if calls >= max_calls:
            raise SupplyError("CALL_BUDGET_EXHAUSTED")
        calls += 1
        try:
            return read_api(path, body)
        except Exception:
            # URLs, signatures, credentials and response messages never leave the transport.
            raise SupplyError("API_TRANSPORT_ERROR") from None

    result = {"schema": SCHEMA, "as_of": as_of,
              "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(), "records": []}
    for sid, asin in pairs:
        record = {"sid": sid, "asin": asin, "state": "verified", "items": [], "errors": []}
        result["records"].append(record)
        try:
            source_response = call(SOURCE_PATH, {"sid": int(sid), "asin": asin, "type": "2"})
            sources = _rows(source_response, "source_list")
            sources = list(sources)
            source_ids = {str((s.get("remark") or {}).get("shipment_id")) for s in sources}
            # Planned shipments can be absent from the current in-transit source.
            # Still resolve their dispatch linkage, without treating declaration as stock.
            missing = {}
            for line in shipment_rows:
                shipment = line.get("shipment_id")
                if (line.get("sid"), line.get("asin")) != (sid, asin) or shipment in source_ids or line.get("status") in {"CLOSED", "CANCELLED", "DELETED"}:
                    continue
                missing.setdefault(shipment, []).append(line)
            for shipment, lines in missing.items():
                qty = sum(max(0, (_qty(i.get("local_shipped_qty")) or 0) - (_qty(i.get("received_qty")) or 0)) for i in lines)
                sources.append({"type": 2, "quantity": qty, "remark": {"shipment_id": shipment}})
            record["source_response_time"] = source_response.get("response_time")
            seen = set()
            for source in sources:
                shipment_id = str((source.get("remark") or {}).get("shipment_id") or "")
                quantity = _qty(source.get("quantity"))
                if str(source.get("type")) != "2" or not shipment_id or quantity is None or shipment_id in seen:
                    raise SupplyError("AMBIGUOUS_SOURCE_ROWS")
                seen.add(shipment_id)
                key = sid, shipment_id
                error = None
                try:
                    if key not in dispatch_cache:
                        rows, offset, seen_orders, expected = [], 0, set(), None
                        while True:
                            response = call(DISPATCH_PATH, {"sids": sid, "search_field": "shipment_id",
                                "search_value": shipment_id, "is_delete": 0, "offset": offset, "length": 100})
                            data = response.get("data") if isinstance(response, dict) else None
                            if response.get("code") != 0 or not isinstance(data, dict) or not isinstance(data.get("list"), list):
                                raise SupplyError("API_SHAPE_ERROR")
                            page = data["list"]
                            total = _qty(data.get("total", response.get("total", len(page))))
                            if total is None or (expected is not None and total != expected):
                                raise SupplyError("API_INCOMPLETE_PAGE")
                            expected = total
                            for order in page:
                                sn = order.get("shipment_sn") if isinstance(order, dict) else None
                                if not sn or sn in seen_orders:
                                    raise SupplyError("API_INCOMPLETE_PAGE")
                                seen_orders.add(sn)
                            rows.extend(page)
                            offset += len(page)
                            if offset == total:
                                break
                            if not page or offset > total:
                                raise SupplyError("API_INCOMPLETE_PAGE")
                        dispatch_cache[key] = rows
                    sn, eta, state = _eta(sid, asin, shipment_id, dispatch_cache[key], as_of)
                except SupplyError as exc:
                    sn, eta, state, error = None, None, "query_failed", str(exc)
                record["items"].append({"shipment_id": shipment_id, "shipment_sn": sn,
                    "quantity": quantity, "fba_arrival_date": eta, "state": state,
                    "relation_state": "matched" if sn else "ambiguous" if state == "ambiguous_dispatch" else "unmatched",
                    "eta_state": "overdue" if eta and eta < as_of else "present" if eta else "missing"})
                if state != "verified":
                    record["state"] = "partial"
                if error:
                    record["errors"].append(error)
        except (SupplyError, TypeError, AttributeError) as exc:
            record.update(state="failed", items=[], errors=[str(exc) if isinstance(exc, SupplyError) else "API_SHAPE_ERROR"])
    result["calls"] = calls
    return result


def apply_supply(snapshot, supply, *, allowed_sids):
    """Enrich raw inventory records, then use the existing JS calculation engine.

    Input is a trusted server/local artifact, not a client permission assertion.
    Never relabel old inventory dates or directly patch derived calculations.
    """
    if supply.get("schema") != SCHEMA or supply.get("as_of") != snapshot.get("metadata", {}).get("asOf"):
        raise SupplyError("SUPPLY_DATE_OR_SCHEMA_MISMATCH")
    allowed = {str(s) for s in allowed_sids}
    records = supply.get("records")
    if not isinstance(records, list):
        raise SupplyError("SUPPLY_RECORDS_REQUIRED")
    index = {}
    for entry in records:
        key = str(entry.get("sid")), str(entry.get("asin"))
        if key[0] not in allowed or key in index:
            raise SupplyError("SUPPLY_SCOPE_OR_DUPLICATE")
        index[key] = entry
    result = copy.deepcopy(snapshot)
    known = {(str(r.get("storeId")), str(r.get("asin"))) for r in result["records"]}
    if any(sid not in allowed for sid, _ in known):
        raise SupplyError("SNAPSHOT_SCOPE_DENIED")
    if not set(index).issubset(known):
        raise SupplyError("SUPPLY_UNKNOWN_PRODUCT")
    applied = 0
    for record in result["records"]:
        entry = index.get((str(record.get("storeId")), str(record.get("asin"))))
        if not entry or entry.get("state") not in {"verified", "partial"}:
            continue
        items, seen = [], set()
        for item in entry["items"]:
            shipment = item.get("shipment_id")
            qty = _qty(item.get("quantity"))
            if not shipment or shipment in seen or qty is None:
                raise SupplyError("INVALID_SUPPLY_ITEM")
            seen.add(shipment)
            eta = _date(item.get("fba_arrival_date"))
            confirmed = item.get("state") == "verified" and qty > 0 and bool(eta) and eta >= supply["as_of"]
            if item.get("state") in {"waiting_pick", "waiting_dispatch", "completed", "void", "unknown_status"}:
                continue  # Keep the relation in evidence, never count planned/closed supply as transit.
            items.append({"date": eta, "qty": qty, "confirmed": confirmed,
                "shipment": shipment, "status": item.get("state"),
                "etaWindow": eta or "", "source": "领星 API / 发货单 FBA 到仓时间",
                "dispatchOrder": item.get("shipment_sn")})
        # Preserve today's stock authority; the existing engine caps ETA at shippedRaw.
        live = _qty((record.get("inventoryLayers") or {}).get("shippedRaw"))
        if live == 0:
            for item in items:
                item["confirmed"] = False
        residual = max(0, live - sum(i["qty"] for i in items)) if live is not None else 0
        if residual:
            items.append({"date": None, "qty": residual, "confirmed": False,
                          "shipment": "领星实时在途（API未覆盖）", "status": "unknown",
                          "etaWindow": "", "source": "领星 MCP / 当前库存"})
        record["inbound"] = items
        ledger = sum(i["qty"] for i in items)
        confirmed_qty = sum(i["qty"] for i in items if i["confirmed"])
        if live is not None:
            confirmed_qty = min(confirmed_qty, live)
        record["etaReconciliation"] = {"ledgerQty": ledger, "liveQty": live,
            "confirmedQty": confirmed_qty, "overLiveQty": max(0, ledger - live) if live is not None else None,
            "orphanLedgerQty": ledger if live == 0 else 0}
        flags = record.get("completenessFlags")
        if isinstance(flags, dict):
            flags["etaEvidence"] = confirmed_qty > 0 or live == 0
            record["dataCompleteness"] = round(100 * sum(bool(v) for v in flags.values()) / len(flags))
        gap = "实时在途有数量但缺可靠ETA，不用于推迟断货日"
        record["dataGaps"] = list(dict.fromkeys(record.get("dataGaps", [])))
        if live and confirmed_qty < live:
            if gap not in record["dataGaps"]:
                record["dataGaps"].append(gap)
        else:
            record["dataGaps"] = [g for g in record["dataGaps"] if g != gap]
        record["supplyEvidence"] = copy.deepcopy(entry)
        record["evidence"] = [e for e in record.get("evidence", []) if e.get("stage") != "API到仓"]
        record["evidence"].append({"stage": "API到仓", "source": "领星 OpenAPI",
            "fact": f"{len(entry['items'])} 个货件；到仓时间不是预计可售时间；状态 {entry['state']}"})
        applied += 1
    result["metadata"]["supplyApi"] = {"schema": SCHEMA, "asOf": supply["as_of"],
        "generatedAt": supply.get("generated_at"), "appliedProducts": applied,
        "failedProducts": sum(e.get("state") == "failed" for e in records),
        "partialProducts": sum(e.get("state") == "partial" for e in records)}
    covered = sum(any(i.get("confirmed") and i.get("qty", 0) > 0 for i in r.get("inbound", [])) for r in result["records"])
    meta = result["metadata"]
    meta["etaStatus"] = f"{covered}/{len(result['records'])} 个ASIN有确认到仓ETA；缺失与过期日期不推迟断货日"
    meta.setdefault("scope", {})["etaCoveredRows"] = covered
    reconciliations = [r.get("etaReconciliation", {}) for r in result["records"]]
    meta["etaReconciliation"] = {k: sum(r.get(k) or 0 for r in reconciliations)
        for k in ("ledgerQty", "liveQty", "overLiveQty", "orphanLedgerQty")}
    meta["etaReconciliation"].update(overLiveAsins=sum(bool(r.get("overLiveQty")) for r in reconciliations),
        orphanAsins=sum(bool(r.get("orphanLedgerQty")) for r in reconciliations))
    return result
