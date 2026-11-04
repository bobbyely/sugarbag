// A small Markdown reader for issue text. Runs in the browser; reads a string, returns HTML. No settings.
// Text is escaped first, so whatever someone writes in an issue stays text.
// shortcut: headings, lists, tables, code, bold and links only, add more when an issue needs them.
(function (root) {
  const esc = s => s.replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  // Only web links, so an issue can't smuggle in javascript:.
  const inline = s => esc(s)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
    .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  const cells = l => l.trim().replace(/^\||\|$/g, "").split("|").map(c => c.trim());
  const listItem = /^\s*(-|\d+\.) /, block = /^(#{1,4} |```|\s*\||\s*(-|\d+\.) )/;

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
        for (; listItem.test(lines[i] || ""); i++) items.push(`<li>${inline(lines[i].replace(listItem, ""))}</li>`);
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
