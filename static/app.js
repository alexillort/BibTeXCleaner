'use strict';
const $ = id => document.getElementById(id);
const input = $('inputArea');
let outputBib = '';
let busy = false;
let revision = 0;
let sourceName = 'bibliografia';
const defaults = new Set(['clean_whitespace', 'remove_empty', 'sort_fields']);
const sample = `@article{Vaswani2017,
  title = {Attention Is All You Need},
  author = {Vaswani, Ashish and   Shazeer, Noam},
  year = {2017},
  eprint = {1706.03762},
  archivePrefix = {arXiv},
  keywords = {},
  abstract = {}
}

@article{Shannon1948,
  title = {A Mathematical  Theory of Communication},
  author = {Shannon, Claude E.},
  year = {1948},
  journal = {The Bell System Technical Journal},
  doi = {10.1002/j.1538-7305.1948.tb01338.x},
  note = {}
}

@article{Shannon1948copy,
  title = {A Mathematical Theory of Communication},
  author = {Shannon, Claude E.},
  year = {1948},
  doi = {https://doi.org/10.1002/j.1538-7305.1948.tb01338.x}
}`;

function status(message, kind = '') {
  $('statusText').textContent = message;
  $('status').className = kind;
}
function updateInput() {
  const count = (input.value.match(/@(?!comment\b|string\b|preamble\b)[a-z]+\s*[{(]/gi) || []).length;
  $('inputCount').textContent = `${count} ${count === 1 ? 'entrada' : 'entradas'}`;
  $('inputSize').textContent = `${input.value.length.toLocaleString('es')} caracteres`;
  $('runBtn').disabled = busy || !input.value.trim();
}
function invalidate() {
  revision++;
  if (outputBib) {
    $('outputState').textContent = 'Cambios pendientes · vuelve a limpiar';
    $('outputState').classList.add('stale');
    $('copyBtn').disabled = true;
    $('downloadBtn').disabled = true;
  }
}
input.addEventListener('input', () => { updateInput(); invalidate(); });
document.querySelectorAll('[data-opt], #sortBy, #removeFields, #addFields').forEach(control => {
  control.addEventListener('input', invalidate);
});

function selectTab(tab) {
  document.querySelectorAll('[role="tab"]').forEach(button => {
    const selected = button === tab;
    button.setAttribute('aria-selected', String(selected));
    button.tabIndex = selected ? 0 : -1;
    $(`panel-${button.dataset.panel}`).hidden = !selected;
  });
}
document.querySelectorAll('[role="tab"]').forEach(tab => {
  tab.addEventListener('click', () => selectTab(tab));
  tab.addEventListener('keydown', event => {
    const tabs = Array.from(document.querySelectorAll('[role="tab"]'));
    let index = tabs.indexOf(tab);
    if (event.key === 'ArrowRight') index = (index + 1) % tabs.length;
    else if (event.key === 'ArrowLeft') index = (index + tabs.length - 1) % tabs.length;
    else if (event.key === 'Home') index = 0;
    else if (event.key === 'End') index = tabs.length - 1;
    else return;
    event.preventDefault();
    selectTab(tabs[index]);
    tabs[index].focus();
  });
});
$('resetBtn').addEventListener('click', () => {
  document.querySelectorAll('[data-opt]').forEach(control => { control.checked = defaults.has(control.dataset.opt); });
  $('sortBy').value = 'none';
  $('removeFields').value = '';
  $('addFields').value = '';
  invalidate();
  status('Opciones restablecidas.');
});
$('sampleBtn').addEventListener('click', () => {
  input.value = sample;
  sourceName = 'ejemplo';
  $('filename').textContent = 'ejemplo.bib';
  updateInput();
  invalidate();
  status('Ejemplo cargado: prueba también «Eliminar duplicados».');
});
$('clearBtn').addEventListener('click', () => {
  input.value = '';
  sourceName = 'bibliografia';
  $('filename').textContent = 'Pega texto o arrastra un archivo .bib';
  $('fileInput').value = '';
  resetOutput();
  invalidate();
  updateInput();
  status('Editor vacío. Listo para otra bibliografía.');
  input.focus();
});
function resetOutput() {
  outputBib = '';
  $('outputText').value = '';
  $('outputText').hidden = true;
  $('emptyState').hidden = false;
  $('copyBtn').disabled = true;
  $('downloadBtn').disabled = true;
  $('outputMeta').textContent = 'Tu archivo limpio aparecerá aquí';
  $('outputState').textContent = 'Esperando tu bibliografía';
  $('outputState').classList.remove('stale');
  $('outputSize').textContent = 'Sin procesar';
  ['statEntries', 'statDuplicates', 'statDois'].forEach(id => { $(id).textContent = '—'; });
  $('logContent').replaceChildren();
  $('logCount').textContent = '0';
}
async function loadFile(file) {
  if (busy) return;
  if (!/\.(bib|txt)$/i.test(file.name)) return status('Selecciona un archivo .bib o .txt.', 'error');
  if (file.size > 4 * 1024 * 1024) return status('El archivo supera el límite de importación de 4 MB.', 'error');
  try {
    input.value = await file.text();
    sourceName = file.name.replace(/\.[^.]+$/, '');
    $('filename').textContent = file.name;
    updateInput();
    invalidate();
    status(`Archivo importado: ${file.name}`);
  } catch { status('No se pudo leer el archivo. Vuelve a seleccionarlo.', 'error'); }
}
$('importBtn').addEventListener('click', () => $('fileInput').click());
$('fileInput').addEventListener('change', async event => {
  if (event.target.files[0]) await loadFile(event.target.files[0]);
  event.target.value = '';
});
const dropZone = $('dropZone');
dropZone.addEventListener('dragover', event => { event.preventDefault(); if (!busy) dropZone.classList.add('drag-over'); });
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag-over'));
dropZone.addEventListener('drop', event => {
  event.preventDefault();
  dropZone.classList.remove('drag-over');
  if (event.dataTransfer.files[0]) loadFile(event.dataTransfer.files[0]);
});
window.addEventListener('dragover', event => event.preventDefault());
window.addEventListener('drop', event => event.preventDefault());

function setBusy(value) {
  busy = value;
  document.body.classList.toggle('processing', value);
  $('runLabel').textContent = value ? 'Procesando…' : 'Limpiar bibliografía';
  document.querySelectorAll('[data-opt], #sortBy, #removeFields, #addFields, #sampleBtn, #importBtn, #clearBtn, #resetBtn').forEach(control => { control.disabled = value; });
  input.readOnly = value;
  $('runBtn').setAttribute('aria-busy', String(value));
  updateInput();
}
async function runCleaner() {
  if (busy || !input.value.trim()) return;
  const options = {};
  document.querySelectorAll('[data-opt]').forEach(control => { options[control.dataset.opt] = control.checked; });
  options.sort_by = $('sortBy').value;
  options.remove_fields = $('removeFields').value;
  options.add_fields = $('addFields').value;
  const snapshot = revision;
  resetOutput();
  setBusy(true);
  status(options.find_dois ? 'Procesando y buscando DOI. Las consultas pueden tardar varios segundos por referencia…' : 'Limpiando y organizando tus referencias…', 'busy');
  try {
    const response = await fetch('/clean', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: input.value, options }),
    });
    const data = await response.json();
    if (!response.ok || data.error) throw new Error(data.error || 'No se pudo procesar el archivo.');
    if (revision !== snapshot) return status('La entrada cambió. Ejecuta la limpieza de nuevo.');
    outputBib = data.output;
    $('outputText').value = outputBib;
    $('outputText').hidden = false;
    $('emptyState').hidden = true;
    $('copyBtn').disabled = false;
    $('downloadBtn').disabled = false;
    $('outputMeta').textContent = `${sourceName}_limpio.bib`;
    $('outputSize').textContent = `${outputBib.length.toLocaleString('es')} caracteres`;
    $('outputState').textContent = 'Listo para exportar';
    $('statEntries').textContent = data.stats.output_entries;
    $('statDuplicates').textContent = data.stats.duplicates_removed;
    $('statDois').textContent = data.stats.dois_found;
    const log = data.log.length ? data.log : ['Formato aplicado. No se necesitaron otros cambios.'];
    $('logContent').replaceChildren(...log.map(line => {
      const paragraph = document.createElement('p');
      paragraph.textContent = line;
      return paragraph;
    }));
    $('logCount').textContent = data.log.length;
    status(`Limpieza completada. ${data.stats.output_entries} referencias listas para exportar.`);
  } catch (error) {
    status(error instanceof TypeError ? 'No hay conexión con la aplicación local. Comprueba que Python siga abierto.' : error.message, 'error');
  } finally { setBusy(false); }
}
$('runBtn').addEventListener('click', runCleaner);
document.addEventListener('keydown', event => {
  if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') { event.preventDefault(); runCleaner(); }
});
$('logBtn').addEventListener('click', () => {
  const expanded = $('logBtn').getAttribute('aria-expanded') !== 'true';
  $('logBtn').setAttribute('aria-expanded', String(expanded));
  $('logContent').hidden = !expanded;
});
$('copyBtn').addEventListener('click', async () => {
  if (!outputBib || $('copyBtn').disabled) return;
  try {
    await navigator.clipboard.writeText(outputBib);
    status('Bibliografía copiada al portapapeles.');
  } catch {
    $('outputText').focus();
    $('outputText').select();
    // Embedded browsers may deny the async clipboard API but allow selection copy.
    let copied = false;
    try { copied = document.execCommand('copy'); } catch { /* Keep the selection available. */ }
    status(copied ? 'Bibliografía copiada al portapapeles.' : 'No se pudo acceder al portapapeles. Usa Ctrl / ⌘ + C para copiar el texto seleccionado.');
  }
});
$('downloadBtn').addEventListener('click', () => {
  if (!outputBib || $('downloadBtn').disabled) return;
  const url = URL.createObjectURL(new Blob([outputBib], { type: 'application/x-bibtex;charset=utf-8' }));
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = `${sourceName}_limpio.bib`;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  status('Archivo .bib preparado para descargar.');
});
updateInput();
