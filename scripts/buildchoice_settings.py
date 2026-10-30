"""Read or explicitly change the Prompt-first/off setting."""
import argparse
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from buildchoice.desktop.settings import SETTINGS, status, update

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser()
    parser.add_argument('command',choices=['status','prompt','off'])
    parser.add_argument('--config',type=Path,default=SETTINGS)
    args=parser.parse_args()
    result=status(args.config) if args.command=='status' else update(args.command,args.config)
    print(json.dumps(result,ensure_ascii=False,indent=2))
