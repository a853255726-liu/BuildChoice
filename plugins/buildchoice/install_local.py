"""Install this initialized local plugin using the official app-server API."""
import argparse
import base64
import json
import sys
from pathlib import Path
from openai_codex.client import CodexClient, CodexConfig
from openai_codex.generated.v2_all import PluginInstallResponse, PluginReadResponse


from installation import windows_hook_command,configure_runtime


def install(workspace,marketplace=None):
    sys.path.insert(0,str(Path(__file__).resolve().parent/'scripts'))
    from launch import binding,data_home
    value=binding(workspace=workspace)
    if Path(value['workspace']).resolve()!=Path(workspace).resolve():
        raise ValueError('Initialize the selected workspace before installation')
    if not value.get('plugin_root'):raise ValueError('Reinitialize this legacy binding before installation')
    package=Path(value['plugin_root']).resolve()
    if not package.is_relative_to(data_home()/'installations'):
        raise ValueError('Plugin copy is outside the installation directory')
    marketplace=Path(marketplace or value['marketplace'])
    name='buildchoice'
    with CodexClient(CodexConfig(cwd=str(workspace))) as client:
        client.initialize()
        client.request('plugin/install',{'pluginName':name,'marketplacePath':str(marketplace)},response_model=PluginInstallResponse)
        detail = client.request('plugin/read',{'pluginName':name,'marketplacePath':str(marketplace)},response_model=PluginReadResponse).plugin
    if detail.mcp_servers != ['buildchoice'] or len(detail.hooks)!=1:
        raise ValueError('Installed plugin does not expose the unified server and UserPromptSubmit Hook')
    return {'installed':detail.summary.installed,'enabled':detail.summary.enabled,'id':detail.summary.id,
            'mcp_servers':detail.mcp_servers,'hook_events':[h.event_name.value for h in detail.hooks],
            'hook_trust_modified':False,'native_ui_visually_verified':False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--workspace',type=Path,required=True)
    parser.add_argument('--marketplace',type=Path)
    args = parser.parse_args()
    print(json.dumps(install(args.workspace,args.marketplace),ensure_ascii=False,indent=2))
