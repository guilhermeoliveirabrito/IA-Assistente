/* Renderizador de Markdown pequeno e seguro (sem bibliotecas).
   Todo texto é escapado ANTES de virar HTML; links só aceitam http(s); não existe HTML cru. */
(function (root) {
  "use strict";

  function esc(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function safeUrl(u) {
    u = String(u).trim();
    return /^https?:\/\//i.test(u) ? u : null;
  }

  // inline: `código`, **negrito**, *itálico*, ~~riscado~~, [texto](url), <https://auto>
  function inline(text) {
    const codes = [];
    let s = text.replace(/`([^`\n]+)`/g, function (_, c) {
      codes.push(c);
      return "\u0000" + (codes.length - 1) + "\u0000";
    });
    s = esc(s);
    s = s.replace(/\[([^\]\n]+)\]\(([^)\s]+)\)/g, function (m, label, url) {
      const u = safeUrl(url.replace(/&amp;/g, "&"));
      return u ? '<a href="' + esc(u) + '" target="_blank" rel="noopener noreferrer">' + label + "</a>" : m;
    });
    s = s.replace(/(^|[\s(])(https?:\/\/[^\s<)]+[^\s<).,;:!?])/g, function (m, pre, url) {
      const u = safeUrl(url.replace(/&amp;/g, "&"));
      return u ? pre + '<a href="' + esc(u) + '" target="_blank" rel="noopener noreferrer">' + url + "</a>" : m;
    });
    s = s.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
    s = s.replace(/(^|[^*\w])\*([^*\n]+)\*(?![*\w])/g, "$1<em>$2</em>");
    s = s.replace(/(^|[^_\w])_([^_\n]+)_(?![_\w])/g, "$1<em>$2</em>");
    s = s.replace(/~~([^~\n]+)~~/g, "<del>$1</del>");
    return s.replace(/\u0000(\d+)\u0000/g, function (_, i) {
      return "<code>" + esc(codes[+i]) + "</code>";
    });
  }

  function splitRow(line) {
    let t = line.trim();
    if (t.startsWith("|")) t = t.slice(1);
    if (t.endsWith("|") && !t.endsWith("\\|")) t = t.slice(0, -1);
    return t.split(/(?<!\\)\|/).map(function (c) { return c.trim().replace(/\\\|/g, "|"); });
  }

  function isTableSep(line) {
    return /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(line) && line.indexOf("-") !== -1 && line.indexOf("|") !== -1;
  }

  function render(src) {
    const lines = String(src || "").replace(/\r\n?/g, "\n").split("\n");
    const out = [];
    let i = 0;

    function listBlock(startIdx) {
      // lista simples/aninhada por indentação
      const items = [];
      let j = startIdx;
      const re = /^(\s*)([-*+]|\d{1,3}[.)])\s+(.*)$/;
      while (j < lines.length) {
        const m = re.exec(lines[j]);
        if (!m) {
          if (lines[j].trim() === "" ) {
            // linha em branco: continua só se a próxima também for item
            if (j + 1 < lines.length && re.test(lines[j + 1])) { j++; continue; }
          }
          break;
        }
        const item = { indent: m[1].replace(/\t/g, "    ").length, ordered: /\d/.test(m[2]), text: m[3] };
        // trocar de lista (marcadores <-> números) no mesmo nível começa outro bloco
        if (items.length && item.indent === items[0].indent && item.ordered !== items[0].ordered) break;
        items.push(item);
        j++;
      }
      function build(from, level) {
        let html = "", k = from;
        const base = items[from].indent;
        const tag = items[from].ordered ? "ol" : "ul";
        html += "<" + tag + ">";
        while (k < items.length && items[k].indent >= base) {
          if (items[k].indent > base) {
            const sub = build(k, level + 1);
            html = html.replace(/<\/li>$/, sub.html + "</li>");
            k = sub.next;
            continue;
          }
          html += "<li>" + inline(items[k].text) + "</li>";
          k++;
        }
        return { html: html + "</" + tag + ">", next: k };
      }
      return { html: build(0, 0).html, next: j };
    }

    while (i < lines.length) {
      const line = lines[i];

      const fence = /^\s*(```+|~~~+)\s*([\w+#.-]*)\s*$/.exec(line);
      if (fence) {
        const marker = fence[1][0];
        const buf = [];
        i++;
        while (i < lines.length && !new RegExp("^\\s*" + marker + "{3,}\\s*$").test(lines[i])) { buf.push(lines[i]); i++; }
        i++; // fecha (ou fim do texto, durante streaming)
        const lang = fence[2] ? '<span class="code-lang">' + esc(fence[2]) + "</span>" : '<span class="code-lang"></span>';
        out.push('<div class="codeblock"><div class="code-head">' + lang +
          '<button type="button" class="code-copy" aria-label="Copiar código">Copiar</button></div><pre><code>' +
          esc(buf.join("\n")) + "</code></pre></div>");
        continue;
      }

      if (line.trim() === "") { i++; continue; }

      const heading = /^(#{1,4})\s+(.*?)\s*#*\s*$/.exec(line);
      if (heading) {
        out.push("<h" + (heading[1].length + 1) + ">" + inline(heading[2]) + "</h" + (heading[1].length + 1) + ">");
        i++;
        continue;
      }

      if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) { out.push("<hr>"); i++; continue; }

      if (line.indexOf("|") !== -1 && i + 1 < lines.length && isTableSep(lines[i + 1])) {
        const head = splitRow(line);
        const aligns = splitRow(lines[i + 1]).map(function (c) {
          return /^:-+:$/.test(c) ? "center" : /-+:$/.test(c) ? "right" : /^:-+/.test(c) ? "left" : "";
        });
        i += 2;
        const rows = [];
        while (i < lines.length && lines[i].trim() !== "" && lines[i].indexOf("|") !== -1) { rows.push(splitRow(lines[i])); i++; }
        const cell = function (tag, text, idx) {
          const a = aligns[idx] ? ' style="text-align:' + aligns[idx] + '"' : "";
          return "<" + tag + a + ">" + inline(text) + "</" + tag + ">";
        };
        let t = '<div class="table-wrap"><table><thead><tr>' + head.map(function (c, k) { return cell("th", c, k); }).join("") + "</tr></thead><tbody>";
        rows.forEach(function (r) {
          t += "<tr>" + head.map(function (_, k) { return cell("td", r[k] || "", k); }).join("") + "</tr>";
        });
        out.push(t + "</tbody></table></div>");
        continue;
      }

      if (/^\s*>/.test(line)) {
        const buf = [];
        while (i < lines.length && /^\s*>/.test(lines[i])) { buf.push(lines[i].replace(/^\s*>\s?/, "")); i++; }
        out.push("<blockquote>" + render(buf.join("\n")) + "</blockquote>");
        continue;
      }

      if (/^\s*([-*+]|\d{1,3}[.)])\s+/.test(line)) {
        const res = listBlock(i);
        out.push(res.html);
        i = res.next;
        continue;
      }

      // parágrafo: junta linhas até uma linha em branco ou um novo bloco
      const buf = [];
      while (i < lines.length && lines[i].trim() !== "" && !/^\s*(```|~~~|#{1,4}\s|>|([-*+]|\d{1,3}[.)])\s)/.test(lines[i]) &&
             !(lines[i].indexOf("|") !== -1 && i + 1 < lines.length && isTableSep(lines[i + 1])) &&
             !/^\s*([-*_])(\s*\1){2,}\s*$/.test(lines[i])) {
        buf.push(lines[i]);
        i++;
      }
      if (!buf.length) { buf.push(lines[i]); i++; }
      out.push("<p>" + buf.map(inline).join("<br>") + "</p>");
    }
    return out.join("\n");
  }

  // texto limpo para a voz (sem marcações)
  function plain(src) {
    return String(src || "")
      .replace(/```[\s\S]*?```/g, " (trecho de código) ")
      .replace(/`([^`]+)`/g, "$1")
      .replace(/!?\[([^\]]*)\]\([^)]*\)/g, "$1")
      .replace(/^\s*\|?[\s:|-]{3,}\|?\s*$/gm, "")
      .replace(/\|/g, ", ")
      .replace(/^\s{0,3}#{1,6}\s*/gm, "")
      .replace(/(\*\*|__|\*|_|~~)/g, "")
      .replace(/^\s*[-*+]\s+/gm, "")
      .replace(/https?:\/\/\S+/g, " link ")
      .replace(/\s+\n/g, "\n")
      .trim();
  }

  const api = { render: render, plain: plain, esc: esc };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.MD = api;
})(typeof window !== "undefined" ? window : globalThis);
