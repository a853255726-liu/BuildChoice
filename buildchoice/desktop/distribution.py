"""Unified plugin metadata and reproducible small source archive (no model resources)."""
import json
import zipfile
from pathlib import Path
from buildchoice.desktop.common import ROOT, file_sha
from buildchoice.desktop.bundle import VERSION

PLUGIN = 'buildchoice'


def write_json(path,value):
    path = Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def build_plugin(root=ROOT):
    root = Path(root)
    package = root/'plugins'/PLUGIN
    write_json(package/'.codex-plugin/plugin.json',{
        'name':PLUGIN,'version':VERSION,'description':'A Codex plugin for reviewing important implementation choices before they become code.',
        'author':{'name':'BuildChoice'},'mcpServers':'./.mcp.json','hooks':'./hooks/hooks.json','skills':'./skills/',
        'requires_local_executor':True,
        'interface':{'displayName':'BuildChoice','shortDescription':'在编程过程中确认重要的实现选择',
                     'longDescription':'结合项目约束整理影响产品行为的选择，在 Codex 对话中逐项确认并记录。默认使用 Prompt-first 策略，可独立开启决策卡。',
                     'developerName':'BuildChoice','category':'Developer Tools','capabilities':['Read','Write']}})
    write_json(package/'.mcp.json',{'mcpServers':{'buildchoice':{
        'command':'python','args':['${PLUGIN_ROOT}/scripts/launch.py'],
        'env':{'PYTHONUTF8':'1','PYTHONIOENCODING':'utf-8'},'startup_timeout_sec':30,'tool_timeout_sec':120}}})
    command = 'python "${PLUGIN_ROOT}/scripts/buildchoice_plugin_hook.py"'
    events = {'UserPromptSubmit': [{'hooks': [{'type':'command','command':command,'timeout':5,
        'statusMessage':'BuildChoice: UserPromptSubmit'}]}]}
    write_json(package/'hooks/hooks.json',{'description':'Prompt policy and observed decision replies; never blocks tasks.','hooks':events})
    marketplace = root/'.claude-plugin/marketplace.json'
    existing = json.loads(marketplace.read_text(encoding='utf-8')) if marketplace.exists() else {
        'name':'buildchoice-local','interface':{'displayName':'BuildChoice'},'plugins':[]}
    if existing.get('name') != 'buildchoice-local':
        raise ValueError('Unrelated local marketplace exists')
    entry = {'name':PLUGIN,'source':{'source':'local','path':'./plugins/'+PLUGIN},
             'policy':{'installation':'AVAILABLE','authentication':'ON_INSTALL'},'category':'Developer Tools'}
    existing['interface'] = {'displayName':'BuildChoice'}
    existing['plugins'] = [p for p in existing['plugins'] if p['name']!=PLUGIN]+[entry]
    write_json(marketplace,existing)
    return {'package':str(package),'marketplace':str(marketplace),'plugin':PLUGIN,'version':VERSION}


def archive_plugin(destination,root=ROOT):
    package = Path(build_plugin(root)['package'])
    names = ['.codex-plugin/plugin.json','.mcp.json','hooks/hooks.json','scripts/launch.py',
             'scripts/buildchoice_plugin_hook.py','setup.py','install_local.py',
             'requirements-core.txt','README.md']
    names += sorted(p.relative_to(package).as_posix() for p in (package/'skills').rglob('*')
                    if p.is_file() and not p.is_symlink() and '__pycache__' not in p.parts)
    destination = Path(destination)
    destination.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(destination,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        for name in names:
            archive.write(package/name,PLUGIN+'/'+name)
    checksum = file_sha(destination)
    destination.with_suffix(destination.suffix+'.sha256').write_text(checksum+'  '+destination.name+'\n',encoding='ascii')
    return {'path':str(destination),'sha256':checksum,'bytes':destination.stat().st_size}
