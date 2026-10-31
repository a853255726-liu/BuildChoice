"""Generate a private, versioned plugin copy; the source package is read-only."""
import base64
import hashlib
import json
import shutil
from pathlib import Path


def windows_hook_command(python,home):
    def quote(value):return "'"+str(value).replace("'","''")+"'"
    script=("$ProgressPreference='SilentlyContinue'; $buildchoiceRoot=$env:PLUGIN_ROOT; "
        "if ([string]::IsNullOrWhiteSpace($buildchoiceRoot)) {$buildchoiceRoot=$env:CLAUDE_PLUGIN_ROOT}; "
        "if ([string]::IsNullOrWhiteSpace($buildchoiceRoot)) {throw 'PLUGIN_ROOT missing'}; "
        f"& {quote(python)} (Join-Path $buildchoiceRoot 'scripts/buildchoice_plugin_hook.py') "
        f"--data-home {quote(home)}; exit $LASTEXITCODE")
    return 'powershell.exe -NoLogo -NoProfile -NonInteractive -EncodedCommand '+base64.b64encode(script.encode('utf-16-le')).decode('ascii')


def configure_runtime(package,value,home):
    from launch import write_json
    package=Path(package).resolve();home=Path(home).resolve()
    if not package.is_relative_to(home/'installations'):raise ValueError('Generated configuration must stay in the private installation directory')
    for name in ('python','runtime_root','workspace'):
        if any(c in str(value[name]) for c in ('"','\n','\r')):raise ValueError('Unsupported installation path characters')
    launcher=package/'scripts/launch.py'
    write_json(package/'.mcp.json',{'mcpServers':{'buildchoice':{
        'command':value['python'],'args':[str(launcher),'--data-home',str(home)],
        'env':{'PYTHONUTF8':'1','PYTHONIOENCODING':'utf-8'},'startup_timeout_sec':30,'tool_timeout_sec':120}}})
    hook_script=package/'scripts/buildchoice_plugin_hook.py'
    hooks=json.loads((package/'hooks/hooks.json').read_text(encoding='utf-8'))
    for groups in hooks['hooks'].values():
        for group in groups:
            for hook in group['hooks']:
                hook['command']=f'"{value["python"]}" "{hook_script}" --data-home "{home}"'
                hook['commandWindows']=windows_hook_command(value['python'],home)
    write_json(package/'hooks/hooks.json',hooks)


def prepare_installation(source,value,home):
    from launch import write_json
    source=Path(source).resolve();home=Path(home).resolve()
    if home.is_relative_to(source):raise ValueError('Choose an installation directory outside the source package')
    files=[p for p in source.rglob('*') if p.is_file() and not p.is_symlink() and '__pycache__' not in p.parts]
    digest=hashlib.sha256()
    for path in sorted(files):
        digest.update(path.relative_to(source).as_posix().encode());digest.update(path.read_bytes())
    digest.update(value['python'].encode())
    target=home/'installations'/digest.hexdigest()[:20]/'buildchoice'
    for path in files:
        relative=path.relative_to(source);destination=target/relative
        destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(path,destination)
    license_file=source/'LICENSE'
    if not license_file.exists():license_file=source.parents[1]/'LICENSE'
    if license_file.exists():shutil.copyfile(license_file,target/'LICENSE')
    configure_runtime(target,value,home)
    marketplace=target.parent/'.claude-plugin/marketplace.json'
    write_json(marketplace,{'name':'buildchoice-local','plugins':[{'name':'buildchoice',
        'source':{'source':'local','path':'./buildchoice'},'policy':{'installation':'AVAILABLE','authentication':'ON_INSTALL'},
        'category':'Developer Tools'}]})
    return target,marketplace
