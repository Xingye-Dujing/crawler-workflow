"""The standalone document shell every LaTeX figure and table is wrapped in.

One preamble, one ``\begin{document}`` and the paste-into-a-paper comment block; the
figure and the table share it so a merged compile document restyles every chart at once.
"""

from core import machine

from .tikz_preamble import (
    CJK_FAMILY,
    _esc,
    _label_key,
    _packages,
    _preamble_extras,
    ctex_options,
)


class DocumentShellMixin:
    # ── document shell ────────────────────────────────────────────────

    @staticmethod
    def _wrap_body(body: str) -> str:
        """A bare ``axis`` must live inside a ``tikzpicture``; a ``tikzpicture``/``minipage``/``tabular``
        body is already a box and is left alone.
        """
        if '\\begin{axis}' in body and '\\begin{tikzpicture}' not in body:
            return '\\begin{tikzpicture}\n' + body + '\n\\end{tikzpicture}'
        return body

    @staticmethod
    def _standalone_head(kind: str, chart_type: str, title: str, caption: str) -> str:
        """The comment block a paper author pastes around, then the documentclass + shared preamble up to
        (and including) ``\\begin{document}``. The figure and the table share this one preamble."""
        distribution = 'MiKTeX（Windows）或 TeX Live / MacTeX'
        os_name = machine.platform_name()
        if os_name == 'win32':
            cjk_hint = '% 并 \\setCJKmainfont[scale=0.95,AutoFakeBold=2.0]{FangSong}（仿宋），\n'
        else:
            # A paper author copying this into their own document is on this machine, so the line has to
            # name the font set THIS document was compiled with — copying a FangSong instruction onto a
            # Linux box is how the paste stops compiling.
            cjk_hint = (
                f'% 并把 ctex 换成 \\usepackage[{ctex_options()}]{{ctex}}'
                f'（本机中文由 {CJK_FAMILY[os_name]} 提供，非 Windows 没有仿宋）。\n'
            )
        return (
            f'% 采析绘 LaTeX {kind}（chart_type={chart_type}）\n'
            f'% 用 {distribution} 的 xelatex 编译（含中文，依赖 ctex）。\n'
            '% 复制进论文：导言区加载 ctex、fontspec、pgfplots(1.18)、tikz(+下列库)、booktabs、xcolor，\n'
            + cjk_hint
            + '% 然后包成：\\begin{figure}[htbp]\\centering  <下面这段>  \\caption{'
            + caption
            + '}\\label{fig:'
            + _label_key(chart_type, title)
            + '}\\end{figure}\n'
            '\\documentclass[border=6pt]{standalone}\n' + _packages() + _preamble_extras() + '\n\\begin{document}\n'
        )

    @classmethod
    def _document(cls, body: str, chart_type: str, title: str, *, table: bool) -> str:
        """Wrap a body in a standalone doc that compiles.

        ``standalone`` boxes its body, so a float (``figure``) or ``\\centering`` is illegal at its
        top level ("Not allowed in LR mode"). The body is emitted bare; the paper ``figure`` wrapper
        and the package list ride along as comments, which is what the user pastes into a real paper.
        """
        kind = '三线表' if table else '图'
        caption = _esc(title) if title else f'{_esc(chart_type)}（{kind}）'
        return cls._standalone_head(kind, chart_type, title, caption) + cls._wrap_body(body) + '\n\\end{document}\n'

    @staticmethod
    def strip_shell(doc: str) -> str:
        """The body this service put between the (exactly one) begin/end ``document`` of a standalone doc.

        Safe to split on those markers because every document consumed here was produced by ``_document``,
        which emits each marker once and nothing that looks like them in the body.
        """
        return doc.split(r'\begin{document}', 1)[1].rsplit(r'\end{document}', 1)[0].strip()

    @classmethod
    def compose_from_standalone(cls, docs: list[str]) -> str:
        """Merge the bodies of several standalone documents (this service's own figure/table sources)
        into ONE standalone sharing a single preamble — so a ``compile`` node emits figure and three-line
        table together in one PDF with a single ``xelatex`` pass.

        ``standalone`` keeps its body in LR mode, so adjacent boxes are separated with ``\\par`` (a bare
        ``axis`` beside a ``tabular`` would otherwise collide). The stripped body is already box-wrapped by
        ``_wrap_body`` from its own source, so it is joined verbatim.
        """
        bodies = [cls.strip_shell(doc) for doc in docs if doc]
        body = '\n\\par\n\n'.join(bodies)
        head = cls._standalone_head('组合', 'compile', '', _esc('图表'))
        return head + body + '\n\\end{document}\n'
