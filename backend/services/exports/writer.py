"""Generic data export service.

Decoupled from the workflow engine on purpose: any code (a workflow output
node, a standalone REST endpoint, a unit test, a future CLI...) can call
``DataExporter.save(df, path)`` and get consistent, format-aware behaviour.
The workflow "Save" node is just a thin wrapper around this service.
"""

import contextlib
import json
import logging
import os
import time
import uuid

import pandas as pd
from core.atomic import replace as atomic_replace

from i18n import platform_label, t

logger = logging.getLogger(__name__)


class UnsupportedFormatError(ValueError):
    """Raised when an export format is not recognised."""


class DataExporter:
    """Saves a DataFrame (or list-of-dict records) to disk in various formats."""

    # Maps a format key to the file extension used when one isn't supplied.
    # This is the canonical list: it is what the output node offers and what
    # ``save`` dispatches on, so no format appears here twice.
    EXTENSIONS = {
        'csv': '.csv',
        'json': '.json',
        'excel': '.xlsx',
        'txt': '.txt',
        'html': '.html',
        'markdown': '.md',
        'parquet': '.parquet',
    }

    #: Accepted spellings that are not their own writer. ``xlsx`` used to sit in
    #: EXTENSIONS next to ``excel``, which made the supported-format list carry
    #: one format twice while the panel showed the other name. Aliasing keeps
    #: saved workflows that say ``xlsx`` working without widening the list.
    ALIASES = {'xlsx': 'excel', 'xls': 'excel', 'md': 'markdown'}

    SUPPORTED_FORMATS = tuple(EXTENSIONS.keys())

    #: One writer per format. This is the dispatch table ``save`` reads, so adding a
    #: format is an extension + a name here + the writer itself — there is no if-chain
    #: that can silently forget the new branch (the old chain raised "unsupported" for a
    #: format it had just been taught to advertise).
    WRITERS = {
        'csv': '_write_csv',
        'json': '_write_json',
        'excel': '_write_excel',
        'txt': '_write_txt',
        'html': '_write_html',
        'markdown': '_write_markdown',
        'parquet': '_write_parquet',
    }

    @classmethod
    def resolve(cls, fmt: str) -> str:
        """The canonical format key for *fmt* ('' when nothing was given)."""
        key = str(fmt or '').strip().lower()
        return cls.ALIASES.get(key, key)

    @classmethod
    def infer_format(cls, filename: str) -> str:
        """Guess the export format from a filename's extension."""
        ext = os.path.splitext(filename)[1].lower().lstrip('.')
        return cls.resolve(ext) or 'csv'

    @classmethod
    def normalize_filename(cls, filename: str, fmt: str) -> str:
        """Ensure the filename carries the extension matching *fmt*.

        A blank or dot-only stem is replaced with a real default: joining
        ``''`` onto the export directory used to produce a hidden/empty ``.csv``.
        """
        stem = str(filename or '').strip()
        root, ext = os.path.splitext(stem)
        requested = cls.resolve(fmt)
        wanted = cls.EXTENSIONS.get(requested, '.csv')
        if not root.strip('. '):
            return f'export{wanted}'
        if not requested:
            # No format was asked for: the extension decides, so a name without one gets
            # the csv default and an unknown extension is left alone for ``save`` to refuse
            # by name. Rewriting it here would hide a typo behind a successful export.
            return stem if ext else stem + '.csv'
        if cls.resolve(ext.lstrip('.')) == requested:
            return stem
        # The extension names a DIFFERENT format than the one asked for (or none at all):
        # ``report.txt`` + ``fmt='csv'`` used to write CSV bytes into a ``.txt`` file, which
        # the export panel then listed as kind ``text``. The explicit format wins, so the
        # suffix follows it.
        return root + wanted

    @staticmethod
    def tagged_filename(filename: str, tag: str) -> str:
        """Put *tag* into *filename* before the extension: ``data.csv`` → ``data_20260101_to_20260315.csv``.

        Before the extension and never after, for the same reason ``stamp_filename``
        gives: the export panel classifies a row by its suffix and refuses to serve a
        name whose extension it does not recognise, so anything landing after ``.csv``
        makes the file unopenable from the very list that shows it. An empty tag leaves
        the name untouched, because most workflows have no window to name.
        """
        name = str(filename or '')
        if not tag:
            return name
        root, ext = os.path.splitext(name)
        return f'{root}{tag}{ext}'

    @classmethod
    def stamp_filename(cls, filename: str, export_dir: str) -> str:
        """Rename *filename* so writing it cannot replace last run's file.

        The stamp is the moment this node ran, so a workflow that is executed
        every day keeps every result and nobody has to edit the filename
        between runs. Two properties the callers cannot check for themselves:
        the stamp goes *before* the extension (``data-20260924-081500.csv``,
        which the export panel still recognises by suffix) and a collision gets
        a counter instead of a silent overwrite, because two runs in the same
        second are exactly what a parallel canvas does.

        The result is deliberately not re-truncated to ``MAX_FILENAME_LENGTH``:
        that cap exists to keep a *user-typed* name writable, the 15 added
        characters cannot cross a path component limit, and cutting the name now
        would cut the part that makes it unique.
        """
        root, ext = os.path.splitext(str(filename or ''))
        stamp = time.strftime('%Y%m%d-%H%M%S')
        candidate = f'{root}-{stamp}{ext}'
        # ``-2`` rather than a finer clock: the timestamp the user reads is
        # second-resolution, so the suffix is what says "this is the other one".
        n = 1
        while os.path.exists(os.path.join(export_dir, candidate)):
            n += 1
            candidate = f'{root}-{stamp}-{n}{ext}'
        return candidate

    @classmethod
    def save(
        cls,
        data,
        filepath: str,
        fmt: str = None,
        text_column: str = None,
        **kwargs,
    ) -> dict:
        """Persist *data* (DataFrame or list[dict]) to *filepath*.

        Parameters
        ----------
        data : pd.DataFrame | list[dict]
        filepath : str
            Full destination path. Directory is created if missing.
        fmt : str, optional
            One of SUPPORTED_FORMATS. Inferred from the filepath extension
            when omitted.
        text_column : str, optional
            When exporting to ``txt``, the column whose values are written
            one-per-line. If omitted, every column is written as a
            tab-separated line.

        Returns
        -------
        dict with keys: path, format, rows
        """
        df = data if isinstance(data, pd.DataFrame) else pd.DataFrame(data or [])
        df = cls.localized_platform(df)
        fmt = cls.resolve(fmt) or cls.infer_format(filepath)
        if fmt not in cls.SUPPORTED_FORMATS:
            raise UnsupportedFormatError(f'Unsupported export format: {fmt}')
        if fmt in ('csv', 'excel'):
            df = cls.neutralize_formulas(df)

        directory = os.path.dirname(filepath) or '.'
        os.makedirs(directory, exist_ok=True)

        writer = getattr(cls, cls.WRITERS.get(fmt) or '', None)
        if writer is None:
            raise UnsupportedFormatError(f'Unsupported export format: {fmt}')
        # Written beside the target and moved into place: a crash midway leaves a hidden
        # temp file, never a half-written ``.csv`` that the export panel lists and the user
        # opens as if the run had finished.
        stem, ext = os.path.splitext(filepath)
        staged = f'{stem}.{uuid.uuid4().hex[:8]}.part{ext}'
        try:
            if fmt == 'txt':
                writer(df, staged, text_column=text_column, **kwargs)
            else:
                writer(df, staged, **kwargs)
            atomic_replace(staged, filepath)
        except BaseException:
            with contextlib.suppress(OSError):
                os.remove(staged)
            raise

        logger.info(t('export.done', n=len(df), path=filepath, fmt=fmt))
        return {'path': filepath, 'format': fmt, 'rows': len(df)}

    #: The first characters Excel reads as the start of a formula. A crawled comment that
    #: begins with one of these (`=HYPERLINK(...)`, `@SUM(...)`) becomes a live cell when the
    #: CSV/Excel export is opened — data the crawler merely recorded starts executing.
    FORMULA_PREFIXES = ('=', '+', '-', '@', '\t', '\r')

    @classmethod
    def neutralize_formulas(cls, df: pd.DataFrame) -> pd.DataFrame:
        """Prefix formula-looking text cells with ``'`` so Excel keeps them as text.

        Applied to csv/excel only (a json/txt export is not evaluated by a spreadsheet),
        and only to string cells, so a numeric ``-5`` keeps its type. The quote is the
        spreadsheet convention for "this is text"; the count is logged once so the change
        to the user's data is visible rather than silent.
        """
        hits = 0

        def _fix(value):
            nonlocal hits
            if isinstance(value, str) and value[:1] in cls.FORMULA_PREFIXES:
                hits += 1
                return "'" + value
            return value

        out = df.copy()
        for column in out.columns:
            series = out[column]
            # A number cannot start a formula, and pandas no longer reports a text column as
            # ``object`` (it has its own ``str`` dtype), so the check is "not numeric/time"
            # rather than "is object".
            if (
                pd.api.types.is_numeric_dtype(series)
                or pd.api.types.is_bool_dtype(series)
                or pd.api.types.is_datetime64_any_dtype(series)
            ):
                continue
            out[column] = series.map(_fix)
        if hits:
            logger.warning(t('export.formula_escaped', n=hits))
        return out

    # ── Individual writers ──────────────────────────────────────

    @staticmethod
    def localized_platform(df: pd.DataFrame) -> pd.DataFrame:
        """Show the “平台” column as the word the user reads (抖音, not ``douyin``).

        The stored column is the raw key — the row's identity, used for dedupe and platform
        detection — and it stays that way in the database; this rewrites only the export frame,
        in the language of the run/request. An unmapped value falls back to itself (never blank),
        so a column that is not a platform key passes through untouched.
        """
        if '平台' not in df.columns:
            return df
        out = df.copy()
        out['平台'] = out['平台'].map(lambda v: platform_label(v) if isinstance(v, str) and v else v)
        return out

    @staticmethod
    def _write_csv(df: pd.DataFrame, filepath: str, encoding: str = 'utf-8-sig', **_):
        df.to_csv(filepath, index=False, encoding=encoding)

    @staticmethod
    def _write_parquet(df: pd.DataFrame, filepath: str, **_):
        # Parquet needs a columnar engine (pyarrow, declared in requirements-optional.txt and NOT
        # CI-installed, exactly like the torch/transformers that bert mode probes for). pandas
        # resolves the engine itself; on a machine without one it raises ImportError, which we turn
        # into a refusal BY NAME with the fix — never a bare traceback from deep inside pandas.
        try:
            df.to_parquet(filepath, index=False)
        except ImportError as exc:
            raise UnsupportedFormatError(t('export.parquet_engine_missing')) from exc

    @staticmethod
    def _write_json(df: pd.DataFrame, filepath: str, orient: str = 'records', **_):
        if orient == 'records':
            # NaN / NaT are not valid JSON. json.dump writes bare ``NaN`` by
            # default and no strict parser — the browser's JSON.parse included —
            # accepts it, so the file could never be re-imported.
            records = df.astype(object).where(pd.notna(df), None).to_dict('records')
        else:
            records = json.loads(df.to_json(orient=orient))
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(records, f, ensure_ascii=False, indent=2, default=str)

    @staticmethod
    def _write_excel(df: pd.DataFrame, filepath: str, sheet_name: str = 'Sheet1', **_):
        df.to_excel(filepath, index=False, sheet_name=sheet_name, engine='openpyxl')

    @staticmethod
    def _write_txt(df: pd.DataFrame, filepath: str, text_column: str = None, **_):
        name = str(text_column or '').strip()
        if name and name not in df.columns:
            # A typo'd 文本列 used to fall into the "all columns" branch: the save succeeded and
            # wrote a tab-separated dump of every column instead of the one-per-line text the node
            # was told to write. Every other writer refuses a column it cannot find.
            raise UnsupportedFormatError(t('export.missing_text_column', column=name))
        with open(filepath, 'w', encoding='utf-8') as f:
            if name:
                for value in df[name].fillna(''):
                    f.write(str(value).strip() + '\n')
            else:
                # A missing cell writes as an empty field, never the literal ``nan``: the file is
                # read by people and by scripts that split on tabs.
                for _, row in df.iterrows():
                    f.write('\t'.join('' if pd.isna(value) else str(value) for value in row.tolist()) + '\n')

    @staticmethod
    def _write_html(df: pd.DataFrame, filepath: str, **_):
        df.to_html(filepath, index=False, escape=True)

    @staticmethod
    def _write_markdown(df: pd.DataFrame, filepath: str, **_):
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(df.to_markdown(index=False))
