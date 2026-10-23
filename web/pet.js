/* Gatinho 2D do assistente: um mascote pequeno que reage ao que o app está fazendo.
   Desenho próprio em SVG + animações em CSS (pet.css). Estados:
   idle (parado), sleeping (dorme depois de um tempo parado), thinking, working (usando ferramentas),
   listening (ouvindo você), happy (terminou), sad (deu erro), parcel (novidade numa encomenda). */
(function () {
  "use strict";
  const A = window.A, S = A.S, h = A.h;

  const SVG = `
<svg class="cat-svg" viewBox="0 0 120 130" role="presentation" aria-hidden="true" focusable="false">
  <g class="tail-wrap"><path class="tail" d="M84 108 C 112 108, 116 80, 100 70" /></g>
  <g class="body-wrap">
    <path class="fur" d="M60 62 C34 62 26 100 32 114 C36 123 84 123 88 114 C94 100 86 62 60 62 Z"/>
    <ellipse class="belly" cx="60" cy="102" rx="16" ry="17"/>
    <path class="stripe" d="M36 84 H44 M35 94 H43 M84 84 H76 M85 94 H77"/>
    <ellipse class="foot" cx="40" cy="118" rx="12" ry="6"/>
    <ellipse class="foot" cx="80" cy="118" rx="12" ry="6"/>
  </g>
  <g class="monitor">
    <rect class="mon-stand" x="99" y="92" width="4" height="9"/><rect class="mon-stand" x="92" y="100" width="18" height="3" rx="1.5"/>
    <rect class="mon-frame" x="82" y="58" width="38" height="36" rx="4"/>
    <rect class="mon-screen" x="85" y="61" width="32" height="30" rx="2"/>
    <g class="scr scr-code"><path class="scr-ln scr-ln1" d="M89 67 H103 M93 73 H112 M89 79 H100 M93 85 H108"/><rect class="scr-cur" x="109" y="83" width="3" height="4"/></g>
    <g class="scr scr-mail"><rect class="scr-env" x="90" y="69" width="22" height="15" rx="2"/><path class="scr-env-l" d="M90 70 L101 78 L112 70"/></g>
    <g class="scr scr-music"><path class="scr-note" d="M96 82 V68 L108 66 V79"/><ellipse class="scr-nh" cx="94" cy="82" rx="3.5" ry="2.6"/><ellipse class="scr-nh" cx="106" cy="79" rx="3.5" ry="2.6"/></g>
    <g class="scr scr-mouse"><path class="scr-arrow" d="M92 67 L92 83 L96 79 L99 86 L102 85 L99 78 L105 78 Z"/><circle class="scr-click" cx="92" cy="67" r="4"/></g>
    <g class="scr scr-web"><circle class="scr-globe" cx="101" cy="76" r="11"/><path class="scr-globe" d="M90 76 H112 M101 65 C95 71 95 81 101 87 M101 65 C107 71 107 81 101 87"/></g>
    <g class="scr scr-parcel"><rect class="scr-box" x="91" y="69" width="20" height="16" rx="2"/><path class="scr-boxl" d="M101 69 V85 M91 77 H111"/></g>
    <g class="scr scr-docs"><rect class="scr-doc" x="93" y="64" width="16" height="22" rx="2"/><path class="scr-ln" d="M96 70 H106 M96 75 H106 M96 80 H102"/></g>
  </g>
  <g class="desk">
    <rect class="desk-top" x="10" y="108" width="100" height="7" rx="3"/>
    <rect class="kb" x="30" y="102" width="52" height="8" rx="2"/>
    <g class="keys"><rect class="key k1" x="33" y="104" width="5" height="4" rx="1"/><rect class="key k2" x="40" y="104" width="5" height="4" rx="1"/><rect class="key k3" x="47" y="104" width="5" height="4" rx="1"/><rect class="key k4" x="54" y="104" width="5" height="4" rx="1"/><rect class="key k5" x="61" y="104" width="5" height="4" rx="1"/><rect class="key k6" x="68" y="104" width="5" height="4" rx="1"/><rect class="key k7" x="75" y="104" width="5" height="4" rx="1"/></g>
  </g>
  <ellipse class="paw paw-l" cx="49" cy="112" rx="7.5" ry="8"/>
  <ellipse class="paw paw-r" cx="71" cy="112" rx="7.5" ry="8"/>
  <g class="parcel">
    <rect class="box" x="86" y="98" width="24" height="19" rx="2"/>
    <path class="tape" d="M98 98 V117 M86 106 H110"/>
  </g>
  <g class="head">
    <g class="ear ear-l"><path class="fur" d="M33 36 L34 9 L55 26 Z"/><path class="inner-ear" d="M38 30 L38.5 17 L48 26 Z"/></g>
    <g class="ear ear-r"><path class="fur" d="M87 36 L86 9 L65 26 Z"/><path class="inner-ear" d="M82 30 L81.5 17 L72 26 Z"/></g>
    <ellipse class="fur" cx="60" cy="48" rx="30" ry="25"/>
    <path class="stripe" d="M60 24 V33 M51 25.5 L53.5 33 M69 25.5 L66.5 33"/>
    <circle class="blush" cx="39" cy="57" r="5"/><circle class="blush" cx="81" cy="57" r="5"/>
    <g class="eyes eyes-open">
      <g class="eye"><ellipse class="pupil" cx="48" cy="48" rx="4.4" ry="5.4"/><circle class="shine" cx="46.6" cy="46" r="1.5"/></g>
      <g class="eye"><ellipse class="pupil" cx="72" cy="48" rx="4.4" ry="5.4"/><circle class="shine" cx="70.6" cy="46" r="1.5"/></g>
    </g>
    <path class="eyes eyes-closed" d="M43 49 Q48 54 53 49 M67 49 Q72 54 77 49"/>
    <path class="eyes eyes-happy" d="M43 51 Q48 43 53 51 M67 51 Q72 43 77 51"/>
    <path class="nose" d="M57 55 H63 L60 59 Z"/>
    <path class="mouth mouth-calm" d="M60 59 Q56 64.5 52 61.5 M60 59 Q64 64.5 68 61.5"/>
    <path class="mouth mouth-happy" d="M53 61 Q60 70 67 61 Z"/>
    <path class="mouth mouth-sad" d="M54 64 Q60 59.5 66 64"/>
    <path class="whisker" d="M40 57 L22 53 M40 61 L22 63 M80 57 L98 53 M80 61 L98 63"/>
    <g class="headset">
      <path class="hs-band" d="M31 52 C27 19 93 19 89 52"/>
      <rect class="hs-cup" x="24" y="44" width="10" height="17" rx="4.5"/><rect class="hs-cup" x="86" y="44" width="10" height="17" rx="4.5"/>
      <rect class="hs-ring" x="26.5" y="47" width="5" height="11" rx="2.5"/><rect class="hs-ring" x="88.5" y="47" width="5" height="11" rx="2.5"/>
      <path class="hs-boom" d="M27 60 Q29 74 43 70"/><circle class="hs-mic" cx="44" cy="70" r="3"/>
    </g>
  </g>
  <g class="waves"><path d="M22 36 Q16 46 22 56"/><path d="M14 31 Q6 46 14 61"/><path d="M98 36 Q104 46 98 56"/><path d="M106 31 Q114 46 106 61"/></g>
  <g class="zzz"><text x="88" y="30" class="z z1">z</text><text x="98" y="20" class="z z2">z</text><text x="108" y="10" class="z z3">Z</text></g>
  <path class="heart" d="M60 14 C60 6 48 6 48 14 C48 20 56 24 60 28 C64 24 72 20 72 14 C72 6 60 6 60 14 Z"/>
  <path class="sweat" d="M86 30 Q82 38 86 41 Q90 38 86 30 Z"/>
</svg>`;

  const BUBBLE = {
    idle: "", sleeping: "zzz…", thinking: "Pensando…", working: "Trabalhando nisso…", listening: "Estou ouvindo!",
    happy: "Pronto!", sad: "Ops… deu erro.", parcel: "Novidade na encomenda!", petted: "Purr~",
  };
  const QUIPS = ["Miau!", "Purr~", "Mais carinho?", "Estou aqui!", "Ronrom…", "Precisa de algo?"];
  const SLEEP_AFTER = 120000;          // ms parado até dormir

  const P = { task: "code", running: new Set(), tools: 0, voice: "off", temp: null, tempTimer: 0, last: Date.now(), sleepTimer: 0, state: "idle", pets: 0 };
  const store = (k, v) => { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) { return null; } };

  // o que ele está fazendo decide o que aparece na telinha do computador
  const TASKS = [[/^(resumo_emails|analisar_agenda)$/, "mail"], [/^(spotify|controle_midia)/, "music"], [/^rastreio/, "parcel"],
    [/^(ver_tela|ver_regiao|clicar|digitar|teclas|rolar)$/, "mouse"], [/^(abrir_site|abrir_aplicativo)$/, "web"],
    [/^(ler_arquivo|listar_arquivos|lembrar|ver_memoria|esquecer)$/, "docs"]];
  const taskOf = (name) => { const t = TASKS.find(([re]) => re.test(String(name || ""))); return t ? t[1] : "code"; };

  const prefs = () => ({ on: store("pet") !== "0", name: (store("pet_name") || "Mia").slice(0, 20) });

  function base() {
    if (P.voice === "recording" || P.voice === "listening-cmd") return "listening";
    if (P.running.size) return P.tools > 0 ? "working" : "thinking";
    if (Date.now() - P.last > SLEEP_AFTER) return "sleeping";
    return "idle";
  }

  function compute() { return P.temp || base(); }

  function paint() {
    const st = compute();
    P.state = st;
    const { on, name } = prefs();
    document.querySelectorAll(".pet").forEach((el) => {
      el.classList.toggle("hidden", !on);
      el.dataset.state = st;
      const svg = el.querySelector(".cat-svg");
      if (svg) { svg.dataset.state = st; svg.dataset.task = P.task; }
      const b = el.querySelector(".pet-bubble");
      const txt = st === "petted" ? QUIPS[P.pets % QUIPS.length] : BUBBLE[st] || "";
      if (b) { b.textContent = txt; b.classList.toggle("show", !!txt); }
      el.setAttribute("aria-label", `${name}, o gatinho do assistente: ${txt || "parado, descansando"}`);
    });
  }

  function touch() { P.last = Date.now(); schedule(); }
  function schedule() {
    clearTimeout(P.sleepTimer);
    P.sleepTimer = setTimeout(paint, SLEEP_AFTER + 500);
  }

  function flash(state, ms) {
    P.temp = state;
    clearTimeout(P.tempTimer);
    P.tempTimer = setTimeout(() => { P.temp = null; paint(); }, ms);
    touch();
    paint();
  }

  function onEvent(e) {
    if (!e || !e.type) return;
    switch (e.type) {
      case "start": if (e.conversation_id) P.running.add(e.conversation_id); P.tools = 0; P.err = false; touch(); break;
      case "tool_start": P.tools++; P.task = taskOf(e.name); touch(); break;
      case "tool_end": P.tools = Math.max(0, P.tools - 1); break;
      case "delta": touch(); break;
      case "error": P.running.delete(e.conversation_id); P.tools = 0; P.err = true; flash("sad", 6000); return;
      case "done":
        P.running.delete(e.conversation_id); P.tools = 0;
        if (!P.running.size && !e.stopped && !P.err) { flash("happy", 3500); return; }
        break;
      case "voice": P.voice = (e.voice && e.voice.state) || "off"; if (P.voice === "recording") touch(); break;
      case "toast": if (String(e.text || "").startsWith("📦")) { flash("parcel", 7000); return; } break;
      case "task_update": touch(); break;
      default: return;
    }
    paint();
  }

  function pet(el) {
    P.pets++;
    store("pet_count", String(((Number(store("pet_count")) || 0) + 1)));
    flash("petted", 2200);
  }

  function build(mini) {
    const el = h("div", { class: "pet" + (mini ? " pet-mini" : ""), role: "button", tabindex: "0", title: "Faça carinho", "data-state": "idle",
      onclick: () => pet(el), onkeydown: (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); pet(el); } } },
      h("div", { class: "pet-bubble", "aria-hidden": "true" }), h("div", { class: "pet-art", html: SVG }));
    return el;
  }

  function mount() {
    const side = document.getElementById("pet-slot");
    const top = document.getElementById("pet-slot-mini");
    if (side && !side.firstChild) side.append(build(false));
    if (top && !top.firstChild) top.append(build(true));
    schedule();
    paint();
  }

  function configure({ on, name }) {
    if (on !== undefined) store("pet", on ? "1" : "0");
    if (name !== undefined) store("pet_name", String(name).trim().slice(0, 20) || "Mia");
    paint();
  }

  A.pet = { mount, onEvent, paint, configure, prefs, count: () => Number(store("pet_count")) || 0, state: () => P.state };
})();
