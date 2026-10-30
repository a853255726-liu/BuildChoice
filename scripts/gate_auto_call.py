"""User-facing fixed switch: on / off / status. No worker restart needed."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from clarification_gate.desktop.auto_call import set_switch, switch_status, set_mode

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['on', 'off', 'status', 'prompt', 'required', 'auto', 'disabled'])
    args = parser.parse_args()
    result = (switch_status() if args.command == 'status' else
              set_mode({'prompt':'prompt','required':'required','auto':'auto','disabled':'off'}[args.command])
              if args.command in ('prompt','required','auto','disabled') else set_switch(args.command == 'on'))
    print(json.dumps(result, ensure_ascii=False, indent=2))
