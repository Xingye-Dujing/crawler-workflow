import json
import logging
import os

from core.refs import sanitize_filename

from config import Config
from i18n import t

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

    def path_for(self, name: str) -> str:
        return os.path.join(self.workflow_dir, f'{self.clean_name(name)}.json')

    def save(self, name: str, workflow: dict) -> str:
        clean = self.clean_name(name)
        path = self.path_for(clean)
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
            with open(self.path_for(name), encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    @staticmethod
    def _draft_nodes(draft: dict) -> list:
        """Every node on a saved canvas, serial groups included — a grouped run's members are nodes
        too, and a parameter read that skips them reports a node it simply never looked for."""
        return list(draft.get('nodes') or []) + [
            node for group in draft.get('serialGroups') or [] for node in (group.get('nodes') or [])
        ]

    def captured_params(self, name: str, node_id: str, fingerprint: str) -> tuple[dict, bool]:
        """The node's parameters, and whether they are provably the ones that ran.

        A run record stores a node's fingerprint but not its settings — the canvas file does. When
        the recomputed fingerprint matches the recorded one the parameters are the run's; when it
        does not (the canvas was rewired, or the file is gone) the caller is told so it can say
        「未核对」 rather than filing a plausible-looking guess as provenance.

        Shared by the snapshot capture (``api/biblio``) and the LaTeX report: two readers of "what
        produced these rows" is how one of them starts disagreeing with the run. The report asks per
        node, so this reads the canvas once rather than once for the parameters and again for the
        fingerprint.
        """
        from services.run_store import fingerprints_for_workflow

        if not str(name or '').strip():
            return {}, False
        draft = self.load(name)
        if not draft:
            return {}, False
        # A saved canvas keeps reusable nodes as groups; a RUN record and its captured
        # nodes use the expanded child ids. Expand before the lookup, or every method
        # paragraph/report for a reusable node would be filed as "unverified" even
        # though the file (and the fingerprint) are right there.
        from services.reusable_expand import expand_reusable_workflow

        expanded, error = expand_reusable_workflow(draft)
        if not error:
            draft = expanded
        nodes = self._draft_nodes(draft)
        node = next((n for n in nodes if isinstance(n, dict) and str(n.get('id')) == str(node_id)), None)
        if node is None:
            return {}, False
        computed = fingerprints_for_workflow({'nodes': nodes, 'connections': draft.get('connections') or []})
        verified = str(computed.get(str(node_id)) or '') == str(fingerprint or '')
        return dict(node.get('params') or {}), verified

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
        src = self.path_for(old)
        if not os.path.exists(src):
            return None
        dst = self.path_for(new)
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
        path = self.path_for(name)
        if os.path.exists(path):
            os.remove(path)
