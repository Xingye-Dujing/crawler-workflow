import json
import logging
import os

from config import Config
from i18n import t
from utils.helpers import sanitize_filename

logger = logging.getLogger(__name__)


class WorkflowManager:
    """Saves and loads workflow configurations."""

    # A name typed in the UI reaches the filesystem, so it is capped and must
    # not be able to walk out of workflow_dir: the guard lives here, not at the
    # endpoints, so every caller inherits it.
    MAX_NAME_LENGTH = 60
    DEFAULT_NAME = 'untitled'

    def __init__(self, workflow_dir: str = None):
        self.workflow_dir = workflow_dir or Config.WORKFLOW_DIR
        os.makedirs(self.workflow_dir, exist_ok=True)

    def clean_name(self, name: str) -> str:
        """Turn a user-typed workflow name into a safe file stem."""
        clean = sanitize_filename(name)[: self.MAX_NAME_LENGTH]
        return clean or self.DEFAULT_NAME

    def _path_for(self, name: str) -> str:
        return os.path.join(self.workflow_dir, f'{self.clean_name(name)}.json')

    def save(self, name: str, workflow: dict) -> str:
        clean = self.clean_name(name)
        path = self._path_for(clean)
        # The name travels inside the file too: a run reports it to the
        # execution history, and a reloaded canvas has to know its own name.
        payload = dict(workflow or {})
        payload['name'] = clean
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        logger.info(t('store.workflow_saved', path=path))
        return path

    def load(self, name: str) -> dict | None:
        try:
            with open(self._path_for(name), encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    def list_workflows(self) -> list:
        if not os.path.exists(self.workflow_dir):
            return []
        files = [f for f in os.listdir(self.workflow_dir) if f.endswith('.json')]
        return [f.replace('.json', '') for f in files]

    def describe(self) -> list:
        """One object per saved file: what the management panel draws.

        The list used to be bare stems, which forced the panel to fetch each file
        to say anything useful (and the old 「打开」 picker could not show what a
        name would overwrite). A corrupt file is STILL a row — with ``broken`` set —
        because the panel must be able to delete the file the loader refuses to open;
        dropping it here would strand it invisible on disk.
        """
        out = []
        for name in self.list_workflows():
            path = os.path.join(self.workflow_dir, f'{name}.json')
            entry = {'name': name, 'nodes': 0, 'labels': [], 'size': 0, 'mtime': 0, 'broken': False}
            try:
                stat = os.stat(path)
                entry['size'] = stat.st_size
                entry['mtime'] = int(stat.st_mtime)
            except OSError:
                entry['broken'] = True
            try:
                with open(path, encoding='utf-8') as f:
                    payload = json.load(f)
                nodes = (payload or {}).get('nodes') or []
                entry['nodes'] = len(nodes)
                # The name nodes are what the run records are keyed by — showing
                # them tells the user which "files" share a run history.
                entry['labels'] = sorted(
                    {
                        str((n.get('params') or {}).get('workflow_name') or '').strip()
                        for n in nodes
                        if n.get('type') == 'name' and str((n.get('params') or {}).get('workflow_name') or '').strip()
                    }
                )[:4]
            except (OSError, ValueError):
                entry['broken'] = True
            out.append(entry)
        out.sort(key=lambda e: str(e['name']).lower())
        return out

    def rename(self, old: str, new: str) -> str | None:
        """Move ``old.json`` to ``new.json``, keeping the name inside the file honest.

        Returns the new stem, or ``None`` when the old file is not there. The inner
        ``name`` field is rewritten because that is what a load reports back as the
        canvas's ambient name — a file that still says the old name would rename
        itself straight back on the next save. A taken target is refused by the
        CALLER (the route answers 409); this method never overwrites, so a rename
        cannot destroy a third workflow the way a same-name save deliberately does.
        """
        src = self._path_for(old)
        if not os.path.exists(src):
            return None
        dst = self._path_for(new)
        if os.path.exists(dst):
            raise FileExistsError(dst)
        try:
            with open(src, encoding='utf-8') as f:
                payload = json.load(f)
            payload = dict(payload or {})
            payload['name'] = self.clean_name(new)
        except ValueError:
            # A corrupt file can still be renamed (the panel may want a readable
            # name for it); keep the bytes, fix the inner name only if parseable.
            payload = None
        if payload is not None:
            with open(dst, 'w', encoding='utf-8') as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.remove(src)
        else:
            os.replace(src, dst)
        return self.clean_name(new)

    def delete(self, name: str):
        path = self._path_for(name)
        if os.path.exists(path):
            os.remove(path)
