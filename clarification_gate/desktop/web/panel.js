'use strict';
const $ = id => document.getElementById(id);
let current = null, csrf = null, saving = false, requestId = 0;
const names = {userpromptsubmit:'消息进入',pretooluse:'执行前检查',posttooluse:'调用回执',stop:'结束前检查'};
async function api(path, options = {}) {
  let response;
  try { response = await fetch(path, {cache:'no-store', credentials:'same-origin', ...options}); }
  catch { throw new Error('无法连接本地面板，请恢复服务后刷新。'); }
  const value = await response.json();
  if (!response.ok) throw new Error(value.message || '本地服务暂时不可用，请刷新重试。');
  return value;
}
function badge(id, text, kind = '') { $(id).textContent = text; $(id).className = id==='effect-badge' ? `badge ${kind}` : `small-status ${kind}`; }
function render() {
  if (!current) return;
  const {switch:setting, hooks, service, effective} = current;
  $('local-status').classList.remove('offline'); $('local-label').textContent='本地连接';
  $('gate-switch').setAttribute('aria-checked', String(setting.enabled));
  $('gate-switch').disabled = saving;
  $('switch-label').textContent = saving ? '正在保存…' : setting.enabled ? '强制调用已打开' : setting.mode==='off' ? '功能已完全关闭' : '自动选择 · 由 Codex 决定调用';
  $('workspace').textContent = setting.workspace;
  const effects = {off:['完全关闭','neutral'],auto:['自动选择','neutral'],pending_trust:['待信任','pending'],unknown:['状态待确认','neutral'],model_unavailable:['模型未就绪','pending'],ready_for_new_session:['配置就绪','ready']};
  badge('effect-badge', ...(effects[effective] || ['状态待确认','neutral']));
  const model = service.model;
  $('model-name').textContent = model ? `mDeBERTa ${model.replace('mdeberta_','')}` : '未连接模型';
  const ready = service.status==='OK' && service.model_loaded;
  badge('model-badge', ready ? '已就绪' : service.status==='UNAVAILABLE' ? '服务未连接' : service.status==='NOT_READY' ? '正在加载' : '未就绪', ready ? 'ok':'warn');
  $('hook-summary').textContent = hooks.status==='unknown' ? '暂时无法确认' : `${hooks.trusted_count} / ${hooks.required_count} 项已信任`;
  badge('hook-badge', hooks.all_ready ? '配置已确认' : hooks.status==='unknown' ? '读取失败' : '待审阅', hooks.all_ready ? 'ok':'warn');
  $('hook-summary').title = `上次检查：${new Date(hooks.checked_at).toLocaleString()}`;
  const notice = $('notice');
  notice.hidden = !setting.enabled;
  if (effective==='pending_trust') {
    $('notice-title').textContent = '开关已打开，首次审阅尚未完成';
    $('notice-text').textContent = '请在 Codex 中信任四项调用检查，再重新打开项目对话。开关本身不会替你完成信任。';
  } else if (effective==='model_unavailable') {
    $('notice-title').textContent = '调用检查已配置，模型暂未就绪';
    $('notice-text').textContent = '请检查本地判别服务。若任务被暂停，可先关闭这个开关。';
  } else if (effective==='ready_for_new_session') {
    $('notice-title').textContent = '配置已就绪，请在新会话中验收';
    $('notice-text').textContent = '四项 Hook 已信任，模型已连接。当前对话是否已加载检查，仍需以实际调用记录为准。';
  } else if (effective==='unknown') {
    $('notice-title').textContent = '开关已保存，暂时无法确认 Hook 状态';
    $('notice-text').textContent = '点击右上角刷新重新检查。当前不应视为强制流程已生效。';
  }
  const list = $('hook-list'); list.replaceChildren();
  for (const key of Object.keys(names)) {
    const matches = hooks.items.filter(h => h.event===key);
    const good = matches.length>0 && matches.every(h => h.enabled && ['trusted','managed'].includes(h.trust));
    const row = document.createElement('li');
    if (good) row.className = 'trusted';
    const label = document.createElement('span'); label.textContent = names[key];
    const status = document.createElement('span');
    status.textContent = good ? '已信任' : hooks.status==='unknown' ? '未知' : matches.length ? '待信任 / 启用' : '未发现';
    row.append(label,status); list.append(row);
  }
  $('updated').textContent = '同步于 ' + new Date(current.updated_at).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'});
}
function unconfirmed(message) {
  csrf=null;
  $('error').textContent=message; $('error').hidden=false;
  $('gate-switch').disabled=true; $('updated').textContent='状态未确认'; $('notice').hidden=true;
  $('switch-label').textContent=current ? `上次读取为${current.switch.enabled?'开启':'关闭'} · 当前无法确认` : '暂时无法读取开关';
  $('local-status').classList.add('offline'); $('local-label').textContent='本地连接已中断';
  badge('effect-badge','连接中断','neutral'); badge('model-badge','状态未确认','warn'); badge('hook-badge','状态未确认','warn');
  if (!current) { $('hook-summary').textContent='未连接'; $('model-name').textContent='未连接'; }
}
async function load(force=false) {
  if (saving) return;
  const id = ++requestId;
  $('refresh').classList.add('busy');
  try {
    if (!csrf) csrf = (await api('/api/session')).csrf;
    const state = await api('/api/status' + (force?'?refresh=1':''));
    if (id!==requestId) return;
    current = state; $('error').hidden = true; render();
  } catch (err) {
    if (id!==requestId) return;
    unconfirmed(err.message);
  } finally { if (id===requestId) $('refresh').classList.remove('busy'); }
}
$('gate-switch').addEventListener('click', async () => {
  if (!current || saving) return;
  saving = true; ++requestId; $('refresh').classList.remove('busy'); $('refresh').disabled = true; render();
  try {
    const saved = await api('/api/switch', {method:'POST',headers:{'Content-Type':'application/json','X-Gate-CSRF':csrf},body:JSON.stringify({enabled:!current.switch.enabled})});
    current.switch = saved.switch; $('error').hidden = true;
    saving = false; render(); await load();
  } catch (err) {
    saving = false; render(); unconfirmed('保存结果未确认，请刷新后查看实际状态。');
  } finally { saving=false; $('refresh').disabled=false; }
});
$('refresh').addEventListener('click', () => load(true));
$('copy-command').addEventListener('click', async () => {
  try { await navigator.clipboard.writeText('/hooks'); $('copy-command').textContent='已复制'; }
  catch { $('copy-command').textContent='请在 Codex 终端输入 /hooks'; }
});
document.addEventListener('visibilitychange', () => {if (!document.hidden) load();});
setInterval(() => {if (!document.hidden && !saving) load();},15000);
load();
