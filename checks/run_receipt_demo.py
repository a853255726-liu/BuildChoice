"""Real browser positive/negative behavior suite, using synthetic decision confirmations."""
import argparse
import json
from pathlib import Path
import sys
from verification_helpers import setup_fixture
from buildchoice.desktop.verification_runner import collect
from buildchoice.desktop.verification import verify


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path);args=parser.parse_args()
    results=[]
    for variant,config,expected in [('correct',{'early_save':False,'ignore_edits':False},'passed'),
                                  ('early-save',{'early_save':True,'ignore_edits':False},'failed'),
                                  ('ignore-edits',{'early_save':False,'ignore_edits':True},'failed')]:
        fixture=setup_fixture(browser=True)
        (fixture['workspace']/'config.json').write_text(json.dumps(config),encoding='utf-8')
        receipt=collect(fixture['workspace'],fixture['conditions']['acceptance_id'],'manifest.json',fixture['global_settings'],fixture['settings'])
        result=verify(fixture['store'],fixture['task'],fixture['item']['decision_id'],1,fixture['conditions']['acceptance_id'],[],receipt['execution_id'],variant)
        summary={'variant':variant,'verdict':result['verdict'],'applicability':result['applicability'],
            'current_pass':result['current_pass'],'tests_run':(receipt['report'] or {}).get('tests_run',0),
            'workspace':str(fixture['workspace']),'execution_id':receipt['execution_id'],
            'verification_id':result['verification_id'],'input_digest':receipt['before']['digest'],
            'environment_digest':receipt['environment']['digest'],'report_sha256':receipt['report_sha256'],
            'runtime_digest':receipt['runtime_digest'],'exit_code':receipt['exit_code'],
            'criteria':[{k:c[k] for k in ('criterion_id','verdict','reason')} for c in result['criteria']]}
        results.append(summary)
        if result['verdict'] != expected:
            # Only synthetic fixture output is printed, never real user workspaces.
            artifact = fixture['workspace'] / '.buildchoice_audit' / 'verification_runs' / receipt['execution_id']
            log_file = artifact / 'output.log'
            detail = log_file.read_text(encoding='utf-8', errors='replace')[-8000:] if log_file.exists() else 'No worker log'
            raise AssertionError((summary, receipt['execution_status'], detail))
        assert result['applicability']=='current',result['stale_reasons']
    document={'scope':'Headless browser and localStorage behavior with synthetic confirmation fixtures.',
              'results':results}
    text=json.dumps(document,ensure_ascii=False,indent=2)
    if args.out:args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(text+'\n',encoding='utf-8')
    print(text)

if __name__=='__main__':main()
