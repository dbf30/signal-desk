import sys, numpy as np, pandas as pd
sys.argv=['x','none']
exec(open('swing_v2.py').read().split('if __name__')[0])
d=dev2.copy(); d['res']=d.r-d.groupby('group').r.transform('mean')
h1,h2=d[d.fill_date<=MID],d[d.fill_date>MID]
for f in FACT[1:]:
    g=d.groupby(f,observed=True).res; t=pd.DataFrame({'n':g.size(),'res':g.mean().round(3)})
    t['h1']=h1.groupby(f,observed=True).res.mean().round(3); t['h2']=h2.groupby(f,observed=True).res.mean().round(3)
    big=t[t.n>=150]; best,worst=big.res.idxmax(),big.res.idxmin(); gap=big.res[best]-big.res[worst]
    holds=(t.h1[best]>t.h1[worst]) and (t.h2[best]>t.h2[worst])
    print(f, 'PASS' if gap>=0.15 and holds else 'fail', f'best {best} worst {worst} gap {gap:.2f} holds {holds}'); print(t.to_string())
# longs only view
L=d[d.bull]; print('\nLONGS ONLY n',len(L),'avg',round(L.r.mean(),3)); S_=d[~d.bull]; print('SHORTS n',len(S_),'avg',round(S_.r.mean(),3))
for f in ['f_stretch','f_anchor','f_room','f_dist','f_vol','backdrop','f_score']:
    g=L.groupby(f,observed=True); print(f, {k:(len(v),round(v.res.mean(),3)) for k,v in g})
d.to_pickle('dev2.pkl')
