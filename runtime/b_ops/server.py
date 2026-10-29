"""Loopback-only review service. It persists opinions, never performs remote writes."""

from __future__ import annotations

import json
import hashlib
import re
import secrets
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from b_ops.model.storage import StateStore


class DecisionInput(BaseModel):
    run_id: str
    action_key: str
    profile_id: str
    value: str
    note: str = Field(default="", max_length=1000)
    bid: float | None = None
    target_campaign_id: str | None = None
    target_ad_group_id: str | None = None
    expected_version: int


class TrackingInput(BaseModel):
    run_id: str
    sid: str
    asin: str
    keyword: str = Field(min_length=1, max_length=120)
    action: str
    expected_version: int


class TrackingBulkInput(BaseModel):
    run_id: str
    sid: str
    asin: str
    keywords: list[str] = Field(min_length=1, max_length=200)
    action: str
    expected_version: int


class PriorityInput(BaseModel):
    run_id: str
    sid: str
    asin: str
    active: bool
    expected_version: int


class SifQueryInput(BaseModel):
    run_id: str
    sid: str
    asin: str


class CompetitorInput(BaseModel):
    run_id: str
    sid: str
    asin: str
    competitor_asin: str
    action: str
    expected_version: int


def create_app(run_dir: Path, state_path: Path, *, sif_client=None,
               html_name: str = 'board.html') -> FastAPI:
    run_dir = Path(run_dir)
    board_bytes = (run_dir / "board.json").read_bytes()
    board = json.loads(board_bytes)
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("state") != "complete" or manifest.get("run_id") != board.get("run_id") or hashlib.sha256(board_bytes).hexdigest() != manifest.get("batch_sha256"):
        raise ValueError("review requires a complete untampered batch")
    if html_name not in {'board.html', 'board-ads-v2.html', 'board-ads-v3.html',
                         'board-ads-v4.html', 'board-ads-v5.html', 'board-ads-v6.html', 'board-ads-v7.html'}:
        raise ValueError('unsupported board view')
    html = (run_dir / html_name).read_text(encoding="utf-8")
    if board.get("run_id") != run_dir.name:
        raise ValueError("run directory and board run_id mismatch")
    action_index = {action["action_key"]: action for action in board.get("actions", [])}
    from b_ops.diagnose.sif_probe import build_probe_candidates
    probe_index = build_probe_candidates(board)
    state = StateStore(state_path)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.session_token = secrets.token_urlsafe(32)
    app.state.run_id = board["run_id"]

    def guard(request: Request, token: str | None):
        if token != app.state.session_token:
            raise HTTPException(403, "local review token required")
        origin = request.headers.get("origin")
        if origin and not re.fullmatch(r"http://127\.0\.0\.1:\d+", origin):
            raise HTTPException(403, "foreign origin rejected")

    def product_scope(sid: str, asin: str) -> dict:
        product = next((item for item in board.get("products", {}).values()
                        if str(item.get("sid")) == str(sid) and
                        str(item.get("asin") or "").upper() == str(asin).upper()), None)
        if product is None:
            raise HTTPException(400, "product scope mismatch")
        return product

    @app.get("/", response_class=HTMLResponse)
    async def index():
        config = "window.B_REVIEW=" + json.dumps({"run_id": board["run_id"], "token": app.state.session_token,
                                                   "sif_available": sif_client is not None}) + ";"
        return HTMLResponse(html.replace("window.B_REVIEW=null;", config))

    @app.get("/api/decisions")
    async def decisions(request: Request, x_local_session: str | None = Header(default=None)):
        guard(request, x_local_session)
        return {"run_id": board["run_id"], "version": state.decision_version(board["run_id"]),
                "items": state.latest_decisions(board["run_id"])}

    @app.post("/api/decisions")
    async def save_decision(item: DecisionInput, request: Request, x_local_session: str | None = Header(default=None)):
        guard(request, x_local_session)
        if item.run_id != board["run_id"]:
            raise HTTPException(400, "stale run")
        action = action_index.get(item.action_key) or probe_index.get(item.action_key)
        if action is None:
            raise HTTPException(404, "unknown action")
        if item.profile_id != action.get("profile_id"):
            raise HTTPException(400, "profile scope mismatch")
        exact_destination = item.target_campaign_id and item.target_ad_group_id
        if action.get('kind') == 'sif_probe':
            if item.value not in {'accept', 'reject', 'observe'}:
                raise HTTPException(400, 'invalid SIF probe opinion')
            if item.bid is not None:
                raise HTTPException(400, 'SIF probe cannot confirm a bid')
            if item.value == 'accept' and len(item.note.strip()) < 8:
                raise HTTPException(400, 'SIF probe requires a relevance rationale')
        elif item.value == "accept" and not action.get("reviewable", action.get("executable")) and not (
                action.get("kind") == "exact" and exact_destination):
            raise HTTPException(400, "non-reviewable action")
        if action.get("processed_status"):
            raise HTTPException(400, "source already processed")
        if item.value == "accept" and action.get("kind") == "exact":
            if item.bid is None or item.bid <= 0:
                raise HTTPException(400, "exact bid must be confirmed")
            if not exact_destination:
                raise HTTPException(400, "exact target campaign/ad group is required")
            group = next((row for row in board.get("ad_group_options") or []
                          if str(row.get("profile_id")) == str(item.profile_id)
                          and str(row.get("campaign_id")) == str(item.target_campaign_id)
                          and str(row.get("ad_group_id")) == str(item.target_ad_group_id)
                          and row.get("campaign_state") == "enabled"
                          and row.get("ad_group_state") == "enabled"), None)
            if group is None:
                group = next((row for row in board.get("ad_keyword_targets") or []
                              if str(row.get("profile_id")) == str(item.profile_id)
                              and str(row.get("campaign_id")) == str(item.target_campaign_id)
                              and str(row.get("ad_group_id")) == str(item.target_ad_group_id)
                              and row.get("campaign_state") == "enabled"
                              and row.get("ad_group_state") == "enabled"), None)
            if group is None:
                # Product-target / ASIN groups may not appear in keyword-target
                # reports. The source action still proves the group is active.
                source_ok = str(action.get("campaign_id")) == str(item.target_campaign_id) and                     str(action.get("ad_group_id")) == str(item.target_ad_group_id) and                     any(row.get("campaign_state") == "enabled" and row.get("ad_group_state") == "enabled"
                        for row in action.get("source_rows") or [])
                if not source_ok:
                    raise HTTPException(400, "exact target ad group is not active for this profile")
        if item.value in {"accept", "modify"} and action.get("kind") == "bid_review" and (
                item.bid is None or item.bid <= 0 or not action.get("target_id")):
            raise HTTPException(400, "target bid review needs a target ID and operator-confirmed bid")
        try:
            saved = state.save_decision(item.run_id, item.action_key, item.profile_id,
                                        item.value, item.note, expected_version=item.expected_version,
                                        bid=item.bid, target_campaign_id=item.target_campaign_id,
                                        target_ad_group_id=item.target_ad_group_id)
        except ValueError as exc:
            if "version" in str(exc):
                raise HTTPException(409, "decision version changed") from None
            raise HTTPException(400, str(exc)) from None
        return saved

    @app.get("/api/tracking")
    async def tracking(request: Request, sid: str, asin: str,
                       x_local_session: str | None = Header(default=None)):
        guard(request, x_local_session)
        product = product_scope(sid, asin)
        return {"run_id": board["run_id"], "version": state.tracking_version(),
                "terms": state.list_keywords(product["site"], product["asin"], sid=str(sid)),
                "sif_priority": state.sif_priority_state(product["key"]),
                "competitors": state.list_competitors(str(sid), product["site"],
                                                       product.get("parent_asin") or product["asin"])}

    @app.get("/api/competitors")
    async def competitors(request: Request, sid: str, asin: str,
                          x_local_session: str | None = Header(default=None)):
        guard(request, x_local_session)
        product = product_scope(sid, asin)
        parent_asin = product.get("parent_asin") or product["asin"]
        return {"run_id": board["run_id"], "version": state.tracking_version(),
                "parent_asin": parent_asin,
                "competitors": state.list_competitors(str(sid), product["site"], parent_asin)}

    @app.post("/api/competitors")
    async def save_competitor(item: CompetitorInput, request: Request,
                              x_local_session: str | None = Header(default=None)):
        guard(request, x_local_session)
        if item.run_id != board["run_id"]:
            raise HTTPException(400, "stale run")
        product = product_scope(item.sid, item.asin)
        if item.expected_version != state.tracking_version():
            raise HTTPException(409, "tracking version changed")
        try:
            parent_asin = product.get("parent_asin") or product["asin"]
            state.stage_competitor_change(item.sid, product["site"], parent_asin,
                                          item.competitor_asin, item.action, item.run_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
        return {"run_id": board["run_id"], "version": state.tracking_version(),
                "parent_asin": parent_asin,
                "competitors": state.list_competitors(item.sid, product["site"], parent_asin)}

    @app.post("/api/tracking")
    async def save_tracking(item: TrackingInput, request: Request,
                            x_local_session: str | None = Header(default=None)):
        guard(request, x_local_session)
        if item.run_id != board["run_id"]:
            raise HTTPException(400, "stale run")
        product = product_scope(item.sid, item.asin)
        if item.expected_version != state.tracking_version():
            raise HTTPException(409, "tracking version changed")
        if item.action not in {"add", "remove", "cancel"}:
            raise HTTPException(400, "invalid tracking action")
        try:
            if item.action == "cancel":
                from b_ops.model.storage import normalize_keyword
                existing = next((term for term in state.list_keywords(product["site"], product["asin"], sid=item.sid)
                                 if term["normalized"] == normalize_keyword(item.keyword)), None)
                if not existing:
                    raise ValueError("unknown tracked keyword")
                state.cancel_tracking_change(item.sid, existing["id"], item.run_id)
                keyword_id = existing["id"]
            else:
                keyword_id = state.stage_tracking_change(item.sid, product["site"], product["asin"],
                                                         item.keyword, item.action, item.run_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
        result = state.tracking_state(keyword_id, item.sid)
        return {"run_id": board["run_id"], "version": state.tracking_version(),
                "keyword_id": keyword_id, "state": result["state"], "pending": result["pending"]}

    @app.post("/api/tracking/bulk")
    async def save_tracking_bulk(item: TrackingBulkInput, request: Request,
                                 x_local_session: str | None = Header(default=None)):
        guard(request, x_local_session)
        if item.run_id != board["run_id"]:
            raise HTTPException(400, "stale run")
        product = product_scope(item.sid, item.asin)
        if item.expected_version != state.tracking_version():
            raise HTTPException(409, "tracking version changed")
        try:
            ids = state.stage_tracking_batch(item.sid, product["site"], product["asin"],
                                             item.keywords, item.action, item.run_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
        return {"run_id": board["run_id"], "version": state.tracking_version(),
                "accepted": len(ids), "terms": state.list_keywords(product["site"], product["asin"], sid=item.sid)}

    @app.post("/api/sif-priority")
    async def save_sif_priority(item: PriorityInput, request: Request,
                                x_local_session: str | None = Header(default=None)):
        guard(request, x_local_session)
        if item.run_id != board["run_id"]:
            raise HTTPException(400, "stale run")
        product = product_scope(item.sid, item.asin)
        if item.expected_version != state.tracking_version():
            raise HTTPException(409, "tracking version changed")
        state.stage_sif_priority(item.sid, product["site"], product["asin"], item.active, item.run_id)
        return {"run_id": board["run_id"], "version": state.tracking_version(),
                "sif_priority": state.sif_priority_state(product["key"])}

    @app.post("/api/sif-query")
    async def sif_query(item: SifQueryInput, request: Request,
                        x_local_session: str | None = Header(default=None)):
        guard(request, x_local_session)
        if item.run_id != board["run_id"]:
            raise HTTPException(400, "stale run")
        product = product_scope(item.sid, item.asin)
        if sif_client is None:
            raise HTTPException(503, "SIF key unavailable in local service")
        from b_ops.collect.sif_single import query_single_sif
        try:
            return await run_in_threadpool(query_single_sif, sif_client, state, run_dir, product)
        except Exception as exc:
            raise HTTPException(502, f"SIF read failed: {type(exc).__name__}") from None

    @app.get("/api/sif-supplement")
    async def sif_supplement(request: Request, sid: str, asin: str,
                             x_local_session: str | None = Header(default=None)):
        guard(request, x_local_session)
        product = product_scope(sid, asin)
        for path in sorted((run_dir / "supplements").glob("sif-*/summary.json"), reverse=True):
            snapshot = json.loads(path.read_text(encoding="utf-8"))
            if snapshot.get("sid") == str(product["sid"]) and snapshot.get("asin") == product["asin"]:
                return snapshot
        return {"run_id": board["run_id"], "terms": [], "state": "not_queried"}

    return app
