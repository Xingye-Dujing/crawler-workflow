from collections import Counter


class StatsService:
    """Statistical analysis for workflow results."""

    @staticmethod
    def emotion_distribution(data: list) -> dict:
        """Label → row count. The charts and the history series plot counts,
        so the per-row confidence is deliberately not collected here."""
        counter = Counter(item['emotion'] for item in data if item.get('emotion'))
        return {
            'labels': list(counter.keys()),
            'values': list(counter.values()),
        }

    @staticmethod
    def tendency_distribution(data: list) -> dict:
        counter = Counter(item['tendency'] for item in data if item.get('tendency'))
        return {
            'labels': list(counter.keys()),
            'values': list(counter.values()),
        }
