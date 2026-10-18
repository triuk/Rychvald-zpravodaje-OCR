/* Public context verification controls; registration never means readiness. */
let contextRequestPending = false;

function renderContextPanel(detail, data) {
  const panel = element('section', undefined, 'codex-panel');
  panel.id = 'context-panel';
  panel.append(element('h3', 'Context-mode · směrování a obnova'), element('p',
    'Ověření vytvoří rozsáhlý místní výstup, dohledá znalost a obnoví skutečnou relaci po kompaktaci. Používá účet ChatGPT a přesně gpt-6.1-sol · high.', 'hint'));
  const start = element('button', 'Ověřit context-mode');
  start.id = 'start-context-diagnostic';
  start.dataset.runId = data.project.run_id;
  start.disabled = !data.run;
  start.addEventListener('click', () => perform(async () => {
    renderContext(await request('start_context_diagnostic', { run_id: data.project.run_id }));
    return 'Skutečné ověření context-mode bylo zahájeno.';
  }));
  const state = element('p', 'Dosud neověřeno');
  state.id = 'context-state';
  state.setAttribute('aria-live', 'polite');
  const readiness = element('p', '', 'hint');
  readiness.id = 'context-readiness';
  const details = element('details');
  details.append(element('summary', 'Důvěra hooků, prostředí a skutečné tahy'));
  const evidence = element('pre');
  evidence.id = 'context-evidence';
  details.append(evidence);
  panel.append(start, state, readiness, details);
  detail.append(panel);
}

function renderContext(status) {
  const state = document.querySelector('#context-state');
  if (!state || status.run_id !== selectedRun) return;
  state.dataset.state = status.state;
  state.dataset.attemptId = status.attempt_id || '';
  const names = { not_started: 'Dosud neověřeno', starting: 'Spouští se ověření', running: 'Probíhá skutečné ověření context-mode',
    completed: 'Ověření context-mode dokončeno', failed: 'Ověření context-mode selhalo', interrupted: 'Ověření přerušeno', invalidated: 'Ověření context-mode zneplatněno' };
  state.textContent = names[status.state] || status.state;
  if (status.error) state.textContent += ` · ${status.error.message} (${status.error.code})`;
  document.querySelector('#context-readiness').textContent = status.autonomous_ocr_ready ?
    'Model, obrazový vstup a context-mode jsou ověřeny pro tento průchod. Čtení, export, validaci a přijetí uvádějí vlastní stavy průchodu.' :
    status.context_verified ? 'Context-mode ověřen; pro připravenost celé kombinace je nutné také platné obrazové ověření tohoto průchodu.' :
    'Autonomní OCR není připraveno. Samotná dostupnost modelu nebo registrace MCP nestačí.';
  document.querySelector('#context-evidence').textContent = JSON.stringify({
    attempt_id: status.attempt_id, thread_id: status.thread_id, turns: status.turns, context_runtime: status.context_runtime,
    requested: status.requested, effective: status.effective, authenticated: status.authenticated,
    effective_context_config: status.effective_context_config, trusted_hooks: status.trusted_hooks,
    context_paths: status.context_paths, context_evidence: status.context_evidence,
    context_verified: status.context_verified || false, model_verified: status.model_verified || false,
    autonomous_ocr_ready: status.autonomous_ocr_ready || false, artifacts: status.artifacts,
  }, null, 2);
  document.querySelector('#start-context-diagnostic').disabled = codexRunning() ||
    ['starting', 'running'].includes(document.querySelector('#preparation-state')?.dataset.state) || !document.querySelector('#run-profile');
  if (typeof updateReadingAvailability === 'function') updateReadingAvailability(status);
}

setInterval(async () => {
  if (!connected || !selectedRun || contextRequestPending || !document.querySelector('#context-state')) return;
  const runId = selectedRun;
  contextRequestPending = true;
  try {
    const status = await request('context_status', { run_id: runId });
    if (selectedRun === runId) renderContext(status);
  } catch (error) {
    const state = document.querySelector('#context-state');
    if (state && selectedRun === runId) state.textContent = error.message;
  } finally {
    contextRequestPending = false;
  }
}, 750);
