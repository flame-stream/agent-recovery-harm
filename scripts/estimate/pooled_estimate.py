"""Stratified estimate of P(harm | confirmed partial execution) over the registry.
Strata: legacy (N=1403), modern (N=514); 100 sampled episodes each.
Cluster bootstrap over runs within each stratum, fixed seed."""
import csv, sys, random, collections as C
rows=list(csv.DictReader(open(sys.argv[1],encoding='utf-8')))
N={'legacy':1403,'modern':514}
def est(rs):
    num=den=0.0
    for g in N:
        s=[r for r in rs if r['group']==g]
        n=len(s)
        if n==0: return None
        conf=[r for r in s if r['partial']=='confirmed' and r['harmful_action'] in('yes','no')]
        harm=sum(r['harmful_action']=='yes' for r in conf)
        num+=N[g]*harm/n; den+=N[g]*len(conf)/n
    return num/den
print('point %.4f'%est(rows))
runs={g:C.defaultdict(list) for g in N}
for r in rows: runs[r['group']][r['source_run']].append(r)
rnd=random.Random(20261113); bs=[]
for _ in range(10000):
    rs=[]
    for g in N:
        keys=list(runs[g]); 
        for k in rnd.choices(keys,k=len(keys)): rs+=runs[g][k]
    e=est(rs)
    if e is not None: bs.append(e)
bs.sort(); print('boot mean %.4f  95%% CI [%.4f, %.4f]'%(sum(bs)/len(bs),bs[int(.025*len(bs))],bs[int(.975*len(bs))]))
print('runs per stratum',{g:len(runs[g]) for g in N})
