"""Real-device smoke test for the three newly wired small-model jobs.

One process, one model at a time; every cache root is published by ``core.config`` before the first
transformer import. A failure names the model that broke instead of being hidden by the fast test
tier's deterministic fakes.
"""

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    sys.path.insert(0, str(ROOT / 'backend'))
    from analyzers import NamedEntityRecognizer
    from analyzers.backends.reranker import rerank
    from analyzers.zero_shot import analyze_zero_shot

    frame = pd.DataFrame({'正文': ['张三在北京大学工作', '这部电影很好看']})

    print('[ner] ckip-ner', flush=True)
    entities = NamedEntityRecognizer(mode='bert', model_name='ckiplab/bert-base-chinese-ner').analyze_dataframe(
        frame, '正文'
    )
    print(entities.to_dict(orient='records'), flush=True)

    print('[zero-shot] mnli-xnli', flush=True)
    labels = analyze_zero_shot(frame, '正文', labels='正面,负面')
    print(labels[['正文', 'zero_shot_label', 'zero_shot_score']].to_dict(orient='records'), flush=True)

    print('[rerank] bge-reranker-base', flush=True)
    ranked = rerank('北京大学', ['张三在北京大学工作', '这部电影很好看'])
    print(ranked, flush=True)

    print('SMOKE OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
