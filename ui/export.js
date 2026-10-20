/* One public action; a finished operation, validation and user acceptance differ. */
let exportRequestPending = false;
const exportTerminal = new Map();

document.querySelector('#start-autonomous').addEventListener('click', () => perform(async () => {
  if (!selectedProfile) throw new Error('Nejdříve prohlédněte externí profil.');
  const status = await request('start_autonomous', {
    source_path: document.querySelector('#source-path').value,
    name: document.querySelector('#run-name').value,
    profile_path: selectedProfile.path, profile_sha256: selectedProfile.sha256,
    environment: document.querySelector('#autonomous-environment').value.trim() || null,
  });
  selectedRun = status.run_id;
  renderEditions(await request('projects'));
  renderRun(await request('select_run', {run_id: status.run_id}));
  renderAutonomous(status);
  return 'Celý průchod zahájen: příprava, skutečné čtení, geometrie, PDF/TXT a kontroly výstupu.';
}));

function renderExportPanel(detail, data) {
  const panel = element('section', undefined, 'codex-panel'); panel.id = 'export-panel';
  panel.append(element('h3', 'První OCR PDF/TXT a kontroly výstupu'), element('p',
    'Export vychází z přesně prohlédnuté geometrie. AI následně zkoumá skutečné rendery vytvořeného PDF a zapíše konkrétní nálezy. Dokončení operace ani otevření souboru neznamená přijetí výsledku.', 'hint'));
  const start = element('button', 'Exportovat a zkontrolovat hotovou geometrii');
  start.id = 'start-first-export'; start.disabled = !data.run;
  start.addEventListener('click', () => perform(async () => {
    const status = await request('start_first_export', {run_id: data.project.run_id,
      environment: document.querySelector('#preparation-environment')?.value.trim() || null});
    renderAutonomous(status);
    return 'Export a skutečná kontrola výstupu zahájeny; původní čtení se neopakuje.';
  }));
  const state = element('p', 'Zjišťování stavu…'); state.id = 'autonomous-state'; state.setAttribute('aria-live', 'polite');
  const stages = element('ol'); stages.id = 'autonomous-stages';
  const results = element('div'); results.id = 'export-results';
  panel.append(start, state, stages, results); detail.append(panel);
  request('output_results', {run_id: data.project.run_id}).then(renderExportResults).catch(error => {
    if (selectedRun === data.project.run_id) results.textContent = error.message;
  });
}

function renderAutonomous(status) {
  if (selectedRun !== status.run_id) return;
  const state = document.querySelector('#autonomous-state'); if (!state) return;
  state.dataset.state = status.state;
  const names = {not_started: 'Autonomní akce dosud nespuštěna', starting: 'Spouštění',
    running: 'Probíhá', completed: 'Operace dokončena', failed: 'Operace selhala', interrupted: 'Operace přerušena'};
  state.textContent = `${names[status.state] || status.state}${status.stage ? ' · ' + status.stage : ''}`;
  if (status.error) state.textContent += ` · ${status.error.message} (${status.error.code})`;
  if (status.validation) state.textContent += ` · validace: ${status.validation} · přijetí: ${status.acceptance}`;
  document.querySelector('#autonomous-stages').replaceChildren(...status.stages.map(stage =>
    element('li', `${stage.stage} · ${stage.state}${stage.error ? ' · ' + stage.error.message : ''}`)));
  document.querySelector('#start-first-export').disabled = codexRunning() || status.state === 'completed';
}

function renderExportResults(result) {
  if (selectedRun !== result.run_id) return;
  const target = document.querySelector('#export-results'); if (!target) return;
  target.replaceChildren();
  if (!result.available) { target.append(element('p', 'PDF/TXT dosud nevytvořeny.')); return; }
  target.append(element('p', `Validace: ${result.project.validation} · přijetí: ${result.project.acceptance}`));
  document.querySelector('#start-first-export').hidden = true;
  if (result.prepared_resume) {
    const resume = element('button', 'Dokončit kontrolu tohoto připraveného exportu'); resume.id = 'resume-first-export';
    resume.dataset.manifestSha256 = result.prepared_resume.existing_export_sha256;
    resume.dataset.preparationSha256 = result.prepared_resume.prepared_review_sha256;
    resume.addEventListener('click', () => perform(async () => {
      renderAutonomous(await request('start_first_export', {run_id: result.run_id, ...result.prepared_resume,
        environment: document.querySelector('#preparation-environment')?.value.trim() || null}));
      return 'Pokračování přesně připraveného exportu zahájeno; čtení ani export se neopakuje.';
    })); target.append(resume);
  }
  for (const item of result.artifacts) {
    const button = element('button', `Otevřít externě: ${item.path}`, 'secondary');
    button.addEventListener('click', () => perform(async () => {
      await request('open_output_artifact', {run_id: result.run_id, ...item});
      return 'Požadavek na externí otevření odeslán. Prohlédnutí ani přijetí tím nebylo potvrzeno.';
    }));
    target.append(button);
  }
  const visual = result.reports.visual_review;
  target.append(element('p', result.report_provenance.status === 'original_turn_verified' ? visual?.conclusion :
    'Vizuální závěr dosud není ověřen proti původnímu modelovému JSON.'));
  if (result.report_provenance.status === 'invalidated') target.append(element('p', result.report_provenance.message, 'error'));
  if (visual) target.append(element('p', `Geometrie: ${visual.geometry_status} · prohlédnuté strany: ${visual.pages_reviewed.join(', ') || 'žádné'}`, 'hint'));
  const table = element('table', undefined, 'artifacts');
  const header = element('tr');
  for (const title of ['Nález', 'Stav', 'Důvod', 'Doklady']) header.append(element('th', title));
  table.append(header);
  for (const finding of result.reports.findings?.items || []) {
    const row = element('tr');
    const evidence = finding.evidence.map(path => path.startsWith(result.workspace + '/') ? path.slice(result.workspace.length + 1) : path);
    for (const value of [finding.id, finding.status, finding.reason || 'Dosud nevyhodnoceno', evidence.join(', ')]) row.append(element('td', value));
    table.append(row);
  }
  target.append(table);
  for (const [name, report] of Object.entries(result.reports)) {
    const detail = element('details'); detail.append(element('summary', name), element('pre', JSON.stringify(report, null, 2))); target.append(detail);
  }
}

setInterval(async () => {
  if (!connected || !selectedRun || exportRequestPending) return;
  exportRequestPending = true;
  const runId = selectedRun;
  try {
    const status = await request('autonomous_status', {run_id: runId});
    if (selectedRun !== runId) return;
    renderAutonomous(status);
    if (['completed', 'failed', 'interrupted'].includes(status.state) && exportTerminal.get(runId) !== status.attempt_id) {
      exportTerminal.set(runId, status.attempt_id);
      renderRun(await request('select_run', {run_id: runId})); renderAutonomous(status);
      renderExportResults(await request('output_results', {run_id: runId}));
    }
  } catch (error) {
    if (selectedRun === runId && document.querySelector('#autonomous-state')) document.querySelector('#autonomous-state').textContent = error.message;
  } finally { exportRequestPending = false; }
}, 650);
