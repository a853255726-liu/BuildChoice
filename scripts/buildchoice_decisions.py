"""Local V3 controls. A confirmation can never be injected through this CLI."""
import argparse
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from buildchoice.desktop.decision_settings import read,update


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser()
    parser.add_argument('command',choices=['settings','pilot','off','model-on','model-off','migrate','rollback'])
    parser.add_argument('--workspace',type=Path,default=ROOT)
    args=parser.parse_args()
    if args.command=='settings':result=read()
    elif args.command in ('pilot','off'):result=update(mode=args.command)
    elif args.command in ('model-on','model-off'):result=update(model_check=args.command[6:])
    else:
        from buildchoice.desktop.migration import migrate_decision_database,rollback_decision_database
        if args.command=='rollback' and read()['mode']!='off':raise ValueError('Turn V3 off and stop its sessions before rollback')
        result=(migrate_decision_database if args.command=='migrate' else rollback_decision_database)(args.workspace)
    print(json.dumps(result,ensure_ascii=False,indent=2))
