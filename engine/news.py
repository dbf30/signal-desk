"""
News intelligence for Signal Desk: the deterministic half.

Usage:  python3 news.py --raw raw_news.json --out news.json [--prev news.json] [--now ISO]

A research step (an AI reading the web) writes raw_news.json: one item per article it found. This module
never trusts that file. It validates every field, strips markup, drops what it cannot place, then:
  - rates each source by what it IS (regulator, company, wire, specialist, press-release wire, unknown);
  - merges articles about the same event (same market, same kind of news, within 36 hours; for kinds of news
    that can repeat within a day the headlines must also overlap, unless both are top-materiality stories
    pointing the same way within 12 hours);
  - counts INDEPENDENT sources: copies of one wire story on five sites count once;
  - downgrades "confirmed" to "reported" unless a primary source or two independent ones back it;
  - scores quality 0-100 from source, corroboration, age and status, and shows the working;
  - marks what is new since the last run and what is old and widely reported (likely priced in).

News does not change any score or grade: Signal Desk tested news tone and attention in Nov 2026 and they did not
improve the signals. Events are shown as context and as risks next to each setup.

raw item fields: title, summary, url, published (ISO, UTC), symbols [..] or ["MARKET"], category, direction,
status, materiality 1-3, horizon ["short","swing"], also_urls [..], related [..], why, origin.
origin (optional): the news agency whose story the page carries ("AP", "Reuters", "Bloomberg", "AFP", "Dow Jones").
Agency copy on a local news site is rated as the agency, and every copy of one agency's story counts as ONE source.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from urllib.parse import urlsplit

CATEGORIES = {"earnings", "guidance", "analyst", "m&a", "contract", "product", "regulatory", "legal", "insider",
              "institutional", "policy", "rates", "economic_data", "sector", "unusual_activity", "supply", "listing",
              "management", "other"}
DIRECTIONS = {"positive", "negative", "neutral", "mixed"}
STATUSES = {"confirmed", "reported", "rumour", "opinion", "analyst"}
HORIZONS = {"short", "swing"}
DEFAULT_HORIZON = {"analyst": ["short"], "unusual_activity": ["short"], "economic_data": ["short", "swing"]}

# tier: 1 primary (the body that made the news) / 2 major wire or financial press / 3 specialist press /
#       4 press-release wire (what an issuer says about itself) / 5 unknown
TIER_NAME = {1: "Primary source", 2: "Major press", 3: "Specialist press", 4: "Press-release wire", 5: "Unrated source"}
TIER_BASE = {1: 50, 2: 40, 3: 28, 4: 30, 5: 12}
TIERS = {
    # regulators, central banks, statistics offices, exchanges
    "sec.gov": 1, "federalreserve.gov": 1, "bankofengland.co.uk": 1, "ecb.europa.eu": 1, "boj.or.jp": 1, "bls.gov": 1,
    "bea.gov": 1, "treasury.gov": 1, "eia.gov": 1, "usda.gov": 1, "opec.org": 1, "cftc.gov": 1, "ons.gov.uk": 1,
    "destatis.de": 1, "cmegroup.com": 1, "nasdaq.com": 2, "nyse.com": 1, "fca.org.uk": 1, "whitehouse.gov": 1,
    "europa.eu": 1, "gov.uk": 1, "census.gov": 1, "newyorkfed.org": 1, "stlouisfed.org": 1,
    # companies on the watchlist (investor relations / newsrooms)
    "apple.com": 1, "microsoft.com": 1, "nvidia.com": 1, "nvidianews.nvidia.com": 1, "aboutamazon.com": 1, "amazon.com": 1,
    "tesla.com": 1, "ethereum.org": 1, "solana.com": 1, "ripple.com": 1, "bitcoin.org": 1,
    # wires and major financial press
    "reuters.com": 2, "bloomberg.com": 2, "ft.com": 2, "wsj.com": 2, "apnews.com": 2, "cnbc.com": 2, "barrons.com": 2,
    "marketwatch.com": 2, "economist.com": 2, "bbc.co.uk": 2, "bbc.com": 2, "nytimes.com": 2, "theguardian.com": 2,
    "nikkei.com": 2, "afp.com": 2, "dowjones.com": 2,
    # specialist / trade press
    "coindesk.com": 3, "theblock.co": 3, "cointelegraph.com": 3, "decrypt.co": 3, "tokenomist.ai": 3, "cryptorank.io": 3,
    "oilprice.com": 3, "kitco.com": 3, "mining.com": 3, "argusmedia.com": 3, "spglobal.com": 3, "fxstreet.com": 3,
    "forexlive.com": 3, "investinglive.com": 3, "tradingeconomics.com": 3, "morningstar.com": 3, "rttnews.com": 3,
    "cryptoslate.com": 3, "investing.com": 3, "seekingalpha.com": 3, "finance.yahoo.com": 3, "yahoo.com": 3,
    "techcrunch.com": 3, "theverge.com": 3, "electrek.co": 3, "semafor.com": 3, "axios.com": 3, "farmdoc.illinois.edu": 3,
    "agweb.com": 3, "dtnpf.com": 3, "investopedia.com": 3, "fool.com": 3, "benzinga.com": 3,
    # press-release wires
    "prnewswire.com": 4, "businesswire.com": 4, "globenewswire.com": 4, "accesswire.com": 4, "newsfilecorp.com": 4,
}
WIRES = {"ap": "AP", "associated press": "AP", "reuters": "Reuters", "bloomberg": "Bloomberg", "afp": "AFP",
         "dow jones": "Dow Jones", "dow jones newswires": "Dow Jones"}
TWO_PART_TLDS = {"co.uk", "org.uk", "gov.uk", "ac.uk", "com.au", "co.jp", "or.jp", "com.cn", "co.in", "com.br"}
SOLICITATION = re.compile(r"class action|lead plaintiff|investor alert|shareholder alert|shareholder rights|law firm|"
                          r"investigation on behalf|securities fraud lawsuit|encouraged to contact|deadline alert", re.I)
PROMO = re.compile(r"\b(presale|pre-sale|100x|1000x|next big|to the moon|guaranteed|price prediction)\b", re.I)
TAG = re.compile(r"<[^>]{0,200}>")
CTRL = re.compile(r"[\x00-\x1f\x7f]")
WORD = re.compile(r"[a-z0-9]+")
STOP = {"the", "a", "an", "to", "of", "in", "on", "for", "and", "as", "at", "by", "with", "its", "is", "after", "from",
        "says", "say", "said", "new", "will", "over", "amid", "into", "that", "this", "has", "have", "be", "are"}
MAX_AGE_H = 7 * 24
# kinds of news where one market has at most one event in a 36-hour window, however the headlines are worded
ONE_EVENT = {"earnings", "guidance", "rates", "economic_data", "m&a", "supply", "listing"}


def clean(s, n: int) -> str:
    """Plain text only: no tags, no control characters, single spaces, capped length."""
    if not isinstance(s, str):
        return ""
    s = CTRL.sub(" ", TAG.sub(" ", s))
    return re.sub(r"\s+", " ", s).strip()[:n]


def domain(url: str) -> str | None:
    try:
        u = urlsplit(url)
    except Exception:
        return None
    if u.scheme not in ("http", "https") or not u.hostname:
        return None
    h = u.hostname.lower().removeprefix("www.")
    if h in TIERS:
        return h
    parts = h.split(".")
    if len(parts) >= 3 and ".".join(parts[-2:]) in TWO_PART_TLDS:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else None


def tier(dom: str | None) -> int:
    if not dom:
        return 5
    if dom in TIERS:
        return TIERS[dom]
    if dom.endswith(".gov") or dom.endswith(".gov.uk") or dom.endswith(".europa.eu"):
        return 1
    return 5


def canonical(url: str) -> str:
    u = urlsplit(url)
    return f"{(u.hostname or '').lower().removeprefix('www.')}{u.path.rstrip('/')}"


def tokens(title: str) -> set[str]:
    """Words of a headline, lower-cased, without filler words; plurals folded (stocks -> stock)."""
    return {(w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w)
            for w in WORD.findall(title.lower()) if w not in STOP and len(w) > 1}


def jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def parse_time(s) -> datetime | None:
    if not isinstance(s, str) or not s:
        return None
    try:
        t = datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t.astimezone(timezone.utc)


def validate(item: dict, symbols: set[str], now: datetime) -> tuple[dict | None, str | None]:
    """Returns (clean item, None) or (None, reason dropped)."""
    if not isinstance(item, dict):
        return None, "not an object"
    title = clean(item.get("title"), 160)
    url = item.get("url") if isinstance(item.get("url"), str) else ""
    dom = domain(url)
    if not title:
        return None, "no title"
    if not dom:
        return None, "no usable link"
    if SOLICITATION.search(title):
        return None, "law-firm solicitation"
    if PROMO.search(title):
        return None, "promotion"
    t = parse_time(item.get("published"))
    if t is None:
        return None, "no publication time"
    age_h = (now - t).total_seconds() / 3600
    if age_h < -6:
        return None, "dated in the future"
    if age_h > MAX_AGE_H:
        return None, "older than 7 days"
    syms = [s for s in (item.get("symbols") or []) if isinstance(s, str) and (s in symbols or s == "MARKET")]
    if not syms:
        return None, "no watchlist market"
    cat = item.get("category") if item.get("category") in CATEGORIES else "other"
    status = item.get("status") if item.get("status") in STATUSES else "reported"
    try:
        mat = min(3, max(1, int(item.get("materiality", 1))))
    except (TypeError, ValueError):
        mat = 1
    hz = [h for h in (item.get("horizon") or []) if h in HORIZONS] or DEFAULT_HORIZON.get(cat, ["short", "swing"])
    extra = []
    for u in (item.get("also_urls") or [])[:8]:
        d = domain(u) if isinstance(u, str) else None
        if d:
            extra.append({"url": u[:500], "domain": d, "tier": tier(d)})
    origin = WIRES.get(clean(item.get("origin"), 30).lower())
    tr = min(tier(dom), 2) if origin else tier(dom)
    return {
        "title": title, "summary": clean(item.get("summary"), 400), "why": clean(item.get("why"), 300),
        "url": url[:500], "domain": dom, "tier": tr, "origin": origin, "who": origin or dom,
        "published": t, "age_h": max(0.0, age_h), "timed": "T" in str(item.get("published")),
        "symbols": sorted(set(syms)), "category": cat,
        "direction": item.get("direction") if item.get("direction") in DIRECTIONS else "neutral",
        "status": status, "materiality": mat, "horizon": hz,
        "related": [clean(r, 20) for r in (item.get("related") or [])[:8] if isinstance(r, str)],
        "extra": extra, "tok": tokens(title),
    }, None


def cluster(items: list[dict]) -> list[list[dict]]:
    items = sorted(items, key=lambda i: i["published"])
    groups: list[list[dict]] = []
    for it in items:
        for g in groups:
            head = g[0]
            same_market = bool(set(head["symbols"]) & set(it["symbols"]))
            close = abs((it["published"] - head["published"]).total_seconds()) <= 36 * 3600
            # a top-materiality story on one market, same kind and direction, within 12 hours is one event
            # even when two desks word the headline differently
            big = (it["materiality"] == 3 and head["materiality"] == 3 and it["direction"] == head["direction"]
                   and abs((it["published"] - head["published"]).total_seconds()) <= 12 * 3600)
            # the same page counts as the same event only for the same market: one round-up can cover several events
            if (same_market and canonical(it["url"]) in {canonical(x["url"]) for x in g}) or (
                    same_market and close and it["category"] == head["category"]
                    and (it["category"] in ONE_EVENT or big or max(jaccard(it["tok"], x["tok"]) for x in g) >= 0.25)):
                g.append(it)
                break
        else:
            groups.append([it])
    return groups


def event_from(g: list[dict], now: datetime) -> dict:
    lead = min(g, key=lambda i: (i["tier"], -len(i["summary"]), i["published"]))   # best source, fullest account, tells the story
    first = min(i["published"] for i in g)
    sources, seen = [], set()
    for i in g:
        for s in [{"url": i["url"], "domain": i["domain"], "tier": i["tier"], "origin": i["origin"],
                   "published": i["published"].strftime("%Y-%m-%dT%H:%MZ")}] + i["extra"]:
            if canonical(s["url"]) not in seen:
                seen.add(canonical(s["url"]))
                sources.append(s)
    # independent sources: one per publisher (a news agency counts once however many sites carry its story),
    # and near-identical titles (unlabelled syndicated copies) count once
    indep: list[dict] = []
    for i in sorted(g, key=lambda i: (i["tier"], i["published"])):
        if any(i["who"] == j["who"] or jaccard(i["tok"], j["tok"]) >= 0.9 for j in indep):
            continue
        indep.append(i)
    extra_domains = {s["domain"] for s in sources} - {i["domain"] for i in g} - {i["who"] for i in g}
    n_indep = len(indep) + len(extra_domains)
    best_tier = min(s["tier"] for s in sources)
    has_primary = best_tier == 1 or (best_tier == 4 and lead["category"] in ("earnings", "guidance", "contract", "product", "m&a", "management"))
    status = lead["status"]
    note = None
    if status == "confirmed" and not has_primary and n_indep < 2:
        status, note = "reported", "Marked 'reported': one secondary source, no primary source."
    age_h = (now - first).total_seconds() / 3600
    pts = {"source": TIER_BASE[best_tier],
           "corroboration": 0 if n_indep < 2 else 20 if n_indep == 2 else 30,
           "recency": 20 if age_h <= 6 else 15 if age_h <= 24 else 8 if age_h <= 72 else 0,
           "status": {"confirmed": 10, "reported": 5, "analyst": 3, "opinion": 0, "rumour": -10}[status]}
    quality = max(0, min(100, sum(pts.values())))
    mat = max(i["materiality"] for i in g)
    syms = sorted({s for i in g for s in i["symbols"]})
    key = hashlib.sha1(("|".join(syms) + "|" + lead["category"] + "|" + " ".join(sorted(lead["tok"]))[:120]).encode()).hexdigest()[:12]
    return {
        "id": key, "title": lead["title"], "summary": lead["summary"], "why": lead["why"],
        "symbols": syms, "related": sorted({r for i in g for r in i["related"]}),
        "category": lead["category"], "direction": lead["direction"], "status": status, "status_note": note,
        "materiality": mat, "horizon": sorted({h for i in g for h in i["horizon"]}),
        "published": first.strftime("%Y-%m-%dT%H:%MZ"), "age_hours": round(max(0.0, age_h), 1),
        "published_precision": "time" if min(g, key=lambda i: i["published"])["timed"] else "day",
        "sources": sources, "independent_sources": n_indep, "articles": len(g),
        "best_source": {"domain": lead["domain"], "origin": lead["origin"], "tier": best_tier, "tier_name": TIER_NAME[best_tier]},
        "corroborated": bool(has_primary or n_indep >= 2),
        "quality": quality, "quality_points": pts,
        "widely_reported": bool(age_h > 24 and n_indep >= 3),
        "impact": round(mat * quality / 100, 2),
    }


def build(raw: dict, symbols: set[str], prev: dict | None = None, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    good, dropped = [], {}
    for it in (raw.get("items") if isinstance(raw, dict) else None) or []:
        v, why = validate(it, symbols, now)
        if v:
            good.append(v)
        else:
            dropped[why] = dropped.get(why, 0) + 1
    events = [event_from(g, now) for g in cluster(good)]
    first_seen = {e["id"]: e.get("first_seen") for e in (prev or {}).get("events", [])}
    stamp = now.strftime("%Y-%m-%dT%H:%MZ")
    for e in events:
        e["first_seen"] = first_seen.get(e["id"]) or stamp
        e["new"] = e["id"] not in first_seen
    events.sort(key=lambda e: (-e["impact"], e["age_hours"]))
    by_symbol: dict[str, dict] = {}
    for e in events:
        if e["age_hours"] > 72 or e["quality"] < 40:
            continue
        for s in e["symbols"]:
            b = by_symbol.setdefault(s, {"positive": 0, "negative": 0, "other": 0, "top": None})
            b["positive" if e["direction"] == "positive" else "negative" if e["direction"] == "negative" else "other"] += 1
            if b["top"] is None:
                b["top"] = {"id": e["id"], "title": e["title"], "direction": e["direction"], "status": e["status"],
                            "quality": e["quality"], "url": e["sources"][0]["url"], "published": e["published"]}
    return {"generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "events": events[:60], "by_symbol": by_symbol,
            "counts": {"articles_in": len((raw.get("items") if isinstance(raw, dict) else None) or []), "articles_kept": len(good),
                       "events": len(events), "new_events": sum(e["new"] for e in events)},
            "dropped": dropped,
            "method": "Quality = source (primary 50, major press 40, press-release wire 30, specialist 28, unrated 12) "
                      "+ corroboration (2 independent sources +20, 3 or more +30) + recency (6h +20, 24h +15, 72h +8) "
                      "+ status (confirmed +10, reported +5, analyst +3, rumour -10). Copies of one story count once."}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", required=True)
    ap.add_argument("--out", default="news.json")
    ap.add_argument("--prev")
    ap.add_argument("--now")
    a = ap.parse_args()
    from run import WATCHLIST
    symbols = {sym for _, sym, _, _ in WATCHLIST}
    try:
        raw = json.load(open(a.raw))
    except Exception as ex:
        print("news: raw file unusable:", ex)
        return 1
    prev = None
    if a.prev:
        try:
            prev = json.load(open(a.prev))
        except Exception:
            prev = None
    out = build(raw, symbols, prev, parse_time(a.now) if a.now else None)
    json.dump(out, open(a.out, "w"), separators=(",", ":"))
    c = out["counts"]
    print(f"news: {c['articles_in']} articles in, {c['articles_kept']} kept, {c['events']} events ({c['new_events']} new), dropped {out['dropped']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
