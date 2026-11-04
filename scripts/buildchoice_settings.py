"""Read or explicitly change the Prompt-first/off setting."""
import argparse
import json
import os
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from buildchoice.desktop.settings import SETTINGS, status, update

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser()
    parser.add_argument('command',choices=['status','prompt','off'])
    parser.add_argument('--config',type=Path)
    parser.add_argument('--workspace',type=Path)
    parser.add_argument('--data-home',type=Path)
    args=parser.parse_args()
    from buildchoice.desktop.project_settings import project_config
    config=args.config or os.environ.get('BUILDCHOICE_SETTINGS')
    if config is None:config=project_config('buildchoice.json',args.data_home,args.workspace) or SETTINGS
    result=status(config) if args.command=='status' else update(args.command,config)
    print(json.dumps(result,ensure_ascii=False,indent=2))
