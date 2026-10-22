/* All controls use the same durable public operations as subprocess tests. */
let queueStatus = null;
let queuePollPending = false;
const queueProofs = new Map();
const enqueueRequests = new Map();
const queueNames = {pending: 'Čeká v pořadí', starting: 'Spouštění', running: 'Probíhá',
  paused: 'Pozastaveno', blocked: 'Zastaveno – vyžaduje zásah', interrupted: 'Přerušeno',
  completed: 'Dokončeno', awaiting_input: 'Čeká na doplnění / revizi', failed: 'Chyba tohoto PDF',
  binding: 'Nedokončené zařazení – prohlédněte existující průchody'};
const queueReasons = {authentication: 'Je potřeba přihlášení účtem ChatGPT.', quota: 'Limit AI je vyčerpán.',
  model_unavailable: 'Požadovaný model nebo nastavení není dostupné.', network: 'Spojení s AI je nedostupné.',
  service_unavailable: 'Služba AI je nedostupná.', ai_unavailable: 'AI nelze bezpečně použít.',
  reconciliation: 'Před pokračováním je nutné ověřit původní práci.'};

async function enqueueFromGUI(payload) {
  const key = JSON.stringify(payload);
  if (!enqueueRequests.has(key)) enqueueRequests.set(key, `${Date.now()}-${Math.random().toString(36).slice(2)}`);
  const item = await request('enqueue_run', {...payload, request_id: enqueueRequests.get(key)});
  await refreshQueue();
  renderEditions(await request('projects'));
  return `Zařazen průchod ${item.run_name || item.run_id}. Práce začne až po spuštění fronty.`;
}

document.querySelector('#queue-new').addEventListener('click', () => perform(async () => {
  if (!selectedProfile) throw new Error('Nejdříve prohlédněte profil.');
  return enqueueFromGUI({source_path: document.querySelector('#source-path').value,
    name: document.querySelector('#run-name').value, profile_path: selectedProfile.path,
    profile_sha256: selectedProfile.sha256,
    environment: document.querySelector('#autonomous-environment').value.trim() || null,
    reuse_from_run_id: document.querySelector('#autonomous-donor').value || null});
}));
document.querySelector('#queue-selected').addEventListener('click', () => perform(async () => {
  if (!selectedRun) throw new Error('Nejdříve vyberte pojmenovaný průchod.');
  return enqueueFromGUI({run_id: selectedRun,
    environment: document.querySelector('#autonomous-environment').value.trim() || null});
}));
for (const action of ['pause', 'interrupt']) {
  document.querySelector(`#queue-${action}`).addEventListener('click', () => perform(async () => {
    queueStatus = await request(`${action}_queue`);
    renderQueue(queueStatus);
    return action === 'pause' ? 'Fronta pozastavena; běžící jednotka se může dokončit.' : 'Fronta přerušena; původní tah se před pokračováním ověří.';
  }));
}
document.querySelector('#queue-resume').addEventListener('click', () => perform(async () => {
  await refreshQueue();
  const active = queueStatus.items.find(i => i.item_id === queueStatus.active_item_id);
  let payload = {};
  if (active) {
    if (active.launch_state === 'not_started' && active.reason?.code === 'runtime_changed') {
      payload = {item_id: active.item_id, run_id: active.run_id, attempt_id: active.parent_attempt_id};
    } else {
    const proof = queueProofs.get(active.item_id);
    if (!proof || proof.attempt_id !== active.parent_attempt_id) throw new Error('Nejdříve u aktivní položky ověřte původní pokus.');
    payload = {item_id: active.item_id, run_id: active.run_id, attempt_id: active.parent_attempt_id,
      reconciliation_id: proof.reconciliation_id};
    }
  }
  queueStatus = await request('resume_queue', payload);
  queueProofs.clear(); renderQueue(queueStatus);
  return 'Fronta pokračuje podle uloženého pořadí.';
}));

function renderQueue(status) {
  queueStatus = status;
  const reason = status.reason;
  document.querySelector('#queue-state').textContent = `${queueNames[status.state] || status.state}${reason ?
    ' · ' + (queueReasons[reason.category] || reason.message) : ''}`;
  document.querySelector('#queue-evidence').textContent = JSON.stringify({reason: status.reason,
    manual_execution: status.manual_execution}, null, 2);
  document.querySelector('#queue-resume').disabled = status.state === 'running';
  const active = status.items.find(i => i.item_id === status.active_item_id);
  const pending = status.pending.map(id => status.items.find(i => i.item_id === id));
  const remaining = status.items.filter(i => i !== active && !status.pending.includes(i.item_id));
  const rows = [active, ...pending, ...remaining].filter(Boolean).map(item => {
    const row = element('li', undefined, 'queue-item');
    row.append(element('strong', `${item.source_name || 'Zdrojové PDF'} · ${item.run_name || item.run_id || 'Zařazování'}`),
      element('span', `${item === active ? 'Aktivní položka · ' : ''}${queueNames[item.state] || item.state}`));
    if (item.reason) row.append(element('p', queueReasons[item.reason.category] || item.reason.message, 'hint'));
    const actions = element('div', undefined, 'queue-actions');
    if (item.run_id) {
      const select = element('button', 'Prohlédnout průchod', 'secondary'); select.type = 'button';
      select.addEventListener('click', () => perform(async () => {
        selectedRun = item.run_id; renderRun(await request('select_run', {run_id: item.run_id}));
        return 'Zobrazen uložený průchod.';
      })); actions.append(select);
    }
    const index = status.pending.indexOf(item.item_id);
    if (index >= 0) for (const [delta, label] of [[-1, 'Posunout výše'], [1, 'Posunout níže']]) {
      const move = element('button', label, 'secondary'); move.type = 'button';
      move.disabled = index + delta < 0 || index + delta >= status.pending.length;
      move.addEventListener('click', () => perform(async () => {
        const order = [...status.pending]; [order[index], order[index + delta]] = [order[index + delta], order[index]];
        renderQueue(await request('reorder_queue', {item_ids: order, expected_revision: status.revision}));
        return 'Pořadí čekajících položek uloženo.';
      })); actions.append(move);
    }
    if (item === active && status.state !== 'running' && item.launch_state !== 'not_started') {
      const inspect = element('button', 'Ověřit původní pokus', 'secondary'); inspect.type = 'button';
      inspect.addEventListener('click', () => perform(async () => {
        const proof = await request('reconcile_autonomous', {run_id: item.run_id, attempt_id: item.parent_attempt_id});
        queueProofs.set(item.item_id, proof);
        return proof.provider.safe_to_continue && proof.checkpoint.valid ?
          'Původní práce i místní checkpoint ověřeny. Pokračování nyní můžete výslovně spustit.' :
          'Původní práce není bezpečně obnovitelná. Fronta zůstává zastavena; žádný tah se neopakuje.';
      })); actions.append(inspect);
    }
    if (item.reason?.code) {
      const details = element('details'); details.append(element('summary', 'Důvod a původní evidence'),
        element('pre', JSON.stringify(item.reason, null, 2))); row.append(details);
    }
    row.append(actions); return row;
  });
  document.querySelector('#queue-items').replaceChildren(...rows);
}

async function refreshQueue() {
  const status = await request('queue_status'); renderQueue(status); return status;
}
async function pollQueue() {
  if (!connected || queuePollPending) return;
  queuePollPending = true;
  try { await refreshQueue(); }
  catch (error) { document.querySelector('#queue-state').textContent = error.message; }
  finally { queuePollPending = false; }
}
setInterval(pollQueue, 800);
