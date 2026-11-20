"""Build the blind relabeling packet from blind_labels_random_input.csv.
Drops episode_id and task_id. Usage: build_main_packet.py input.csv out.json [slots.csv | --exclude slots.csv]"""
import csv, json, sys, collections as C
csv.field_size_limit(10**9)
BIG=50
def item(r):
    w=json.loads(r['writes_after_B'] or '[]')
    tot=C.defaultdict(lambda:[0,0]); summ=C.Counter(); nflag=0
    for c in w:
        summ[(c['api'],'error' if c.get('error') else 'ok')]+=1
        dl=c.get('delta') or {}
        if any(max(v['n_added'],v['n_removed'])>=BIG for v in dl.values()):
            c['possible_snapshot_artifact']=True; nflag+=1; continue
        for t,v in dl.items(): tot[t][0]+=v['n_added']; tot[t][1]+=v['n_removed']
    return {'slot':int(r['slot']),'task':r['instruction'],'reproduced':r['reproduced'],'reason':r['reason'],
      'A_to_B_made_by_failed_block':json.loads(r['made_by_failed_block'] or '{}'),
      'net_B_to_C':json.loads(r['net_B_to_C'] or '{}'),'n_writes_after_B':r['n_writes_after_B'],
      'writes_after_B_summary':[{'api':a,'status':s,'count':n} for (a,s),n in summ.items()],
      'writes_after_B':w,
      'per_call_delta_totals':[{'table':t,'rows_added':a,'rows_removed':b} for t,(a,b) in sorted(tot.items())],
      'calls_flagged_as_possible_snapshot_artifact':nflag}
rows=list(csv.DictReader(open(sys.argv[1],encoding='utf-8')))
sel=None; excl=set()
if len(sys.argv)>3:
    if sys.argv[3]=='--exclude': excl={r['slot'] for r in csv.DictReader(open(sys.argv[4],encoding='utf-8-sig'))}
    else: sel={r['slot'] for r in csv.DictReader(open(sys.argv[3],encoding='utf-8-sig'))}
out=[item(r) for r in rows if (sel is None or r['slot'] in sel) and r['slot'] not in excl]
json.dump(out,open(sys.argv[2],'w',encoding='utf-8'),ensure_ascii=False,indent=1)
print(len(out))
