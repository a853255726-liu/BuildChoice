/* Fixed recognition fixture: no camera or OCR claim. Configuration supports negative controls. */
// Keep the demo usable when index.html is opened without the test harness.
window.receiptFixture ??= {amount: 38.5, date: '2026-10-30', category: '餐饮'};
window.receiptConfig ??= {early_save: false, ignore_edits: false};
const form = document.querySelector('#review');
const message = document.querySelector('#message');
let draft = null;
function commit(value) {
  const ledger = JSON.parse(localStorage.getItem('formal-ledger') || '[]');
  ledger.push({...value});
  localStorage.setItem('formal-ledger', JSON.stringify(ledger));
}
document.querySelector('#recognize').onclick = () => {
  draft = {...window.receiptFixture};
  for (const name of ['amount', 'date', 'category']) document.querySelector('#' + name).value = draft[name];
  form.hidden = false;
  if (window.receiptConfig.early_save) commit(draft);
};
form.onsubmit = event => {
  event.preventDefault();
  if (!draft) return;
  const value = window.receiptConfig.ignore_edits ? draft : {
    amount: Number(document.querySelector('#amount').value),
    date: document.querySelector('#date').value,
    category: document.querySelector('#category').value
  };
  commit(value); draft = null; form.hidden = true; message.textContent = '已正式保存';
};
document.querySelector('#cancel').onclick = () => {
  draft = null; form.hidden = true; message.textContent = '已取消';
};
