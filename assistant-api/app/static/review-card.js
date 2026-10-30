/* Reviews live only in this page's memory. No browser storage or autosave. */
(() => {
  let active = null;
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
    el('h2', persisted ? `Pregled #${persisted.inspection_id}` : 'Provera pregleda — nije sačuvano', root);
    el('p', `AI ekstrakcija: ${data.extraction_status === 'completed' ? 'uspešna' : 'neuspešna; unesite podatke ručno'}`, root);
    if (data.error) el('p', data.error.message, root);
    const transcript = el('details', null, root);
    el('summary', 'Originalni Whisper transkript (samo čitanje)', transcript);
    el('pre', data.preview.raw_transcript, transcript);
    if (!persisted) el('p', 'Kartica se gubi pri zatvaranju ili osvežavanju stranice. Sačuvajte je izričitom potvrdom.', root);
    const form = el('form', null, root); form.className = 'form-stack';
    const fields = el('fieldset', null, form); fields.className = 'review-fields';
    const labelInput = (label, input, parent = fields) => { const l = el('label', label, parent); l.append(input); return input; };
    let hiveSelect, hiveId, hiveName;
    if (!persisted) {
      hiveSelect = el('select'); hiveSelect.required = true;
      hiveSelect.append(new Option('Izaberite košnicu', ''), ...hives.map(h => new Option(`${h.name || 'Košnica'} · ${h.hive_id}`, h.hive_id)), new Option('Nova košnica', '__new__'));
      labelInput('Košnica', hiveSelect);
      hiveId = labelInput('ID košnice', el('input')); hiveId.required = true; hiveId.readOnly = true;
      hiveId.pattern = '[A-Za-z0-9][A-Za-z0-9_.-]*'; hiveId.maxLength = 64;
      hiveName = labelInput('Naziv košnice', el('input')); hiveName.maxLength = 200;
      const extracted = data.preview.structured.hive;
      const found = hives.find(h => h.hive_id === extracted.hive_id);
      hiveSelect.value = found ? found.hive_id : '';
      hiveId.value = found?.hive_id || ''; hiveName.value = found?.name || '';
      const suggestion = el('p', extracted.hive_id && extracted.hive_id !== 'UNKNOWN' ? `Predloženi ID iz transkripta: ${extracted.hive_id}. Izaberite postojeću ili novu košnicu.` : 'Identifikujte košnicu pre potvrde.', fields);
      suggestion.className = 'muted';
      hiveSelect.addEventListener('change', () => {
        const selected = hives.find(h => h.hive_id === hiveSelect.value);
        hiveId.readOnly = hiveSelect.value !== '__new__';
        hiveId.value = selected?.hive_id || ''; hiveName.value = selected?.name || '';
      });
    } else {
      const hive = data.preview.structured.hive;
      el('p', `Košnica: ${hive.name || '—'} · ID: ${persisted.hive_id} (nepromenljiv)`, fields);
    }
    const date = labelInput('Datum i vreme pregleda', el('input'));
    date.type = 'datetime-local'; date.step = '1'; date.required = true;
    date.value = (persisted?.inspected_at || data.inspected_at || data.preview.created_at).replace(' ', 'T');
    el('small', 'Vreme pregleda je prikazano u UTC.', fields);
    const controls = {};
    const addField = (key, parent) => {
      const def = spec.fields[key]; let input;
      if (def.flag || def.enum) {
        input = el('select'); input.append(new Option('Nepoznato', ''));
        const options = def.flag ? [[1, 'Da'], [0, 'Ne']] : def.enum.map(v => [v, ({pljacka:'pljačka', rastrkano:'raštrkano', kriticno:'kritično', visak:'višak', previse:'previše', zapoceti:'započeti', teska:'teška', vrlo_teska:'vrlo teška', veoma_jako:'veoma jako'})[v] || v]);
        options.forEach(([value, label]) => input.append(new Option(label, String(value))));
      } else if (def.type === 'integer' || def.type === 'number') {
        input = el('input'); input.type = 'number'; input.step = def.type === 'integer' ? '1' : 'any';
        if (def.minimum !== undefined) input.min = def.minimum;
        if (def.maximum !== undefined) input.max = def.maximum;
      } else { input = el('textarea'); input.rows = 2; }
      input.value = initial[key] ?? ''; input.name = key;
      controls[key] = input; labelInput(def.label, input, parent);
    };
    spec.compact.forEach(key => addField(key, fields));
    const expanded = el('details', null, fields); el('summary', 'Proširi / skupi detalje pregleda', expanded);
    Object.entries(spec.groups).forEach(([group, keys]) => { const section = el('section', null, expanded); el('h3', group, section); keys.forEach(key => addField(key, section)); });
    const status = el('p', '', root); status.setAttribute('role', 'status');
    const submit = el('button', persisted?.confirmation_status === 'confirmed' ? 'Sačuvaj izmene' : 'Potvrdi i sačuvaj pregled', form); submit.type = 'submit';
    const discard = el('button', persisted ? 'Odustani od izmena' : 'Odbaci karticu', form); discard.type = 'button';
    let edit;
    if (persisted) {
      fields.disabled = true; submit.hidden = true; discard.hidden = true;
      edit = el('button', 'Uredi podatke', root); edit.type = 'button';
      edit.onclick = () => { fields.disabled = false; submit.hidden = false; discard.hidden = false; edit.hidden = true; };
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
      submit.disabled = true; discard.disabled = true; fields.disabled = true;
      status.textContent = 'Čuvanje…';
      try {
        const response = await fetch(url, {method, headers: {'Content-Type':'application/json'}, body: JSON.stringify(body)});
        const saved = await response.json();
        if (!response.ok) throw new Error(typeof saved.detail === 'string' ? saved.detail : 'Proverite unete vrednosti. Kartica je zadržana.');
        state.unsaved = false;
        location.href = `/logs/${persisted?.raw_log_id || saved.id}`;
      } catch (error) {
        status.textContent = `${error.message} Podaci su i dalje u kartici; pokušajte ponovo.`;
        fields.disabled = false; submit.disabled = false; discard.disabled = false;
      }
    };
  };
})();
