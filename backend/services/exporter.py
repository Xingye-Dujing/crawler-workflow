"""Generic data export service.

Decoupled from the workflow engine on purpose: any code (a workflow output
node, a standalone REST endpoint, a unit test, a future CLI...) can call
``DataExporter.save(df, path)`` and get consistent, format-aware behaviour.
The workflow "Save" node is just a thin wrapper around this service.
"""

import json
import logging
import os
import time

import pandas as pd

from i18n import t

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
    }

    #: Accepted spellings that are not their own writer. ``xlsx`` used to sit in
    #: EXTENSIONS next to ``excel``, which made the supported-format list carry
    #: one format twice while the panel showed the other name. Aliasing keeps
    #: saved workflows that say ``xlsx`` working without widening the list.
    ALIASES = {'xlsx': 'excel', 'xls': 'excel', 'md': 'markdown'}

    SUPPORTED_FORMATS = tuple(EXTENSIONS.keys())

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
        wanted = cls.EXTENSIONS.get(cls.resolve(fmt), '.csv')
        if ext.lower() in ('.csv', '.json', '.xlsx', '.xls', '.txt', '.html', '.md'):
            return stem
        if not root.strip('. '):
            return f'export{wanted}'
        return root + wanted

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
        fmt = cls.resolve(fmt) or cls.infer_format(filepath)
        if fmt not in cls.SUPPORTED_FORMATS:
            raise UnsupportedFormatError(f'Unsupported export format: {fmt}')

        os.makedirs(os.path.dirname(filepath) or '.', exist_ok=True)

        if fmt == 'excel':
            cls._write_excel(df, filepath, **kwargs)
        elif fmt == 'csv':
            cls._write_csv(df, filepath, **kwargs)
        elif fmt == 'json':
            cls._write_json(df, filepath, **kwargs)
        elif fmt == 'txt':
            cls._write_txt(df, filepath, text_column=text_column, **kwargs)
        elif fmt == 'html':
            cls._write_html(df, filepath, **kwargs)
        elif fmt == 'markdown':
            cls._write_markdown(df, filepath, **kwargs)
        else:
            raise UnsupportedFormatError(f'Unsupported export format: {fmt}')

        logger.info(t('export.done', n=len(df), path=filepath, fmt=fmt))
        return {'path': filepath, 'format': fmt, 'rows': len(df)}

    # ── Individual writers ──────────────────────────────────────

    @staticmethod
    def _write_csv(df: pd.DataFrame, filepath: str, encoding: str = 'utf-8-sig', **_):
        df.to_csv(filepath, index=False, encoding=encoding)

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
        with open(filepath, 'w', encoding='utf-8') as f:
            if text_column and text_column in df.columns:
                for value in df[text_column].fillna(''):
                    f.write(str(value).strip() + '\n')
            else:
                for _, row in df.iterrows():
                    f.write('\t'.join(str(v) for v in row.tolist()) + '\n')

    @staticmethod
    def _write_html(df: pd.DataFrame, filepath: str, **_):
        df.to_html(filepath, index=False, escape=True)

    @staticmethod
    def _write_markdown(df: pd.DataFrame, filepath: str, **_):
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(df.to_markdown(index=False))
