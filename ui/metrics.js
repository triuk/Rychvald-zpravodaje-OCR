/* Audit views use the same public operations as process-boundary verification. */
(() => {
  const text = (tag, value, cls) => {
    const node = document.createElement(tag);
    if (value !== undefined) node.textContent = value;
    if (cls) node.className = cls;
    return node;
  };
  const number = value => value === null || value === undefined ? 'Neznámé' : value.toLocaleString('cs-CZ');
  const seconds = value => value === null || value === undefined ? 'Neznámé' : `${value.toLocaleString('cs-CZ', {maximumFractionDigits: 3})} s`;
  const money = value => value === null || value === undefined ? 'Neznámá cena' : `${value.toFixed(6)} USD`;
  const states = {completed: 'Dokončeno', failed: 'Selhalo', interrupted: 'Přerušeno', running: 'Probíhá', cached: 'Místní cache', starting: 'Spouštění'};
  const operations = {vision_diagnostic: 'Obrazové ověření', context_diagnostic: 'Ověření context-mode', visual_reading: 'Úplné vizuální čtení', prepare: 'Místní příprava'};
  const reasons = {
    'Some attempts have unknown usage; run totals are incomplete.': 'Některé pokusy nemají známou spotřebu; součet průchodu je neúplný.',
    'No AI usage observation was reported.': 'Proces neposkytl údaje o spotřebě AI.',
    'Some steps cannot be priced under the exact-model scenario.': 'Některé kroky nelze ocenit podle scénáře pro přesný model.',
    'No verified page count is available.': 'Počet ověřených stran zatím není dostupný.',
    'Local work is not AI usage.': 'Místní zpracování není spotřeba AI.',
    'Attempt did not complete; observed consumption is retained.': 'Pokus nebyl dokončen; naměřená spotřeba zůstává zachována.',
    'Complete input/cache-write/output observations are required for pricing.': 'Pro cenu chybí úplné údaje o vstupu, zápisu cache nebo výstupu.',
    'No exact-model price card; no replacement model was substituted.': 'Pro přesný model není ceník; cena jiného modelu se nepoužije.',
    'Local work has no applicable API token price.': 'Na místní zpracování se cena tokenů API nevztahuje.',
    'Metric source artifacts are incomplete or invalid; known step observations remain available.': 'Podklady měření jsou neúplné nebo neplatné; známé údaje jednotlivých kroků zůstávají dostupné.',
    'Protocol contains an incomplete or invalid row; accounting coverage is incomplete.': 'Protokol obsahuje neúplný nebo neplatný řádek; měření je neúplné.'
  };
  const reason = value => reasons[value] || 'Měření je neúplné; podrobné důvody jsou v podkladech kroku.';
  const date = value => value ? new Date(value).toLocaleString('cs-CZ', {dateStyle: 'short', timeStyle: 'medium'}) : 'Neznámé';
  function swatch(color, label) {
    const node = text('span', undefined, 'metric-legend-item');
    const colorNode = text('i');
    colorNode.style.backgroundColor = color;
    node.append(colorNode, text('span', label));
    return node;
  }
  function tokenView(usage, categories) {
    const group = text('div', undefined, 'metric-tokens');
    for (const category of categories) {
      const value = usage.values?.[category.key];
      const node = swatch(category.color, `${category.label}: ${number(value)}`);
      node.dataset.category = category.key;
      node.dataset.value = value ?? 'unknown';
      group.append(node);
    }
    if (usage.reasons.length) group.append(text('p', [...new Set(usage.reasons.map(reason))].join(' '), 'hint metric-reasons'));
    return group;
  }
  function costColor(cost, scale) {
    if (cost === null) return scale.unknown_color;
    let index = 0;
    scale.thresholds.forEach((threshold, i) => { if (cost >= threshold) index = i; });
    return scale.colors[index];
  }
  window.renderMetricsPanel = (parent, run, request) => {
    if (!run.run) return;
    const panel = text('section', undefined, 'metrics-panel');
    panel.id = 'metrics-panel';
    panel.append(text('h3', 'Časy, tokeny a srovnávací cena'));
    const refresh = text('button', 'Obnovit metriky', 'secondary');
    refresh.id = 'refresh-metrics';
    refresh.type = 'button';
    const body = text('div', 'Načítání měření…');
    body.id = 'metrics-content';
    panel.append(refresh, body);
    parent.append(panel);
    async function load() {
      refresh.disabled = true;
      try {
        const data = await request('run_metrics', {run_id: run.project.run_id});
        while (data.step_next_offset !== null) {
          const page = await request('run_metrics', {run_id: run.project.run_id, offset: data.step_next_offset});
          data.steps.push(...page.steps);
          data.step_next_offset = page.step_next_offset;
        }
        if (!panel.isConnected) return;
        body.replaceChildren();
        body.dataset.sourceHash = data.source_hash;
        body.append(text('p', 'Srovnávací scénář API; nejde o účtování předplatného ChatGPT.', 'metric-notice'),
          text('p', 'Standard API · do 272 000 vstupních tokenů na požadavek · bez regionální přirážky', 'hint'), tokenView(data.tokens, data.categories));
        const total = text('p', `Průchod: ${money(data.cost.usd)} · Na stránku: ${money(data.per_page.usd)} (${number(data.per_page.page_count)} stran)`, 'metric-total');
        total.id = 'metrics-run-cost';
        total.style.borderColor = costColor(data.cost.usd, data.cost_scale);
        body.append(total, text('p', `Pozorovaný běh kroků: ${seconds(data.timing.active_seconds)} · Doložené čekání: ${seconds(data.timing.waiting_seconds)}. Jde o čas aplikace, nikoli měření výpočtu poskytovatele. Vnořené nástroje se nepřičítají podruhé.`, 'hint'));
        body.append(text('p', `Od prvního do posledního doloženého kroku: ${seconds(data.timing.observed_span_seconds)} · Nezařazené mezery: ${seconds(data.timing.unattributed_seconds)}. Mezery se nevydávají za čekání ani za dokončení celého OCR.`, 'hint'));
        if (data.cost.reason) body.append(text('p', reason(data.cost.reason), 'hint'));
        if (data.per_page.reason) body.append(text('p', reason(data.per_page.reason), 'hint'));
        const legend = text('div', undefined, 'metric-legend');
        legend.id = 'metrics-cost-legend';
        legend.append(text('span', 'Společná škála ceny kroku/průchodu: '));
        data.cost_scale.thresholds.forEach((v, i) => legend.append(swatch(data.cost_scale.colors[i], `≥ ${v} USD`)));
        legend.append(swatch(data.cost_scale.unknown_color, 'Neznámá cena'));
        body.append(legend);
        const table = text('table', undefined, 'metric-steps');
        const head = text('tr');
        ['Krok / pokus', 'Stav a čas', 'Tokeny', 'Srovnávací cena', 'Podklady'].forEach(v => head.append(text('th', v)));
        const thead = text('thead'); thead.append(head); table.append(thead);
        const tbody = text('tbody');
        for (const step of data.steps) {
          const row = text('tr');
          row.dataset.stepId = step.step_id;
          row.dataset.attemptId = step.attempt_id;
          const label = text('td');
          const id = text('small', step.attempt_id.slice(0, 12) + '…');
          id.title = step.attempt_id;
          label.append(text('strong', step.native_step_id || operations[step.operation] || step.operation), id);
          if (step.duplicate_of) label.append(text('small', 'Shodné původní měření; v součtu je započteno jen jednou.'));
          const time = text('td');
          const dates = text('small', `${date(step.started_at)} → ${date(step.ended_at)}`);
          dates.title = `${step.started_at || ''} → ${step.ended_at || ''}`;
          time.append(text('strong', states[step.state] || step.state), dates,
            text('small', `Celkem ${seconds(step.timing.wall_seconds)} · běh práce ${seconds(step.timing.active_seconds)} · čekání ${seconds(step.timing.waiting_seconds)}`));
          if (step.kind === 'ai') time.append(text('small', `Příprava a spuštění: ${seconds(step.timing.startup_seconds)} · Běh AI tahu: ${seconds(step.timing.turn_wall_seconds)}`));
          if (step.timing.tool_seconds !== null) time.append(text('small', `Nástroje uvnitř aktivní práce: ${seconds(step.timing.tool_seconds)}`));
          const usage = text('td'); usage.append(tokenView(step.tokens, data.categories));
          const cost = text('td', money(step.cost.usd), 'metric-cost');
          cost.dataset.usd = step.cost.usd ?? 'unknown';
          cost.style.borderLeftColor = costColor(step.cost.usd, data.cost_scale);
          const detail = text('td');
          const button = text('button', 'Detail kroku', 'secondary');
          button.type = 'button';
          button.addEventListener('click', async () => {
            button.disabled = true;
            try {
              const dialog = text('details'); dialog.open = true;
              dialog.className = 'metric-step-detail';
              dialog.append(text('summary', 'Původní události, zadání, odpověď a ceník'));
              async function page(offset) {
                const value = await request('step_detail', {run_id: run.project.run_id, step_id: step.step_id, offset});
                dialog.append(text('pre', JSON.stringify(value, null, 2)));
                const nextOffset = value.usage_next_offset ?? value.event_next_offset;
                if (nextOffset !== null) {
                  const more = text('button', 'Další původní události', 'secondary');
                  more.type = 'button';
                  more.addEventListener('click', async () => { more.disabled = true; await page(nextOffset); more.remove(); });
                  dialog.append(more);
                }
              }
              await page(0);
              detail.querySelector('details')?.remove();
              detail.append(dialog);
            } catch (error) { detail.append(text('p', error.message)); }
            finally { button.disabled = false; }
          });
          detail.append(button); row.append(label, time, usage, cost, detail); tbody.append(row);
        }
        table.append(tbody); body.append(table);
        const provenance = text('details');
        provenance.append(text('summary', 'Původ měření a předpoklady ceny'), text('pre', JSON.stringify({
          policy: data.policy, source_hash: data.source_hash, sources: data.sources,
          price_card_sha256: data.price_card_sha256, price_card: data.price_card,
          assumptions: data.assumptions, warnings: data.warnings, artifacts: data.artifacts
        }, null, 2)));
        body.append(provenance);
      } catch (error) { body.replaceChildren(text('p', error.message)); }
      finally { refresh.disabled = false; }
    }
    refresh.addEventListener('click', load);
    load();
  };
})();
