"""Bind a controlled feedback run to an execution output, not a lookalike source copy."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath

FORMAT = 'guidance-case-output.v1'


def safe_file(root, relative):
    if not isinstance(relative,str) or '\\' in relative:
        raise ValueError('Manifest paths must be relative POSIX file paths')
    part=PurePosixPath(relative)
    if part.is_absolute() or '..' in part.parts or not part.parts or ':' in relative:
        raise ValueError('Manifest path must stay within the output root')
    path=root.joinpath(*part.parts)
    if not path.resolve().is_relative_to(root) or path.is_symlink() or not path.is_file():
        raise ValueError('Manifest file is unavailable or outside the output root')
    return path


def capture(root, case_id, files):
    root=Path(root).resolve()
    if not root.is_dir() or not isinstance(case_id,str) or not case_id.strip() or not files:
        raise ValueError('An actual output root, case_id and explicit files are required')
    if len(set(files))!=len(files):
        raise ValueError('Duplicate manifest file')
    entries=[]
    for name in sorted(files):
        path=safe_file(root,name)
        entries.append({'path':name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    return {'format':FORMAT,'case_id':case_id,'output_root':str(root),
            'scope':'listed_files_only','files':entries}


def verify(root, case_id, manifest):
    root=Path(root).resolve()
    if (manifest.get('format')!=FORMAT or manifest.get('case_id')!=case_id or
            manifest.get('output_root')!=str(root) or manifest.get('scope')!='listed_files_only'):
        raise ValueError('Feedback target does not match the execution output identity')
    entries=manifest.get('files')
    if not isinstance(entries,list) or not entries or any(not isinstance(x,dict) or set(x)!={'path','sha256'} for x in entries):
        raise ValueError('Invalid execution output file list')
    actual=capture(root,case_id,[x['path'] for x in entries])
    if actual['files']!=sorted(entries,key=lambda x:x['path']):
        raise ValueError('Execution output changed; do not fall back to an original copy')
    return actual


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='action',required=True)
    for action in ('capture','verify'):
        p=sub.add_parser(action)
        p.add_argument('--root',required=True)
        p.add_argument('--case-id',required=True)
        if action=='capture':
            p.add_argument('--files',nargs='+',required=True)
            p.add_argument('--output',required=True)
        else:p.add_argument('--manifest',required=True)
    args=parser.parse_args()
    if args.action=='capture':
        value=capture(args.root,args.case_id,args.files)
        # Capture at execution completion; never silently replace earlier provenance.
        with Path(args.output).open('x',encoding='utf-8') as stream:
            json.dump(value,stream,ensure_ascii=False,indent=2)
    else:
        value=verify(args.root,args.case_id,json.loads(Path(args.manifest).read_text(encoding='utf-8')))
    print(json.dumps({'case_id':value['case_id'],'output_root':value['output_root'],'files':len(value['files'])},ensure_ascii=False))


if __name__=='__main__':main()
