"""Conservative SIF-only keyword intents; never remote advertising actions."""

from __future__ import annotations

import re

from b_ops.model.storage import normalize_keyword


def build_probe_candidates(board: dict) -> dict[str, dict]:
    """Offer an operator relevance check without inferring an unobserved target is absent."""
    if (board.get('status') or {}).get('ads_diagnosis', {}).get('source_complete') is not True:
        return {}
    profile_by_sid = {str(sid): str(profile) for profile, sid in
                      (board.get('profile_to_sid') or {}).items()}
    candidates: dict[str, dict] = {}
    for product in (board.get('products') or {}).values():
        profile = profile_by_sid.get(str(product.get('sid')))
        if (not profile or str(product.get('status')) != '1' or
            (product.get('keyword_state') or {}).get('sif_state') != 'verified'):
            continue
        actions = product.get('actions') or []
        for row in (product.get('keyword_state') or {}).get('terms') or []:
            keyword = str(row.get('keyword') or '').strip()
            sources = row.get('sources') or []
            is_competitor_gap = ('sif_competitor_gap' in sources and
                                 row.get('current_competitor_gap') is True)
            if (not row.get('id') or not keyword or
                re.fullmatch(r'B0[A-Z0-9]{8}', keyword, re.I) or
                not ('sif_asin_signals' in sources or is_competitor_gap) or
                (not is_competitor_gap and not (row.get('weekly_volume') or 0) > 0) or
                (is_competitor_gap and row.get('weekly_volume') is not None and
                 row.get('weekly_volume') <= 0) or
                row.get('internal_evidence') or
                (row.get('tracking') or {}).get('state') not in {'active', 'candidate'} or
                any(target.get('match_type') == 'exact' and
                    all(target.get(field) == 'enabled' for field in
                        ('target_state', 'campaign_state', 'ad_group_state'))
                    for target in (row.get('keyword_targets') or []))):
                continue
            normalized = normalize_keyword(keyword)
            if any(action.get('kind') == 'exact' and
                   normalize_keyword(str(action.get('normalized_keyword') or action.get('query') or '')) == normalized
                   for action in actions):
                continue
            key = f"sif-probe:{profile}:{row['id']}"
            candidates[key] = {
                'action_key': key, 'kind': 'sif_probe', 'profile_id': profile,
                'sid': str(product['sid']), 'site': product['site'],
                'asin': product['asin'], 'product_key': product['key'],
                'query': keyword, 'normalized_keyword': normalized,
                'weekly_volume': row.get('weekly_volume'),
                'volume_period': row.get('volume_period'),
                'natural_rank_display': row.get('natural_rank_display'),
                'ad_rank_display': row.get('ad_rank_display'),
                'source_keyword_id': str(row['id']),
                'source': ('sif_competitor_gap' if is_competitor_gap
                           else 'sif_asin_signals'),
                'reviewable': False, 'executable': False,
                'blocked_reason': '活跃精准投放状态、承接广告组与出价尚未核实',
            }
    return candidates
