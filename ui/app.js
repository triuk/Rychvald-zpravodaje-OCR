'use strict';

const labels = {
  registered: 'Zaregistrován', prepared: 'Místní příprava dokončena',
  preparing: 'Místní příprava', preparation_failed: 'Příprava selhala',
  preparation_interrupted: 'Příprava přerušena', exporting: 'Export',
  export_interrupted: 'Export přerušen', ready: 'Připraven k revizi',
  ready_with_open_items: 'Čeká na doplnění', failed: 'Selhalo',
  idle: 'Neprobíhá', running: 'Probíhá', completed: 'Dokončeno',
  interrupted: 'Přerušeno', not_run: 'Neprovedena', passed: 'Prošla',
  not_recorded: 'Nezaznamenáno', accepted: 'Přijato zadavatelem',
};
const artifactLabels = {
  source: 'Zdrojový sken', workspace: 'Pracovní adresář', project: 'Záznam průchodu',
  output_pdf: 'OCR PDF', output_txt: 'Text článků', history: 'Historie průchodu',
  profile_snapshot: 'Použitý profil', run_manifest: 'Identita průchodu',
};
let selectedRun = null;
let runSelection = 0;
let selectedProfile = null;
let connected = false;
let requestQueue = Promise.resolve();
let progressRequestPending = false;
let displayedPreparation = null;
const preparationEnvironments = new Map();
const diagnosticImages = new Map();
let codexRequestPending = false;
const rootInput = document.querySelector('#registry-root');
const message = document.querySelector('#message');
window.addEventListener('error', event => {
  message.className = 'error';
  message.textContent = `Aplikaci se nepodařilo načíst: ${event.message}`;
});

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

// Serialize user requests so a slower selection cannot overwrite a newer one.
function request(operation, payload = {}) {
  const call = requestQueue.then(async () => {
    if (!connected) throw new Error('Aplikace ještě není připojena.');
    const result = JSON.parse(await window.requestB(JSON.stringify({ operation, payload })));
    if (!result.ok) throw new Error(`${result.error.message} (${result.error.code})`);
    return result.data;
  });
  requestQueue = call.catch(() => {});
  return call;
}

async function perform(action) {
  try {
    message.className = '';
    message.textContent = 'Načítání…';
    const success = await action();
    message.textContent = success || 'Evidence načtena. Zobrazené stavy odpovídají uloženým průchodům.';
  } catch (error) {
    message.className = 'error';
    message.textContent = error.message;
  }
}

function renderEditions(data) {
  rootInput.value = data.root;
  document.querySelector('#edition-count').textContent = data.editions.length;
  const list = document.querySelector('#editions');
  list.replaceChildren();
  const choice = document.querySelector('#edition-choice');
  const previousEdition = choice.value;
  choice.replaceChildren();
  for (const edition of data.editions) {
    const option = element('option', `${edition.name} · ${edition.edition_id.slice(0, 12)}`);
    option.value = edition.edition_id;
    choice.append(option);
  }
  if (data.editions.some(edition => edition.edition_id === previousEdition)) choice.value = previousEdition;
  if (!data.editions.length) {
    list.append(element('p', 'Evidence zatím neobsahuje průchody OCR. Otevřete adresář existující evidence.', 'hint'));
  }
  for (const edition of data.editions) {
    const section = element('section', undefined, 'edition');
    section.append(element('h3', edition.name));
    const digest = element('div', `Zdroj ${edition.source_sha256.slice(0, 12)}…`, 'source-id');
    digest.title = edition.source_sha256;
    section.append(digest);
    for (const run of edition.runs) {
      const button = element('button', run.run_name || `Importovaný průchod ${run.run_id.slice(-12)}`, 'run');
      button.type = 'button';
      button.dataset.runId = run.run_id;
      button.setAttribute('aria-pressed', String(run.run_id === selectedRun));
      button.append(element('span', labels[run.phase] || run.phase));
      button.addEventListener('click', () => perform(() => selectRun(run.run_id)));
      section.append(button);
    }
    list.append(section);
  }
}

function renderRun(data) {
  const detail = document.querySelector('#detail');
  const project = data.project;
  detail.dataset.runId = project.run_id;
  detail.replaceChildren(element('span', 'PŘEHLED PRŮCHODU', 'eyebrow'),
    element('h2', project.run_name || project.original_name, 'detail-title'),
    element('div', `${project.original_name} · ${project.run_id}`, 'run-id'));
  const statuses = element('dl', undefined, 'statuses');
  for (const [key, title] of [['phase', 'Fáze OCR'], ['operation_state', 'Stav operace'],
    ['validation', 'Validace'], ['acceptance', 'Přijetí zadavatelem']]) {
    const card = element('div', undefined, 'status-card');
    const value = element('dd', labels[project[key]] || project[key]);
    value.append(element('span', project[key], 'status-code'));
    card.append(element('dt', title), value);
    statuses.append(card);
  }
  detail.append(statuses, element('p',
    'Načtení do aplikace nemění výsledek validace ani neznamená přijetí zadavatelem.', 'hint'));
  const section = element('section', undefined, 'artifact-section');
  section.append(element('h3', 'Artefakty průchodu'));
  const table = element('table', undefined, 'artifacts');
  const head = element('tr');
  for (const title of ['Artefakt', 'Cesta v evidenci', 'Dostupnost']) head.append(element('th', title));
  const thead = element('thead');
  thead.append(head);
  table.append(thead);
  const body = element('tbody');
  for (const [key, artifact] of Object.entries(data.artifacts)) {
    const row = element('tr');
    row.append(element('td', artifactLabels[key] || key), element('td', artifact.path),
      element('td', artifact.available ? 'Dostupný' : 'Není k dispozici',
        artifact.available ? 'availability' : 'availability missing'));
    body.append(row);
  }
  table.append(body);
  section.append(table);
  detail.append(section);
  const preparation = element('section', undefined, 'preparation-panel');
  preparation.append(element('h3', 'Místní příprava'));
  const controls = element('form', undefined, 'input-row');
  controls.id = 'preparation-form';
  const environment = element('input');
  environment.id = 'preparation-environment';
  environment.type = 'text';
  environment.placeholder = 'Manifest prostředí (volitelné; jinak prostředí OCR procesu)';
  environment.value = preparationEnvironments.get(project.run_id) || '';
  environment.setAttribute('aria-label', 'Manifest nativního OCR prostředí');
  const start = element('button', 'Spustit místní přípravu');
  start.id = 'start-preparation';
  start.type = 'submit';
  start.disabled = !data.run;
  controls.append(environment, start);
  controls.addEventListener('submit', event => {
    event.preventDefault();
    perform(async () => {
      const payload = { run_id: project.run_id };
      preparationEnvironments.set(project.run_id, environment.value);
      if (environment.value.trim()) payload.environment = environment.value;
      const status = await request('start_preparation', payload);
      renderPreparation(status);
      return 'Místní příprava byla spuštěna. Přehled a výběr průchodů zůstávají dostupné.';
    });
  });
  preparation.append(controls);
  if (!data.run) preparation.append(element('p', 'Pro spuštění založte pojmenovaný průchod s profilem.', 'hint'));
  const status = element('p', 'Zjišťování stavu…');
  status.id = 'preparation-state';
  status.setAttribute('aria-live', 'polite');
  const units = element('p', '', 'hint');
  units.id = 'preparation-counts';
  const events = element('ol', undefined, 'preparation-events');
  events.id = 'preparation-events';
  preparation.append(status, units, events);
  detail.append(preparation);
  renderCodexPanel(detail, data);
  if (typeof renderContextPanel === 'function') renderContextPanel(detail, data);
  window.renderMetricsPanel(detail, data, request);
  if (data.run) {
    const profile = element('section', undefined, 'run-profile');
    profile.id = 'run-profile';
    profile.append(element('h3', `Použitý profil: ${data.run.profile.name}`));
    const parameters = data.run.profile.parameters;
    profile.append(element('p', `${parameters.dpi} DPI · ${parameters.language} · ${parameters.model} · ${parameters.reasoning_effort}`, 'hint'));
    const content = element('details');
    content.append(element('summary', 'Prompty a nastavení uložené s tímto průchodem'),
      element('pre', JSON.stringify(data.run.profile, null, 2)));
    profile.append(content);
    const history = element('ul', undefined, 'run-history');
    history.id = 'run-history';
    const summaries = { run_created: 'Průchod založen', attempt_started: 'Místní příprava zahájena',
      codex_attempt_started: 'Pokus Codex zahájen', codex_attempt_completed: 'Pokus Codex dokončen',
      codex_attempt_failed: 'Pokus Codex selhal', codex_attempt_interrupted: 'Pokus Codex přerušen',
      attempt_completed: 'Místní příprava dokončena', attempt_failed: 'Místní příprava selhala', attempt_interrupted: 'Místní příprava přerušena' };
    for (const event of data.history) {
      if (summaries[event.type]) history.append(element('li', `${summaries[event.type]} · ${event.timestamp}`));
    }
    profile.append(element('h3', 'Historie průchodu'), history);
    detail.append(profile);
  }
}

async function selectRun(runId) {
  const selection = ++runSelection;
  selectedRun = null;
  const detail = document.querySelector('#detail');
  detail.dataset.runId = '';
  detail.replaceChildren(element('p', 'Načítá se vybraný průchod…'));
  const data = await request('select_run', { run_id: runId });
  if (selection !== runSelection) return;
  selectedRun = runId;
  document.querySelector('#edition-choice').value = data.edition_id;
  document.querySelectorAll('.run').forEach(button => {
    button.setAttribute('aria-pressed', String(button.dataset.runId === selectedRun));
  });
  renderRun(data);
}

function stepLabel(step) {
  if (step.startsWith('raster:page:')) return `Rastr · strana ${step.split(':')[2]}`;
  if (step.startsWith('ocr:page:')) return `OCR · strana ${step.split(':')[2]}, PSM ${step.split(':')[4]}`;
  return { environment: 'Ověření prostředí', candidates: 'Kandidátní text',
    artifact_validation: 'Kontrola hashů podkladů', preparation: 'Místní příprava' }[step] || step;
}

function renderPreparation(status) {
  const state = document.querySelector('#preparation-state');
  if (!state || status.run_id !== selectedRun) return;
  const names = { not_started: 'Dosud nespouštěna', starting: 'Spouští se', running: 'Probíhá',
    completed: 'Dokončena; podklady ověřeny', failed: 'Poslední pokus selhal',
    interrupted: 'Přerušena', invalidated: 'Podklady se změnily; kontrola neprošla' };
  state.dataset.state = status.state;
  state.dataset.attemptId = status.attempt_id || '';
  state.dataset.activeSteps = (status.active_steps || []).join(' ');
  if (status.environment && !preparationEnvironments.has(selectedRun)) {
    preparationEnvironments.set(selectedRun, status.environment);
    document.querySelector('#preparation-environment').value = status.environment;
  }
  const active = status.active_steps?.map(stepLabel).join(' · ');
  state.textContent = `${names[status.state] || status.state}${active ? ` · ${active}` : ''}${status.elapsed_seconds !== undefined ? ` · ${status.elapsed_seconds.toFixed(1)} s` : ''}`;
  if (status.error) state.textContent += ` · ${status.error.message} (${status.error.code})`;
  const failureDetail = [...status.events].reverse().find(event => event.error?.detail)?.error.detail;
  if (failureDetail) state.textContent += ` · ${failureDetail}`;
  const counts = status.counts;
  const countDisplay = document.querySelector('#preparation-counts');
  countDisplay.dataset.pagesTotal = counts.pages_total || 0;
  countDisplay.textContent = counts.pages_total === undefined ? '' : counts.totals_known ?
    `Ověřené rastry stránek: ${counts.pages_completed}/${counts.pages_total}. Ověřené úlohy OCR: ${counts.ocr_completed}/${counts.ocr_total}. Převzato z platné cache: ${counts.rasters_cached} rastrů, ${counts.ocr_cached} úloh OCR.` :
    'Počet stránek a úloh nebyl dosud zjištěn; dokončené jednotky: 0.';
  const list = document.querySelector('#preparation-events');
  list.replaceChildren();
  const eventNames = { attempt_started: 'Pokus zahájen', step_started: 'Zahájeno', unit_started: 'Jednotka zahájena',
    step_completed: 'Dokončeno', unit_completed: 'Jednotka ověřena', unit_cached: 'Ověřená cache',
    units_planned: 'Načten počet stránek', checkpoint_completed: 'Checkpoint ověřen',
    attempt_completed: 'Pokus dokončen', step_failed: 'Krok selhal', attempt_failed: 'Pokus selhal', attempt_interrupted: 'Pokus přerušen' };
  for (const event of status.events.slice(-12)) {
    const row = element('li', `${eventNames[event.type] || event.type} · ${stepLabel(event.step_id)}${event.duration_seconds !== undefined ? ` · ${event.duration_seconds.toFixed(2)} s` : ''}`);
    row.title = event.event_id;
    list.append(row);
  }
  const button = document.querySelector('#start-preparation');
  if (button) button.disabled = ['starting', 'running'].includes(status.state) || codexRunning() || !document.querySelector('#run-profile');
}

function codexRunning() {
  return ['starting', 'running', 'awaiting_login'].includes(document.querySelector('#codex-state')?.dataset.state) ||
    ['starting', 'running'].includes(document.querySelector('#context-state')?.dataset.state);
}

function renderCodexPanel(detail, data) {
  const panel = element('section', undefined, 'codex-panel');
  panel.append(element('h3', 'Codex · obrazové ověření'), element('p',
    'Požadavek: gpt-6.1-sol · high. Dokončená diagnostika účtu a obrazu nenahrazuje autonomní OCR; to vyžaduje také ověřený context-mode.', 'hint'));
  const accountControls = element('div', undefined, 'input-row');
  for (const [operation, id, title] of [['check_codex_account', 'codex-account-check', 'Ověřit přihlášení'],
    ['start_codex_login', 'codex-login', 'Přihlásit účet ChatGPT']]) {
    const button = element('button', title, 'secondary');
    button.id = id;
    button.type = 'button';
    button.disabled = !data.run;
    button.addEventListener('click', () => perform(async () => {
      renderCodex(await request(operation, { run_id: data.project.run_id }));
      return 'Ověření účtu Codex bylo zahájeno.';
    }));
    accountControls.append(button);
  }
  const form = element('form', undefined, 'setup-form');
  form.id = 'codex-diagnostic-form';
  const label = element('label', 'Připravený diagnostický obrázek PNG/JPEG');
  label.htmlFor = 'diagnostic-image';
  const row = element('div', undefined, 'input-row');
  const input = element('input');
  input.id = 'diagnostic-image';
  input.type = 'text';
  input.placeholder = 'Cesta k obrázku; prázdná použije připravený rastr první strany';
  input.value = diagnosticImages.get(data.project.run_id) || '';
  const start = element('button', 'Přečíst diagnostický obrázek');
  start.id = 'start-model-diagnostic';
  start.type = 'submit';
  start.disabled = !data.run;
  row.append(input, start);
  form.append(label, row);
  form.addEventListener('submit', event => {
    event.preventDefault();
    perform(async () => {
      diagnosticImages.set(data.project.run_id, input.value);
      const payload = { run_id: data.project.run_id };
      if (input.value.trim()) payload.image_path = input.value;
      renderCodex(await request('start_model_diagnostic', payload));
      return 'Skutečné diagnostické čtení obrázku bylo zahájeno.';
    });
  });
  const state = element('p', 'Dosud nespouštěno');
  state.id = 'codex-state';
  state.setAttribute('aria-live', 'polite');
  const account = element('p', '', 'hint');
  account.id = 'codex-account';
  const login = element('a', 'Pokračovat přihlášením v prohlížeči');
  login.id = 'codex-login-link';
  login.target = '_blank';
  login.rel = 'noopener noreferrer';
  login.hidden = true;
  const answer = element('pre');
  answer.id = 'codex-answer';
  answer.setAttribute('aria-label', 'Dostupná odpověď diagnostického tahu');
  const evidence = element('details');
  evidence.append(element('summary', 'Zadání, identity a původní usage údaje'));
  const content = element('pre');
  content.id = 'codex-evidence';
  evidence.append(content);
  panel.append(accountControls, form, state, account, login, answer, evidence);
  detail.append(panel);
}

function renderCodex(status) {
  const state = document.querySelector('#codex-state');
  if (!state || status.run_id !== selectedRun) return;
  const names = { not_started: 'Dosud nespouštěno', starting: 'Spouští se ověřený Codex',
    running: 'Codex pracuje', awaiting_login: 'Čeká na přihlášení účtem ChatGPT',
    completed: 'Diagnostický krok dokončen', failed: 'Diagnostický krok selhal',
    interrupted: 'Diagnostický krok přerušen', invalidated: 'Obrazový doklad se změnil' };
  state.dataset.state = status.state;
  state.dataset.attemptId = status.attempt_id || '';
  state.dataset.operation = status.operation || '';
  state.dataset.combinationVerified = String(status.combination_verified || false);
  state.textContent = names[status.state] || status.state;
  if (status.error) state.textContent += ` · ${status.error.message} (${status.error.code})`;
  const account = document.querySelector('#codex-account');
  account.textContent = status.authenticated === true ? 'Účet: přihlášen přes ChatGPT.' :
    status.authenticated === false ? 'Účet: není přihlášen přes ChatGPT.' : 'Přihlášení účtu dosud neověřeno.';
  if (status.effective) account.textContent += ` Konfigurace vlákna: ${status.effective.model} · ${status.effective.reasoning_effort}.`;
  if (status.combination_verified) account.textContent += ' Požadovaná kombinace dokončila obrazový tah bez hlášeného přesměrování.';
  const login = document.querySelector('#codex-login-link');
  login.hidden = !status.login_url;
  if (status.login_url) login.href = status.login_url;
  else login.removeAttribute('href');
  document.querySelector('#codex-answer').textContent = status.answer || '';
  document.querySelector('#codex-evidence').textContent = JSON.stringify({
    attempt_id: status.attempt_id, thread_id: status.thread_id, turn_id: status.turn_id,
    requested: status.requested, effective: status.effective, image: status.image,
    prompt: status.prompt, profile_sha256: status.profile_sha256, runtime: status.runtime,
    reroutes: status.reroutes, usage_events: status.usage_events, artifacts: status.artifacts,
    autonomous_ocr_ready: false,
  }, null, 2);
  const busy = codexRunning() || ['starting', 'running'].includes(document.querySelector('#preparation-state')?.dataset.state);
  for (const id of ['codex-account-check', 'codex-login', 'start-model-diagnostic']) {
    document.querySelector('#' + id).disabled = busy || !document.querySelector('#run-profile');
  }
}

async function pollCodex() {
  if (!connected || !selectedRun || codexRequestPending) return;
  const runId = selectedRun;
  codexRequestPending = true;
  try {
    const status = await request('model_diagnostic_status', { run_id: runId });
    if (selectedRun === runId) renderCodex(status);
  } catch (error) {
    const state = document.querySelector('#codex-state');
    if (state && selectedRun === runId) state.textContent = error.message;
  } finally {
    codexRequestPending = false;
  }
}
setInterval(pollCodex, 450);

async function pollPreparation() {
  if (!connected || !selectedRun || progressRequestPending) return;
  const runId = selectedRun;
  progressRequestPending = true;
  try {
    const status = await request('preparation_status', { run_id: runId });
    if (selectedRun !== runId) return;
    renderPreparation(status);
    if (['completed', 'failed', 'interrupted', 'invalidated'].includes(status.state) && status.attempt_id !== displayedPreparation) {
      displayedPreparation = status.attempt_id;
      await selectRun(runId);
      renderPreparation(status);
    }
  } catch (error) {
    const state = document.querySelector('#preparation-state');
    if (state && selectedRun === runId) state.textContent = error.message;
  } finally {
    progressRequestPending = false;
  }
}
setInterval(pollPreparation, 350);

async function refresh() {
  const data = await request('projects');
  renderEditions(data);
  if (selectedRun) await selectRun(selectedRun);
}

document.querySelector('#registry-form').addEventListener('submit', event => {
  event.preventDefault();
  perform(async () => {
    const data = await request('open_registry', { root: rootInput.value });
    selectedRun = null;
    renderEditions(data);
    const detail = document.querySelector('#detail');
    detail.replaceChildren(element('h2', 'Vyberte průchod OCR'),
      element('p', 'Průchody vybraného vydání najdete v levém sloupci.', 'hint'));
  });
});
document.querySelector('#refresh').addEventListener('click', () => perform(refresh));

document.querySelector('#source-form').addEventListener('submit', event => {
  event.preventDefault();
  perform(async () => {
    const data = await request('import_sources', { path: document.querySelector('#source-path').value });
    renderEditions(data);
    return `Import dokončen: ${data.counts.created} nových průchodů, ${data.counts.reused} již evidovaných zdrojů.`;
  });
});
document.querySelector('#profile-path').addEventListener('input', () => {
  selectedProfile = null;
  document.querySelector('#create-run').disabled = true;
  document.querySelector('#profile-preview').hidden = true;
});
document.querySelector('#profile-form').addEventListener('submit', event => {
  event.preventDefault();
  perform(async () => {
    selectedProfile = null;
    document.querySelector('#create-run').disabled = true;
    const data = await request('inspect_profile', { path: document.querySelector('#profile-path').value });
    selectedProfile = data;
    document.querySelector('#profile-path').value = data.path;
    document.querySelector('#profile-title').textContent = data.profile.name;
    const parameters = data.profile.parameters;
    document.querySelector('#profile-parameters').textContent = `${parameters.dpi} DPI · ${parameters.language} · ${parameters.model} · ${parameters.reasoning_effort}`;
    document.querySelector('#profile-text').textContent = data.text;
    document.querySelector('#profile-preview').hidden = false;
    document.querySelector('#create-run').disabled = false;
    return 'Profil načten. Prompty a parametry lze prohlédnout před založením průchodu.';
  });
});
document.querySelector('#run-form').addEventListener('submit', event => {
  event.preventDefault();
  perform(async () => {
    if (!selectedProfile) throw new Error('Nejdříve prohlédněte externí profil.');
    const data = await request('create_run', {
      edition_id: document.querySelector('#edition-choice').value,
      name: document.querySelector('#run-name').value,
      profile_path: selectedProfile.path, profile_sha256: selectedProfile.sha256,
    });
    selectedRun = data.project.run_id;
    renderEditions(await request('projects'));
    renderRun(data);
    return `Průchod „${data.project.run_name}“ založen. Použitý profil je uložen s průchodem.`;
  });
});

function onConnected() {
  if (!connected) {
    connected = true;
    perform(refresh);
  }
}

function connectBridge() {
  // WebUI creates its bridge during document startup, after deferred scripts.
  if (typeof webui === 'undefined') {
    setTimeout(connectBridge, 100);
    return;
  }
  webui.setEventCallback(event => {
    if (event === webui.event.CONNECTED) {
      onConnected();
    } else if (event === webui.event.DISCONNECTED) {
      connected = false;
      message.className = 'error';
      message.textContent = 'Spojení s aplikací bylo ukončeno.';
    }
  });
  if (webui.isConnected()) onConnected();
  else setTimeout(connectBridge, 100);
}
connectBridge();
