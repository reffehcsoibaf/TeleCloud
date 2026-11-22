// Escolha da versão mais nova entre as versões publicadas no GitHub. Funções puras, sem rede,
// para poderem ser testadas fora do Worker (testes/versoes_teste.html).

// "v2026.11.9" vale 2026.11.9.0. Tag fora do padrão ano.mês.dia[.N] ou rascunho não conta.
export function chaveDe(release) {
  const v = String((release && release.tag_name) || "").replace(/^[vV]/, "");
  if (!release || release.draft || !/^\d{4}\.\d{1,2}\.\d{1,2}(\.\d{1,3})?$/.test(v)) return null;
  const k = v.split(".").map(Number);
  if (k.length < 4) k.push(0);
  return { versao: v, chave: k };
}

export function maior(a, b) {
  for (let i = 0; i < 4; i++) {
    if (a[i] !== b[i]) return a[i] > b[i];
  }
  return false;
}

export function arquivo(release, nome) {
  return (release.assets || []).find((a) => a.name === nome) || null;
}

// A versão mais nova que tem o arquivo `nome`. Devolve { versao, url, tamanho, pagina } ou null.
export function maisNova(lista, nome) {
  let melhor = null;
  for (const r of lista || []) {
    const c = chaveDe(r);
    const a = c && arquivo(r, nome);
    if (!c || !a) continue;
    if (!melhor || maior(c.chave, melhor.chave)) {
      melhor = { versao: c.versao, chave: c.chave, url: a.browser_download_url, tamanho: a.size, pagina: r.html_url };
    }
  }
  if (!melhor) return null;
  return { versao: melhor.versao, url: melhor.url, tamanho: melhor.tamanho, pagina: melhor.pagina };
}
