"""Local V3 controls. A confirmation can never be injected through this CLI."""
import argparse
import json
import os
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from buildchoice.desktop.decision_settings import read,update


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser()
    parser.add_argument('command',choices=['settings','pilot','off','migrate','rollback'])
    parser.add_argument('--workspace',type=Path)
    parser.add_argument('--data-home',type=Path)
    parser.add_argument('--config',type=Path)
    args=parser.parse_args()
    from buildchoice.desktop.project_settings import project_config
    config=args.config or os.environ.get('BUILDCHOICE_V3_SETTINGS')
    if config is None:config=project_config('decision_v3.json',args.data_home,args.workspace)
    def current():return read(config) if config else read()
    if args.command=='settings':result=current()
    elif args.command in ('pilot','off'):result=update(mode=args.command,**({'path':config} if config else {}))
    else:
        from buildchoice.desktop.migration import migrate_decision_database,rollback_decision_database
        if args.command=='rollback' and current()['mode']!='off':raise ValueError('Turn V3 off and stop its sessions before rollback')
        result=(migrate_decision_database if args.command=='migrate' else rollback_decision_database)(args.workspace or ROOT)
    print(json.dumps(result,ensure_ascii=False,indent=2))
