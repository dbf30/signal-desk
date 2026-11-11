# Scheduled task instructions, version 1 (in use 2 Nov – 11 Nov 2026)

Kept so the app can be rolled back. To roll back: republish `web/index.html` and `engine/*.py` from the `main`
branch as it stood at commit c9e012a to the artifact, then set the "Signal Desk update" task's instructions to the
text below. Trade rules (`trades.py`) are identical in both versions, and v1 code reads v2 data files.

---

You are refreshing "Signal Desk", Dylan's trading-signals app (stocks, indices, forex, commodity futures, bond futures, crypto, plus funded-account tools, swing and intraday setups and a live setup scorecard). It is a Claude artifact with slug eb0a514d-7537-426e-9c37-fd7720e28aa2 (https://claude.ai/artifact/W2NzW3zN3k8ivb52aTuFPF). It runs every 4 hours (01:40, 05:40, 09:40, 13:40, 17:40, 21:40 UK). Work unattended: do not ask questions. Do not change index.html, setup_stats.json, intraday_stats.json or the engine files. Do not give trading advice beyond what the app shows.

0. Run `TZ=Europe/London date +%H` and remember the UK hour. The run whose UK hour is 21 is the "close run" (just after the US stock market closes). The run whose UK hour is 09 is the "intraday run" (just after the 08:00-09:00 UK crypto range candle).

1. Load tools in one ToolSearch call: "select:mcp__claude-artifacts__read_file,mcp__claude-artifacts__list_files,mcp__claude-artifacts__get_artifact,mcp__claude-artifacts__publish_files,PushNotification".

2. Get the engine. Call read_file with slug and paths ["engine/engine.py.txt","engine/run.py.txt","engine/test_engine.py.txt","engine/levels.py.txt","engine/test_levels.py.txt","engine/trades.py.txt","engine/test_trades.py.txt","engine/scorecard.py.txt","engine/test_scorecard.py.txt","engine/intraday.py.txt","engine/test_intraday.py.txt","state.json","catalysts.json","scorecard.json","intraday.json"] (if the call is refused because state.json, catalysts.json, scorecard.json or intraday.json doesn't exist, repeat without the missing one). The tool saves each file to disk and prints the saved path of each. Copy them with `cp` (never retype them) into /tmp/sd: each engine/X.py.txt -> X.py, state.json -> prev.json, catalysts.json -> prev_catalysts.json, scorecard.json -> prev_scorecard.json, intraday.json -> prev_intraday.json. Verify with `sha256sum`:
   engine.py          752f618fa22f8e7b12948923dac96f371d0e3c234aea2fd726e6203f500bf364
   run.py             a052fcf53845c7a056a053b4f2b48e9f9262f4d2b3509166ee17e0ac7a2610c5
   test_engine.py     434f027fd342a8f62cad2b2841c19e62783abed28a92839dd1f41e8e22a6f32b
   levels.py          6baa028db0af0a73ecb910f7e8e6b95387a3e4aca7f30dc10b3f52ea9e66e05d
   test_levels.py     1860c62cb8c70a52b4b7c2ad90b75577ac35c9e2207033d0adf44a5e11dc298e
   trades.py          88c18a0996309a2528de4f1c543048689c297be653be1c4318336109370fa5c4
   test_trades.py     6ec4da913dc1a945312bf1395eb6eb744525296ea2349ea1b6bd09fd04a18f38
   scorecard.py       dbf04c138ddfa808964b9d190731df10ff0e5d0b6d827c0ea2c913509b7081f6
   test_scorecard.py  992310896bd0d5187fd4f51c493a3dcf275f937e9bf0cabce7d855c8c6a711f2
   intraday.py        6c57d5677bcdfecf41d6e25f67078c4bda2e9a61dc8e1287a4b2beb6f13d4b49
   test_intraday.py   77a4cfd995f9c160a75215b8877b7d17da7bd5b21b46a90ed472c5794f35b802
   If any hash differs, stop: send a PushNotification "Signal Desk: update failed (engine copy mismatch)" and end. Then run `cd /tmp/sd && python3 test_engine.py && python3 test_levels.py && python3 test_trades.py && python3 test_scorecard.py && python3 test_intraday.py`; each must end with ALL TESTS PASSED, otherwise notify "Signal Desk: update failed (engine tests)" and end.

3. Run `cd /tmp/sd && python3 run.py --out /tmp/sd/data.json`, adding `--prev /tmp/sd/prev.json` if that file exists. It downloads daily prices from query1/query2.finance.yahoo.com. If it prints "assets ok: 0", the price feed is blocked: on the 09:40 UK run only (UK hour 09), send PushNotification "Signal Desk: can't reach Yahoo Finance. Check query1.finance.yahoo.com and query2.finance.yahoo.com are allowed in claude.ai Settings > Capabilities." Either way continue to step 4 (still publish catalysts), but do not publish data.json, state.json, setups.json, scorecard.json or intraday.json. Never invent or hand-type any prices.
   If prices loaded, also run:
   a) `cd /tmp/sd && python3 levels.py --data /tmp/sd/data.json --out /tmp/sd/setups.json`. If it fails or prints "levels ok: 0", skip setups.json and step b this run, and mention it in the final reply.
   b) `cd /tmp/sd && python3 scorecard.py --data /tmp/sd/data.json --setups /tmp/sd/setups.json --out /tmp/sd/scorecard.json` adding `--prev /tmp/sd/prev_scorecard.json` if that file exists, and adding `--record` ONLY on the close run (UK hour 21). If it fails, skip scorecard.json and mention it in the final reply.
   c) `cd /tmp/sd && python3 intraday.py --data /tmp/sd/data.json --out /tmp/sd/intraday.json` adding `--prev /tmp/sd/prev_intraday.json` if that file exists. If it fails, skip intraday.json and mention it in the final reply.

4. Catalysts. (Word for word the same as step 4 of the task's current instructions; version 2 did not change it. Copy it from there.)

5. Publish. Call get_artifact for the slug to get the live version, then ONE publish_files call with slug, base_version = that version, mode "patch", and files: {"as":"data.json","path":"/tmp/sd/data.json"}, {"as":"state.json","path":"/tmp/sd/state.json"}, {"as":"setups.json","path":"/tmp/sd/setups.json"}, {"as":"scorecard.json","path":"/tmp/sd/scorecard.json"} and {"as":"intraday.json","path":"/tmp/sd/intraday.json"} (only those that step 3 produced), plus {"as":"catalysts.json","path":"/tmp/sd/catalysts.json"}. If publish_files refuses a path under /tmp, copy the files into your working directory and retry with those paths. On a version conflict, get_artifact again and retry once.

6. Notify. Build at most ONE PushNotification, under 200 characters, starting "Signal Desk:", from:
   a) Signal changes in /tmp/sd/alerts.txt. Crypto changes (BTC, ETH, SOL, XRP) count on every run. All other changes (stocks, indices, forex, commodities, bonds) count only on the close run (UK hour 21); on other runs leave them out of the notification (they still show in the app).
   b) Any watchlist coin (BTC, ETH, SOL, XRP) with an unlock in the next 3 days or named in a big_posts item, but only if that item's source URL is NOT already in /tmp/sd/prev_catalysts.json (so the same news isn't sent every 4 hours).
   c) Scorecard trades that closed this run (status changed from open to win/loss versus prev_scorecard.json): list them briefly, e.g. "AAPL long +2.1R".
   d) On the intraday run only (UK hour 09): today's crypto intraday levels from /tmp/sd/intraday.json, for plans with a bias and an entry, e.g. "BTC short 77952 stop 78262" (add "stopped" or "in trade" if that is already the status), ending "exit 20:00". Put d) first on that run; trim a)-c) to fit.
   If none of a)-d) has anything, send nothing.

7. Final reply: 3 lines max: assets updated, alerts, any errors.
