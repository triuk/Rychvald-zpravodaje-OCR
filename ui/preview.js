'use strict';

// One viewer for every automatic phase. View state belongs to the run, not to
// a phase panel, so comparing phases keeps the same page and magnification.
window.phasePreview = (() => {
  const views = new Map();
  let mounted = null;
  let generation = 0;
  function node(tag, text, cls) {
    const item = document.createElement(tag);
    if (text !== undefined) item.textContent = text;
    if (cls) item.className = cls;
    return item;
  }
  function button(text, action) {
    const item = node('button', text, 'secondary');
    item.type = 'button'; item.addEventListener('click', action); return item;
  }
  function mount(detail, run) {
    generation++;
    const runId = run.project.run_id;
    const view = views.get(runId) || {page: 1, zoom: 100, detailWidth: 38};
    views.set(runId, view);
    const workspace = node('div', undefined, 'phase-workspace');
    workspace.style.setProperty('--phase-detail-width', `${view.detailWidth}%`);
    const descriptions = node('div', undefined, 'phase-details');
    detail.querySelectorAll('.phase-panel').forEach(panel => descriptions.append(panel));
    const separator = node('div', undefined, 'phase-splitter');
    separator.tabIndex = 0; separator.setAttribute('role', 'separator');
    separator.setAttribute('aria-orientation', 'vertical');
    separator.setAttribute('aria-label', 'Šířka detailu fáze');
    function setWidth(value) {
      view.detailWidth = Math.max(20, Math.min(65, value));
      workspace.style.setProperty('--phase-detail-width', `${view.detailWidth}%`);
      separator.setAttribute('aria-valuenow', Math.round(view.detailWidth));
    }
    separator.setAttribute('aria-valuemin', '20'); separator.setAttribute('aria-valuemax', '65');
    setWidth(view.detailWidth);
    separator.addEventListener('pointerdown', event => {
      separator.setPointerCapture(event.pointerId);
      const move = moved => {
        const bounds = workspace.getBoundingClientRect();
        setWidth((moved.clientX - bounds.left) / bounds.width * 100);
      };
      const done = () => {separator.removeEventListener('pointermove', move); separator.removeEventListener('pointerup', done);};
      separator.addEventListener('pointermove', move); separator.addEventListener('pointerup', done);
    });
    separator.addEventListener('keydown', event => {
      if (['ArrowLeft', 'ArrowRight'].includes(event.key)) {
        event.preventDefault(); setWidth(view.detailWidth + (event.key === 'ArrowLeft' ? -3 : 3));
      }
    });
    const viewer = node('section', undefined, 'phase-preview');
    viewer.setAttribute('aria-label', 'Náhled stránky vybrané fáze');
    const controls = node('div', undefined, 'preview-controls');
    const pageInput = node('input'); pageInput.type = 'number'; pageInput.min = '1'; pageInput.value = view.page;
    pageInput.setAttribute('aria-label', 'Strana náhledu');
    const pageCount = node('span', '/ ?', 'preview-page-count');
    const zoom = node('select'); zoom.setAttribute('aria-label', 'Přiblížení náhledu');
    for (const value of [50, 75, 100, 125, 150, 200, 300]) {
      const option = node('option', `${value} %`); option.value = value; zoom.append(option);
    }
    zoom.value = view.zoom;
    const enlarged = button('Zvětšit náhled', () => {
      const active = viewer.classList.toggle('preview-enlarged');
      enlarged.textContent = active ? 'Vrátit do pracovní plochy' : 'Zvětšit náhled';
      enlarged.setAttribute('aria-pressed', String(active));
    });
    enlarged.setAttribute('aria-pressed', 'false');
    controls.append(node('span', 'Strana'), pageInput, pageCount, zoom,
      button('Obnovit', () => refresh()), enlarged);
    const state = node('p', 'Načítání náhledu…', 'preview-state'); state.setAttribute('role', 'status');
    const viewport = node('div', undefined, 'preview-viewport');
    const surface = node('div', undefined, 'preview-surface');
    viewport.append(surface); viewer.append(controls, state, viewport);
    pageInput.addEventListener('change', () => {
      if (Number.isInteger(Number(pageInput.value)) && Number(pageInput.value) >= 1) {
        view.page = Number(pageInput.value); refresh();
      }
    });
    zoom.addEventListener('change', () => {view.zoom = Number(zoom.value); surface.style.width = `${view.zoom}%`;});
    surface.style.width = `${view.zoom}%`;
    viewer.addEventListener('keydown', event => {
      if (event.key === 'Escape') {viewer.classList.remove('preview-enlarged'); enlarged.textContent = 'Zvětšit náhled'; enlarged.setAttribute('aria-pressed', 'false');}
    });
    workspace.append(descriptions, separator, viewer);
    detail.querySelector('.phase-tabs').after(workspace);
    mounted = {runId, editionId: run.edition_id, view, workspace, viewer, state, surface, pageInput, pageCount};
  }
  async function refresh(phase = selectedPhase) {
    if (!mounted) return;
    const current = mounted;
    current.workspace.classList.toggle('phase-placeholder', ['manual', 'outputs'].includes(phase));
    if (['manual', 'outputs'].includes(phase)) {generation++; return;}
    const token = ++generation;
    const page = current.view.page;
    current.state.textContent = 'Načítání náhledu…';
    current.surface.replaceChildren();
    try {
      // Rendering uses an independent public query, leaving the control queue
      // available for pause, stop and background progress while pixels load.
      const result = JSON.parse(await window.requestB(JSON.stringify({operation: 'phase_preview', payload: {
        run_id: current.runId, edition_id: current.editionId, phase, page}})));
      if (token !== generation || mounted !== current) return;
      if (!result.ok) throw new Error(result.error.message);
      const data = result.data;
      if (data.identity.run_id !== current.runId || data.identity.phase !== phase || data.identity.page !== page) return;
      current.state.textContent = data.message;
      current.state.dataset.state = data.state;
      current.viewer.dataset.artifactId = data.identity.artifact_sha256 || '';
      current.pageCount.textContent = `/ ${data.page_count}`;
      current.pageInput.max = data.page_count;
      if (!data.image) return;
      const image = node('img'); image.src = data.image.data_url;
      image.alt = `Strana ${page} · ${phase === 'preparation' ? 'zdrojový sken' : 'podklad fáze'}`;
      image.width = data.image.width; image.height = data.image.height;
      current.surface.append(image);
      for (const region of data.overlays) {
        const [x0, y0, x1, y1] = region.normalized_bbox;
        const box = node('span', `${region.order != null ? `${region.order}. ` : ''}${region.text}`, `preview-overlay ${region.kind}`);
        box.style.left = `${x0 * 100}%`; box.style.top = `${y0 * 100}%`;
        box.style.width = `${(x1 - x0) * 100}%`; box.style.height = `${(y1 - y0) * 100}%`;
        box.title = region.text; current.surface.append(box);
      }
    } catch (error) {
      if (token === generation && mounted === current) {current.state.textContent = `Náhled není dostupný: ${error.message}`; current.state.dataset.state = 'error';}
    }
  }
  return {mount, refresh};
})();
