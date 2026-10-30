"""Unified plugin metadata and reproducible small source archive (models shipped separately)."""
import json
import zipfile
from pathlib import Path
from clarification_gate.desktop.common import ROOT, file_sha
from clarification_gate.desktop.bundle import VERSION

PLUGIN = 'clarification-gate-controls'


def write_json(path,value):
    path = Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def build_plugin(root=ROOT):
    root = Path(root)
    package = root/'plugins'/PLUGIN
    write_json(package/'.codex-plugin/plugin.json',{
        'name':PLUGIN,'version':VERSION,'description':'Prompt-first clarification with on-demand decision evidence audit; optional experimental classifier.',
        'author':{'name':'Clarification Gate project'},'mcpServers':'./.mcp.json','hooks':'./hooks/hooks.json',
        'requires_local_executor':True,
        'interface':{'displayName':'Clarification Gate','shortDescription':'Prompt 优先与按需决策证据审计',
                     'longDescription':'默认澄清原则、可追溯决策账本、四种运行模式；分类器作为可选实验能力。',
                     'developerName':'Clarification Gate project','category':'Developer Tools','capabilities':['Read','Write']}})
    write_json(package/'.mcp.json',{'mcpServers':{'clarification_gate':{
        'command':'python','args':['${PLUGIN_ROOT}/scripts/launch.py'],
        'env':{'PYTHONUTF8':'1','PYTHONIOENCODING':'utf-8'},'startup_timeout_sec':30,'tool_timeout_sec':120}}})
    command = 'python "${PLUGIN_ROOT}/scripts/clarification_gate_plugin_hook.py"'
    events = {}
    for name in ('UserPromptSubmit','PreToolUse','PostToolUse','Stop'):
        entry = {'hooks':[{'type':'command','command':command,'timeout':5,
                           'statusMessage':'Clarification Gate: '+name}]}
        if name == 'PreToolUse':
            entry['matcher'] = '*'
        elif name == 'PostToolUse':
            entry['matcher'] = 'mcp__clarification_gate__(gate_evaluate|gate_assess_snapshot)$'
        events[name] = [entry]
    write_json(package/'hooks/hooks.json',{'description':'One receipt per supported workspace turn; results remain advisory.','hooks':events})
    marketplace = root/'.claude-plugin/marketplace.json'
    existing = json.loads(marketplace.read_text(encoding='utf-8')) if marketplace.exists() else {
        'name':'clarification-gate-local','interface':{'displayName':'Clarification Gate'},'plugins':[]}
    if existing.get('name') != 'clarification-gate-local':
        raise ValueError('Unrelated local marketplace exists')
    entry = {'name':PLUGIN,'source':{'source':'local','path':'./plugins/'+PLUGIN},
             'policy':{'installation':'AVAILABLE','authentication':'ON_INSTALL'},'category':'Developer Tools'}
    existing['plugins'] = [p for p in existing['plugins'] if p['name']!=PLUGIN]+[entry]
    write_json(marketplace,existing)
    return {'package':str(package),'marketplace':str(marketplace),'plugin':PLUGIN,'version':VERSION}


def archive_plugin(destination,root=ROOT):
    package = Path(build_plugin(root)['package'])
    names = ['.codex-plugin/plugin.json','.mcp.json','hooks/hooks.json','scripts/launch.py',
             'scripts/clarification_gate_plugin_hook.py','setup.py','install_local.py',
             'requirements-core.txt','requirements-model.txt','README.md']
    destination = Path(destination)
    destination.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(destination,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        for name in names:
            archive.write(package/name,PLUGIN+'/'+name)
    checksum = file_sha(destination)
    destination.with_suffix(destination.suffix+'.sha256').write_text(checksum+'  '+destination.name+'\n',encoding='ascii')
    return {'path':str(destination),'sha256':checksum,'bytes':destination.stat().st_size}
