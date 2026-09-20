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

    def delete(self, name: str):
        path = self._path_for(name)
        if os.path.exists(path):
            os.remove(path)
