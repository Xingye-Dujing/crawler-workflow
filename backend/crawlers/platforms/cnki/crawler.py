"""CNKI (中国知网): page-by-page 全选, then one Refworks export of the selection.

Measured on the real site 2026-10-30 (a visible throwaway profile, user-solved
slider and signed-in session):

* the result page is ``/kns8s/search``; rows are ``.result-table-list tbody tr``,
  each carrying an ``input.cbItem`` whose value is the export key, and the
  per-page 全选 control is ``#selectCheckAll1``;
* **全选 only selects the page it is on**, while the site keeps the selection
  across pages (localStorage ``FileNameSNZKPT`` / ``SEARCHINFONZKPT``), so the
  crawl ticks 全选 on every page it walks and exports once at the end;
* the pager's next link is ``.pages a`` with the text 下一页;
* the export is the site's own flow, not the ``/dm8/API/GetExport`` endpoint
  (that one answers ``code=0 暂无数据``): clicking
  「导出与分析 → 导出文献 → Refworks」 (an ``li`` whose
  ``a[exporttype="Refworks"]``) opens
  ``https://kns.cnki.net/dm8/manage/export.html?language=CHS&uniplatform=NZKPT``
  in a new window. Its on-screen list is a **preview** (measured: 40 selected
  rows rendered as 20 ``li``), so the crawl clicks 「导出题录文件」 and reads the
  downloaded ``CNKI-…txt`` — that file carries the whole selection. It writes a
  blank line between every field, which ``_split_refworks`` removes before the
  importer sees it;
* the menu's own handler refuses an anonymous session, and the check-box handler
  refuses a 501st selection, so the profile/cookie path is mandatory and a batch
  is capped at the site's own 500-record selection ceiling.

The RefWorks text then goes through ``services.biblio.importer.parse_cnki`` — the
same reader an uploaded ``CNKI-…-RefWorks.txt`` uses — so a crawled record and an
imported one cannot disagree about columns or identity.
"""

import contextlib
import logging
import shutil
import tempfile
import time
from pathlib import Path

from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.support.ui import WebDriverWait

from crawlers.core.crawler import UNDER_TARGET, Crawler, as_index
from crawlers.core.faults import CrawlerStopped, PageNotArrivedError
from i18n import t
from services.biblio import importer

logger = logging.getLogger(__name__)

SEARCH_URL = 'https://kns.cnki.net/kns8s/search'
EXPORT_TYPE = 'Refworks'
#: The site's own selection ceiling: ``filenameClick`` refuses a 501st row and
#: shows 最多选择 500 篇. A search larger than this is exported in batches of one
#: full selection, never by silently dropping the tail.
SELECTION_CAP = 500

#: One search page renders ~20 rows. The pauses are anti-bot hygiene, not a row
#: budget: the user's target decides how far the walk goes.
ROW_PAUSE = 1.2
PAGE_PAUSE = 1.5


class CnkiCrawler(Crawler):
    """Search CNKI, select every page, and export the selection as RefWorks rows."""

    domain = 'kns.cnki.net'
    login_url = 'https://kns.cnki.net/'
    #: The identity provider that issues the login cookies is a sibling host.
    cookie_domains = ('login.cnki.net',)
    supports_crawl = True

    SEARCH_WAIT = 20.0
    EXPORT_WAIT = 20.0

    #: A botched batch is a fact about that batch, never a row. The walk reports
    #: how many selected records did not come back so a short table cannot be
    #: licensed as "the site ran out".
    class ExportError(ValueError):
        pass

    def search(self, keyword: str, target_count: int = 50, **_kwargs):
        resume = self.resume_of(_kwargs)
        if self.collected() >= target_count:
            logger.info(t('crawl.cnki.target_reached', n=target_count))
            return self.results()
        logger.info(t('crawl.cnki.start', kw=keyword, n=target_count))
        if not self._open_search(keyword):
            if self.login_wall:
                return self.results()
            if self.risk_blocked:
                raise ValueError(t('crawl.cnki.verifyRequired'))
            raise PageNotArrivedError(t('crawl.cnki.noPage'), verdict=self.verdict(), gave_up=self.pending_waits)
        first_rows = self._page_rows()
        if self._total_results() == 0 and not any(self._row_id(row) for row in first_rows):
            logger.info(t('crawl.cnki.noResults', kw=keyword))
            self.note_end('empty', scanned=0, kept=0)
            return self.results()
        if self._is_logged_in() is False:
            self.login_wall = True
            raise ValueError(t('crawl.cnki.loginNeeded'))

        resume_page = max(1, as_index(resume.get('page'), 1))
        page = 1
        if resume_page > 1 and not self._advance_to(resume_page):
            # The pager could not be driven back to the stored page. Restart the
            # walk instead of pretending the cursor was honoured: the ledger drops
            # the overlap, so the cost is requests, never duplicate rows.
            resume_page = 1
        else:
            page = resume_page
        # A selection can outlive a previous crawl in the same profile; every run
        # owns a clean batch before its first 全选.
        self._clear_selection()
        scanned = refused = 0
        exhausted = False
        batch_pages: list[int] = []
        batch_selected = 0
        batch_rows = 0
        while self.collected() < target_count:
            if self.may_stop():
                raise CrawlerStopped(t('crawl.stopped'))
            rows = self._page_rows()
            if not rows:
                # A page that painted nothing is not the site saying "no more";
                # leave ``exhausted`` alone so the shortfall stays convicted.
                break
            scanned += len(rows)
            ids = [export_id for row in rows if (export_id := self._row_id(row))]
            if not ids:
                # The table rendered but no row carries its export key: the page
                # model moved. Filing this as "found nothing" would hand the
                # canvas an empty literature table that looks complete.
                raise ValueError(t('crawl.cnki.noExportIds'))
            refused += len(rows) - len(ids)
            if batch_selected and batch_selected + len(ids) > SELECTION_CAP:
                _emitted, refused_extra, _complete, export_ok = self._flush_batch(
                    batch_pages, batch_selected, batch_rows, target_count
                )
                refused += refused_extra
                batch_pages, batch_selected, batch_rows = [], 0, 0
                if self.collected() >= target_count:
                    break
                if not export_ok or self.login_wall:
                    break
            previous = batch_selected
            count = self._select_page(ids)
            if count <= previous:
                refused += len(ids)
                logger.warning(t('crawl.cnki.nothingSelected'))
                break
            refused += max(0, (previous + len(ids)) - count)
            batch_selected = count
            batch_pages.append(page)
            batch_rows += len(rows)
            logger.info(t('crawl.cnki.selectPage', page=page, n=len(rows), selected=count))
            if target_count and batch_selected >= target_count:
                break
            moved = self._next_page()
            if moved == 'end':
                exhausted = True
                break
            if moved != 'ok':
                # The 下一页 click did not turn the page: that is not the site
                # saying it has no more, so the shortfall stays convicted.
                break
            page += 1
            self._polite_pause(PAGE_PAUSE, 0.3)

        if batch_selected and self.collected() < target_count:
            _emitted, refused_extra, _complete, _ok = self._flush_batch(
                batch_pages, batch_selected, batch_rows, target_count
            )
            refused += refused_extra

        if self.collected() >= target_count:
            logger.info(t('crawl.cnki.target_reached', n=target_count))
            return self.results()
        if exhausted and not refused and not (self.login_wall or self.risk_blocked):
            # The pager itself offered no 下一页 — a site-attested end.
            self.note_end('site_end', scanned=scanned, kept=self.collected(), refused=refused)
        else:
            # Refused records, an empty page mid-list or a page that refused to
            # turn all mean this walk cannot prove the site had nothing more.
            self.note_end(UNDER_TARGET, scanned=scanned, kept=self.collected(), refused=refused)
        logger.info(t('crawl.cnki.finished', n=self.collected(), total=target_count))
        return self.results()

    def _flush_batch(
        self, pages: list[int], selected: int, rows_expected: int, target: int
    ) -> tuple[int, int, bool, bool]:
        """Export one accumulated selection and emit what it returned.

        Returns ``(emitted, refused, complete, export_ok)``. ``complete`` licenses
        the cursor to move past the batch's last page: every selected record came
        back and parsed (or the target was reached mid-batch). ``export_ok`` is
        only about the window answering at all, so a systemic failure stops the
        walk instead of hammering the remaining pages.
        """
        try:
            texts = self._export_page_records()
        except self.ExportError as exc:
            logger.warning(str(exc))
            return 0, selected, False, False
        refused = max(0, selected - len(texts))
        emitted = parsed_ok = 0
        for text in texts:
            if self.collected() >= target:
                break
            parsed = self._rows_from_refworks(text)
            if not parsed:
                refused += 1
                logger.warning(t('crawl.cnki.emptyRecord'))
                continue
            parsed_ok += 1
            for item in parsed:
                if self.collected() >= target:
                    break
                if self.emit(item):
                    emitted += 1
        reached = self.collected() >= target
        complete = len(texts) >= selected and selected >= rows_expected and (reached or parsed_ok == len(texts))
        if complete and pages:
            # The cursor moves only past a batch whose whole selection returned;
            # 继续 then starts at the next page, and the ledger drops any overlap.
            self.mark_position(page=pages[-1], done=self.collected())
        logger.info(
            t(
                'crawl.cnki.exportBatch',
                n=len(texts),
                first=pages[0] if pages else 0,
                last=pages[-1] if pages else 0,
            )
        )
        return emitted, refused, complete, len(texts) >= selected

    # ─── the search page ─────────────────────────────────────────

    def _open_search(self, keyword: str) -> bool:
        """Open the search page, type the keyword and wait for a result table."""
        self.open(SEARCH_URL)
        if self.login_wall or self.risk_blocked:
            return False
        try:
            box = WebDriverWait(self.driver, self.SEARCH_WAIT).until(
                ec.presence_of_element_located((By.CSS_SELECTOR, 'input.search-input'))
            )
        except TimeoutException:
            self.check_intercept()
            return False
        try:
            box.clear()
            box.send_keys(str(keyword))
            button = self.driver.find_element(By.CSS_SELECTOR, 'input.search-btn')
            self.driver.execute_script('arguments[0].click();', button)
        except WebDriverException as exc:
            logger.warning(t('crawl.cnki.pageError', err=exc))
            self.check_intercept()
            return False
        waited = self.wait_for_first_content(
            has_content=self._results_ready,
            stalled=self._verify_shown,
            timeout=self.SEARCH_WAIT,
        )
        if not waited['arrived']:
            self.check_intercept()
            return False
        self.check_intercept()
        return not (self.login_wall or self.risk_blocked)

    def _results_ready(self) -> bool:
        try:
            return bool(
                self.driver.execute_script(
                    "return !!(document.querySelector('.result-table-list tbody tr')"
                    " || /共找到\\s*0\\s*条结果/.test(document.body ? document.body.innerText : ''));"
                )
            )
        except WebDriverException:
            return False

    def _verify_shown(self) -> bool:
        """The slider the site mounts for an untrusted session."""
        try:
            return bool(
                self.driver.execute_script(
                    "var e = document.querySelector('#tcaptcha_transform_dy');"
                    ' return !!e && e.getBoundingClientRect().top >= 0;'
                )
            )
        except WebDriverException:
            return False

    def _total_results(self) -> int | None:
        """The count the site prints, or ``None`` when the plate is not there."""
        try:
            text = self.driver.execute_script(
                "var e = document.querySelector('.pagerTitleCell'); return e ? e.innerText : '';"
            )
        except WebDriverException:
            return None
        digits = ''.join(ch for ch in str(text or '') if ch.isdigit() or ch == ',')
        try:
            return int(digits.replace(',', '')) if digits else None
        except ValueError:
            return None

    def _page_rows(self) -> list[dict]:
        """The rows this page renders, with each row's checkbox export key."""
        try:
            rows = self.driver.execute_script(
                """
                var out = [];
                var rows = document.querySelectorAll('.result-table-list tbody tr');
                for (var i = 0; i < rows.length; i++) {
                    var box = rows[i].querySelector('input.cbItem');
                    var link = rows[i].querySelector('td.name a.fz14');
                    if (!box && !link) continue;
                    out.push({id: box ? box.value : '', title: link ? link.innerText.trim() : ''});
                }
                return out;
                """
            )
        except WebDriverException:
            return []
        return [row for row in (rows or []) if isinstance(row, dict)]

    @staticmethod
    def _row_id(row: dict) -> str:
        return str(row.get('id') or '').strip()

    # ─── selection + the site's export window ────────────────────

    def _is_logged_in(self):
        """The site's own answer: True, False, or None when the function is absent."""
        try:
            return self.driver.execute_script("return (typeof islogin === 'function') ? !!islogin() : null;")
        except WebDriverException:
            return None

    def _selection_count(self) -> int:
        try:
            text = self.driver.execute_script(
                "var c = document.querySelector('#selectCount'); return c ? c.innerText.trim() : '';"
            )
        except WebDriverException:
            return 0
        try:
            return int(str(text or '0').strip())
        except ValueError:
            return 0

    def _select_page(self, ids: list[str]) -> int:
        """Click the page's 全选 (or tick its rows) and answer the site's total.

        CNKI's 全选 applies to the page it is on; the total count is what carries
        the earlier pages forward, which is exactly the accumulation this crawl
        exports once at the end.
        """
        before = self._selection_count()
        try:
            clicked = self.driver.execute_script(
                """
                var all = document.querySelector('#selectCheckAll1');
                if (!all || all.checked) { return false; }
                all.click();
                return true;
                """
            )
        except WebDriverException:
            clicked = False
        if clicked:
            after = self._selection_count()
            if after - before >= len(ids):
                return after
        return self._select_rows(ids)

    def _select_rows(self, ids: list[str]) -> int:
        """Fallback for a page whose 全选 did not cover every row."""
        try:
            self.driver.execute_script(
                """
                var wanted = arguments[0] || [];
                var boxes = document.querySelectorAll('.result-table-list tbody input.cbItem');
                for (var i = 0; i < boxes.length; i++) {
                    if (wanted.indexOf(boxes[i].value) >= 0 && !boxes[i].checked) { boxes[i].click(); }
                }
                """,
                list(ids),
            )
        except WebDriverException as exc:
            raise self.ExportError(t('crawl.cnki.selectFailed', err=exc)) from exc
        return self._selection_count()

    def _clear_selection(self) -> None:
        """Untick every selected row, so a batch never borrows from the previous one."""
        with contextlib.suppress(WebDriverException):
            self.driver.execute_script(
                """
                var boxes = document.querySelectorAll('.result-table-list tbody input.cbItem:checked');
                for (var i = 0; i < boxes.length; i++) { boxes[i].click(); }
                """
            )
        # The export menu reads the site's own storage, not the DOM count; an
        # unticked page with a stale key list would silently re-export old rows.
        with contextlib.suppress(WebDriverException):
            self.driver.execute_script(
                """
                var boxes = document.querySelectorAll('.result-table-list tbody input.cbItem');
                for (var i = 0; i < boxes.length; i++) { boxes[i].checked = false; }
                Object.keys(localStorage).forEach(function (k) {
                    if (/^FileNameS/i.test(k)) { localStorage.removeItem(k); }
                });
                var c = document.querySelector('#selectCount');
                if (c) { c.innerText = '0'; }
                """
            )

    def _click_export_menu(self) -> dict:
        """Open 导出与分析 → 导出文献 and click the Refworks item."""
        try:
            answer = self.driver.execute_script(
                """
                var scope = document.querySelector('.dropdown-analysis-btns') ? '.dropdown-analysis-btns ' : '';
                var items = document.querySelectorAll(scope + 'li.export ul.secondUl li');
                if (!items.length) { items = document.querySelectorAll('li.export ul.secondUl li'); }
                for (var i = 0; i < items.length; i++) {
                    var a = items[i].querySelector('a');
                    if (a && (a.getAttribute('exporttype') || '').toLowerCase() === arguments[0]) {
                        items[i].click();
                        return {clicked: true, text: a.innerText};
                    }
                }
                return {clicked: false, count: items.length};
                """,
                EXPORT_TYPE.lower(),
            )
        except WebDriverException as exc:
            raise self.ExportError(t('crawl.cnki.noExportMenu', err=exc)) from exc
        return answer or {}

    def _export_page_records(self) -> list[str]:
        """Export the accumulated selection once and read its RefWorks list."""
        if self._is_logged_in() is False:
            self.login_wall = True
            raise self.ExportError(t('crawl.cnki.loginNeeded'))
        if self._selection_count() <= 0:
            raise self.ExportError(t('crawl.cnki.nothingSelected'))
        before = list(self.driver.window_handles)
        main = before[0] if before else None
        try:
            menu = self._click_export_menu()
        except self.ExportError:
            self._clear_selection()
            raise
        if not menu.get('clicked'):
            self._clear_selection()
            count = menu.get('count')
            raise self.ExportError(t('crawl.cnki.noExportMenu', err=f'items={count}'))
        handle = self._wait_for_export_window(before)
        if handle is None:
            self._clear_selection()
            if self._is_logged_in() is False:
                self.login_wall = True
                raise self.ExportError(t('crawl.cnki.loginNeeded'))
            raise self.ExportError(t('crawl.cnki.noExportWindow'))
        try:
            self.driver.switch_to.window(handle)
            texts = self._download_export_file()
        finally:
            with contextlib.suppress(WebDriverException):
                self.driver.close()
            if main:
                with contextlib.suppress(WebDriverException):
                    self.driver.switch_to.window(main)
            self._clear_selection()
        if not texts:
            raise self.ExportError(t('crawl.cnki.exportEmpty'))
        return texts

    def _wait_for_export_window(self, before: list[str]):
        """The newest window handle the export click opened, or None."""
        try:
            WebDriverWait(self.driver, self.EXPORT_WAIT).until(lambda _d: len(self.driver.window_handles) > len(before))
        except TimeoutException:
            return None
        handles = [h for h in self.driver.window_handles if h not in before]
        return handles[-1] if handles else None

    def _download_export_file(self) -> list[str]:
        """Click 导出题录文件 and read the full RefWorks download.

        The export page's on-screen list is a preview (measured: 40 selected rows
        rendered as 20 ``li``), so the records are taken from the downloaded
        ``CNKI-…txt`` instead. The file writes a blank line between every field;
        ``_split_refworks`` removes those and splits on ``RT``.
        """
        folder = tempfile.mkdtemp(prefix='cnki-export-')
        try:
            try:
                self.driver.execute_cdp_cmd(
                    'Browser.setDownloadBehavior',
                    {'behavior': 'allow', 'downloadPath': folder, 'eventsEnabled': True},
                )
            except WebDriverException as exc:
                raise self.ExportError(t('crawl.cnki.downloadFailed', err=exc)) from exc
            self._wait_export_page_ready()
            summary = self._page_summary()
            if self._export_forbidden(summary):
                raise self.ExportError(t('crawl.cnki.exportForbidden', err=summary))
            try:
                clicked = self._click_download_button()
            except WebDriverException as exc:
                raise self.ExportError(t('crawl.cnki.downloadFailed', err=exc)) from exc
            if not clicked:
                summary = self._page_summary()
                if self._export_forbidden(summary):
                    raise self.ExportError(t('crawl.cnki.exportForbidden', err=summary))
                raise self.ExportError(t('crawl.cnki.noExportButton', err=summary))
            path = self._wait_download(folder)
            if path is None:
                raise self.ExportError(t('crawl.cnki.downloadFailed', err='timeout'))
            try:
                text = importer.decode_text(path.read_bytes(), path.name)
            except ValueError as exc:
                raise self.ExportError(t('crawl.cnki.downloadFailed', err=exc)) from exc
            records = self._split_refworks(text)
            if not records:
                raise self.ExportError(t('crawl.cnki.exportEmpty'))
            return records
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def _wait_export_page_ready(self) -> None:
        """Let the POST document commit before touching it.

        The export window's handle exists while the POST page is still navigating;
        a CDP/click command sent into that gap answers ``aborted by navigation``.
        """
        deadline = time.monotonic() + self.EXPORT_WAIT
        while time.monotonic() < deadline:
            try:
                if str(self.driver.execute_script('return document.readyState;') or '') == 'complete':
                    return
            except WebDriverException:
                pass
            time.sleep(0.5)

    def _click_download_button(self) -> bool:
        """Wait for the export page's 导出题录文件 link and click it.

        The export window's address returns before its script builds the toolbar
        (measured in a headless session: an immediate look found no button), so
        this polls the page instead of reading it once.
        """
        script = """
        var links = document.querySelectorAll('a');
        for (var i = 0; i < links.length; i++) {
            if ((links[i].title || '').indexOf('导出题录文件') >= 0) {
                links[i].click();
                return true;
            }
        }
        return false;
        """
        deadline = time.monotonic() + self.EXPORT_WAIT
        while time.monotonic() < deadline:
            if self.may_stop():
                raise CrawlerStopped(t('crawl.stopped'))
            try:
                if self.driver.execute_script(script):
                    return True
            except WebDriverException:
                pass
            time.sleep(0.5)
        return False

    @staticmethod
    def _export_forbidden(summary: str) -> bool:
        """The export page itself was refused (measured: headless answers HTTP 403)."""
        text = str(summary or '')
        return any(mark in text for mark in ('403', '无权', '拒绝', 'Forbidden'))

    def _page_summary(self) -> str:
        """Where the export window actually is, for a refusal that can be acted on."""
        try:
            url = str(self.driver.current_url or '')
            title = str(self.driver.title or '')
            body = str(
                self.driver.execute_script("return document.body ? document.body.innerText.slice(0, 160) : '';") or ''
            )
        except WebDriverException:
            return 'unreadable'
        return f'{url} | {title} | {body}'.strip()

    def _wait_download(self, folder: str):
        """The finished file in *folder*, or ``None`` when the budget runs out."""
        deadline = time.monotonic() + self.EXPORT_WAIT
        while time.monotonic() < deadline:
            if self.may_stop():
                raise CrawlerStopped(t('crawl.stopped'))
            files = [p for p in Path(folder).iterdir() if p.suffix != '.crdownload' and p.stat().st_size > 0]
            if files:
                # A download is complete when the progress file is gone; one more
                # look after a short pause is enough for the browser to rename it.
                time.sleep(0.5)
                if not any(p.suffix == '.crdownload' for p in Path(folder).iterdir()):
                    return max(files, key=lambda p: p.stat().st_mtime)
            time.sleep(0.5)
        return None

    @staticmethod
    def _split_refworks(text: str) -> list[str]:
        """One RefWorks block per record, without the download's inter-field blanks."""
        lines = [line.strip() for line in text.replace('\r\n', '\n').replace('\r', '\n').split('\n') if line.strip()]
        records: list[str] = []
        current: list[str] = []
        for line in lines:
            if line.startswith('RT ') and current:
                records.append('\n'.join(current))
                current = []
            current.append(line)
        if current:
            records.append('\n'.join(current))
        return records

    # ─── pager ───────────────────────────────────────────────────

    def _next_page(self) -> str:
        """Click 下一页: ``'ok'`` turned, ``'end'`` no link, ``'failed'`` clicked but stuck."""
        before = self._page_mark()
        try:
            clicked = self.driver.execute_script(
                """
                var links = document.querySelectorAll('.pages a');
                for (var i = 0; i < links.length; i++) {
                    if (links[i].innerText.trim() === '下一页') { links[i].click(); return true; }
                }
                return false;
                """
            )
        except WebDriverException:
            return 'failed'
        if not clicked:
            return 'end'
        try:
            WebDriverWait(self.driver, self.SEARCH_WAIT).until(lambda _d: self._page_mark() != before)
        except TimeoutException:
            self.check_intercept()
            return 'failed'
        return 'ok'

    def _advance_to(self, page: int) -> bool:
        """Drive the pager from page 1 to the stored resume page."""
        current = 1
        while current < page:
            if self._next_page() != 'ok':
                return False
            current += 1
        return True

    def _page_mark(self) -> str:
        try:
            return str(
                self.driver.execute_script(
                    "var e = document.querySelector('.countPageMark'); return e ? e.innerText.trim() : '';"
                )
                or ''
            )
        except WebDriverException:
            return ''

    # ─── the imported record shape ───────────────────────────────

    def _rows_from_refworks(self, text: str) -> list[dict]:
        """The repo's CNKI reader, so a crawled row and an upload cannot disagree."""
        rows, _skipped = importer.parse_cnki(text)
        return rows

    def get_detail(self, url: str) -> dict | None:
        """No per-URL detail step: a record comes from the export page's list."""
        return None
