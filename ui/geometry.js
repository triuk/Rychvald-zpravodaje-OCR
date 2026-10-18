/* Source-bound geometry work; opening or generating an image confirms nothing. */
let geometryRequestPending = false;
let displayedGeometry = null;
const geometryInputs = new Map();
const geometryStatuses = new Map();

function renderGeometryPanel(detail, data) {
  const panel = element('section', undefined, 'codex-panel');
  panel.id = 'geometry-panel';
  panel.append(element('h3', 'Pořadí, geometrie a zdrojové vzorky'), element('p',
    'AI připraví nezávislá očekávání z původních obrazů před exportem a prohlédne původní výřezy, červené překryvy znaků i zelené testovací oblasti. Přesnost znakových řezů zůstává aproximací; otevřené nálezy se evidují jednotlivě.', 'hint'));
  const options = element('details');
  options.append(element('summary', 'Znovu použít dříve nezávisle připravené vzorky zdroje'));
  for (const [id, label] of [['geometry-samples', 'Soubor původních zdrojových vzorků'],
    ['geometry-commitment', 'Původní doklad identity a závazku vzorků'], ['geometry-commitment-pointer', 'Poloha závazku v dokladu']]) {
    const field = element('label', label);
    const input = element('input'); input.id = id; input.type = 'text';
    if (id.endsWith('pointer')) input.value = '/samples_commitment';
    if (geometryInputs.get(data.project.run_id)?.[id] !== undefined) input.value = geometryInputs.get(data.project.run_id)[id];
    input.addEventListener('input', () => {
      const values = geometryInputs.get(data.project.run_id) || {};
      values[id] = input.value; geometryInputs.set(data.project.run_id, values);
    });
    field.append(input); options.append(field);
  }
  const start = element('button', 'Připravit a prohlédnout geometrii');
  start.id = 'start-geometry'; start.dataset.runId = data.project.run_id; start.disabled = true;
  start.addEventListener('click', () => perform(async () => {
    const payload = {run_id: data.project.run_id};
    const previous = geometryStatuses.get(data.project.run_id);
    if (previous?.attempt_id) payload.previous_attempt_id = previous.attempt_id;
    const samples = document.querySelector('#geometry-samples').value.trim();
    if (samples) Object.assign(payload, {samples_path: samples,
      source_commitment_path: document.querySelector('#geometry-commitment').value.trim(),
      commitment_pointer: document.querySelector('#geometry-commitment-pointer').value.trim()});
    renderGeometry(await request('start_geometry', payload));
    return 'Příprava zdrojových vzorků a skutečná kontrola geometrie zahájena.';
  }));
  const state = element('p', 'Zjišťování stavu…'); state.id = 'geometry-state'; state.setAttribute('aria-live', 'polite');
  const counts = element('p', '', 'hint'); counts.id = 'geometry-counts';
  const output = element('div'); output.id = 'geometry-output';
  panel.append(options, start, state, counts, output); detail.append(panel);
}

function renderGeometry(status) {
  if (status.run_id !== selectedRun) return;
  const state = document.querySelector('#geometry-state'); if (!state) return;
  state.dataset.state = status.state; state.dataset.attemptId = status.attempt_id || '';
  geometryStatuses.set(status.run_id, status);
  document.querySelector('#start-geometry').textContent = status.attempt_id ? 'Pokračovat po kontrole uloženého pokusu' : 'Připravit a prohlédnout geometrii';
  const names = {not_started: 'Dosud nepřipraveno', starting: 'Spouští se', running: 'Probíhá příprava a skutečné prohlížení',
    completed: 'Podklady a skutečné prohlédnutí ověřeny; znaková geometrie zůstává aproximací',
    failed: 'Operace selhala; uložené podklady nejsou dokončeným milníkem', interrupted: 'Přerušeno', invalidated: 'Podklady se změnily; je nutná nová kontrola'};
  state.textContent = names[status.state] || status.state;
  if (status.error) state.textContent += ` · ${status.error.message} (${status.error.code})`;
  document.querySelector('#start-geometry').disabled = !readingReadiness.get(selectedRun) || codexRunning() ||
    document.querySelector('#reading-state')?.dataset.state !== 'completed' ||
    ['starting','running'].includes(document.querySelector('#preparation-state')?.dataset.state);
  const counts = status.counts || {};
  document.querySelector('#geometry-counts').textContent = `Řádky: ${counts.lines || 0} · zdrojové vzorky: ${counts.samples || 0} · otevřené položky geometrie: ${counts.open_items || 0}. Exportní kontroly dosud neprovedeny; přijetí zadavatelem je samostatné.`;
  const output = document.querySelector('#geometry-output'); output.replaceChildren();
  if (status.prepared) {
    const images = element('details'); images.append(element('summary', 'Otevřít originály, překryvy a zdrojové vzorky'));
    for (const image of status.prepared.images) {
      const button = element('button', image.path, 'secondary');
      button.addEventListener('click', () => perform(async () => {
        await request('open_geometry_artifact', {run_id: selectedRun, path: image.path});
        return 'Otevření v externím nástroji vyžádáno; samo nepotvrzuje prohlédnutí.';
      }));
      images.append(button);
    }
    output.append(images);
    output.append(element('p', `Nevyřešené čtení zdroje: ${status.prepared.unresolved.length} · původní rizika: ${status.prepared.source_risks.length}`, 'hint'));
  }
  if (status.observations) {
    const observations = element('details'); observations.open = true;
    observations.append(element('summary', 'Jednotlivá rozhodnutí a zbývající rizika'));
    for (const row of [...status.observations.lines, ...status.observations.samples]) {
      observations.append(element('p', `${row.id} · ${row.status === 'open' ? 'Otevřeno' : 'Prohlédnutá aproximace'} · ${row.reason}`));
    }
    for (const risk of status.observations.remaining_risks) observations.append(element('p', risk, 'hint'));
    output.append(observations);
  }
}

setInterval(async () => {
  if (!connected || !selectedRun || geometryRequestPending || !document.querySelector('#geometry-state')) return;
  const runId = selectedRun; geometryRequestPending = true;
  try {
    const status = await request('geometry_status', {run_id: runId});
    if (selectedRun !== runId) return;
    renderGeometry(status);
    if (status.geometry_complete && displayedGeometry !== status.attempt_id) {
      displayedGeometry = status.attempt_id;
      await refreshSelectedRun(runId); renderGeometry(status);
    }
  } catch (error) {
    if (selectedRun === runId) document.querySelector('#geometry-state').textContent = error.message;
  } finally { geometryRequestPending = false; }
}, 1000);
