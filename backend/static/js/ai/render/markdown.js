/* Model text into elements: the escape, the small Markdown subset, tables and inline spans.
 *
 * Everything is escaped FIRST, then the subset is rebuilt; raw HTML never survives and a link is
 * limited to http/https. `AIRender` is declared here (the first render script) and extended by the
 * three card modules with `Object.assign(AIRender, ...)`.
 */

const AIRender = {};

Object.assign(AIRender, {
    escape(value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    },

    safeUrl(value) {
        const raw = String(value || '').trim();
        return /^https?:\/\//i.test(raw) ? raw : '';
    },

    inline(text) {
        /* Links are lifted out BEFORE escaping. Escaping first turned a URL's ``&`` into ``&amp;``
           and the link pass then escaped it again, so ``?a=1&b=2`` became ``?a=1&amp;amp;b=2`` and
           every link with a query string opened the wrong address. The placeholders survive the
           escape and the emphasis passes; the anchors are inserted last. */
        const anchors = [];
        const linked = String(text == null ? '' : text).replace(
            /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
            (match, label, url) => {
                const safe = this.safeUrl(url);
                if (!safe) return match;
                const token = '\u0000LINK' + anchors.length + '\u0000';
                anchors.push(
                    '<a href="' + this.escape(safe) + '" target="_blank" rel="noopener noreferrer">' +
                        this.escape(label) + '</a>'
                );
                return token;
            }
        );
        let out = this.escape(linked);
        out = out.replace(/`([^`]+)`/g, '<code>$1</code>');
        out = out.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
        out = out.replace(/(^|[^*])\*([^*]+)\*/g, '$1<em>$2</em>');
        out = out.replace(/\u0000LINK(\d+)\u0000/g, (match, index) => anchors[Number(index)] || '');
        return out;
    },

    /* Split one table row into cells. Two things are NOT column breaks:
       - a `|` inside inline code (`` `a|b` ``), which a model writes all the time when naming a
         pipe-joined value;
       - an escaped `\|`, Markdown's own way to keep a literal pipe in a cell.
       Without this, one cell became two and the rest of the row shifted. */
    tableCells(line) {
        const body = String(line || '').slice(1, -1);
        const cells = [];
        let current = '';
        let inCode = false;
        for (let index = 0; index < body.length; index += 1) {
            const ch = body[index];
            if (ch === '\\' && body[index + 1] === '|') {
                current += '|';
                index += 1;
                continue;
            }
            if (ch === '`') {
                inCode = !inCode;
                current += ch;
                continue;
            }
            if (ch === '|' && !inCode) {
                cells.push(current.trim());
                current = '';
                continue;
            }
            current += ch;
        }
        cells.push(current.trim());
        return cells;
    },

    markdown(text) {
        const source = String(text || '');
        const parts = [];
        let buffer = [];
        let inCode = false;
        let code = [];
        const flush = () => {
            if (buffer.length) {
                parts.push(this.paragraphs(buffer.join('\n')));
                buffer = [];
            }
        };
        for (const line of source.split(/\r?\n/)) {
            if (line.trim().startsWith('```')) {
                if (inCode) {
                    parts.push('<pre class="ai-code"><code>' + this.escape(code.join('\n')) + '</code></pre>');
                    code = [];
                    inCode = false;
                } else {
                    flush();
                    inCode = true;
                }
                continue;
            }
            if (inCode) {
                code.push(line);
            } else {
                buffer.push(line);
            }
        }
        if (inCode) parts.push('<pre class="ai-code"><code>' + this.escape(code.join('\n')) + '</code></pre>');
        flush();
        return parts.join('');
    },

    paragraphs(text) {
        const lines = text.split(/\r?\n/);
        const out = [];
        let list = null;
        let table = null;
        const closeList = () => {
            if (list) {
                out.push('<' + list.tag + '>' + list.items.map((item) => '<li>' + this.inline(item) + '</li>').join('') + '</' + list.tag + '>');
                list = null;
            }
        };
        const closeTable = () => {
            if (table) {
                /* A table is RECTANGULAR: a row with one cell too few/too many used to shift every
                   following column. Rows are padded/trimmed to the header's width. */
                const width = table.head.length;
                const head = '<thead><tr>' + table.head.map((cell) => '<th>' + this.inline(cell) + '</th>').join('') + '</tr></thead>';
                const body = '<tbody>' + table.rows
                    .map((row) => {
                        const cells = row.slice(0, width);
                        while (cells.length < width) cells.push('');
                        return '<tr>' + cells.map((cell) => '<td>' + this.inline(cell) + '</td>').join('') + '</tr>';
                    })
                    .join('') + '</tbody>';
                out.push('<div class="ai-table-wrap"><table class="ai-table">' + head + body + '</table></div>');
                table = null;
            }
        };
        for (const line of lines) {
            const trimmed = line.trim();
            if (!trimmed) {
                closeList();
                closeTable();
                continue;
            }
            if (trimmed.startsWith('|') && trimmed.endsWith('|')) {
                closeList();
                const cells = this.tableCells(trimmed);
                if (cells.every((cell) => /^:?-{2,}:?$/.test(cell))) continue;
                if (!table) table = { head: cells, rows: [] };
                else table.rows.push(cells);
                continue;
            }
            closeTable();
            const heading = /^(#{1,4})\s+(.*)$/.exec(trimmed);
            if (heading) {
                closeList();
                const level = Math.min(4, heading[1].length);
                out.push('<h' + level + '>' + this.inline(heading[2]) + '</h' + level + '>');
                continue;
            }
            if (/^>\s?/.test(trimmed)) {
                closeList();
                out.push('<blockquote>' + this.inline(trimmed.replace(/^>\s?/, '')) + '</blockquote>');
                continue;
            }
            const ordered = /^\d+[.)]\s+(.*)$/.exec(trimmed);
            const bullet = /^[-*+]\s+(.*)$/.exec(trimmed);
            if (ordered || bullet) {
                closeTable();
                const tag = ordered ? 'ol' : 'ul';
                if (!list || list.tag !== tag) {
                    closeList();
                    list = { tag, items: [] };
                }
                list.items.push((ordered || bullet)[1]);
                continue;
            }
            closeList();
            out.push('<p>' + this.inline(trimmed) + '</p>');
        }
        closeList();
        closeTable();
        return out.join('');
    },

    /* The exact act behind an approval question: resolved target facts and, for a write, the diff
       the user is being asked to allow. The server supplies every key; this only paints it. */
    number(value) {
        return Number(value || 0).toLocaleString();
    },
});

window.AIRender = AIRender;
