"""Install this initialized local plugin using the official app-server API."""
import argparse
import base64
import json
import sys
from pathlib import Path
from openai_codex.client import CodexClient, CodexConfig
from openai_codex.generated.v2_all import PluginInstallResponse, PluginReadResponse


def windows_hook_command(python,home):
    """ASCII launcher accepted by both cmd and PowerShell, with quoted paths inside PowerShell."""
    def quote(value):
        return "'"+str(value).replace("'","''")+"'"
    script = (
        "$ProgressPreference='SilentlyContinue'; $buildchoiceRoot=$env:PLUGIN_ROOT; "
        "if ([string]::IsNullOrWhiteSpace($buildchoiceRoot)) {$buildchoiceRoot=$env:CLAUDE_PLUGIN_ROOT}; "
        "if ([string]::IsNullOrWhiteSpace($buildchoiceRoot)) {throw 'PLUGIN_ROOT missing'}; "
        f"& {quote(python)} (Join-Path $buildchoiceRoot 'scripts/buildchoice_plugin_hook.py') "
        f"--data-home {quote(home)}; exit $LASTEXITCODE")
    encoded = base64.b64encode(script.encode('utf-16-le')).decode('ascii')
    return 'powershell.exe -NoLogo -NoProfile -NonInteractive -EncodedCommand '+encoded


def configure_runtime(package,value,home):
    """Resolve paths once during initialization; avoid desktop PATH and cwd placeholder differences."""
    package = Path(package)
    for name in ('python','runtime_root','workspace'):
        if any(c in str(value[name]) for c in ('"','\n','\r')):
            raise ValueError('Unsupported installation path characters')
    root = Path(value['runtime_root'])
    mcp = {'mcpServers':{'buildchoice':{
        'command':value['python'],'args':[str(root/'scripts/buildchoice_mcp.py'),'--native-settings'],
        'cwd':str(root),'env':{'BUILDCHOICE_WORKSPACE':value['workspace'],
            'PYTHONUTF8':'1','PYTHONIOENCODING':'utf-8'},'startup_timeout_sec':30,'tool_timeout_sec':120}}}
    (package/'.mcp.json').write_text(json.dumps(mcp,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    hooks_path = package/'hooks/hooks.json'
    hooks = json.loads(hooks_path.read_text(encoding='utf-8'))
    command = f'"{value["python"]}" "${{PLUGIN_ROOT}}/scripts/buildchoice_plugin_hook.py" --data-home "{home}"'
    for groups in hooks['hooks'].values():
        for group in groups:
            for hook in group['hooks']:
                hook['command'] = command
                hook['commandWindows'] = windows_hook_command(value['python'],home)
    hooks_path.write_text(json.dumps(hooks,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def install(workspace,marketplace=None):
    package = Path(__file__).resolve().parent
    sys.path.insert(0,str(package/'scripts'))
    from launch import binding,data_home
    value = binding()
    if Path(value['workspace']).resolve()!=Path(workspace).resolve():
        raise ValueError('Initialize the selected workspace before installation')
    configure_runtime(package,value,data_home())
    name = 'buildchoice'
    if marketplace is None:
        marketplace = package.parent/'.claude-plugin/marketplace.json'
        marketplace.parent.mkdir(parents=True,exist_ok=True)
        if marketplace.exists():
            catalog = json.loads(marketplace.read_text(encoding='utf-8'))
            if catalog.get('name')!='buildchoice-local':
                raise ValueError('Unrelated marketplace exists')
        else:
            catalog = {'name':'buildchoice-local','plugins':[]}
        catalog['plugins'] = [p for p in catalog['plugins'] if p['name']!=name]+[{
            'name':name,'source':{'source':'local','path':'./'+package.name},
            'policy':{'installation':'AVAILABLE','authentication':'ON_INSTALL'},'category':'Developer Tools'}]
        marketplace.write_text(json.dumps(catalog,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    with CodexClient(CodexConfig(cwd=str(workspace))) as client:
        client.initialize()
        client.request('plugin/install',{'pluginName':name,'marketplacePath':str(marketplace)},response_model=PluginInstallResponse)
        detail = client.request('plugin/read',{'pluginName':name,'marketplacePath':str(marketplace)},response_model=PluginReadResponse).plugin
    if detail.mcp_servers != ['buildchoice'] or len(detail.hooks)!=4:
        raise ValueError('Installed plugin does not expose the unified server and four Hooks')
    return {'installed':detail.summary.installed,'enabled':detail.summary.enabled,'id':detail.summary.id,
            'mcp_servers':detail.mcp_servers,'hook_events':[h.event_name.value for h in detail.hooks],
            'hook_trust_modified':False,'native_ui_visually_verified':False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--workspace',type=Path,required=True)
    parser.add_argument('--marketplace',type=Path)
    args = parser.parse_args()
    print(json.dumps(install(args.workspace,args.marketplace),ensure_ascii=False,indent=2))
