/* Paste-parsing for the studio's data panel.
 *
 * It lives in its own file so the parser can be run by a test: the studio app is one 14k-line IIFE
 * whose scope a harness cannot enter, and this is the one piece of it that turns untrusted text into
 * the table every chart is drawn from — worth measuring directly.
 *
 * Quoting follows RFC 4180. The lookup it replaced said `line.split(delim)`, so a quoted field
 * containing the delimiter was cut in half ("Beijing, China" became two cells) and every column
 * after it shifted by one: the pasted table loaded with each value under its neighbour's header and
 * nothing said so, because the grid still looked plausible. A doubled quote inside a quoted field is
 * one literal quote.
 */
(function (root) {
    'use strict';

    function delimiterOf(headerLine) {
        if (headerLine.includes('\t')) return '\t';
        if (headerLine.includes(',')) return ',';
        if (headerLine.includes(';')) return ';';
        if (/\s{2,}/.test(headerLine)) return 'whitespace';
        return ' ';
    }

    /* One line, split on `delim`, honouring quotes. Quoting only means anything for a character
       delimiter: the "two or more spaces" shape has no quote character to honour. */
    function splitLine(line, delim) {
        if (delim === 'whitespace') return line.trim().split(/\s{2,}/);
        var out = [];
        var cell = '';
        var quoted = false;
        for (var i = 0; i < line.length; i += 1) {
            var ch = line.charAt(i);
            if (quoted) {
                if (ch === '"') {
                    if (line.charAt(i + 1) === '"') {
                        cell += '"';
                        i += 1;
                    } else {
                        quoted = false;
                    }
                } else {
                    cell += ch;
                }
            } else if (ch === '"' && cell.trim() === '') {
                quoted = true;
                cell = '';
            } else if (ch === delim) {
                out.push(cell.trim());
                cell = '';
            } else {
                cell += ch;
            }
        }
        out.push(cell.trim());
        return out;
    }

    function textData(raw) {
        var lines = String(raw == null ? '' : raw)
            .split(/\r?\n/)
            .filter(function (line) {
                return line.trim();
            });
        if (!lines.length) return { headers: [], rows: [] };
        var delim = delimiterOf(lines[0]);
        var headers = splitLine(lines[0], delim);
        var rows = lines.slice(1).map(function (line) {
            return splitLine(line, delim);
        });
        var max = headers.length;
        rows.forEach(function (row) {
            if (row.length > max) max = row.length;
        });
        while (headers.length < max) headers.push('列' + (headers.length + 1));
        rows = rows.map(function (row) {
            while (row.length < max) row.push('');
            return row;
        });
        return { headers: headers, rows: rows };
    }

    root.ZenvizParse = { textData: textData, delimiterOf: delimiterOf, splitLine: splitLine };
})(typeof window !== 'undefined' ? window : globalThis);
