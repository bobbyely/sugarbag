// A small Markdown reader for issue text. Runs in the browser; reads a string, returns HTML. No settings.
// Text is escaped first, so whatever someone writes in an issue stays text.
// shortcut: headings, lists, tick boxes, tables, code, bold, strikethrough and links only, add more when an issue needs them.
(function (root) {
  const esc = s => s.replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  // Only web links, so an issue can't smuggle in javascript:. Neither part may hold a "[" (bar an IPv6 host like [::1]): each try stops at the next one,
  // so a line of unclosed brackets is read once, not once per bracket (which froze the page on 100,000 of them).
  const inline = s => esc(s)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
    .replace(/~~([^~]+)~~/g, "<s>$1</s>")
    .replace(/\[([^[\]]+)\]\((https?:\/\/(?:\[[0-9A-Fa-f:.]+\][^)\s[]*|[^)\s[]+))\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  root.mdInline = inline;  // for one-line titles
  const cells = l => l.trim().replace(/^\||\|$/g, "").split("|").map(c => c.trim());
  const listItem = /^\s*(-|\d+\.) /, block = /^(#{1,4} |```|\s*\||\s*(-|\d+\.) )/;

  // Tick boxes show what's done. They aren't controls, so they're drawn as marks rather than inputs.
  const listLine = s => {
    const box = /^\[( |x)\] (.*)/i.exec(s);
    if (!box) return `<li>${inline(s)}</li>`;
    const done = box[1] !== " ";
    return `<li class="tick${done ? " ticked" : ""}"><span aria-label="${done ? "Done" : "Not done"}">${done ? "☑" : "☐"}</span>${inline(box[2])}</li>`;
  };

  root.mdToHtml = function (text) {
    const lines = text.split("\n"), out = [];
    for (let i = 0; i < lines.length;) {
      const l = lines[i];
      let m;
      if (l.startsWith("```")) {
        const code = [];
        for (i++; i < lines.length && !lines[i].startsWith("```"); i++) code.push(lines[i]);
        i++;
        out.push(`<pre><code>${esc(code.join("\n"))}</code></pre>`);
      } else if ((m = /^(#{1,4}) (.*)/.exec(l))) {
        const level = Math.min(m[1].length + 2, 6);  // the issue's own title is the top heading
        out.push(`<h${level}>${inline(m[2])}</h${level}>`); i++;
      } else if (/^\s*\|/.test(l) && /^\s*\|[\s:|-]+\|\s*$/.test(lines[i + 1] || "")) {
        const head = cells(l).map(c => `<th>${inline(c)}</th>`).join(""), rows = [];
        for (i += 2; /^\s*\|/.test(lines[i] || ""); i++) rows.push(`<tr>${cells(lines[i]).map(c => `<td>${inline(c)}</td>`).join("")}</tr>`);
        out.push(`<div class="scroll"><table><thead><tr>${head}</tr></thead><tbody>${rows.join("")}</tbody></table></div>`);
      } else if (listItem.test(l)) {
        const tag = /^\s*-/.test(l) ? "ul" : "ol", items = [];
        for (; listItem.test(lines[i] || ""); i++) items.push(listLine(lines[i].replace(listItem, "")));
        out.push(`<${tag}>${items.join("")}</${tag}>`);
      } else if (!l.trim()) {
        i++;
      } else {
        const para = [];
        for (; (lines[i] || "").trim() && !block.test(lines[i]); i++) para.push(lines[i]);
        if (!para.length) { para.push(lines[i]); i++; }
        out.push(`<p>${inline(para.join(" "))}</p>`);
      }
    }
    return out.join("\n");
  };
})(globalThis);
