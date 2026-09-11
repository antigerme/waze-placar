// Confere o que o navegador REALMENTE pinta contra o payload embutido.
// O payload estar certo não garante página certa: o bug das barras provou.
import { chromium } from 'playwright';
import { resolve, join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const raiz = dirname(dirname(fileURLToPath(import.meta.url)));
const alvo = 'file://' + resolve(process.argv[2] || join(raiz, 'placar.html'));

const b = await chromium.launch(
  process.env.PLAYWRIGHT_CHROMIUM
    ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM }
    : {}
);
let falhas = 0, checks = 0;
const erro = (m) => { falhas++; console.log('  FALHA ' + m); };

for (const largura of [390, 768, 1400]) {
  const ctx = await b.newContext({ viewport: { width: largura, height: 1000 } });
  const p = await ctx.newPage();
  const jsErros = [];
  p.on('pageerror', (e) => jsErros.push(e.message));
  p.on('console', (m) => { if (m.type() === 'error') jsErros.push(m.text()); });
  await p.goto(alvo);
  await p.waitForTimeout(700);

  for (const aba of ['d30', 'd7', 'd90', 'tot']) {
    await p.evaluate((k) => {
      const t = [...document.querySelectorAll('.tab')].find((x) => x.dataset.k === k);
      if (t) t.click();
    }, aba);
    await p.waitForTimeout(250);

    const r = await p.evaluate((k) => {
      const out = { probs: [], n: 0 };
      const COL = { d7: 4, d30: 5, d90: 6, tot: 3 };
      const NFtxt = (v) => new Intl.NumberFormat('pt-BR').format(v);
      const idx = D.abas[k];

      // contagem na aba
      const tab = [...document.querySelectorAll('.tab')].find((x) => x.dataset.k === k);
      const cont = parseInt(tab.textContent.replace(/\D/g, '').slice(-String(idx.length).length), 10);
      out.n++;
      if (tab.textContent.indexOf(NFtxt(idx.length)) < 0) {
        out.probs.push('aba ' + k + ' mostra "' + tab.textContent.trim() + '" e tem ' + idx.length);
      }

      // cada linha visível contra o payload
      const trs = [...document.querySelectorAll('#body tr:not(.regua)')];
      const teto = D.cfg.linhasMax || Infinity;
      const esperadas = Math.min(idx.length, teto);
      out.n++;
      if (trs.length !== esperadas) {
        out.probs.push('aba ' + k + ': ' + trs.length + ' linhas na tela, esperado ' + esperadas);
      }
      // quando corta, o aviso tem que aparecer com a conta certa
      const resto = document.getElementById('resto');
      out.n++;
      if (!resto) {
        out.probs.push('a página não tem o aviso de corte (#resto)');
      } else if (idx.length > teto) {
        if (resto.hidden) out.probs.push('aba ' + k + ': cortou e não avisou');
        else if (!resto.textContent.includes(new Intl.NumberFormat('pt-BR').format(idx.length)))
          out.probs.push('aba ' + k + ': aviso sem o total — "' + resto.textContent.trim() + '"');
      } else if (!resto.hidden) {
        out.probs.push('aba ' + k + ': avisou corte sem cortar');
      }
      trs.forEach((tr, i) => {
        const e = D.editores[idx[i]];
        const td = tr.querySelectorAll('td');
        out.n += 3;
        if (td[0].textContent.trim() !== String(i + 1)) {
          out.probs.push('posição ' + (i + 1) + ' mostra "' + td[0].textContent.trim() + '"');
        }
        const a = td[1].querySelector('a');
        if (!a || a.textContent.trim() !== e[0]) {
          out.probs.push('linha ' + (i + 1) + ': nome "' + (a && a.textContent.trim()) + '" != "' + e[0] + '"');
        }
        if (a && a.getAttribute('href') !== 'https://www.waze.com/user/editor/' + encodeURIComponent(e[0])) {
          out.probs.push('linha ' + (i + 1) + ': link errado para ' + e[0]);
        }
        if (td[3].textContent.trim() !== NFtxt(e[COL[k]])) {
          out.probs.push('linha ' + (i + 1) + ' (' + e[0] + '): edições "' +
            td[3].textContent.trim() + '" != "' + NFtxt(e[COL[k]]) + '"');
        }
        // histórico sempre a carreira
        if (td[6] && td[6].textContent.trim() !== NFtxt(e[3])) {
          out.probs.push('linha ' + (i + 1) + ': histórico errado para ' + e[0]);
        }
      });

      // Os dois controles têm regras diferentes, e a conferência acima — que
      // compara posição com índice, sem filtro — não distingue as duas.
      //
      //   estado  troca o recorte: renumera de 1, é o placar daquele estado
      //   busca   procura dentro do recorte: NÃO renumera
      //
      // Buscar o próprio nome mostrava "#1" para quem é #30 da aba.
      const posDe = (nome) => {
        const tr = [...document.querySelectorAll('#body tr')].find(
          (x) => (x.querySelector('.name a') || {}).textContent === nome);
        return tr ? tr.children[0].textContent.trim() : null;
      };
      const alvo = D.editores[idx[Math.min(idx.length - 1, teto - 1)]];
      const q = document.getElementById('q');
      const sel = document.getElementById('uf');
      if (alvo) {
        const naAba = String(idx.indexOf(D.editores.indexOf(alvo)) + 1);
        // buscar não pode mudar a posição que a pessoa já tinha
        q.value = alvo[0]; q.oninput();
        out.n++;
        if (posDe(alvo[0]) !== naAba) {
          out.probs.push('aba ' + k + ' com busca: ' + alvo[0] + ' aparece em #' +
            posDe(alvo[0]) + ' e é #' + naAba + ' da aba');
        }
        q.value = ''; q.oninput();

        // filtrar o estado renumera de 1, e a busca dentro dele também não mexe
        if (alvo[1]) {
          const noEstado = String(idx.map((i) => D.editores[i])
            .filter((e) => e[1] === alvo[1]).indexOf(alvo) + 1);
          sel.value = alvo[1]; sel.onchange();
          out.n++;
          if (posDe(alvo[0]) !== noEstado) {
            out.probs.push('aba ' + k + ' filtrando ' + alvo[1] + ': ' + alvo[0] +
              ' aparece em #' + posDe(alvo[0]) + ' e é #' + noEstado +
              ' do estado');
          }
          q.value = alvo[0]; q.oninput();
          out.n++;
          if (posDe(alvo[0]) !== noEstado) {
            out.probs.push('aba ' + k + ' filtrando ' + alvo[1] +
              ' e buscando: ' + alvo[0] + ' aparece em #' + posDe(alvo[0]) +
              ' e é #' + noEstado + ' do estado');
          }
          q.value = ''; q.oninput();
          sel.value = ''; sel.onchange();
        }
      }

      // As réguas, em cada estado que a aba oferece. O valor sai do escopo, e
      // as duas têm que aparecer sempre que o escopo for grande o bastante —
      // no Histórico inteiro a mediana caía além do pedaço desenhado e sumia,
      // deixando só a média, que é a leitura que as duas existem para evitar.
      // A lista de estados é remontada por aba: pedir um que não existe nela
      // faz o select cair para "todos" calado, e a conferência vira mentira.
      const selUf = document.getElementById('uf');
      for (const uf of [...selUf.options].map((o) => o.value)) {
        selUf.value = uf;
        if (selUf.value !== uf) { out.probs.push('estado ' + uf + ' sumiu da aba ' + k); continue; }
        selUf.onchange();
        const escopo = idx.map((i) => D.editores[i]).filter((e) => !uf || e[1] === uf);
        const v = escopo.map((e) => e[COL[k]]);
        const ord = v.slice().sort((a, b) => a - b);
        const espera = {
          mediana: ord[Math.floor(ord.length / 2)],
          média: Math.round(v.reduce((s, x) => s + x, 0) / v.length),
        };
        const vistas = {};
        for (const tr of document.querySelectorAll('tr.regua')) {
          const rot = tr.children[1].textContent.trim();
          vistas[rot.split(' ')[0]] = {
            rotulo: rot,
            valor: Number(tr.children[3].textContent.replace(/\./g, '')),
          };
        }
        const onde = uf ? 'aba ' + k + '/' + uf : 'aba ' + k;
        if (v.length < D.cfg.refMin) {
          out.n++;
          if (Object.keys(vistas).length) {
            out.probs.push(onde + ': régua desenhada com só ' + v.length + ' editor(es)');
          }
          continue;
        }
        for (const rot of Object.keys(espera)) {
          out.n++;
          if (!(rot in vistas)) {
            out.probs.push(onde + ': a régua de ' + rot + ' não foi desenhada');
          } else if (vistas[rot].valor !== espera[rot]) {
            out.probs.push(onde + ': ' + rot + ' desenhada ' + vistas[rot].valor +
              ' e o escopo dá ' + espera[rot]);
          } else if (uf && !vistas[rot].rotulo.includes(uf)) {
            out.probs.push(onde + ': rótulo "' + vistas[rot].rotulo + '" não diz de quem fala');
          }
        }
      }
      selUf.value = ''; selUf.onchange();

      // KPIs
      const kpis = [...document.querySelectorAll('.kpi b')].map((x) => x.textContent.trim());
      const R = D.resumo;
      const esperado = D.cfg.semAtividade
        ? [NFtxt(R.historico), NFtxt(R.edicoesTotal)]
        : [NFtxt(R.ativos30), NFtxt(R.edicoes90), NFtxt(R.concKpi) + '%', NFtxt(R.fator1)];
      out.n += esperado.length;
      esperado.forEach((v, i) => {
        if (kpis[i] !== v) out.probs.push('KPI ' + i + ': "' + kpis[i] + '" != "' + v + '"');
      });

      // lixo de geração em qualquer texto visível
      const txt = document.body.innerText;
      ['undefined', 'NaN', '[object Object]', 'null', '${'].forEach((lixo) => {
        out.n++;
        if (txt.includes(lixo)) out.probs.push('a página mostra "' + lixo + '"');
      });
      // célula obrigatória vazia
      out.n++;
      const vazias = trs.filter((tr) => !tr.querySelectorAll('td')[3].textContent.trim()).length;
      if (vazias) out.probs.push(vazias + ' linha(s) com a coluna de edições vazia');
      return out;
    }, aba);

    checks += r.n;
    r.probs.forEach((m) => erro(largura + 'px/' + aba + ': ' + m));
  }
  // --- painéis, uma vez por largura ---------------------------------------
  const pr = await p.evaluate(() => {
    const out = { probs: [], n: 0 };
    const NFtxt = (v) => new Intl.NumberFormat('pt-BR').format(v);
    const pain = (nome) => [...document.querySelectorAll('.painel')]
      .find((e) => e.querySelector('h2') && e.querySelector('h2').textContent.includes(nome));
    const visivel = (el) => el && el.offsetParent !== null;
    const barras = (nome) => {
      const pa = pain(nome);
      return pa ? [...pa.querySelectorAll('.barra')].map((br) => ({
        rot: br.querySelector('span').textContent.trim(),
        val: br.querySelector('.v').textContent.replace(/\s+/g, ' ').trim() })) : null;
    };
    const P = D.paineis;

    // concentração
    const c = barras('Concentra');
    if (c) { P.concentracao.forEach(([n, pc], i) => { out.n += 2;
      if (c[i].rot !== 'top ' + n) out.probs.push('concentração rótulo ' + c[i].rot);
      if (c[i].val !== NFtxt(pc) + '%') out.probs.push('concentração top ' + n + ': "' + c[i].val + '" != ' + NFtxt(pc) + '%'); }); }

    // ritmo semanal
    const s = barras('Ritmo semanal');
    if (s) { P.semana.forEach(([d, v], i) => { out.n += 2;
      if (s[i].rot !== d) out.probs.push('semana rótulo ' + s[i].rot);
      if (s[i].val !== NFtxt(v)) out.probs.push('semana ' + d + ': "' + s[i].val + '" != ' + NFtxt(v)); }); }

    // níveis
    const nv = barras('Nível');
    if (nv) { P.niveis.forEach(([lv, n, viv], i) => { out.n += 2;
      const pct = n ? Math.round(100 * viv / n) : 0;
      if (nv[i].rot !== 'N' + lv) out.probs.push('nível rótulo ' + nv[i].rot);
      if (!nv[i].val.startsWith(pct + '%')) out.probs.push('nível ' + lv + ': "' + nv[i].val + '" != ' + pct + '%'); }); }

    // safras
    const sa = barras('Safras');
    if (sa) { P.entrada.forEach(([ano, n], i) => { out.n += 2;
      if (sa[i].rot !== String(ano)) out.probs.push('safra rótulo ' + sa[i].rot);
      if (!sa[i].val.startsWith(String(n))) out.probs.push('safra ' + ano + ': "' + sa[i].val + '" != ' + n); }); }

    // estados
    const pe = pain('Estados');
    if (pe) { const trs = [...pe.querySelectorAll('tbody tr')];
      out.n++; if (trs.length !== P.estados.length)
        out.probs.push('estados: ' + trs.length + ' linhas, esperado ' + P.estados.length);
      trs.forEach((tr, i) => { const td = tr.querySelectorAll('td'); const r = P.estados[i]; out.n += 3;
        if (td[0].textContent.trim() !== r[0]) out.probs.push('estado ' + i + ': UF ' + td[0].textContent.trim());
        if (td[1].textContent.trim() !== NFtxt(r[1])) out.probs.push('estado ' + r[0] + ': edições');
        const f = [...td].slice(-2)[0];
        if (f && f.textContent.trim() !== String(r[3])) out.probs.push('estado ' + r[0] + ': fator'); }); }

    // gigantes parados
    const pp = pain('Gigantes');
    if (pp) { const trs = [...pp.querySelectorAll('tbody tr')]; out.n++;
      if (trs.length !== P.parados.length) out.probs.push('parados: ' + trs.length + ' != ' + P.parados.length);
      trs.forEach((tr, i) => { out.n++;
        if (!tr.textContent.includes(P.parados[i][0])) out.probs.push('parados linha ' + i); }); }

    // calendário
    const pc2 = pain('Calendário');
    if (pc2) { out.n += 2;
      const q = pc2.querySelectorAll('svg rect[fill-opacity]').length;
      if (q !== P.calendario.length) out.probs.push('calendário: ' + q + ' quadrados, ' + P.calendario.length + ' dias');
      const anel = pc2.querySelectorAll('svg rect[stroke]').length;
      const fora = P.calendario.filter((d) => d[2]).length;
      if (anel !== fora) out.probs.push('calendário: ' + anel + ' anéis, ' + fora + ' fora da curva'); }

    // candidatos
    const pk = pain('caminho');
    if (pk && P.candidatos) { out.n += 2;
      const cols = [...pk.querySelectorAll('.duplo > div')];
      const nProntos = cols[0].querySelectorAll('tbody tr').length;
      const nQuase = cols[1].querySelectorAll('tbody tr').length;
      if (nProntos !== P.candidatos.prontos.length) out.probs.push('candidatos prontos: ' + nProntos);
      if (nQuase !== P.candidatos.quase.length) out.probs.push('candidatos quase: ' + nQuase); }

    // todo painel visível tem título e conteúdo
    [...document.querySelectorAll('.painel')].forEach((pa) => { out.n++;
      if (visivel(pa) && pa.textContent.trim().length < 20)
        out.probs.push('painel vazio: ' + (pa.querySelector('h2') || {}).textContent); });
    return out;
  });
  checks += pr.n;
  pr.probs.forEach((m) => erro(largura + 'px: ' + m));

  if (jsErros.length) erro(largura + 'px: erro de JS — ' + jsErros[0]);
  await ctx.close();
}

await b.close();
console.log('\nconferências no DOM: ' + checks);
console.log(falhas ? falhas + ' FALHA(S)' : 'tudo bate');
process.exit(falhas ? 1 : 0);
