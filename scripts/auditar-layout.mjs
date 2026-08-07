// Audita o layout do placar num navegador de verdade, em quatro larguras.
//
// Existe porque validar por métrica no Python não pegava o problema: a tabela
// principal estourava o container em TODAS as larguras, e o sintoma ficava
// escondido atrás de barras de rolagem que pareciam intencionais. A checagem
// que importa é esta — nada pode rolar lateralmente nem vazar do painel.
//
// Confere também o que só se vê renderizado: erro de JS no console e ponto
// decimal em número, que numa página em português é sempre defeito.
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

    // A barra tem que desenhar o que diz desenhar. Um seletor sem `>` já
    // aplicou o max-width do rótulo à barra azul e travou todo gráfico em
    // 8rem: acima de dois terços, valores diferentes saíam do mesmo tamanho.
    // Nada disso estoura layout, então só comparando pedido com pintado.
    out.barras = [];
    document.querySelectorAll('.barra').forEach((br) => {
      const t = br.querySelector('.t'), f = br.querySelector('.f');
      if (!t || !f) return;
      const pedido = parseFloat(f.style.width);
      const larg = t.getBoundingClientRect().width;
      if (!isFinite(pedido) || !larg) return;
      const real = (100 * f.getBoundingClientRect().width) / larg;
      if (Math.abs(real - pedido) > 2) {
        out.barras.push(
          (br.querySelector('span') || {}).textContent.trim().slice(0, 14) +
          ' pede ' + pedido.toFixed(0) + '% e pinta ' + real.toFixed(0) + '%');
      }
    });

    // Decimal com ponto numa página em português. Em pt-BR o ponto é separador
    // de milhar, então "1.690.773" está certo e "67.2%" está errado: o que
    // denuncia é o ponto seguido de menos de três dígitos. Já escapou um
    // "0.5°" e um "67.2%" no KPI, os dois por concatenar float direto.
    out.decimais = [];
    const anda = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    for (let n = anda.nextNode(); n; n = anda.nextNode()) {
      if (n.parentElement.closest('script, style')) continue;
      const m = n.nodeValue.match(/\d\.\d{1,2}(?!\d)/g);
      if (m) out.decimais.push(...m);
    }
    return out;
  });

  const ok = !r.overflowPagina && !r.rolagem.length && !r.vazando.length &&
             !r.decimais.length && !r.barras.length && !erros.length;
  if (!ok) problemas++;
  console.log(largura + 'px  ' + (ok ? 'ok' : 'PROBLEMA'));
  if (r.overflowPagina) console.log('   página rola lateralmente');
  if (r.rolagem.length) console.log('   com rolagem:', [...new Set(r.rolagem)].join(', '));
  if (r.vazando.length) {
    console.log('   vazando do painel:', [...new Set(r.vazando)].slice(0, 6).join(' | '));
  }
  if (r.barras.length) {
    console.log('   barra desenhando errado:', [...new Set(r.barras)].slice(0, 4).join(' | '));
  }
  if (r.decimais.length) {
    console.log('   ponto decimal em página pt-BR:',
      [...new Set(r.decimais)].slice(0, 6).join(' | '));
  }
  if (erros.length) console.log('   erros JS:', erros.slice(0, 3).join(' | '));

  await pag.close();
}

await navegador.close();
console.log(problemas ? '\n' + problemas + ' largura(s) com problema' : '\nnenhum problema');
process.exit(problemas ? 1 : 0);
