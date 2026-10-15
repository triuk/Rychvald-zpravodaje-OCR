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
let selectedProfile = null;
let connected = false;
let requestQueue = Promise.resolve();
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
    for (const event of data.history) {
      history.append(element('li', `${event.type === 'run_created' ? 'Průchod založen' : event.type} · ${event.timestamp}`));
    }
    profile.append(element('h3', 'Historie průchodu'), history);
    detail.append(profile);
  }
}

async function selectRun(runId) {
  const data = await request('select_run', { run_id: runId });
  selectedRun = runId;
  document.querySelector('#edition-choice').value = data.edition_id;
  document.querySelectorAll('.run').forEach(button => {
    button.setAttribute('aria-pressed', String(button.dataset.runId === selectedRun));
  });
  renderRun(data);
}

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
