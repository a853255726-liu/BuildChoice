"""Read-only installation diagnostics. Unknown host state never counts as healthy."""
import json
import os
from pathlib import Path
import queue
import signal
import subprocess
import sys
import threading
from .common import ROOT


def _run_json(command, timeout, env=None):
    options={'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {'start_new_session':True}
    process=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                             text=True,encoding='utf-8',env=env,**options)
    timed_out=False
    try:
        output,_=process.communicate(timeout=timeout)
        if process.returncode:raise ValueError('Probe process failed')
        return json.loads(output)
    except subprocess.TimeoutExpired:
        timed_out=True
        # Only terminate this diagnostic helper's own process tree, never a running app.
        if os.name=='nt' and process.poll() is None:
            try:
                subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=3,
                    creationflags=subprocess.CREATE_NO_WINDOW)
            except (OSError,subprocess.SubprocessError):pass
        elif os.name!='nt':
            try:os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError:pass
        if process.poll() is None:process.kill()
        process.wait(timeout=2)
        raise
    finally:
        # On Windows communicate's daemon reader can still hold a pipe after a
        # descendant timeout; never turn a bounded diagnostic into an unbounded close.
        if not timed_out:process.stdout.close()


def probe_python(python, timeout):
    code=('import sys,json,importlib.util,importlib.metadata; '
          'names={"mcp":"mcp","jsonschema":"jsonschema","openai_codex":"openai-codex"}; '
          'found={n:importlib.util.find_spec(n) is not None for n in names}; '
          'print(json.dumps({"version":list(sys.version_info[:3]),"modules":found,'
          '"packages":{n:importlib.metadata.version(p) if found[n] else None for n,p in names.items()}}))')
    return _run_json([str(python),'-c',code],timeout)


def probe_mcp(python, runtime, workspace, timeout):
    process=subprocess.Popen([str(python),str(runtime/'scripts/buildchoice_mcp.py'),'--native-settings'],
        cwd=runtime,env={**os.environ,'BUILDCHOICE_WORKSPACE':str(workspace),'PYTHONUTF8':'1','PYTHONIOENCODING':'utf-8'},
        stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf-8',
        creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    responses=queue.Queue()
    def collect():
        try:
            while True:
                line=process.stdout.readline(1024*1024+1)
                if not line:break
                if len(line)>1024*1024:break
                responses.put(json.loads(line))
        except (OSError,ValueError):pass
        responses.put(None)
    threading.Thread(target=collect,daemon=True).start()
    def request(ident,method,params):
        process.stdin.write(json.dumps({'jsonrpc':'2.0','id':ident,'method':method,'params':params})+'\n')
        process.stdin.flush()
        while True:
            result=responses.get(timeout=timeout)
            if result is None:raise ValueError('MCP server exited')
            if result.get('id')==ident:
                if 'error' in result:raise ValueError('MCP request rejected')
                return result['result']
    try:
        init=request(1,'initialize',{'protocolVersion':'2024-11-05','capabilities':{},
            'clientInfo':{'name':'BuildChoice doctor','version':'1'}})
        process.stdin.write('{"jsonrpc":"2.0","method":"notifications/initialized"}\n')
        process.stdin.flush()
        names=[tool['name'] for tool in request(2,'tools/list',{})['tools']]
        return {'server':init['serverInfo']['name'],'tools':names}
    finally:
        process.stdin.close()
        try:process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill();process.wait(timeout=2)
        process.stdout.close()


def probe_host(workspace, marketplace):
    """Only plugin/read and hooks/list; never install, reconcile, or trust hooks."""
    from openai_codex.client import CodexClient,CodexConfig
    from openai_codex.generated.v2_all import PluginReadResponse,HooksListResponse,HookEventName
    with CodexClient(CodexConfig(cwd=str(workspace))) as client:
        client.initialize()
        plugin=client.request('plugin/read',{'pluginName':'buildchoice','marketplacePath':str(marketplace)},
                              response_model=PluginReadResponse).plugin
        listing=client.request('hooks/list',{'cwds':[str(workspace)]},response_model=HooksListResponse)
    keys={hook.key for hook in plugin.hooks if hook.event_name==HookEventName.user_prompt_submit}
    matching=[]
    for entry in listing.data:
        if Path(entry.cwd).resolve()!=Path(workspace).resolve():continue
        for wrapped in entry.hooks:
            hook=wrapped.root
            if hook.key in keys and hook.plugin_id==plugin.summary.id and hook.event_name==HookEventName.user_prompt_submit:
                matching.append({'enabled':hook.enabled,'trust_status':hook.trust_status.value})
    return {'installed':plugin.summary.installed,'enabled':plugin.summary.enabled,
            'server_declared':'buildchoice' in plugin.mcp_servers,'hooks':matching}


def diagnose(home=None, workspace=None, host=False, timeout=10):
    if not 1<=timeout<=60:raise ValueError('Timeout must be between 1 and 60 seconds')
    home=Path(home or os.environ.get('BUILDCHOICE_DATA') or Path.home()/'.buildchoice').resolve()
    checks=[]
    def add(name,status,detail,action=''):
        checks.append({'name':name,'status':status,'detail':detail,'action':action})
    runtime=ROOT;python=Path(sys.executable);bound_workspace=None
    binding_file=home/'binding.json'
    if binding_file.is_file():
        try:
            value=json.loads(binding_file.read_text(encoding='utf-8'))
            if value.get('binding_version')!=1:raise ValueError('Binding version')
            for key in ('python','runtime_root','workspace'):
                if not isinstance(value.get(key),str) or not Path(value[key]).is_absolute() or not Path(value[key]).exists():
                    raise ValueError('Invalid bound path')
            runtime=Path(value['runtime_root']).resolve();python=Path(value['python']).resolve()
            bound_workspace=Path(value['workspace']).resolve()
            add('binding','pass','已找到有效的本地安装绑定。')
        except (OSError,ValueError,KeyError,TypeError):
            add('binding','fail','安装绑定无效或路径已失效。','保留旧数据，用 setup.py --runtime-root 重新初始化。')
    else:
        add('binding','fail','当前数据目录没有安装绑定。','运行 plugins/buildchoice/setup.py --workspace "目标项目" --runtime-root . --install。')
    workspace=Path(workspace).resolve() if workspace is not None else bound_workspace or ROOT
    valid_workspace=workspace.is_dir() and (bound_workspace is None or workspace==bound_workspace)
    add('workspace','pass' if valid_workspace and bound_workspace else 'unknown' if valid_workspace else 'fail',
        '目标工作区与安装绑定一致。' if valid_workspace and bound_workspace else '未确认绑定工作区。',
        '' if valid_workspace else '选择已绑定的项目，或用独立 --data-home 安装到另一项目。')
    try:
        deps=probe_python(python,timeout)
        ready=deps['version'][:2]>=[3,11] and all(deps['modules'].values())
        add('python_dependencies','pass' if ready else 'fail',
            {'python':deps['version'],'packages':deps['packages']},'' if ready else '通过 setup.py 安装核心依赖。')
    except (OSError,ValueError,subprocess.SubprocessError):
        ready=False
        add('python_dependencies','fail','无法运行绑定的 Python 或读取依赖。','用有效的 Python 3.11+ 重新初始化安装。')
    required=['scripts/buildchoice_mcp.py','scripts/buildchoice_hook.py','scripts/buildchoice_doctor.py',
              'buildchoice/desktop/implementation.py','configs/buildchoice.json',
              'scripts/buildchoice_run_verification.py','scripts/buildchoice_test_worker.py',
              'buildchoice/desktop/acceptance.py','buildchoice/desktop/verification.py',
              'buildchoice/desktop/verification_inputs.py','buildchoice/desktop/verification_runner.py',
              'buildchoice/desktop/verification_worker.py',
              'docs/contracts/acceptance-v1.schema.json','docs/contracts/verification-v1.schema.json']
    files_ready=all((runtime/name).is_file() for name in required)
    add('runtime_files','pass' if files_ready else 'fail','运行时入口完整。' if files_ready else '运行时入口缺失。',
        '' if files_ready else '恢复 BuildChoice 运行时目录并重新初始化。')
    if ready and files_ready and valid_workspace:
        try:
            result=probe_mcp(python,runtime,workspace,timeout)
            good=result['server']=='buildchoice' and 'buildchoice_decision_status' in result['tools']
            add('local_mcp','pass' if good else 'fail',{'server':result['server'],'tool_count':len(result['tools'])},
                '' if good else '核对绑定版本与运行时入口。')
        except (OSError,ValueError,KeyError,queue.Empty,subprocess.SubprocessError):
            add('local_mcp','fail','本地 MCP 启动或协议检查未通过。','检查 Python 依赖和 configs 设置，然后重新运行自检。')
    else:add('local_mcp','unknown','前置环境未通过，未启动协议检查。')
    add('host_plugin','unknown','尚未读取宿主插件状态。','加 --host 进行只读 plugin/read 与 hooks/list 检查。')
    add('hook_trust','unknown','没有独立确认 Hook 的启用与信任状态。','加 --host 检查；信任或修改操作由用户在宿主完成。')
    if host and ready and valid_workspace:
        marketplaces=[runtime/'plugins/.claude-plugin/marketplace.json',runtime/'.claude-plugin/marketplace.json']
        marketplace=next((path for path in marketplaces if path.is_file()),None)
        if marketplace is not None:
            try:
                script=runtime/'scripts/buildchoice_doctor.py'
                result=_run_json([str(python),str(script),'--host-probe','--workspace',str(workspace),
                                  '--marketplace',str(marketplace)],timeout)
                checks=[c for c in checks if c['name'] not in ('host_plugin','hook_trust')]
                installed=result['installed'] and result['enabled'] and result['server_declared']
                add('host_plugin','pass' if installed else 'fail',
                    {'installed':result['installed'],'enabled':result['enabled']},
                    '' if installed else '在宿主中安装并启用 BuildChoice。')
                hooks=result['hooks'];trusted=bool(hooks) and all(h['enabled'] and h['trust_status'] in ('trusted','managed') for h in hooks)
                add('hook_trust','pass' if trusted else 'unknown',{'definitions':hooks},
                    '' if trusted else '在宿主中审阅当前 UserPromptSubmit 定义并按需启用、信任。')
            except (OSError,ValueError,KeyError,subprocess.SubprocessError):
                # Timeouts/unsupported hosts are unknown, not proof of failure or success.
                pass
    overall='needs_attention' if any(c['status']=='fail' for c in checks) else 'unverified' if any(c['status']=='unknown' for c in checks) else 'pass'
    return {'overall':overall,'checks':checks,'read_only':True,'hook_trust_modified':False,
            'scope':'本地安装与声明状态；独立 MCP 启动不证明宿主已加载，信任定义不证明实际聊天回调已执行。'}
