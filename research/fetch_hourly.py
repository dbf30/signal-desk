import json, urllib.request, pickle, time, pandas as pd
COINS = {"BTC":"BTC-USD","ETH":"ETH-USD","SOL":"SOL-USD","XRP":"XRP-USD",
         "ADA":"ADA-USD","DOGE":"DOGE-USD","LTC":"LTC-USD","BCH":"BCH-USD","LINK":"LINK-USD","BNB":"BNB-USD","XLM":"XLM-USD","TRX":"TRX-USD"}
def fetch(y):
    last=None
    for host in ("query1.finance.yahoo.com","query2.finance.yahoo.com"):
        try:
            url=f"https://{host}/v8/finance/chart/{y}?range=730d&interval=60m"
            with urllib.request.urlopen(urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0"}),timeout=40) as r:
                res=json.load(r)["chart"]["result"][0]
            q=res["indicators"]["quote"][0]
            df=pd.DataFrame({k:q[k] for k in ("open","high","low","close","volume")},index=pd.to_datetime(res["timestamp"],unit="s",utc=True)).dropna(subset=["open","high","low","close"])
            return df[~df.index.duplicated(keep="last")]
        except Exception as e: last=e
    raise RuntimeError(f"{y}: {last}")
out={}
for s,y in COINS.items():
    out[s]=fetch(y); print(s,len(out[s]),out[s].index[0],out[s].index[-1],flush=True); time.sleep(0.5)
pickle.dump(out,open("hourly.pkl","wb"))
