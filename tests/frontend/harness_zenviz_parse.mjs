/* The studio's paste parser, run as the REAL shipped file.
 *
 * `parseTextData` is the one place in the 14k-line studio app that turns untrusted pasted text into
 * the table every chart is drawn from, and it lived inside that page's IIFE where no harness could
 * reach it. It is now `js/zenviz-parse.js` (a standalone module, not a split of a panel — the page
 * loads it before `zenviz-page.js`), so the cases here execute the bytes the browser executes.
 *
 * What the cases pin:
 *
 *   · a QUOTED field containing the delimiter is one cell (RFC 4180). The lookup it replaced said
 *     `line.split(delim)`, so `"Beijing, China"` became two cells and every column after it shifted
 *     by one: the table loaded with each value under its neighbour's header, silently, because the
 *     grid still looked plausible;
 *   · a doubled quote inside a quoted field is one literal quote;
 *   · the delimiter is chosen from the header line (tab, comma, semicolon, two-or-more spaces);
 *   · a short row is padded and a header line is padded from the longest row, so the grid is a
 *     rectangle — a ragged row is what makes `rows[r][c]` undefined on a contenteditable cell.
 *
 * Usage: node harness_zenviz_parse.mjs <jsDir>
 * Prints one JSON object to stdout.
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import vm from 'node:vm';

const [jsDir] = process.argv.slice(2);
if (!jsDir) throw new Error('usage: node harness_zenviz_parse.mjs <jsDir>');

/* No DOM: the module takes `window` if there is one and `globalThis` otherwise, exactly as a
   `<script>` tag would leave it. One read of the file — the module has no companions. */
const sandbox = vm.createContext({});
vm.runInContext(readFileSync(join(jsDir, 'zenviz-parse.js'), 'utf8'), sandbox, { filename: 'zenviz-parse.js' });
const parse = sandbox.ZenvizParse;
if (!parse || typeof parse.textData !== 'function') throw new Error('zenviz-parse.js declared no ZenvizParse.textData');
const textData = (raw) => JSON.parse(JSON.stringify(parse.textData(raw)));

const out = {};

out.quotedDelimiter = textData('城市,备注,数量\n"北京, 中国","他说 ""你好""",3\n上海,,4');
out.tabSeparated = textData('城市\t数量\n北京\t3');
out.semicolonSeparated = textData('城市;数量\n北京;3');
out.spaceSeparated = textData('城市    数量\n北京    3');
out.singleColumn = textData('名称\n甲\n乙');
out.raggedRows = textData('a,b,c\n1\n4,5');
out.empty = textData('   \n\n');
out.blankHeader = textData('a,,c\n1,2,3');

process.stdout.write(JSON.stringify(out));
