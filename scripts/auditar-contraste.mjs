// Contraste WCAG do texto realmente pintado.
// Compõe as camadas: fundo semitransparente (a linha par usa color-mix com
// transparent) precisa ser mesclado com o que está atrás, e a opacidade
// herdada precisa ser aplicada à cor do texto. Sem isso o medidor inventa
// falha — chegou a acusar nome preto sobre branco com 1,28:1.
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
let ruins = 0, medidos = 0;

for (const tema of ['light', 'dark']) {
  const ctx = await b.newContext({ colorScheme: tema, viewport: { width: 1400, height: 1200 } });
  const p = await ctx.newPage();
  await p.goto(alvo);
  await p.waitForTimeout(700);

  const r = await p.evaluate(() => {
    // Chromium devolve color-mix como `color(srgb 0.93 0.95 0.97 / 0.45)`, com
    // componentes de 0 a 1, e o resto como rgb()/rgba() de 0 a 255. Ler os dois
    // com a mesma escala é o que fazia o medidor acusar texto preto sobre
    // branco a 1,3:1.
    const cor = (s) => {
      s = s || '';
      const m = s.match(/[\d.]+/g);
      if (!m) return null;
      const esc = s.startsWith('color(') ? 255 : 1;
      return { r: +m[0] * esc, g: +m[1] * esc, b: +m[2] * esc,
               a: m.length > 3 ? +m[3] : 1 };
    };
    const sobre = (f, t) => ({            // f sobre t
      r: f.a * f.r + (1 - f.a) * t.r,
      g: f.a * f.g + (1 - f.a) * t.g,
      b: f.a * f.b + (1 - f.a) * t.b, a: 1 });
    const lum = (c) => {
      const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
      return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b);
    };

    // fundo efetivo: empilha do elemento até a raiz, compondo alfa
    const fundoDe = (el) => {
      const pilha = [];
      for (let n = el; n; n = n.parentElement) {
        const c = cor(getComputedStyle(n).backgroundColor);
        if (c && c.a > 0) { pilha.push(c); if (c.a === 1) break; }
      }
      let base = { r: 255, g: 255, b: 255, a: 1 };
      for (let i = pilha.length - 1; i >= 0; i--) base = sobre(pilha[i], base);
      return base;
    };

    const out = [];
    const visto = new Set();
    const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    for (let n = w.nextNode(); n; n = w.nextNode()) {
      const t = n.nodeValue.trim();
      if (!t) continue;
      const el = n.parentElement;
      if (!el || el.offsetParent === null || el.closest('script,style,svg')) continue;
      const cs = getComputedStyle(el);
      let op = 1;
      for (let x = el; x; x = x.parentElement) op *= parseFloat(getComputedStyle(x).opacity || 1);
      const bg = fundoDe(el);
      let c = cor(cs.color);
      if (!c) continue;
      c = sobre({ ...c, a: c.a * op }, bg);   // opacidade e alfa do texto sobre o fundo
      const L1 = lum(c), L2 = lum(bg);
      const cr = (Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05);
      const px = parseFloat(cs.fontSize);
      const grande = px >= 24 || (px >= 18.66 && +cs.fontWeight >= 700);
      const min = grande ? 3 : 4.5;
      const k = cs.color + '|' + JSON.stringify(bg) + '|' + px + '|' + cs.fontWeight + '|' + op.toFixed(2);
      if (visto.has(k)) continue;
      visto.add(k);
      const hx = (o) => '#' + [o.r, o.g, o.b].map((v) =>
        Math.round(v).toString(16).padStart(2, '0')).join('');
      out.push({ cr, min, px, op, ok: cr >= min, fg: hx(c), bg: hx(bg),
                 onde: (el.className || el.tagName) + ' < ' + (el.parentElement.className || el.parentElement.tagName),
                 ex: t.slice(0, 26) });
    }
    return out;
  });

  medidos += r.length;
  const maus = r.filter((x) => !x.ok);
  console.log('\n=== tema ' + tema + ' — ' + r.length + ' combinações distintas ===');
  if (!maus.length) console.log('  todas passam na WCAG AA');
  for (const m of maus) {
    ruins++;
    console.log('  ' + m.cr.toFixed(2) + ':1 (min ' + m.min + ')  ' + m.px + 'px op=' +
                m.op.toFixed(2) + '  ' + m.fg + ' sobre ' + m.bg + '  ' + m.onde +
                '  "' + m.ex + '"');
  }
  await ctx.close();
}

await b.close();
console.log('\n' + medidos + ' combinações medidas, ' + ruins + ' abaixo do mínimo');
process.exit(ruins ? 1 : 0);
