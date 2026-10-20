/* Saved-data comparison never changes the selected worker or starts a job. */
const originLabels = {computed: 'Nově spočítáno', same_run_cache: 'Vlastní místní cache', imported_local: 'Převzaté místní podklady'};

function updateComparisonChoices() {
  const left = document.querySelector('#comparison-left');
  const right = document.querySelector('#comparison-right');
  const previous = [left.value, right.value];
  left.replaceChildren();
  for (const edition of editionCatalog) {
    const group = element('optgroup'); group.label = edition.name;
    for (const run of edition.runs.filter(r => r.run_name)) {
      const option = element('option', run.run_name); option.value = run.run_id;
      option.dataset.editionId = edition.edition_id; group.append(option);
    }
    left.append(group);
  }
  if ([...left.options].some(o => o.value === previous[0])) left.value = previous[0];
  updateComparisonRight(previous[1]);
  const donor = document.querySelector('#autonomous-donor');
  const old = donor.value;
  const none = element('option', 'Nová místní příprava'); none.value = ''; donor.replaceChildren(none);
  for (const run of editionCatalog.find(e => e.edition_id === document.querySelector('#edition-choice').value)?.runs || []) {
    if (!run.run_name) continue;
    const option = element('option', run.run_name); option.value = run.run_id; donor.append(option);
  }
  if ([...donor.options].some(o => o.value === old)) donor.value = old;
}

function updateComparisonRight(previous) {
  const left = document.querySelector('#comparison-left');
  const right = document.querySelector('#comparison-right');
  const editionId = left.selectedOptions[0]?.dataset.editionId;
  right.replaceChildren();
  for (const run of editionCatalog.find(e => e.edition_id === editionId)?.runs || []) {
    if (!run.run_name || run.run_id === left.value) continue;
    const option = element('option', run.run_name); option.value = run.run_id; right.append(option);
  }
  if ([...right.options].some(o => o.value === previous)) right.value = previous;
}
document.querySelector('#comparison-left').addEventListener('change', () => updateComparisonRight());
document.querySelector('#edition-choice').addEventListener('change', updateComparisonChoices);

function comparisonJson(parent, title, value) {
  const detail = element('details');
  detail.append(element('summary', title), element('pre', typeof value === 'string' ? value : JSON.stringify(value, null, 2)));
  parent.append(detail);
}
const comparisonMoney = value => value == null ? 'Neznámá cena' : `${value.toFixed(6)} USD`;
const comparisonSeconds = value => value == null ? 'Neznámé' : `${value.toFixed(3)} s`;
function comparisonColor(usd, scale) {
  if (usd == null) return scale.unknown_color;
  let color = scale.colors[0];
  scale.thresholds.forEach((v, i) => { if (usd >= v) color = scale.colors[i]; });
  return color;
}

document.querySelector('#comparison-form').addEventListener('submit', event => {
  event.preventDefault();
  perform(async () => {
    const payload = {left_run_id: document.querySelector('#comparison-left').value,
      right_run_id: document.querySelector('#comparison-right').value};
    const data = await request('compare_runs', payload);
    let offset = Math.min(...data.runs.map(r => r.metrics.step_next_offset).filter(v => v !== null));
    while (Number.isFinite(offset)) {
      const page = await request('compare_runs', {...payload, offset});
      page.runs.forEach((r, i) => data.runs[i].metrics.steps.push(...r.metrics.steps));
      offset = Math.min(...page.runs.map(r => r.metrics.step_next_offset).filter(v => v !== null));
    }
    let historyOffset = Math.min(...data.runs.map(r => r.history_next_offset).filter(v => v !== null));
    while (Number.isFinite(historyOffset)) {
      const page = await request('compare_runs', {...payload, history_offset: historyOffset});
      page.runs.forEach((r, i) => data.runs[i].history.push(...r.history));
      historyOffset = Math.min(...page.runs.map(r => r.history_next_offset).filter(v => v !== null));
    }
    renderComparison(data);
    return 'Porovnání načteno z uložených podkladů obou průchodů.';
  });
});

function renderComparison(data) {
  const target = document.querySelector('#comparison-results'); target.replaceChildren();
  target.dataset.editionId = data.edition_id;
  target.append(element('p', 'Srovnávací scénář API; nejde o účtování předplatného ChatGPT. Převzatá místní příprava není cache vstupních tokenů AI.', 'metric-notice'));
  if (!data.price_cards_equal) target.append(element('p', 'Průchody mají různé zmrazené ceníky. Částky se vztahují ke scénáři uvedenému v každém sloupci.', 'error'));
  if (data.shared_ai_threads.length) target.append(element('p', 'Pozor: průchody obsahují shodná AI vlákna; nezávislost není doložena.', 'error'));
  const legend = element('div', undefined, 'metric-legend'); legend.id = 'comparison-legend';
  legend.append(element('span', 'Společná cenová škála: '));
  data.cost_scale.thresholds.forEach((value, i) => {
    const item = element('span', `≥ ${value} USD`, 'metric-legend-item');
    item.style.borderBottom = `5px solid ${data.cost_scale.colors[i]}`; legend.append(item);
  });
  const unknown = element('span', 'Neznámá cena', 'metric-legend-item');
  unknown.style.borderBottom = `5px solid ${data.cost_scale.unknown_color}`; legend.append(unknown); target.append(legend);
  const columns = element('div', undefined, 'comparison-columns');
  for (const run of data.runs) {
    const column = element('section', undefined, 'comparison-run'); column.dataset.runId = run.project.run_id;
    const metrics = run.metrics;
    column.append(element('h3', run.run.name), element('p', run.project.run_id, 'run-id'),
      element('p', `Fáze: ${labels[run.project.phase] || run.project.phase} · Validace: ${labels[run.project.validation] || run.project.validation} · Přijetí: ${labels[run.project.acceptance] || run.project.acceptance}`));
    column.append(element('p', `Profil SHA256: ${run.profile.sha256}`, 'run-id'));
    comparisonJson(column, 'Přesné použité nastavení a prompty', run.profile.text);
    const origins = element('ul');
    for (const [key, count] of Object.entries(run.local_origins)) origins.append(element('li', `${originLabels[key] || key}: ${count}`));
    column.append(origins);
    const cost = element('p', `Průchod: ${comparisonMoney(metrics.cost.usd)} · Na stranu: ${comparisonMoney(metrics.per_page.usd)}`, 'metric-total');
    cost.style.borderColor = comparisonColor(metrics.cost.usd, data.cost_scale); column.append(cost);
    column.append(element('p', `Pozorovaný běh: ${comparisonSeconds(metrics.timing.active_seconds)} · Doložené čekání: ${comparisonSeconds(metrics.timing.waiting_seconds)} · Nezařazené mezery: ${comparisonSeconds(metrics.timing.unattributed_seconds)}`, 'hint'));
    for (const category of data.categories) {
      const token = element('p', `${category.label}: ${metrics.tokens.values?.[category.key]?.toLocaleString('cs-CZ') ?? 'Neznámé'}`);
      token.style.borderLeft = `5px solid ${category.color}`; token.style.paddingLeft = '8px'; column.append(token);
    }
    const steps = element('table', undefined, 'metric-steps');
    const head = element('tr'); ['Krok', 'Původ / stav', 'Čas', 'Cena / podklady'].forEach(v => head.append(element('th', v))); steps.append(head);
    for (const step of metrics.steps) {
      const row = element('tr'); row.dataset.stepId = step.step_id;
      row.append(element('td', step.native_step_id || step.operation),
        element('td', step.kind === 'local' ? originLabels[step.origin] || step.origin : step.state),
        element('td', comparisonSeconds(step.timing.wall_seconds)));
      const details = element('td'); details.style.borderLeft = `5px solid ${comparisonColor(step.cost.usd, data.cost_scale)}`;
      details.append(element('p', comparisonMoney(step.cost.usd)));
      const button = element('button', 'Detail kroku', 'secondary'); button.type = 'button';
      button.addEventListener('click', () => perform(async () => {
        const pages = []; let offset = 0;
        do {
          const value = await request('step_detail', {run_id: run.project.run_id, step_id: step.step_id, offset});
          pages.push(value); offset = value.usage_next_offset ?? value.event_next_offset;
        } while (offset !== null);
        comparisonJson(details, 'Původní zadání, odpověď, události a měření', pages);
        return 'Podklady kroku načteny.';
      })); details.append(button); row.append(details); steps.append(row);
    }
    column.append(steps);
    const findings = run.output.reports?.findings?.items || [];
    column.append(element('h4', 'Výsledky kontrol a otevřené nálezy'));
    if (!run.output.available) column.append(element('p', 'Výstupy dosud nevytvořeny.'));
    for (const finding of findings) column.append(element('p', `${finding.id} · ${finding.status} · ${finding.reason || ''}`));
    comparisonJson(column, 'Úplné výsledky kontrol', run.output);
    comparisonJson(column, `Úplná historie (${run.history_total} událostí)`, run.history);
    comparisonJson(column, 'Samostatný AI kontext a pozorovaná vlákna', run.ai_context);
    comparisonJson(column, 'Původ metrik, ceník a předpoklady', {price_card: metrics.price_card,
      price_card_sha256: metrics.price_card_sha256, assumptions: metrics.assumptions, warnings: metrics.warnings,
      tokens: metrics.tokens, sources: metrics.sources});
    columns.append(column);
  }
  target.append(columns);
}
