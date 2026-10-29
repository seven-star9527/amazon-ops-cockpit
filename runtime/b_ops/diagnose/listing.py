"""Listing patrol: observations first; performance signals are triage, not blame."""

from __future__ import annotations

from b_ops.model.snapshot import number


def _field_state(value):
    if value is None:
        return "unverified"
    return "present" if bool(value) else "missing"


def _cvr(product):
    weeks = (product.get("weeks") or [])[-4:]
    if len(weeks) < 4 or any(w.get("quality") != "measured" or number(w.get("sessions_total")) is None
                              or number(w.get("orders")) is None for w in weeks):
        return {"state": "insufficient_weeks"}
    recent, baseline = weeks[-1], weeks[-4:-1]
    sessions = number(recent.get("sessions_total")) or 0
    orders = number(recent.get("orders")) or 0
    prior_sessions = sum(number(w.get("sessions_total")) or 0 for w in baseline)
    prior_orders = sum(number(w.get("orders")) or 0 for w in baseline)
    if sessions < 50 or prior_sessions < 150 or prior_orders < 10:
        return {"state": "low_sample", "week": recent.get("label"), "sessions": sessions, "orders": orders}
    baseline_cvr = prior_orders / prior_sessions
    current_cvr = orders / sessions
    weekly_traffic = prior_sessions / 3
    traffic_change = sessions / weekly_traffic - 1 if weekly_traffic else None
    price_pairs = [(number(w.get("avg_price")), number(w.get("units"))) for w in baseline]
    valid_prices = [(price, units) for price, units in price_pairs if price is not None and units is not None and units > 0]
    baseline_price = (sum(price * units for price, units in valid_prices) / sum(units for _, units in valid_prices)
                      if len(valid_prices) == len(baseline) else None)
    return {"state": "measured", "week": recent.get("label"), "current_cvr": round(current_cvr, 4),
            "baseline_cvr": round(baseline_cvr, 4), "sessions": sessions, "orders": orders,
            "baseline_sessions_weekly": round(weekly_traffic, 1),
            "current_avg_price": number(recent.get("avg_price")),
            "baseline_avg_price": round(baseline_price, 2) if baseline_price is not None else None,
            "current_fba_sellable": number((product.get("stock") or {}).get("sellable")),
            "traffic_change": round(traffic_change, 3) if traffic_change is not None else None}


def listing_summary(product: dict) -> dict:
    content = product.get("content") or {}
    return {"content": {"title": _field_state(content.get("title")),
                        "main_image": _field_state(content.get("main_image_url")),
                        "bullets": _field_state(content.get("bullets")),
                        "gallery": _field_state(content.get("gallery_urls")),
                        "source": content.get("source")},
            "cvr": _cvr(product), "returns": product.get("return_analysis"),
            "rating": product.get("rating"), "reviews": product.get("reviews")}


def listing_issues(product: dict) -> list[dict]:
    summary = listing_summary(product)
    issues = []
    missing = [label for key, label in (("title", "标题"), ("main_image", "主图"),
                                       ("bullets", "五点"), ("gallery", "图片组"))
               if summary["content"][key] == "missing"]
    if missing and str(product.get("status")) == "1":
        issues.append({"domain": "listing", "type": "content_missing", "severity": "high",
                       "title": "Listing 内容缺项", "hypothesis": "已取得的内容字段为空；先核对前台与 ERP 同步状态。",
                       "evidence": {"missing_fields": missing, "source": summary["content"]["source"]},
                       "gaps": [], "actionability": 1, "next_step": "补全内容并复核前台展示"})
    cvr = summary["cvr"]
    if cvr["state"] == "measured" and cvr["baseline_cvr"] >= .02 and cvr["current_cvr"] < cvr["baseline_cvr"] * .7:
        traffic_surge = cvr["traffic_change"] is not None and cvr["traffic_change"] >= .3
        issues.append({"domain": "listing", "type": "conversion_drop", "severity": "medium",
                       "title": "总转化率明显回落",
                       "hypothesis": ("流量增幅伴随转化率回落，先排查流量结构与词的匹配。"
                                      if traffic_surge else "同口径总转化率回落，仍需排查价格、库存、评论与页面承诺。"),
                       "evidence": cvr, "gaps": [], "actionability": 1,
                       "next_step": "先复核广告与流量词" if traffic_surge else "复核价格、库存、差评与页面承诺"})
    returns = summary["returns"] or {}
    rate, prior = number(returns.get("rate")), number(returns.get("prior_rate"))
    count = number(returns.get("returns"))
    jumped = (prior is not None and rate is not None and rate - prior >= .02
              and rate >= max(prior * 1.5, .05))
    if rate is not None and count is not None and count >= 5 and (jumped or prior is None and rate >= .1):
        issues.append({"domain": "listing", "type": "return_rate", "severity": "medium",
                       "title": "退货率升高待复核", "hypothesis": "退货变化是信号，主因分类不能直接证明产品缺陷。",
                       "evidence": {"rate": rate, "prior_rate": prior, "returns": count,
                                    "units": returns.get("units"), "main_reason": returns.get("main_reason"),
                                    "reason_share": returns.get("reason_share"), "period": returns.get("period")},
                       "gaps": [] if returns.get("main_reason") else ["退货原因"], "actionability": 1,
                       "next_step": "核对退货原因与页面承诺、包装及实物"})
    rating, reviews = number(product.get("rating")), number(product.get("reviews"))
    if rating is not None and reviews is not None and rating < 3.8 and reviews >= 20:
        issues.append({"domain": "listing", "type": "low_rating", "severity": "medium",
                       "title": "评分低于 3.8", "hypothesis": "需结合近期评论与退货原因排查，不能仅凭星级归因。",
                       "evidence": {"rating": rating, "reviews": reviews}, "gaps": ["近期评论内容"],
                       "actionability": 1, "next_step": "读取评论与原因后拟定改进"})
    return issues
