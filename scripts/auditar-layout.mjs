// Audita o layout do placar num navegador de verdade, em quatro larguras.
//
// Existe porque validar por métrica no Python não pegava o problema: a tabela
// principal estourava o container em TODAS as larguras, e o sintoma ficava
// escondido atrás de barras de rolagem que pareciam intencionais. A checagem
// que importa é esta — nada pode rolar lateralmente nem vazar do painel.
//
//   npm i playwright
//   node scripts/auditar-layout.mjs [caminho-do-html]
//
// PLAYWRIGHT_CHROMIUM aponta um binário próprio, se houver.

import { chromium } from 'playwright';
import { resolve, join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const raiz = dirname(dirname(fileURLToPath(import.meta.url)));
const alvo = 'file://' + resolve(process.argv[2] || join(raiz, 'placar.html'));
const LARGURAS = [390, 768, 1024, 1400];

const navegador = await chromium.launch(
  process.env.PLAYWRIGHT_CHROMIUM
    ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM }
    : {}
);

let problemas = 0;
console.log(alvo + '\n');

for (const largura of LARGURAS) {
  const pag = await navegador.newPage({ viewport: { width: largura, height: 1000 } });
  const erros = [];
  pag.on('pageerror', (e) => erros.push(e.message));
  pag.on('console', (m) => { if (m.type() === 'error') erros.push(m.text()); });
  await pag.goto(alvo);
  await pag.waitForTimeout(700);

  const r = await pag.evaluate(() => {
    const out = {
      overflowPagina:
        document.documentElement.scrollWidth > document.documentElement.clientWidth,
      rolagem: [],
      vazando: [],
    };
    document.querySelectorAll('.painel, .tablewrap, table, .kpi').forEach((el) => {
      if (el.scrollWidth > el.clientWidth + 2) {
        out.rolagem.push((el.className || el.tagName) + ' +' +
          (el.scrollWidth - el.clientWidth) + 'px');
      }
    });
    document.querySelectorAll('.painel td, .painel th, .kpi b').forEach((el) => {
      const pai = el.closest('.painel, .kpi');
      if (!pai) return;
      if (el.getBoundingClientRect().right > pai.getBoundingClientRect().right + 1) {
        out.vazando.push(el.textContent.trim().slice(0, 30));
      }
    });
    return out;
  });

  const ok = !r.overflowPagina && !r.rolagem.length && !r.vazando.length && !erros.length;
  if (!ok) problemas++;
  console.log(largura + 'px  ' + (ok ? 'ok' : 'PROBLEMA'));
  if (r.overflowPagina) console.log('   página rola lateralmente');
  if (r.rolagem.length) console.log('   com rolagem:', [...new Set(r.rolagem)].join(', '));
  if (r.vazando.length) {
    console.log('   vazando do painel:', [...new Set(r.vazando)].slice(0, 6).join(' | '));
  }
  if (erros.length) console.log('   erros JS:', erros.slice(0, 3).join(' | '));

  await pag.close();
}

await navegador.close();
console.log(problemas ? '\n' + problemas + ' largura(s) com problema' : '\nnenhum problema');
process.exit(problemas ? 1 : 0);
