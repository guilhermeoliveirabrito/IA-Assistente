/* Tema e tamanho do texto: lidos antes de a página aparecer (sem piscar). Guardados só neste navegador. */
(function () {
  "use strict";
  var THEMES = { dark: "#1f1e1d", light: "#f7f5f1", auto: "" };
  var SIZES = { s: "14px", m: "15px", l: "17px", xl: "19px" };
  function get(k, d) { try { return localStorage.getItem(k) || d; } catch (e) { return d; } }
  function set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* sem armazenamento */ } }
  // cor de destaque: [escuro: destaque, hover, texto sobre ele] [claro: idem]. "laranja" é o padrão do CSS.
  var ACCENTS = {
    laranja: { name: "Laranja", sw: "#d08a62" },
    azul: { name: "Azul", sw: "#6ea8e6", d: ["#6ea8e6", "#86b8ee", "#0f1a26"], l: ["#1f63b8", "#2a73cf", "#ffffff"] },
    verde: { name: "Verde", sw: "#6fbf8a", d: ["#6fbf8a", "#85cd9f", "#0f2016"], l: ["#2a7a3b", "#338d47", "#ffffff"] },
    roxo: { name: "Roxo", sw: "#a58bea", d: ["#a58bea", "#b79df0", "#1a1230"], l: ["#6b4bc4", "#7a5cd3", "#ffffff"] },
    rosa: { name: "Rosa", sw: "#e68cb0", d: ["#e68cb0", "#ee9fc0", "#2a0f1b"], l: ["#b83a74", "#c84a85", "#ffffff"] },
    ciano: { name: "Ciano", sw: "#5ec4cf", d: ["#5ec4cf", "#76d0da", "#0c2326"], l: ["#17737d", "#1e8591", "#ffffff"] },
  };
  function rgba(hex, a) { var n = parseInt(hex.slice(1), 16); return "rgba(" + (n >> 16) + "," + ((n >> 8) & 255) + "," + (n & 255) + "," + a + ")"; }
  function applyAccent(root, light) {
    var a = ACCENTS[get("accent", "laranja")], names = ["--accent", "--accent-hover", "--accent-ink", "--accent-soft"];
    if (!a || !a.d) { names.forEach(function (n) { root.style.removeProperty(n); }); return; }
    var c = light ? a.l : a.d;
    root.style.setProperty("--accent", c[0]); root.style.setProperty("--accent-hover", c[1]); root.style.setProperty("--accent-ink", c[2]);
    root.style.setProperty("--accent-soft", rgba(c[0], light ? 0.12 : 0.14));
  }
  function apply() {
    var theme = get("theme", "dark"), size = get("fontsize", "m"), root = document.documentElement;
    if (!(theme in THEMES)) theme = "dark";
    root.setAttribute("data-theme", theme);
    root.style.setProperty("--fs", SIZES[size] || SIZES.m);
    var light = theme === "light" || (theme === "auto" && window.matchMedia && matchMedia("(prefers-color-scheme: light)").matches);
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", light ? THEMES.light : THEMES.dark);
    applyAccent(root, light);
  }
  window.Theme = {
    get: function () { return { theme: get("theme", "dark"), size: get("fontsize", "m"), accent: get("accent", "laranja") }; },
    set: function (o) { if (o.theme) set("theme", o.theme); if (o.size) set("fontsize", o.size); if (o.accent) set("accent", o.accent); apply(); },
    accents: ACCENTS,
  };
  apply();
  if (window.matchMedia) { try { matchMedia("(prefers-color-scheme: light)").addEventListener("change", apply); } catch (e) { /* navegador antigo */ } }
})();
