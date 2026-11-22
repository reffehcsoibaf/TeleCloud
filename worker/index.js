// Worker do TeleCloud (telecloud.fabioscheffer.workers.dev).
//
// - Serve a página (pasta site/) como arquivos estáticos.
// - /baixar/windows e /baixar/android levam sempre ao arquivo da versão mais nova publicada no GitHub
//   (TeleCloud.exe e TeleCloud.apk), para o endereço de download nunca mudar.
// - /versao.json diz qual é essa versão e o tamanho do arquivo, para a página mostrar.
//
// Os arquivos ficam como anexos das versões do repositório; o Worker só aponta para eles.

import { maisNova } from "./versoes.js";

const ARQUIVOS = { windows: "TeleCloud.exe", android: "TeleCloud.apk" };
const CINCO_MINUTOS = 300;

async function versoes(env) {
  const repo = env.REPOSITORIO || "reffehcsoibaf/TeleCloud";
  const resp = await fetch(`https://api.github.com/repos/${repo}/releases?per_page=30`, {
    headers: { Accept: "application/vnd.github+json", "User-Agent": "telecloud-site" },
    // O GitHub limita consultas sem login; o cache da Cloudflare evita bater nele a cada visita.
    cf: { cacheEverything: true, cacheTtl: CINCO_MINUTOS },
  });
  if (!resp.ok) throw new Error(`GitHub respondeu ${resp.status}`);
  const lista = await resp.json();
  return {
    repo,
    windows: maisNova(lista, ARQUIVOS.windows),
    android: maisNova(lista, ARQUIVOS.android),
  };
}

function json(corpo, status = 200) {
  return new Response(JSON.stringify(corpo), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": `public, max-age=${CINCO_MINUTOS}`,
    },
  });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const caminho = url.pathname.replace(/\/+$/, "");

    if (caminho === "/versao.json") {
      try {
        const v = await versoes(env);
        return json({ windows: v.windows, android: v.android });
      } catch (e) {
        return json({ erro: "Não consegui consultar as versões agora." }, 502);
      }
    }

    const m = caminho.match(/^\/baixar\/(windows|android)$/);
    if (m) {
      const repo = env.REPOSITORIO || "reffehcsoibaf/TeleCloud";
      let destino = `https://github.com/${repo}/releases`; // sem versão publicada (ou GitHub fora do ar): lista de versões
      try {
        const v = await versoes(env);
        if (v[m[1]]) destino = v[m[1]].url;
      } catch (e) {
        // fica na lista de versões
      }
      return new Response(null, {
        status: 302,
        headers: { Location: destino, "Cache-Control": "no-store" },
      });
    }

    return env.ASSETS.fetch(request);
  },
};
