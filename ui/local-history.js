/* Phase-local observations use the existing public metric/detail operations. */
(() => {
  let timer;
  const states = {running: 'Probíhá', completed: 'Dokončeno', cached: 'Ověřená místní cache',
    failed: 'Selhalo', interrupted: 'Přerušeno; výsledek nepotvrzen', paused: 'Pozastaveno'};
  const node = (tag, value, cls) => {
    const result = document.createElement(tag);
    if (value !== undefined) result.textContent = value;
    if (cls) result.className = cls;
    return result;
  };
  const time = value => value ? new Date(value).toLocaleString('cs-CZ') : 'Nezaznamenáno';
  const duration = value => value === null || value === undefined ? 'Doba zatím neznámá' :
    `${value.toLocaleString('cs-CZ', {maximumFractionDigits: 3})} s`;

  window.renderLocalHistory = (phases, run, request) => {
    clearInterval(timer);
    if (!run.run) return;
    const views = new Map();
    let pending = false;
    for (const phase of ['preparation', 'reading', 'geometry', 'assembly']) {
      const panel = phases[phase];
      const section = node('section', undefined, 'local-history');
      section.dataset.localPhase = phase;
      const activity = node('p', 'Místní práce: načítání uloženého stavu…', 'local-activity');
      const details = node('details');
      details.append(node('summary', 'Místní kroky a historie'));
      const hint = node('p', 'Jde o místní nástroje. Podřízené kroky jsou součástí času rodiče; jejich časy se nesčítají.', 'hint');
      const list = node('div');
      const more = node('button', 'Další starší kroky', 'secondary');
      more.type = 'button';
      more.hidden = true;
      details.append(hint, list, more);
      section.append(activity, details);
      panel.append(section);
      const view = {panel, section, activity, details, list, more, phase, offset: 0, hash: null, next: null};
      views.set(phase, view);
      details.addEventListener('toggle', () => { if (details.open) load(view); });
      more.addEventListener('click', () => { view.offset = view.next; load(view, true); });
    }

    async function load(view, append = false) {
      if (pending || !view.section.isConnected || !connected || selectedRun !== run.project.run_id) return;
      pending = true;
      try {
        const data = await request('run_metrics', {run_id: run.project.run_id, kind: 'local',
          phase: view.phase, newest_first: true, offset: append ? view.offset : 0, limit: 25});
        if (!view.section.isConnected || selectedRun !== run.project.run_id) return;
        const active = data.steps.filter(step => step.state === 'running');
        view.activity.textContent = active.length ? `Místní práce: ${active.map(step => step.tool?.name || step.operation).join(' · ')}` :
          `Místní práce: právě neběží · ${data.step_total} zaznamenaných kroků v této fázi.`;
        if (!append && view.hash === data.source_hash) return;
        view.hash = data.source_hash;
        if (!append) { view.list.replaceChildren(); view.offset = 0; }
        for (const step of data.steps) {
          const item = node('details', undefined, 'local-step');
          item.dataset.stepId = step.step_id;
          const title = `${step.tool?.name || step.operation} · ${states[step.state] || step.state} · ${duration(step.timing.wall_seconds)}`;
          item.append(node('summary', title));
          const text = node('p', `${time(step.started_at)} → ${time(step.ended_at)} · ${step.operation} · Pokus ${step.attempt_id}`);
          const origin = step.origin === 'imported_local' ? 'Převzaté místní podklady jiného průchodu' :
            step.state === 'cached' ? 'Vlastní ověřená místní cache; OCR se znovu nepočítalo' : 'Nově provedená místní práce';
          const version = step.tool?.version || 'Verze nebyla zaznamenána';
          const metadata = node('p', `${origin} · ${version}${step.parent_step_id ? ' · Vnořený krok' : ''}`);
          const command = node('pre', step.command?.length ? JSON.stringify(step.command, null, 2) : 'Samostatný příkaz nebyl použit nebo ve starších datech chybí.');
          const full = node('pre', 'Načítání úplných dokladů…');
          full.hidden = true;
          item.append(text, metadata, command);
          if (step.error) item.append(node('p', `${step.error.message} (${step.error.code})`, 'error'));
          item.append(full);
          item.addEventListener('toggle', async () => {
            if (!item.open || full.dataset.loaded) return;
            full.hidden = false;
            try {
              const detail = await request('step_detail', {run_id: run.project.run_id, step_id: step.step_id});
              if (!item.isConnected) return;
              full.textContent = JSON.stringify({tool: detail.tool, parameters: detail.parameters,
                observations: detail.observations,
                inputs: detail.inputs, outputs: detail.outputs, parent_step_id: detail.parent_step_id,
                origin: detail.origin, import_provenance: detail.import_provenance,
                error: detail.error, artifacts: detail.artifacts}, null, 2);
              full.dataset.loaded = 'true';
            } catch (error) { full.textContent = error.message; }
          });
          view.list.append(item);
        }
        if (!data.step_total) view.list.append(node('p', 'Pro tuto fázi zatím nejsou uložené místní kroky.', 'hint'));
        view.next = data.step_next_offset;
        view.more.hidden = view.next === null;
        if (data.local_warnings?.length) view.activity.textContent += ' Část starších dokladů není čitelná; podrobnosti jsou v celkové historii.';
      } catch (error) {
        view.activity.textContent = `Místní historii nelze načíst: ${error.message}`;
      } finally { pending = false; }
    }
    function refreshVisible() {
      const view = [...views.values()].find(item => !item.panel.hidden);
      if (view) load(view);
    }
    timer = setInterval(refreshVisible, 2000);
    setTimeout(refreshVisible, 0);
  };
})();
