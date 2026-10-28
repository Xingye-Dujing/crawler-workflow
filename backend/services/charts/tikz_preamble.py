"""LaTeX figure + three-line-table generator for the ``visualize`` node.

A chart is emitted here as *source*, not a raster: a self-contained ``standalone`` document the user compiles
with MiKTeX ``xelatex`` (the figures carry Chinese, so ``ctex``). The look mirrors the hand-tuned paper this tool
feeds — 仿宋 (FangSong) CJK text, a muted paper palette, a light dotted grid, thousands-separated ticks, value
labels on bars, and boxed leader-line labels on the topic/network/sankey figures — because these are figures for
a paper, not a dashboard. Every figure and table shares ONE ``cixi`` axis style and a pair of tikz styles
(``lblbox``/``leadline``) defined once in the preamble, so a merged ``compile`` document restyles all charts at once.

The numbers come from the SAME helpers ``VisualizationService`` uses to draw the chart, so the LaTeX and
the on-screen figure are two projections of one value and cannot disagree. Colour is the exception and
says so: ``_PAPER_PALETTE`` below is the paper's own list, matched color-for-color to the reference
figures this build imitates, and it is NOT ``visualizer.CATEGORY_COLORS`` — the two agree on the data,
not on the ink, and claiming otherwise would make a screen recolour silently rewrite a submitted figure.

Two types have no faithful TikZ equivalent in this build (no province geometry, no word-cloud/sankey layout
engine — see ``visualizer.py:397``): ``map`` is drawn as a province-centroid **bubble map** and ``wordcloud``
as a frequency-sized word block, and BOTH list every value in an appendix ``tabular`` so content stays
complete even where a centroid is missing. A chart whose required field is absent refuses by name
(``ChartConfigError``), the rule the renderers already follow.
"""

import math
import re

from core import machine

# ── paper preamble ──────────────────────────────────────────────────────
#: Exactly the packages a figure copied into a paper needs; harmless if the document already loads them.
#: fontspec under ctex/xelatex makes the CJK \setCJKmainfont below available; ctex would load it anyway.
#:
#: The ctex line is built per operating system (see :func:`ctex_options`), so this tuple is the part that
#: is the same everywhere.
_PACKAGES_TAIL = (
    '\\usepackage{fontspec}\n'
    '\\usepackage{pgfplots}\n'
    '\\pgfplotsset{compat=1.18}\n'
    '\\usepackage{amssymb}\n'
    '\\usepackage{booktabs}\n'
    '\\usepackage{xcolor}\n'
    '\\usetikzlibrary{arrows.meta,calc,positioning,backgrounds}\n'
)

#: ctex's own CJK font set per OS, as the package option that selects it. Empty means "ctex's default",
# which on Windows is the system Chinese fonts — and the explicit 仿宋 lines below override it there.
#:
#: 仿宋 (FangSong) is what the reference paper this look is copied from is set in, and it is a Windows
#: font: TeX Live ships no FangSong and macOS does not either, so asking for it by name on those machines
#: is a compile that dies with 「The font "FangSong" cannot be found」. Off Windows the ask becomes a
#: Chinese text that EXISTS on that system (fandol comes with ``texlive-lang-chinese``, macnew uses the
#: system Songti/Heiti). The family differs — that difference is said here and in the emitted comment,
#: not hidden by a document that will not compile.
CTEX_FONTSET = {'win32': '', 'linux': 'fontset=fandol', 'darwin': 'fontset=macnew'}

#: The CJK main family the figures actually get, per OS — used by the refusal text and the source comment.
CJK_FAMILY = {'win32': 'FangSong', 'linux': 'FandolSong', 'darwin': 'Songti SC'}


def ctex_options(system: str | None = None) -> str:
    """The ctex package option that picks a font set this operating system owns."""
    return CTEX_FONTSET.get(machine.platform_name(system), '')


def _packages(system: str | None = None) -> str:
    """``\\usepackage[fontset=…]{ctex}`` plus the packages that are the same on every OS."""
    options = ctex_options(system)
    ctex = f'\\usepackage[{options}]{{ctex}}\n' if options else '\\usepackage{ctex}\n'
    return ctex + _PACKAGES_TAIL


_CYCLE_NAMES = ['cA', 'cB', 'cC', 'cD', 'cE', 'cF', 'cG', 'cH', 'cI', 'cJ']

#: The paper's own palette, taken color-for-color from the reference figures it is made to match. It is a
#: separate list from ``visualizer.CATEGORY_COLORS`` on purpose: these print in grayscale and carry a caption,
#: so the screen colours are not the ones a reviewer reads in the journal version. Hex without ``#`` because
#: TikZ's ``definecolor`` takes the raw digits.
_PAPER_PALETTE = [
    '22557A',
    'B5563C',
    '3E7A5A',
    'C79A3B',
    '6A5A8C',
    '2E7D8C',
    '9C6B3C',
    '5C8A5C',
    '8A5A6B',
    '4A6B8A',
]


#: The box a network picture is sized into, in centimetres. A4 with the paper's 1.5 cm margins leaves
#: 18 cm of text and a bibliometric figure's own minipage is 17.5 cm wide, so a picture that fits here
#: cannot run off the page — and height binds first, because a ring is as tall as it is wide while the
#: caption and the formula paragraph have to reach the same page.
GRAPH_BOX_CM = (15.0, 10.5)

#: One line of a Chinese label, tall enough to count as overhang when sizing.
GRAPH_LINE_CM = 0.6


def _preamble_extras() -> str:
    """仿宋 CJK text (Windows) or the OS's own ctex font set + the paper palette + the shared ``cixi``
    axis style and two reusable tikz styles.

    One style block instead of repeating the paper rules per ``axis``: a figure that quietly kept
    gridlines in one branch and dropped them in another is the kind of inconsistency a reader spots. The
    merged ``compile`` document embeds this preamble once, so ``lblbox``/``leadline`` are in scope for every
    boxed label regardless of how many charts are stitched together.
    """
    os_name = machine.platform_name()
    if os_name == 'win32':
        lines = [
            r'\setCJKmainfont[scale=0.95,AutoFakeBold=2.0]{FangSong}',
            r'\setCJKsansfont[AutoFakeBold=2.0]{FangSong}',
            r'\setCJKmonofont[AutoFakeBold=2.0]{FangSong}',
        ]
    else:
        # Naming a font this system does not have is the failure; ctex's fontset (chosen on the ctex line)
        # already set main/sans/mono. The comment is for the person who opens the .tex to paste it.
        lines = [
            rf'% 中文由 ctex 的 {CTEX_FONTSET[os_name].split("=")[1]} 字体集提供（主字体 {CJK_FAMILY[os_name]}）：'
            rf'% 本机没有仿宋（FangSong 是 Windows 字体），所以这里不指名任何字体。'
        ]
    lines += [rf'\definecolor{{{n}}}{{HTML}}{{{h}}}' for n, h in zip(_CYCLE_NAMES, _PAPER_PALETTE, strict=False)]
    # The sentiment overlay's neutral band, exactly the grey the screen uses (chart_contracts.POLARITY_COLORS).
    lines.append(r'\definecolor{cNeutral}{HTML}{9AA0A6}')
    entries = ','.join(f'{{color={n},mark=*,solid,thick}}' for n in _CYCLE_NAMES[: len(_PAPER_PALETTE)])
    lines.append(rf'\pgfplotsset{{cycle list={{{entries}}}}}')
    lines.append(
        r'\pgfplotsset{cixi/.style={'
        r'axis lines=left,xmajorgrids=false,ymajorgrids=true,'
        r'major grid style={black!12,dotted},'
        r'scaled ticks=false,/pgf/number format/1000 sep={,},'
        r'tick label style={font=\scriptsize},'
        r'label style={font=\small},'
        r'legend style={font=\scriptsize,draw=none,at={(0.5,1.03)},anchor=south},'
        r'width=9cm,height=5.6cm}}'
    )
    # A boxed label + its leader line: the reference draws topic/network/sankey captions this way so long
    # Chinese labels never collide with a data point.
    lines.append(
        r'\tikzset{lblbox/.style={font=\scriptsize,align=center,inner sep=1.6pt,'
        r'fill=white,draw=black!14,line width=0.3pt,rounded corners=2pt,text=black},'
        r'leadline/.style={black!30,line width=0.3pt}}'
    )
    lines.append(r'\renewcommand{\arraystretch}{1.25}')
    return '\n'.join(lines)


def _esc(value) -> str:
    """Make a label safe for LaTeX text. Chinese passes through (ctex); TeX's ten specials are escaped."""
    out = []
    for ch in str(value):
        if ch in '\\&%#_{}$':
            out.append('\\' + ch)
        elif ch == '~':
            out.append('\\textasciitilde{}')
        elif ch == '^':
            out.append('\\textasciicircum{}')
        else:
            out.append(ch)
    return ''.join(out)


#: The same escaper under a public name: anything that pastes free text (a node title, a method
#: sentence) into a document assembled elsewhere has to go through it — ``top_n=50`` in a caption
#: is a ``Missing $ inserted`` error without it.
esc = _esc


def _num(value) -> str:
    """A finite number as clean LaTeX (drop a trailing .0); never emit a nan/inf token."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return '0'
    if not math.isfinite(f):
        return '0'
    if f == int(f):
        return str(int(f))
    return f'{f:g}'


def _sym(labels) -> str:
    """A pgfplots ``symbolic coords`` set: comma-separated, each label escaped and spaces made robust."""
    return ','.join(_esc(label).replace(' ', '~') for label in labels)


def _fold_label(text, width=7) -> str:
    r"""Break a long label onto ``width``-character lines so its box stays narrow, like the reference's.

    Each line is escaped whole, never by slicing an escaped string (that would split ``\&`` into a stray
    backslash and an active ampersand). ``\\`` is a line break inside an ``align`` node.
    """
    s = str(text)
    return r'\\'.join(_esc(s[i : i + width]) for i in range(0, len(s), width))


def _cat_axis(labels, xlabel='') -> str:
    """A categorical x-axis with the paper's crowding rule.

    Beyond a handful of categories pgfplots drops every other tick and lies about the granularity, so
    we rotate the labels and show a regular, spaced subset — while keeping every DATA point, so a reader
    counts points and recovers the labels. That is the only irregularity the X axis is allowed.
    """
    rotate = (
        'xticklabel style={rotate=45,anchor=east,align=right,font=\\scriptsize},xtick distance=2,'
        if len(labels) > 10
        else 'xticklabel style={font=\\scriptsize},'
    )
    name = f',xlabel={{{_esc(xlabel)}}}' if xlabel else ''
    return f'symbolic x coords={{{_sym(labels)}}},xtick=data,{rotate}enlargelimits=0.15{name}'


def _label_key(chart_type, title) -> str:
    base = re.sub(r'[^0-9a-zA-Z]+', '-', str(title or chart_type)).strip('-').lower()
    return (base or chart_type)[:40]


def paper_preamble() -> str:
    """ctex + fontspec + pgfplots + booktabs + the palette + the shared tikz styles.

    Every source this service writes defines ``cA``…``cJ``, ``lblbox``, ``leadline`` and the
    ``cixi`` axis style in its own preamble. A document that pastes their BODIES has to carry the
    same definitions, or the first ``\\draw[cA,...]`` dies with ``Undefined color`` — which is why
    the paper report asks for this instead of writing its own package list.
    """
    return _packages() + _preamble_extras()


# ── compact province-centroid table (capital cities) for the bubble map ──
_CHINA_LON0, _CHINA_LON1 = 73.0, 135.0
_CHINA_LAT0, _CHINA_LAT1 = 17.0, 54.0
_PROVINCE_CENTROIDS = {
    '北京': (116.41, 39.90),
    '天津': (117.20, 39.13),
    '河北': (114.51, 38.04),
    '石家庄': (114.51, 38.04),
    '山西': (112.55, 37.87),
    '太原': (112.55, 37.87),
    '内蒙古': (111.75, 40.84),
    '呼和浩特': (111.75, 40.84),
    '辽宁': (123.43, 41.80),
    '沈阳': (123.43, 41.80),
    '吉林': (125.32, 43.89),
    '长春': (125.32, 43.89),
    '黑龙江': (126.63, 45.75),
    '哈尔滨': (126.63, 45.75),
    '上海': (121.47, 31.23),
    '江苏': (118.79, 32.06),
    '南京': (118.79, 32.06),
    '浙江': (120.15, 30.28),
    '杭州': (120.15, 30.28),
    '安徽': (117.28, 31.86),
    '合肥': (117.28, 31.86),
    '福建': (119.30, 26.08),
    '福州': (119.30, 26.08),
    '江西': (115.89, 28.68),
    '南昌': (115.89, 28.68),
    '山东': (117.00, 36.65),
    '济南': (117.00, 36.65),
    '河南': (113.62, 34.75),
    '郑州': (113.62, 34.75),
    '湖北': (114.30, 30.59),
    '武汉': (114.30, 30.59),
    '湖南': (112.98, 28.19),
    '长沙': (112.98, 28.19),
    '广东': (113.26, 23.13),
    '广州': (113.26, 23.13),
    '广西': (108.32, 22.82),
    '南宁': (108.32, 22.82),
    '海南': (110.33, 20.03),
    '海口': (110.33, 20.03),
    '重庆': (106.54, 29.56),
    '四川': (104.07, 30.57),
    '成都': (104.07, 30.57),
    '贵州': (106.71, 26.65),
    '贵阳': (106.71, 26.65),
    '云南': (102.83, 24.88),
    '昆明': (102.83, 24.88),
    '西藏': (91.13, 29.66),
    '拉萨': (91.13, 29.66),
    '陕西': (108.95, 34.34),
    '西安': (108.95, 34.34),
    '甘肃': (103.82, 36.06),
    '兰州': (103.82, 36.06),
    '青海': (101.78, 36.62),
    '西宁': (101.78, 36.62),
    '宁夏': (106.23, 38.49),
    '银川': (106.23, 38.49),
    '新疆': (87.62, 43.79),
    '乌鲁木齐': (87.62, 43.79),
    '台湾': (121.51, 25.04),
    '香港': (114.17, 22.32),
    '澳门': (113.55, 22.20),
}
