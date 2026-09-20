import json
import logging
import os

from config import Config

logger = logging.getLogger(__name__)


class WorkflowManager:
    """Saves and loads workflow configurations."""

    def __init__(self, workflow_dir: str = None):
        self.workflow_dir = workflow_dir or Config.WORKFLOW_DIR
        os.makedirs(self.workflow_dir, exist_ok=True)

    def save(self, name: str, workflow: dict) -> str:
        path = os.path.join(self.workflow_dir, f'{name}.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(workflow, f, ensure_ascii=False, indent=2)
        logger.info('Workflow saved: %s', path)
        return path

    def load(self, name: str) -> dict | None:
        path = os.path.join(self.workflow_dir, f'{name}.json')
        try:
            with open(path, encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    def list_workflows(self) -> list:
        if not os.path.exists(self.workflow_dir):
            return []
        files = [f for f in os.listdir(self.workflow_dir) if f.endswith('.json')]
        return [f.replace('.json', '') for f in files]

    def delete(self, name: str):
        path = os.path.join(self.workflow_dir, f'{name}.json')
        if os.path.exists(path):
            os.remove(path)
