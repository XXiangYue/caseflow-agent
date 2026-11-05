"""Recompute primary counts from the published measured rows; no API calls."""
from pathlib import Path
import json
import math
ROOT=Path(__file__).resolve().parents[1]
def load(n):return json.loads((ROOT/'results'/n).read_text())
def rows(n):return [json.loads(x) for x in (ROOT/'results'/n).read_bytes().split(b'\n') if x.strip()]
def check(a,b):
    assert a==b,(a,b)
project='P4'
s=load('measured_summary.json')
result={}
if project=='P1':
    r=rows('main.jsonl')
    for arm in ['R0','R1','R2']:
        x=[v for v in r if v['arm']==arm]
        n=sum(v['success'] for v in x);check(n,s['main'][arm]['reproducible_delivery_success']['num'])
        check(len(x),36);result[arm]=f'{n}/{len(x)}'
    e=load('actual_exits.json');check(sum(v['formal_publications']>1 for v in e['rows']),0)
    for arm in ['R0','R1']:check(sum(v['success'] for v in e['rows'] if v['arm']==arm),5)
elif project=='P2':
    r=rows('public_trials.jsonl')
    for arm in ['M0','M1','M2']:
        x=[v for v in r if v['arm']==arm];check(len(x),500)
        n=sum(v.get('autoeval_label') is True for v in x)
        check(n,s['public'][arm]['qa_accuracy']['num'])
        tokens=sum(v.get('usage',{}).get('prompt_tokens',0) for v in x)
        check(tokens,s['public'][arm]['reader_input_tokens']);result[arm]={'correct':n,'n':len(x),'reader_input_tokens':tokens}
    result['reader_input_reduction']=1-result['M2']['reader_input_tokens']/result['M1']['reader_input_tokens']
    ingestion=load('ingestion_statuses.json');check(len(ingestion),500)
    check(sum(v['status']=='error' for v in ingestion),282)
elif project=='P3':
    r=load('verdicts.json')
    for arm in ['V0','V1']:
        invalid=[v for v in r if v['split']=='test' and v['arm']==arm and not v['valid']]
        valid=[v for v in r if v['split']=='test' and v['arm']==arm and v['valid']]
        check(len(invalid),100);check(len(valid),100)
        fa=sum(v['passed'] for v in invalid);fr=sum(not v['passed'] for v in valid)
        check(fa,load('summary.json')[arm]['false_acceptance']['num']);check(fr,0)
        result[arm]={'false_accepts':fa,'false_rejects':fr,'invalid':100,'valid':100}
    mutants=load('release_mutations.json');check(len(mutants),20);check(sum(v['detected'] for v in mutants),20)
else:
    r=rows('main_v2_trials.jsonl')
    for arm in ['W0','W1','W2']:
        x=[v for v in r if v['arm']==arm];check(len(x),72)
        n=sum(v['success'] for v in x);check(n,s['main'][arm]['all_conditions_success']['num'])
        tokens=sum(v['input_tokens'] for v in x);check(tokens,s['main'][arm]['input_tokens'])
        result[arm]={'success':n,'n':len(x),'input_tokens':tokens}
    f=load('faults.json');check(len(f['rows']),12);check(sum(v['passed'] for v in f['rows']),12)
    result['input_reduction']=1-result['W1']['input_tokens']/result['W0']['input_tokens']
print(json.dumps({'verified':True,'project':project,'recomputed':result},indent=2))
