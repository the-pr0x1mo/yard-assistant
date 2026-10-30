/* Reviews live only in this page's memory. No browser storage or autosave. */
(() => {
  let active = null;
  let fieldId = 0;
  const specPromise = fetch('/api/inspection-fields').then(r => r.json());
  const el = (tag, text, parent) => {
    const node = document.createElement(tag);
    if (text !== undefined && text !== null) node.textContent = text;
    if (parent) parent.append(node);
    return node;
  };
  window.canReplaceReview = () => !active?.unsaved || window.confirm('Nepotvrđeni podaci će biti izgubljeni. Odbaciti karticu?');
  window.addEventListener('beforeunload', event => {
    if (active?.unsaved) { event.preventDefault(); event.returnValue = ''; }
  });
  window.addEventListener('pagehide', () => {
    // Prevent a back/forward cache restore from resurrecting a discarded draft.
    if (active?.unsaved) { active.root.replaceChildren(); active = null; }
  });
  window.showReviewCard = async (data, root = document.getElementById('review-card')) => {
    const spec = await specPromise;
    const persisted = data.inspection;
    const initial = persisted || data.preview.structured.inspection;
    const hivesResponse = await fetch('/api/hives');
    if (!hivesResponse.ok) throw new Error('Spisak košnica nije dostupan. Pokušajte ponovo.');
    const hives = await hivesResponse.json();
    root.replaceChildren();
    const state = {unsaved: !persisted, root}; active = state;
    const header = el('div', null, root); header.className = 'review-header';
    const title = el('h2', persisted ? `Pregled #${persisted.inspection_id}` : 'Provera pregleda', header);
    title.tabIndex = -1;
    const badge = el('span', persisted?.confirmation_status === 'confirmed' ? 'Potvrđeno' : 'Nije potvrđeno', header);
    badge.className = `badge ${persisted?.confirmation_status === 'confirmed' ? 'badge-good' : 'badge-warn'}`;
    const extraction = el('p', `AI ekstrakcija: ${data.extraction_status === 'completed' ? 'uspešna' : 'neuspešna; unesite podatke ručno'}`, root);
    extraction.className = 'review-caption muted';
    if (data.error) el('p', data.error.message, root).className = 'status-error review-caption';
    const form = el('form', null, root); form.className = 'inspection-form';
    const fields = el('fieldset', null, form); fields.className = 'review-fields';
    el('legend', 'Osnovni pregled', fields).className = 'inspection-section-title';
    const displayFields = [];
    const labelInput = (label, input, parent) => {
      const field = el('div', null, parent); field.className = 'inspection-field';
      input.id = `inspection-field-${++fieldId}`; input.classList.add('inspection-control');
      const caption = el('label', label, field); caption.htmlFor = input.id;
      caption.id = `${input.id}-label`;
      field.append(input);
      const value = el('p', '', field); value.className = 'inspection-value';
      value.setAttribute('aria-labelledby', caption.id);
      displayFields.push({input, value});
      return input;
    };
    const identityValue = (label, text, parent) => {
      const field = el('div', null, parent); field.className = 'inspection-field';
      el('span', label, field).className = 'inspection-label';
      const value = el('p', text || 'Bez naziva', field); value.className = 'inspection-value';
      if (!text) value.classList.add('value-unknown');
    };
    const compact = el('div', null, fields); compact.className = 'inspection-fields-grid';
    const date = labelInput('Datum i vreme pregleda · UTC', el('input'), compact);
    date.type = 'datetime-local'; date.step = '1'; date.required = true;
    date.value = (persisted?.inspected_at || data.inspected_at || data.preview.created_at).replace(' ', 'T');
    let hiveSelect, hiveId, hiveName;
    if (!persisted) {
      hiveSelect = el('select'); hiveSelect.required = true;
      hiveSelect.append(new Option('Izaberite košnicu', ''), ...hives.map(h => new Option(`${h.name || 'Košnica'} · ${h.hive_id}`, h.hive_id)), new Option('Nova košnica', '__new__'));
      labelInput('Košnica', hiveSelect, compact);
      hiveSelect.parentElement.classList.add('inspection-field-wide');
      compact.prepend(hiveSelect.parentElement);
      hiveName = labelInput('Naziv košnice', el('input'), compact); hiveName.maxLength = 200;
      hiveId = labelInput('ID košnice · stalan za postojeću', el('input'), compact); hiveId.required = true; hiveId.readOnly = true;
      hiveId.pattern = '[A-Za-z0-9][A-Za-z0-9_.-]*'; hiveId.maxLength = 64;
      const extracted = data.preview.structured.hive;
      const found = hives.find(h => h.hive_id === extracted.hive_id);
      hiveSelect.value = found ? found.hive_id : '';
      hiveId.value = found?.hive_id || ''; hiveName.value = found?.name || '';
      const suggestion = el('p', extracted.hive_id && extracted.hive_id !== 'UNKNOWN' ? `Predloženi ID iz transkripta: ${extracted.hive_id}. Izaberite postojeću ili novu košnicu.` : 'Identifikujte košnicu pre potvrde.', compact);
      suggestion.className = 'muted review-caption inspection-field-wide';
      hiveSelect.addEventListener('change', () => {
        const selected = hives.find(h => h.hive_id === hiveSelect.value);
        hiveId.readOnly = hiveSelect.value !== '__new__';
        hiveId.value = selected?.hive_id || ''; hiveName.value = selected?.name || '';
      });
    } else {
      const hive = data.preview.structured.hive;
      identityValue('Naziv košnice', hive.name, compact);
      identityValue('ID košnice · nepromenljiv', persisted.hive_id, compact);
    }
    const controls = {};
    const addField = (key, parent) => {
      const def = spec.fields[key]; let input;
      if (def.flag || def.enum) {
        input = el('select'); input.append(new Option('Nepoznato', ''));
        const options = def.flag ? [[1, 'Da'], [0, 'Ne']] : def.enum.map(v => [v, ({pljacka:'pljačka', rastrkano:'raštrkano', kriticno:'kritično', visak:'višak', previse:'previše', zapoceti:'započeti', teska:'teška', vrlo_teska:'vrlo teška', veoma_jako:'veoma jako'})[v] || v]);
        options.forEach(([value, label]) => input.append(new Option(label, String(value))));
      } else if (def.type === 'integer' || def.type === 'number') {
        input = el('input'); input.type = 'number'; input.step = def.type === 'integer' ? '1' : 'any'; input.placeholder = 'Nepoznato';
        if (def.minimum !== undefined) input.min = def.minimum;
        if (def.maximum !== undefined) input.max = def.maximum;
      } else { input = el('textarea'); input.rows = 2; input.placeholder = 'Nepoznato'; }
      input.value = initial[key] ?? ''; input.name = key;
      controls[key] = input; labelInput(def.label, input, parent);
      const showUnknown = () => { input.classList.toggle('is-unknown', input.value === ''); };
      showUnknown(); input.addEventListener('input', showUnknown); input.addEventListener('change', showUnknown);
      if (input.tagName === 'TEXTAREA') input.parentElement.classList.add('inspection-field-wide');
      if (key === 'note' || key === 'actions_taken') input.parentElement.classList.add('inspection-field-note');
    };
    spec.compact.forEach(key => addField(key, compact));
    // Keep the disclosure usable even while persisted factual controls are disabled.
    const expanded = el('details', null, form); expanded.className = 'review-details';
    el('summary', 'Sva polja i originalni transkript', expanded);
    const extraFields = el('fieldset', null, expanded); extraFields.className = 'review-fields';
    Object.entries(spec.groups).forEach(([group, keys]) => {
      const section = el('details', null, extraFields); section.className = 'review-group';
      el('summary', group === 'Preduzete radnje' ? 'Radnje i beleške' : group, section);
      const grid = el('div', null, section); grid.className = 'inspection-fields-grid';
      keys.forEach(key => addField(key, grid));
    });
    const transcript = el('details', null, expanded); transcript.className = 'review-group review-transcript';
    el('summary', 'Originalni Whisper transkript', transcript);
    el('p', 'Samo čitanje · izvorni tekst ostaje neizmenjen.', transcript).className = 'muted review-caption';
    el('pre', data.preview.raw_transcript, transcript);
    if (!persisted) el('p', 'Nije sačuvano. Kartica se gubi pri napuštanju ili osvežavanju stranice.', form).className = 'muted review-caption';
    const status = el('p', '', form); status.className = 'review-status'; status.setAttribute('role', 'status');
    const actions = el('div', null, form); actions.className = 'review-actions';
    const submit = el('button', persisted?.confirmation_status === 'confirmed' ? 'Sačuvaj izmene' : 'Potvrdi pregled', actions); submit.type = 'submit';
    const discard = el('button', persisted ? 'Odustani od izmena' : 'Odbaci karticu', actions); discard.type = 'button'; discard.className = 'button-secondary';
    const setDisabled = disabled => { fields.disabled = disabled; extraFields.disabled = disabled; };
    const setEditing = editing => {
      setDisabled(!editing);
      displayFields.forEach(({input, value}) => {
        input.hidden = !editing; value.hidden = editing;
        value.textContent = input.value === '' ? 'Nepoznato' : input.tagName === 'SELECT' ? input.selectedOptions[0].textContent : input === date ? `${input.value.replace('T', ' ')} UTC` : input.value;
        value.classList.toggle('value-unknown', input.value === '');
      });
      submit.hidden = !editing; discard.hidden = !editing;
    };
    let edit;
    const confirmed = persisted?.confirmation_status === 'confirmed';
    setEditing(!confirmed);
    if (confirmed) {
      edit = el('button', 'Uredi podatke', actions); edit.type = 'button';
      edit.onclick = () => { setEditing(true); edit.hidden = true; date.focus({preventScroll: true}); };
    }
    form.addEventListener('input', () => { state.unsaved = true; });
    form.addEventListener('change', () => { state.unsaved = true; });
    discard.onclick = () => {
      if (state.unsaved && !window.confirm('Odbaciti nesačuvane podatke?')) return;
      state.unsaved = false;
      if (persisted) window.showReviewCard(data, root);
      else { root.replaceChildren(); active = null; }
    };
    form.onsubmit = async event => {
      event.preventDefault();
      if (!form.reportValidity()) return;
      const inspection = {};
      for (const [key, input] of Object.entries(controls)) {
        const def = spec.fields[key];
        inspection[key] = input.value === '' ? null : (def.flag || ['integer','number'].includes(def.type)) ? Number(input.value) : input.value;
      }
      if (Object.entries(inspection).some(([key, value]) => spec.fields[key].type === 'integer' && value !== null && !Number.isSafeInteger(value))) {
        status.textContent = 'Broj je prevelik za tačan unos u pregledaču.';
        return;
      }
      const body = {inspected_at: date.value, inspection};
      let url, method = 'POST';
      if (!persisted) {
        body.review_token = data.review_token;
        body.hive = {hive_id: hiveId.value, name: hiveName.value || null, create: hiveSelect.value === '__new__'};
        url = '/api/reviews/confirm';
      } else {
        url = `/api/inspections/${persisted.inspection_id}`;
        if (persisted.confirmation_status === 'confirmed') method = 'PUT'; else url += '/confirm';
      }
      submit.disabled = true; discard.disabled = true; setDisabled(true);
      status.textContent = 'Čuvanje…';
      try {
        const response = await fetch(url, {method, headers: {'Content-Type':'application/json'}, body: JSON.stringify(body)});
        const saved = await response.json();
        if (!response.ok) throw new Error(typeof saved.detail === 'string' ? saved.detail : 'Proverite unete vrednosti. Kartica je zadržana.');
        state.unsaved = false;
        location.href = `/logs/${persisted?.raw_log_id || saved.id}`;
      } catch (error) {
        status.textContent = `${error.message} Podaci su i dalje u kartici; pokušajte ponovo.`;
        setDisabled(false); submit.disabled = false; discard.disabled = false;
      }
    };
    if (!persisted) {
      title.focus({preventScroll: true});
      root.scrollIntoView({block: 'start'});
    }
  };
})();
