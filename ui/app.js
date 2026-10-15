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
};
let selectedRun = null;
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
    await action();
    message.textContent = 'Evidence načtena. Zobrazené stavy odpovídají uloženým průchodům.';
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
      const button = element('button', `Průchod ${run.run_id.slice(-12)}`, 'run');
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
    element('h2', project.original_name, 'detail-title'),
    element('div', project.run_id, 'run-id'));
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
}

async function selectRun(runId) {
  const data = await request('select_run', { run_id: runId });
  selectedRun = runId;
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
