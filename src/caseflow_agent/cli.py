"""Project-specific entry points; inference credentials come from the environment."""
import argparse, json, uuid
from pathlib import Path
from .common import ROOT
def output(v): print(json.dumps(v,ensure_ascii=False,indent=2))
def main():
    p=argparse.ArgumentParser(prog='caseflow')
    sub=p.add_subparsers(dest='command',required=True)
    sub.add_parser('results',help='Read the measured summary without API calls')
    e=sub.add_parser('demo');e.add_argument('--family',choices=['normal','clarification','approval','scope','version','retry'],default='retry');e.add_argument('--blocked',action='store_true');e.add_argument('--arm',choices=['W0','W1','W2'],default='W1');e.add_argument('--out',type=Path,required=True)
    e=sub.add_parser('evaluate');e.add_argument('--out',type=Path,required=True);e.add_argument('--split',choices=['dev','test'],default='test');e.add_argument('--workers',type=int,default=1)
    e=sub.add_parser('faults');e.add_argument('--out',type=Path,required=True)
    a=p.parse_args()
    if a.command in ('run', 'demo') and (a.out/'trial.json').exists():
        old=json.loads((a.out/'trial.json').read_text())
        expected_task=a.task if a.command=='run' else None
        if old.get('arm')!=a.arm or (expected_task and old.get('task')!=expected_task):
            p.error('Output directory belongs to another terminal task/configuration; choose a new directory')
    if a.command=='results':
        output(json.loads((ROOT/'results/measured_summary.json').read_text()));return
    if a.command=='faults':
        from .caseflow_faults import run_witnesses
        r=run_witnesses(a.out);output({'coverage':r['coverage'],'summary':str(a.out/'summary.json')});return
    import asyncio
    from .caseflow_eval import task_corpus, trial, suite
    from .caseflow_runtime import services
    with services() as cfg:
        if a.command=='evaluate':output(asyncio.run(suite(cfg,a.out,a.split,a.workers)));return
        matches=[t for t in task_corpus() if t['split']=='dev' and t['family']==a.family and t['index']==int(a.blocked)]
        if not matches or (a.blocked and matches[0]['actionable']):p.error('Choose approval, clarification, scope or version for a blocked task')
        if (a.out/'trial.json').exists() and json.loads((a.out/'trial.json').read_text()).get('task')!=matches[0]['id']:p.error('Output directory belongs to another task; choose a new directory')
        output(asyncio.run(trial(cfg,matches[0],a.arm,a.out,'demo:'+a.out.name)))
if __name__=='__main__':main()
