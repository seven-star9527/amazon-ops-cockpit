"""Conservative shop/site/child-ASIN identity and profile joins."""


def product_key(sid: str, site: str, asin: str) -> str:
    if not sid or not site or not asin:
        raise ValueError("product requires sid, site and child ASIN")
    return f"{str(sid).strip()}|{site.strip().upper()}|{asin.strip().upper()}"


def map_profiles(rows: list[dict]) -> dict[str, str]:
    result: dict[str, str] = {}
    for row in rows:
        profile = str(row.get("profile_id") or row.get("profileId") or "").strip()
        sid = str(row.get("s_id") or row.get("sid") or "").strip()
        if not profile or not sid:
            continue
        if profile in result and result[profile] != sid:
            raise ValueError(f"profile {profile} maps to multiple stores")
        result[profile] = sid
    return result
