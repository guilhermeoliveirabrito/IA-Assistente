/* Tema e tamanho do texto: lidos antes de a página aparecer (sem piscar). Guardados só neste navegador. */
(function () {
  "use strict";
  var THEMES = { dark: "#1f1e1d", light: "#f7f5f1", auto: "" };
  var SIZES = { s: "14px", m: "15px", l: "17px", xl: "19px" };
  function get(k, d) { try { return localStorage.getItem(k) || d; } catch (e) { return d; } }
  function set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* sem armazenamento */ } }
  function apply() {
    var theme = get("theme", "dark"), size = get("fontsize", "m"), root = document.documentElement;
    if (!(theme in THEMES)) theme = "dark";
    root.setAttribute("data-theme", theme);
    root.style.setProperty("--fs", SIZES[size] || SIZES.m);
    var light = theme === "light" || (theme === "auto" && window.matchMedia && matchMedia("(prefers-color-scheme: light)").matches);
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", light ? THEMES.light : THEMES.dark);
  }
  window.Theme = {
    get: function () { return { theme: get("theme", "dark"), size: get("fontsize", "m") }; },
    set: function (o) { if (o.theme) set("theme", o.theme); if (o.size) set("fontsize", o.size); apply(); },
  };
  apply();
  if (window.matchMedia) { try { matchMedia("(prefers-color-scheme: light)").addEventListener("change", apply); } catch (e) { /* navegador antigo */ } }
})();
