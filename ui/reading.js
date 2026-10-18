/* Source-first visual reading. Published text is a read-only view of model evidence. */
let readingRequestPending = false;
let displayedReading = null;
const readingReadiness = new Map();

function renderReadingPanel(detail, data) {
  const panel = element('section', undefined, 'codex-panel');
  panel.id = 'reading-panel';
  panel.append(element('h3', 'Úplné první vizuální čtení'), element('p',
    'AI nejprve přečte všechny původní stránky bez OCR kandidátů. Potom vypořádá kandidáty a předá celý přepis k místní validaci. Vyžaduje platné obrazové ověření a context-mode tohoto průchodu.', 'hint'));
  const start = element('button', 'Spustit vizuální čtení');
  start.id = 'start-reading';
  start.dataset.runId = data.project.run_id;
  start.disabled = true;
  start.addEventListener('click', () => perform(async () => {
    const status = await request('start_reading', {run_id: data.project.run_id});
    if (selectedRun === data.project.run_id) renderReading(status);
    return 'Úplné vizuální čtení bylo zahájeno.';
  }));
  const state = element('p', 'Zjišťování stavu…');
  state.id = 'reading-state';
  state.setAttribute('aria-live', 'polite');
  const counts = element('p', '', 'hint');
  counts.id = 'reading-counts';
  const explanation = element('p', '', 'hint');
  explanation.id = 'reading-publication';
  const output = element('div');
  output.id = 'reading-output';
  const evidence = element('details');
  evidence.append(element('summary', 'Použitý profil, zadání, odpovědi a zdrojové doklady'));
  const raw = element('pre');
  raw.id = 'reading-evidence';
  evidence.append(raw);
  panel.append(start, state, counts, explanation, output, evidence);
  detail.append(panel);
}

function updateReadingAvailability(context) {
  if (context.run_id !== selectedRun) return;
  readingReadiness.set(context.run_id, Boolean(context.autonomous_ocr_ready));
  const start = document.querySelector('#start-reading');
  if (start) start.disabled = !readingReadiness.get(selectedRun) || codexRunning() ||
    ['starting', 'running'].includes(document.querySelector('#preparation-state')?.dataset.state) || !document.querySelector('#run-profile');
}

function renderReading(status) {
  const state = document.querySelector('#reading-state');
  if (!state || status.run_id !== selectedRun) return;
  state.dataset.state = status.state;
  state.dataset.attemptId = status.attempt_id || '';
  const names = {not_started: 'Čtení dosud nezačalo', starting: 'Spouští se čtení', running: 'Probíhá skutečné AI čtení',
    completed: 'První úplné čtení dokončeno', failed: 'Čtení selhalo', interrupted: 'Čtení přerušeno', invalidated: 'Doklad čtení zneplatněn'};
  const stages = {source: 'Původní obrazy bez OCR kandidátů', accounting: 'Vypořádání kandidátů a validace celého přepisu'};
  const last = status.turns?.at(-1);
  state.textContent = names[status.state] || status.state;
  if (last) state.textContent += ` · ${stages[last.stage] || last.stage}`;
  if (status.error) state.textContent += ` · ${status.error.message} (${status.error.code})`;
  const counts = status.counts || {};
  document.querySelector('#reading-counts').textContent = `Skutečně přečtené stránky: ${counts.pages_read || 0} · řádky: ${counts.lines_read || 0} · logické jednotky: ${counts.units_read || 0}`;
  document.querySelector('#reading-publication').textContent = status.reading_complete ?
    'Celý zdrojově doložený přepis byl atomicky zveřejněn. Geometrie, export PDF/TXT, závěrečné kontroly a přijetí zadavatelem mají vlastní stav.' :
    'Mezivýsledek je rozpracovaný. Dokončení tahu ani místní OCR samy nepotvrzují a nezveřejňují úplný přepis.';
  const output = document.querySelector('#reading-output');
  output.replaceChildren();
  if (status.reading_complete && status.answer) {
    try {
      const review = JSON.parse(status.answer).review;
      const lines = new Map(review.lines.map(line => [line.id, line]));
      output.append(element('h4', 'Zveřejněný přepis v pořadí čtení'));
      for (const unit of review.units) {
        const text = unit.line_ids.map(id => lines.get(id)?.text || '').join(' ');
        const row = element(unit.tag === 'P' ? 'p' : 'h4', text);
        row.title = `Strana ${unit.page} · ${unit.article} · ${unit.id}`;
        output.append(row);
      }
      output.append(element('p', `Nevyřešená místa: ${review.unresolved.length} · chyby vydavatele: ${review.publisher_errors.length}`, 'hint'));
      if (review.unresolved.length || review.publisher_errors.length) {
        const registers = element('details');
        registers.append(element('summary', 'Nejistoty a čitelné chyby předlohy'),
          element('pre', JSON.stringify({unresolved: review.unresolved, publisher_errors: review.publisher_errors}, null, 2)));
        output.append(registers);
      }
    } catch (error) {
      output.append(element('p', 'Uložená strukturovaná odpověď není dostupná: ' + error.message));
    }
  }
  document.querySelector('#reading-evidence').textContent = JSON.stringify({
    attempt_id: status.attempt_id, thread_id: status.thread_id, requested: status.requested, effective: status.effective,
    profile_sha256: status.profile_sha256, runtime: status.runtime, preflight: status.preflight,
    source: status.source, turns: status.turns, coverage: status.coverage, dynamic_tools: status.dynamic_tools,
    reading_complete: Boolean(status.reading_complete), review_sha256: status.review_sha256,
    usage_events: status.usage_events, artifacts: status.artifacts,
  }, null, 2);
  const start = document.querySelector('#start-reading');
  start.disabled = !readingReadiness.get(selectedRun) || codexRunning() ||
    ['starting', 'running'].includes(document.querySelector('#preparation-state')?.dataset.state) || !document.querySelector('#run-profile');
}

setInterval(async () => {
  if (!connected || !selectedRun || readingRequestPending || !document.querySelector('#reading-state')) return;
  const runId = selectedRun;
  readingRequestPending = true;
  try {
    const status = await request('reading_status', {run_id: runId});
    if (selectedRun !== runId) return;
    renderReading(status);
    if (status.reading_complete && status.attempt_id !== displayedReading) {
      displayedReading = status.attempt_id;
      await refreshSelectedRun(runId);
      renderReading(status);
    }
  } catch (error) {
    const state = document.querySelector('#reading-state');
    if (state && selectedRun === runId) state.textContent = error.message;
  } finally {
    readingRequestPending = false;
  }
}, 750);
