const assert = require("assert");
const MD = require("../md.js");
let n = 0;
function t(name, fn) { fn(); n++; }

t("escapa HTML cru e scripts", () => {
  const h = MD.render('<script>alert(1)</script> <img src=x onerror=alert(1)>');
  assert(!h.includes("<script"), h);
  assert(!h.includes("<img"), h);
  assert(h.includes("&lt;script&gt;"));
});
t("links só http(s)", () => {
  assert(MD.render("[ok](https://a.com/x?y=1&z=2)").includes('href="https://a.com/x?y=1&amp;z=2"'));
  const bad = MD.render("[x](javascript:alert(1))");
  assert(!bad.includes("href"), bad);
  assert(!MD.render("[x](data:text/html,<b>)").includes("href"));
  assert(!MD.render('[x](https://a.com" onclick="alert(1))').includes("onclick=\"alert"), "aspas escapadas");
});
t("link automático", () => {
  const h = MD.render("veja https://github.com/guilherme, ok");
  assert(h.includes('href="https://github.com/guilherme"'), h);
});
t("negrito, itálico, riscado, código", () => {
  const h = MD.render("**a** *b* ~~c~~ `d <x>`");
  assert(h.includes("<strong>a</strong>") && h.includes("<em>b</em>") && h.includes("<del>c</del>"));
  assert(h.includes("<code>d &lt;x&gt;</code>"));
});
t("código não interpreta markdown dentro", () => {
  const h = MD.render("`**x**`");
  assert(h.includes("<code>**x**</code>"), h);
});
t("bloco de código com linguagem e escape", () => {
  const h = MD.render("```python\nprint('<oi>')\n```");
  assert(h.includes('class="codeblock"') && h.includes("python") && h.includes("&lt;oi&gt;"), h);
});
t("bloco de código sem fechar (streaming)", () => {
  const h = MD.render("antes\n```js\nconst a = 1;");
  assert(h.includes("const a = 1;") && h.includes("codeblock"), h);
});
t("tabela com alinhamento", () => {
  const h = MD.render("| Item | Valor |\n|:--|--:|\n| luz | R$ 10 |\n| água | **5** |");
  assert(h.includes("<table>") && h.includes("<th>Item</th>") || h.includes('<th style="text-align:left">Item</th>'), h);
  assert(h.includes('style="text-align:right">R$ 10</td>'), h);
  assert(h.includes("<strong>5</strong>"));
});
t("tabela sem pipes nas pontas", () => {
  const h = MD.render("a | b\n--- | ---\n1 | 2");
  assert(h.includes("<table>") && h.includes("<td>2</td>"), h);
});
t("listas simples e numeradas", () => {
  const h = MD.render("- um\n- dois\n\n1. a\n2. b");
  assert(h.includes("<ul><li>um</li><li>dois</li></ul>"), h);
  assert(h.includes("<ol><li>a</li><li>b</li></ol>"), h);
});
t("lista aninhada", () => {
  const h = MD.render("- pai\n  - filho\n- outro");
  assert(h.includes("<li>pai<ul><li>filho</li></ul></li>"), h);
});
t("títulos, citação e linha", () => {
  const h = MD.render("# T1\n## T2\n> citado\n\n---");
  assert(h.includes("<h2>T1</h2>") && h.includes("<h3>T2</h3>") && h.includes("<blockquote>") && h.includes("<hr>"), h);
});
t("parágrafos e quebras de linha", () => {
  const h = MD.render("linha 1\nlinha 2\n\nnovo");
  assert(h.includes("<p>linha 1<br>linha 2</p>") && h.includes("<p>novo</p>"), h);
});
t("texto vazio e nulo", () => {
  assert.strictEqual(MD.render(""), "");
  assert.strictEqual(MD.render(null), "");
});
t("underscores no meio de palavras não viram itálico", () => {
  const h = MD.render("snake_case_name e 2*3*4");
  assert(!h.includes("<em>snake"), h);
});
t("texto para voz", () => {
  const p = MD.plain("# Título\n**Olá** `x` [site](https://a.com)\n```js\ncode\n```\n- item");
  assert(!/[*#`\[\]]/.test(p) && p.includes("Olá") && p.includes("site") && p.includes("trecho de código"), p);
});
console.log(n + " testes de markdown ok");
