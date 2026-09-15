// wallet_core.js — Ponte JS <-> Python (pywebview)

const log = (msg) => {
  const el = document.getElementById('console-log');
  if (!el) return;
  const ts = new Date().toLocaleTimeString();
  el.textContent = `[${ts}] ${msg}\n` + el.textContent;
};

async function callApi(fnName, ...args) {
  if (!window.pywebview || !window.pywebview.api) {
    log("pywebview nao disponivel.");
    return null;
  }
  if (typeof window.pywebview.api[fnName] !== 'function') {
    log(`Metodo '${fnName}' nao existe.`);
    return null;
  }
  try { return await window.pywebview.api[fnName](...args); }
  catch (e) { log(`Erro em ${fnName}: ${e}`); return null; }
}

async function uiGenerateWallet() {
  log("Gerando carteira...");
  const w = await callApi('generate_wallet');
  if (!w || w.erro) { log("Falha: " + (w?.erro || "vazio")); return; }
  document.getElementById('w-addr').value = w.address;
  document.getElementById('w-sk').value   = w.spend_secret_key;
  document.getElementById('w-pk').value   = w.public_key;
  log("Carteira criada: " + w.address);
}

function toggleKeys() {
  for (const id of ['w-sk', 'w-pk']) {
    const el = document.getElementById(id);
    el.type = (el.type === 'password') ? 'text' : 'password';
  }
}

async function uiSyncPortfolio() {
  const addr = document.getElementById('w-addr').value.trim();
  if (!addr) { log("Sem endereco."); return; }
  const p = await callApi('portfolio', addr);
  if (!p) return;
  if (p.erro) { log("Erro: " + p.erro); return; }
  const count = Object.keys(p).length;
  document.getElementById('asset-count').textContent = "Ativos: " + count;
  document.getElementById('portfolio-display').textContent =
    count === 0 ? "Nenhum ativo." : JSON.stringify(p, null, 2);
  log("Portfolio sincronizado (" + count + " ativos).");
}

async function uiMineBlock() {
  const addr = document.getElementById('w-addr').value.trim();
  if (!addr) { log("Sem endereco."); return; }
  const r = await callApi('mine_block', addr);
  log(r ? JSON.stringify(r) : "Sem resposta.");
}

async function uiCallFaucet() {
  const addr = document.getElementById('w-addr').value.trim();
  const sk   = document.getElementById('w-sk').value;
  const pk   = document.getElementById('w-pk').value;
  if (!addr || !sk || !pk) { log("Carregue uma carteira antes."); return; }
  const r = await callApi('call_faucet', addr, sk, pk);
  log(r ? JSON.stringify(r) : "Sem resposta.");
}

async function uiSaveWallet() {
  const name = document.getElementById('f-name').value.trim();
  const pass = document.getElementById('f-pass').value;
  const addr = document.getElementById('w-addr').value.trim();
  const sk   = document.getElementById('w-sk').value;
  const pk   = document.getElementById('w-pk').value;
  if (!addr || !sk) { log("Nada para salvar."); return; }
  if (pass.length < 12) { log("Senha < 12 caracteres."); return; }
  const r = await callApi('save_wallet', name, pass, addr, sk, pk);
  log(r ? (r.status === 'sucesso' ? "OK: " + r.message : "Erro: " + r.message)
         : "Sem resposta.");
}

async function uiLoadWallet() {
  const name = document.getElementById('f-name').value.trim();
  const pass = document.getElementById('f-pass').value;
  if (!name || !pass) { log("Informe nome e senha."); return; }
  const r = await callApi('load_wallet', name, pass);
  if (!r) return;
  if (r.status !== 'sucesso') { log("Erro: " + r.message); return; }
  document.getElementById('w-addr').value = r.address;
  document.getElementById('w-sk').value   = r.spend_secret_key;
  document.getElementById('w-pk').value   = r.public_key || "";
  log("Carteira carregada: " + r.address);
}

async function uiExecuteTransfer() {
  const sender = document.getElementById('w-addr').value.trim();
  const sk     = document.getElementById('w-sk').value;
  const pk     = document.getElementById('w-pk').value;
  const to     = document.getElementById('t-to').value.trim();
  const asset  = document.getElementById('t-asset').value.trim();
  const amount = document.getElementById('t-amount').value;
  if (!sender || !sk || !pk) { log("Carregue uma carteira antes."); return; }
  if (!to || !asset || !amount) { log("Preencha todos os campos."); return; }
  const r = await callApi('transfer', sender, to, asset, amount, sk, pk);
  log(r ? JSON.stringify(r) : "Sem resposta.");
}

async function uiCheckNode() {
  const r = await callApi('node_status');
  if (r && r.ok) log("No online - altura " + r.height);
  else log("No offline: " + (r?.msg || "sem resposta"));
}

window.addEventListener('pywebviewready', () => {
  log("pywebview pronto.");
  uiCheckNode();
});

setTimeout(() => {
  if (!window.pywebview || !window.pywebview.api) {
    log("pywebview nao detectado. Rode via app_wallet.py.");
  }
}, 3000);
