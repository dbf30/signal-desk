import sys, os, json, numpy as np, pandas as pd
sys.argv=['x','none']
src=open('grade_model.py').read().split('MP = os.path.join')[0].replace('mode = sys.argv[1]; sys.argv = [sys.argv[0], "none"]','mode="x"')
exec(src)
M=json.load(open('results/grade_model.json'))
X=pd.concat([trades(("watch",), pd.Timestamp("2023-01-01"), HOLD1), trades(("unseen",), DEV0, HOLD1)])
X=X.assign(pred=predict(M,X)); X['grade']=grade(X.pred)
print("second-look sets, by group: n, avg R, and avg R for above/below the group's median prediction")
rows=[]
for g,v in X.groupby('group'):
    med=v.pred.median(); hi=v[v.pred>med].r; lo=v[v.pred<=med].r
    rows.append((g,len(v),round(v.r.mean(),3),round(hi.mean(),3) if len(hi) else None,round(lo.mean(),3) if len(lo) else None, v.grade.value_counts().to_dict()))
print(pd.DataFrame(rows,columns=['group','n','avg','hi_half','lo_half','grades']).to_string())
Fc=factor_cols(X); X2=X.join(Fc, rsuffix='_f'); X2['res']=X2.r-X2.groupby('group').r.transform('mean')
for f in ['backdrop_f','location','freshness','overhead','anchor']:
    print(f, {k:(len(v),round(v.res.mean(),3)) for k,v in X2.groupby(f)})
print("A+ by class:", X[X.grade=='A+'].groupby('cls').r.agg(['size','mean']).round(3).to_dict('index'))
print("longs all:", round(X[X.bull].r.mean(),3), len(X[X.bull]), " shorts all:", round(X[~X.bull].r.mean(),3), len(X[~X.bull]))
# years: A+ by year
a=X[X.grade=='A+']; print(a.groupby(a.fill_date.dt.year).r.agg(['size','mean']).round(2).T.to_string())
