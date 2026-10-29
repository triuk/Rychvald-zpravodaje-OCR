'use strict';

// Delegation also covers path fields created when a different run is selected.
document.addEventListener('click', event => {
  const button = event.target.closest('[data-pick-path][data-path-target]');
  if (!button) return;
  event.preventDefault();
  const input = document.getElementById(button.dataset.pathTarget);
  if (!input) return;
  const previous = input.value;
  button.disabled = true;
  perform(async () => {
    try {
      // Dialogs have their own callback and never occupy the serialized queue
      // used by status polling, selections and workflow operations.
      if (!connected) throw new Error('Aplikace ještě není připojena.');
      const response = JSON.parse(await window.requestB(JSON.stringify({operation: 'choose_path',
        payload: {kind: button.dataset.pickPath, current_path: previous}})));
      if (!response.ok) throw new Error(`${response.error.message} (${response.error.code})`);
      if (response.data.cancelled) return 'Výběr zrušen; dosavadní cesta zůstává.';
      // A run can change or a manually entered value can change while the
      // native dialog is open. Do not overwrite that newer field state.
      if (!input.isConnected || input.value !== previous) return 'Cesta se mezitím změnila; výběr nebyl použit.';
      input.value = response.data.path;
      input.dispatchEvent(new Event('input', {bubbles: true}));
      return 'Cesta vybrána.';
    } finally {
      button.disabled = false;
    }
  });
});
