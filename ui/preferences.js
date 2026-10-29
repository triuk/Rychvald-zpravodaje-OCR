/* Public model preferences; existing runs keep their frozen profile. */
let preferenceIdentity = null;
let preferenceGeneration = 0;
let preferenceCatalog = {state: 'not_checked', models: []};
let preferenceValues = {};
let catalogPending = false;
const preferenceActivities = [['reading', 'Čtení a ověření prostředí'], ['geometry', 'Pořadí a geometrie'],
  ['final_check', 'Kontroly výsledku'], ['repair', 'Cílené opravy']];

function preferenceSelection(scope) {
  const result = {model: document.querySelector(`#${scope}-model`).value,
    reasoning_effort: document.querySelector(`#${scope}-reasoning`).value};
  if (scope === 'global' || scope === 'project') {
    result.overrides = {};
    for (const [activity] of preferenceActivities) {
      if (document.querySelector(`#${scope}-${activity}-enabled`).checked) {
        result.overrides[activity] = preferenceSelection(`${scope}-${activity}`);
      }
    }
  }
  return result;
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
  const effective = document.querySelector(`#${scope}-effective-settings`);
  effective.replaceChildren();
  for (const [activity, title] of preferenceActivities) {
    const override = data.preferences.overrides?.[activity];
    const checkbox = document.querySelector(`#${scope}-${activity}-enabled`);
    checkbox.checked = Boolean(override);
    const pair = data.effective[activity];
    fillPreferenceChoices(`${scope}-${activity}`, pair);
    for (const key of ['model', 'reasoning']) document.querySelector(`#${scope}-${activity}-${key}`).disabled = !override;
    document.querySelector(`#${scope}-${activity}-availability`).textContent = data.activity_availability[activity].message;
    effective.append(element('li', `${title}: ${pair.model} · ${pair.reasoning_effort} (${override ? 'výjimka' : 'společné'})`));
  }
  document.querySelector(`#${scope}-model-availability`).textContent = data.availability.message;
  if (scope === 'project') {
    document.querySelector('#effective-run-preferences').textContent =
      'Nový průchod použije uložená nastavení činností uvedená výše. Prompty a ostatní parametry převezme z vybraného externího profilu.';
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
  const fields = document.querySelector(`#${scope}-activity-fields`);
  for (const [activity, title] of preferenceActivities) {
    const field = element('fieldset');
    field.append(element('legend', title));
    const toggleLabel = element('label');
    const toggle = element('input');
    toggle.type = 'checkbox';
    toggle.id = `${scope}-${activity}-enabled`;
    toggleLabel.append(toggle, document.createTextNode(' Použít vlastní model a reasoning'));
    field.append(toggleLabel);
    for (const [key, label] of [['model', 'Model AI'], ['reasoning', 'Reasoning']]) {
      const id = `${scope}-${activity}-${key}`;
      const caption = element('label', label);
      caption.htmlFor = id;
      const select = element('select');
      select.id = id;
      select.disabled = true;
      select.addEventListener('change', () => {
        if (key === 'model') fillPreferenceChoices(`${scope}-${activity}`, preferenceSelection(`${scope}-${activity}`));
        document.querySelector(`#${scope}-${activity}-availability`).textContent = 'Výjimka není uložená.';
      });
      field.append(caption, select);
    }
    const availability = element('p', '', 'hint');
    availability.id = `${scope}-${activity}-availability`;
    field.append(availability);
    toggle.addEventListener('change', () => {
      for (const key of ['model', 'reasoning']) document.querySelector(`#${scope}-${activity}-${key}`).disabled = !toggle.checked;
      availability.textContent = toggle.checked ? 'Výjimka není uložená.' : 'Po uložení se použije společná dvojice.';
    });
    fields.append(field);
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
