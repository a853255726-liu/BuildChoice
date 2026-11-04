"""Inspect an installation without installing, editing configuration or trusting hooks."""
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from buildchoice.desktop.doctor import diagnose,probe_host


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(description='BuildChoice 安装自检（只读）')
    parser.add_argument('--data-home',type=Path)
    parser.add_argument('--workspace',type=Path)
    parser.add_argument('--host',action='store_true',help='额外读取宿主插件与 Hook 声明；不安装或修改信任')
    parser.add_argument('--json',action='store_true',help='输出结构化结果')
    parser.add_argument('--timeout',type=float,default=10)
    parser.add_argument('--host-probe',action='store_true',help=argparse.SUPPRESS)
    parser.add_argument('--marketplace',type=Path,help=argparse.SUPPRESS)
    args=parser.parse_args()
    if args.host_probe:
        try:
            print(json.dumps(probe_host(args.workspace,args.marketplace),ensure_ascii=False))
            return 0
        except Exception:
            return 1
    result=diagnose(args.data_home,args.workspace,args.host,args.timeout)
    if args.json:print(json.dumps(result,ensure_ascii=False,indent=2))
    else:
        labels={'pass':'通过','fail':'需处理','unknown':'未验证'}
        for check in result['checks']:
            print(f"[{labels[check['status']]}] {check['name']}: "+(check['detail'] if isinstance(check['detail'],str) else json.dumps(check['detail'],ensure_ascii=False)))
            if check['action']:print('  '+check['action'])
        print(result['scope'])
    return 1 if result['overall']=='needs_attention' else 0


if __name__=='__main__':sys.exit(main())
