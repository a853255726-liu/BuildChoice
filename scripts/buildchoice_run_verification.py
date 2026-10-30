"""Explicit authorized test execution; never invoked by an MCP verification call."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from buildchoice.desktop.verification_runner import collect

def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(description='Run a declared local unittest entry and collect evidence; this executes project code.')
    parser.add_argument('--workspace',type=Path,required=True)
    parser.add_argument('--acceptance-id',required=True)
    parser.add_argument('--manifest',required=True,help='Workspace-relative manifest file; fixed python-unittest-v1 adapter only')
    parser.add_argument('--settings',type=Path)
    parser.add_argument('--decision-settings',type=Path)
    args=parser.parse_args()
    receipt=collect(args.workspace,args.acceptance_id,args.manifest,args.settings,args.decision_settings)
    print(json.dumps({'execution_id':receipt['execution_id'],'execution_status':receipt['execution_status'],
        'exit_code':receipt['exit_code'],'tests_run':(receipt['report'] or {}).get('tests_run',0),
        'provenance':receipt['provenance'],'does_not_itself_mean_verified':True},ensure_ascii=False,indent=2))
    return 0 if receipt['execution_status']=='completed' and receipt['exit_code']==0 else 1
if __name__=='__main__':sys.exit(main())
