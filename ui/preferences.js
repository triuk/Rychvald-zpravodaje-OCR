/* Public model preferences; existing runs keep their frozen profile. */
let preferenceIdentity = null;
let preferenceGeneration = 0;
let preferenceCatalog = {state: 'not_checked', models: []};
let preferenceValues = {};
let catalogPending = false;

function preferenceSelection(scope) {
  return {model: document.querySelector(`#${scope}-model`).value,
    reasoning_effort: document.querySelector(`#${scope}-reasoning`).value};
}

function fillPreferenceChoices(scope, preferences) {
  const model = document.querySelector(`#${scope}-model`);
  const reasoning = document.querySelector(`#${scope}-reasoning`);
  model.replaceChildren();
  const available = preferenceCatalog.models.filter(item => item.input_modalities.includes('image'));
  for (const item of available) {
    const option = element('option', item.display_name || item.model);
    option.value = item.model;
    model.append(option);
  }
  if (!available.some(item => item.model === preferences.model)) {
    const option = element('option', `${preferences.model} · ${preferenceCatalog.state === 'completed' ? 'nedostupný' : 'dosud neověřený'}`);
    option.value = preferences.model;
    model.append(option);
  }
  model.value = preferences.model;
  reasoning.replaceChildren();
  const selected = available.find(item => item.model === preferences.model);
  const efforts = selected ? [...selected.reasoning_efforts] : [];
  if (!efforts.includes(preferences.reasoning_effort)) efforts.push(preferences.reasoning_effort);
  for (const value of efforts) {
    const option = element('option', value);
    option.value = value;
    reasoning.append(option);
  }
  reasoning.value = preferences.reasoning_effort;
}

function renderPreferenceValue(scope, data) {
  preferenceValues[scope] = data.preferences;
  fillPreferenceChoices(scope, data.preferences);
  document.querySelector(`#${scope}-model-availability`).textContent = data.availability.message;
  if (scope === 'project') {
    document.querySelector('#effective-run-preferences').textContent =
      `Nový průchod použije ${data.preferences.model} · ${data.preferences.reasoning_effort}. Prompty a ostatní parametry převezme z vybraného externího profilu.`;
  }
}

async function updateModelPreferences(force = false) {
  if (!connected) return;
  const edition = document.querySelector('#edition-choice').value;
  const identity = `${rootInput.value}\n${edition}`;
  if (!force && identity === preferenceIdentity) return;
  preferenceIdentity = identity;
  const generation = ++preferenceGeneration;
  try {
    preferenceCatalog = await request('model_capabilities');
    const global = await request('global_preferences');
    const project = edition ? await request('project_preferences', {edition_id: edition}) : null;
    if (generation !== preferenceGeneration) return;
    renderPreferenceValue('global', global);
    document.querySelector('#project-preferences-form').hidden = !project;
    if (project) renderPreferenceValue('project', project);
    else document.querySelector('#effective-run-preferences').textContent = 'Nejdříve vyberte projekt vydání.';
  } catch (error) {
    if (generation === preferenceGeneration) {
      document.querySelector('#global-model-availability').textContent = error.message;
      document.querySelector('#project-model-availability').textContent = error.message;
    }
  }
}

for (const scope of ['global', 'project']) {
  document.querySelector(`#${scope}-model`).addEventListener('change', () => {
    const selection = preferenceSelection(scope);
    fillPreferenceChoices(scope, selection);
    document.querySelector(`#${scope}-model-availability`).textContent = 'Změna není uložená.';
  });
  document.querySelector(`#${scope}-preferences-form`).addEventListener('submit', event => {
    event.preventDefault();
    perform(async () => {
      const payload = preferenceSelection(scope);
      if (scope === 'project') payload.edition_id = document.querySelector('#edition-choice').value;
      renderPreferenceValue(scope, await request(`set_${scope}_preferences`, payload));
      return scope === 'project' ? 'Předvolby projektu uloženy pro další průchod.' : 'Globální předvolby uloženy pro nové projekty.';
    });
  });
}
document.querySelector('#adopt-global-preferences').addEventListener('click', () => perform(async () => {
  renderPreferenceValue('project', await request('adopt_global_preferences', {edition_id: document.querySelector('#edition-choice').value}));
  return 'Projekt převzal aktuální globální předvolby. Starší průchody mají původní nastavení.';
}));
document.querySelector('#refresh-model-capabilities').addEventListener('click', () => perform(async () => {
  await request('start_model_capabilities');
  catalogPending = true;
  document.querySelector('#refresh-model-capabilities').disabled = true;
  return 'Načítá se nabídka modelů připojeného Codexu.';
}));
setInterval(async () => {
  if (!connected) return;
  updateModelPreferences();
  if (!catalogPending) return;
  try {
    const catalog = await request('model_capabilities');
    if (['starting', 'running'].includes(catalog.state)) return;
    catalogPending = false;
    document.querySelector('#refresh-model-capabilities').disabled = false;
    document.querySelector('#model-capabilities-state').textContent = catalog.state === 'completed' ?
      'Nabídka modelů byla načtena. Skutečnou dostupnost zvolené kombinace ověří běh.' : (catalog.error?.message || 'Nabídka modelů zatím není dostupná.');
    updateModelPreferences(true);
  } catch (error) {
    catalogPending = false;
    document.querySelector('#refresh-model-capabilities').disabled = false;
    document.querySelector('#model-capabilities-state').textContent = error.message;
  }
}, 750);
