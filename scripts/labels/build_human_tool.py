"""Build a self-contained HTML page for human labeling.
Part 1: blind labeling of a random subsample of episodes on which both LLM annotators agree.
Part 2: non-blind verification of all continuations with a harmful final label.
Usage: build_human_tool.py all200.json final_labels.csv history_labels.csv second_40.csv second_160.csv adjudication_all.csv out.html
"""
import csv, json, random, sys

csv.field_size_limit(10**9)
SEED = 20261115
N_BLIND = 60
allp, fin, first, s40, s160, adj, out = sys.argv[1:8]
R = lambda p: list(csv.DictReader(open(p, encoding='utf-8-sig')))
packet = {str(x['slot']): x for x in json.load(open(allp, encoding='utf-8'))}
final = {r['slot']: r for r in R(fin)}
firstl = {r['slot']: r for r in R(first)}
second = {}
for p in (s40, s160):
    for r in R(p):
        v = list(r.values())
        second[v[0]] = {'h': v[1], 'r': v[2], 'k': v[3], 'b': v[4]}
adjud = {r['slot']: r for r in R(adj)}


def slim(x):
    calls = []
    for c in x['writes_after_B']:
        d = {}
        for t, v in (c.get('delta') or {}).items():
            d[t] = {'a': v['n_added'], 'r': v['n_removed'],
                    'A': [s[:400] for s in v.get('added', [])[:3]],
                    'R': [s[:400] for s in v.get('removed', [])[:3]]}
        calls.append({'api': c['api'], 'args': json.dumps(c['args'], ensure_ascii=False)[:600],
                      'err': (str(c['error'])[:300] if c.get('error') else None), 'd': d,
                      'art': bool(c.get('possible_snapshot_artifact'))})
    return {'slot': x['slot'], 'task': x['task'], 'repro': x['reproduced'], 'reason': x['reason'],
            'a2b': x['A_to_B_made_by_failed_block'], 'b2c': x['net_B_to_C'],
            'tot': x['per_call_delta_totals'], 'nart': x['calls_flagged_as_possible_snapshot_artifact'],
            'calls': calls}


rng = random.Random(SEED)
# the pool is the 'both agree' episodes; ', database' marks labels later checked against the database state
# (slot 26), which were in the pool when the sample was drawn
pool = sorted((s for s in final if final[s]['source'].startswith('both agree')), key=int)
blind_slots = rng.sample(pool, N_BLIND)
harm_slots = sorted((s for s in final if final[s]['harmful_action'] == 'yes'), key=int)
rng.shuffle(harm_slots)

blind = [slim(packet[s]) for s in blind_slots]
verify = []
for s in harm_slots:
    e = slim(packet[s])
    f = final[s]
    e['final'] = {'h': f['harmful_action'], 'k': f['harm_kind'], 'r': f['residual_violation'], 'src': f['source']}
    e['first'] = {'h': firstl[s]['harmful_action'], 'k': firstl[s]['harm_kind'], 'b': firstl[s]['basis']}
    e['second'] = second[s]
    e['adj'] = adjud[s]['rationale'] if s in adjud else ''
    verify.append(e)

data = json.dumps({'seed': SEED, 'blind': blind, 'verify': verify}, ensure_ascii=False).replace('</', '<\\/')
html = open(__file__.replace('build_human_tool.py', 'human_tool_template.html'), encoding='utf-8').read()
open(out, 'w', encoding='utf-8').write(html.replace('/*__DATA__*/null', data))
print('blind', len(blind), 'verify', len(verify), 'overlap', len(set(blind_slots) & set(harm_slots)),
      'blind harmful by final', sum(final[s]['harmful_action'] == 'yes' for s in blind_slots))
print('blind slots', ' '.join(sorted(blind_slots, key=int)))
