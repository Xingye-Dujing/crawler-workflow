from collections import Counter


class StatsService:
    """Statistical analysis for workflow results."""

    @staticmethod
    def emotion_distribution(data: list) -> dict:
        labels = []
        values = []
        for item in data:
            emotion = item.get('emotion')
            if emotion:
                labels.append(emotion)
                values.append(item.get('confidence', 0.5))
        counter = Counter(labels)
        return {
            'labels': list(counter.keys()),
            'values': list(counter.values()),
        }

    @staticmethod
    def tendency_distribution(data: list) -> dict:
        labels = []
        values = []
        for item in data:
            tendency = item.get('tendency')
            if tendency:
                labels.append(tendency)
                values.append(item.get('confidence', 0.5))
        counter = Counter(labels)
        return {
            'labels': list(counter.keys()),
            'values': list(counter.values()),
        }
