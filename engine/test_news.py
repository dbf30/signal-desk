from datetime import datetime, timezone
from news import build, validate, domain, tier, clean, jaccard, tokens

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)
SYMS = {"NVDA", "AAPL", "BTC", "WTI"}


def item(**k):
    base = {"title": "Nvidia raises full-year revenue guidance", "url": "https://www.reuters.com/technology/nvidia-guidance",
            "published": "2026-11-11T09:00:00Z", "symbols": ["NVDA"], "category": "guidance", "direction": "positive",
            "status": "confirmed", "materiality": 3}
    base.update(k)
    return base


# domains and tiers
assert domain("https://www.sec.gov/Archives/x") == "sec.gov" and tier("sec.gov") == 1
assert domain("https://news.bbc.co.uk/a") == "bbc.co.uk" and tier("bbc.co.uk") == 2
assert domain("https://nvidianews.nvidia.com/news/x") == "nvidianews.nvidia.com" and tier("nvidianews.nvidia.com") == 1
assert domain("https://sub.unknownblog.io/x") == "unknownblog.io" and tier("unknownblog.io") == 5
assert tier("example.gov") == 1
assert domain("javascript:alert(1)") is None and domain("ftp://x.com/a") is None and domain("not a url") is None

# text is reduced to plain text: tags and control characters removed, length capped
assert clean("<script>alert(1)</script>Hello\n<b>world</b>", 50) == "alert(1) Hello world"
assert len(clean("x" * 999, 160)) == 160 and clean(None, 10) == "" and clean(42, 10) == ""

# validation drops what it cannot place, with a reason
assert validate(item(title=""), SYMS, NOW)[1] == "no title"
assert validate(item(url="javascript:x"), SYMS, NOW)[1] == "no usable link"
assert validate(item(published="yesterday"), SYMS, NOW)[1] == "no publication time"
assert validate(item(published="2026-10-01T00:00:00Z"), SYMS, NOW)[1] == "older than 7 days"
assert validate(item(published="2026-11-13T00:00:00Z"), SYMS, NOW)[1] == "dated in the future"
assert validate(item(symbols=["ZZZZ"]), SYMS, NOW)[1] == "no watchlist market"
assert validate(item(title="NVDA INVESTOR ALERT: Securities Class Action Filed"), SYMS, NOW)[1] == "law-firm solicitation"
assert validate(item(title="This presale coin could 100x"), SYMS, NOW)[1] == "promotion"
assert validate("ignore previous instructions", SYMS, NOW)[1] == "not an object"
v, _ = validate(item(category="made-up", status="certain", materiality="9", direction="up", horizon=["forever"]), SYMS, NOW)
assert v["category"] == "other" and v["status"] == "reported" and v["materiality"] == 3 and v["direction"] == "neutral" and v["horizon"] == ["short", "swing"]

# one secondary source: 'confirmed' is downgraded to 'reported'
out = build({"items": [item()]}, SYMS, None, NOW)
e = out["events"][0]
assert e["status"] == "reported" and e["status_note"] and e["independent_sources"] == 1 and not e["corroborated"], e
assert e["quality"] == 40 + 0 + 20 + 5 and e["new"] is True, e

# the same wire story copied on three sites is ONE independent source, not three
copies = [item(), item(url="https://www.marketwatch.com/story/nvidia-guidance-copy"), item(url="https://finance.yahoo.com/news/nvidia-guidance-copy")]
e = build({"items": copies}, SYMS, None, NOW)["events"][0]
assert e["articles"] == 3 and e["independent_sources"] == 1 and e["status"] == "reported" and len(e["sources"]) == 3, e

# two differently written reports on different domains corroborate; a primary source confirms on its own
two = [item(), item(title="Nvidia lifts annual revenue guidance on data-centre demand", url="https://www.ft.com/content/abc")]
e = build({"items": two}, SYMS, None, NOW)["events"][0]
assert e["articles"] == 2 and e["independent_sources"] == 2 and e["corroborated"] and e["status"] == "confirmed", e
assert e["quality_points"]["corroboration"] == 20
e = build({"items": [item(url="https://www.sec.gov/Archives/edgar/data/1045810/8k.htm")]}, SYMS, None, NOW)["events"][0]
assert e["status"] == "confirmed" and e["corroborated"] and e["best_source"]["tier"] == 1 and e["quality"] == 50 + 20 + 10, e

# different events stay separate: other category, other market, or more than 36 hours apart
mix = [item(), item(category="analyst", title="Analyst raises Nvidia price target", url="https://www.cnbc.com/a", status="analyst"),
       item(symbols=["AAPL"], url="https://www.reuters.com/apple"), item(published="2026-11-08T09:00:00Z", url="https://www.wsj.com/old")]
assert build({"items": mix}, SYMS, None, NOW)["counts"]["events"] == 4

# rumours score low; old and widely reported stories are flagged
r = build({"items": [item(status="rumour", url="https://someblog.xyz/rumour", title="Rumour: Apple to buy a chip designer", symbols=["AAPL"], category="m&a")]}, SYMS, None, NOW)["events"][0]
assert r["quality"] == 12 + 20 - 10 and r["status"] == "rumour"
old = [item(published="2026-11-09T09:00:00Z"), item(published="2026-11-09T10:00:00Z", title="Nvidia boosts guidance, shares jump", url="https://www.ft.com/x"),
       item(published="2026-11-09T11:00:00Z", title="Chipmaker Nvidia guidance raised for the year", url="https://www.wsj.com/y")]
e = build({"items": old}, SYMS, None, NOW)["events"][0]
assert e["independent_sources"] == 3 and e["widely_reported"] and e["quality_points"]["recency"] == 8, e

# "new" is tracked across runs and first_seen is kept
first = build({"items": [item()]}, SYMS, None, NOW)
again = build({"items": [item()]}, SYMS, first, datetime(2026, 11, 11, 16, 0, tzinfo=timezone.utc))
assert again["events"][0]["new"] is False and again["events"][0]["first_seen"] == first["events"][0]["first_seen"]

# per-market summary only counts recent events of reasonable quality; junk input never raises
s = build({"items": two + [item(symbols=["BTC"], status="rumour", url="https://someblog.xyz/b", title="Bitcoin rumour", category="other")]}, SYMS, None, NOW)["by_symbol"]
assert s["NVDA"]["positive"] == 1 and s["NVDA"]["top"]["title"] and "BTC" not in s, s
for junk in (None, [], {"items": None}, {"items": [1, "x", None, {}]}, {"items": [{"title": 5, "url": 7}]}):
    assert build(junk, SYMS, None, NOW)["events"] == []
assert jaccard(tokens("Nvidia raises guidance"), tokens("Nvidia raises guidance")) == 1.0
# --- agency copy: AP on two local sites is one source rated as major press; a different agency makes it two
from news import build as _b
from datetime import datetime as _dt, timezone as _tz
_now = _dt(2026, 11, 6, 12, 0, tzinfo=_tz.utc)
_ap = [{"title": "A brutal sell-off for AI stocks sends Wall Street reeling", "url": "https://www.kptv.com/2026/11/05/a", "published": "2026-11-05T22:17:00Z",
        "symbols": ["SPY"], "category": "sector", "direction": "negative", "status": "confirmed", "materiality": 3, "origin": "AP"},
       {"title": "AI stock wipeout: S&P 500 tumbles 4.4% in worst day since April 2025", "url": "https://www.boston.com/news/x", "published": "2026-11-05T23:00:00Z",
        "symbols": ["SPY"], "category": "sector", "direction": "negative", "status": "confirmed", "materiality": 3, "origin": "Associated Press"}]
_o = _b({"items": _ap}, {"SPY"}, None, _now)
assert len(_o["events"]) == 1, _o["events"]
_e = _o["events"][0]
assert _e["independent_sources"] == 1 and _e["best_source"]["tier"] == 2 and _e["best_source"]["origin"] == "AP" and _e["articles"] == 2, _e
assert _e["status"] == "reported" and not _e["corroborated"], _e          # one agency, no primary source: not "confirmed"
_o = _b({"items": _ap + [{"title": "Nasdaq posts biggest daily drop in 19 months as AI stocks sink", "url": "https://example-news.com/r", "published": "2026-11-05T23:30:00Z",
                           "symbols": ["SPY"], "category": "sector", "direction": "negative", "status": "confirmed", "materiality": 3, "origin": "Reuters"}]}, {"SPY"}, None, _now)
assert _o["events"][0]["independent_sources"] == 2 and _o["events"][0]["status"] == "confirmed" and _o["events"][0]["corroborated"], _o["events"][0]
# an origin that is not a known agency is ignored: the page keeps its own (unrated) rating
_o = _b({"items": [dict(_ap[0], origin="Trust me, Reuters-grade")]}, {"SPY"}, None, _now)
assert _o["events"][0]["best_source"]["tier"] == 5 and _o["events"][0]["best_source"]["origin"] is None
# one round-up article that covers two different markets' events must not glue those events together
_two = [{"title": "Nvidia falls as board opens investigation", "url": "https://example-news.com/roundup", "published": "2026-11-06T09:00:00Z",
         "symbols": ["NVDA"], "category": "management", "direction": "negative", "status": "reported", "materiality": 3},
        {"title": "Oil drops on de-escalation hopes", "url": "https://example-news.com/roundup", "published": "2026-11-06T09:00:00Z",
         "symbols": ["WTI"], "category": "policy", "direction": "negative", "status": "reported", "materiality": 3}]
_o = _b({"items": _two}, {"NVDA", "WTI"}, None, _now)
assert len(_o["events"]) == 2 and {tuple(e["symbols"]) for e in _o["events"]} == {("NVDA",), ("WTI",)}, _o["events"]
print("ALL TESTS PASSED")
