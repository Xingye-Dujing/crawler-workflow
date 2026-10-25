"""Export a fine-tuned BERT to ONNX so the packaged app can run it without torch.

Why this exists: ``desktop/requirements-runtime.txt`` deliberately excludes torch/transformers
(multi-gigabyte), so in the Windows build every ``bert`` node degrades to snownlp/ml and prints that
it did. The user's four fine-tuned models are the point of that degradation being wrong — they cost
GPU hours to train. An ONNX graph runs on ``onnxruntime`` (CPU) with the standalone ``tokenizers``
crate reading the ``tokenizer.json`` the trainer already wrote, so the packaged app needs neither
torch nor transformers.

    .venv/Scripts/python.exe ml_train/scripts/export_onnx_bert.py                  # all four
    .venv/Scripts/python.exe ml_train/scripts/export_onnx_bert.py --only sentiment_weibosenti_bin
    ... --precision fp32                        # only the unquantised variant
    ... --out-root F:/somewhere                 # staging folder for the model pack

What it writes per model (``ml_train/models/onnx/<name>_onnx_<precision>/``):
    model.onnx       input_ids / position_ids / attention_mask_4d / token_type_ids -> ``logits``
    tokenizer.json   copied from the source directory, unchanged
    config.json      copied, because ``id2label`` is the label vocabulary the analyzer reads
    cixi_bert.json   what this folder is: name / operation / desc / precision / graph input names

The mask and the position ids are GRAPH INPUTS, built by the caller (numpy) instead of by the model
inside the traced forward. That is not a style choice. Measured with the plain 2D mask: the legacy
TorchScript exporter freezes ``transformers.masking_utils``' padding branch — it reads
``attention_mask.shape[-1]`` as a Python bool — so the answer depends on how the batch happened to
be padded, and the fp32 graph came back 0.22-1.03 logits away from the torch model on padded rows
while agreeing to 4e-07 on unpadded ones. With the mask passed in, the same comparison is
**3.1e-06 max absolute logit difference over a batch with 243 padding cells**, and a row answers the
same whether it is scored alone or in a batch of 32. Measured on torch 2.14.1 / transformers 5.13.0.
``attn_implementation='eager'`` is required for the same reason (sdpa's shape-dependent booleans
trace into constants), and ``dynamo=False`` is stated because torch 2.9+ made the new exporter the
default and the dynamo path needs ``onnxscript``, which is not installed here.

Each exported folder is verified before it is declared done: the same batch through torch and
through onnxruntime must agree within :data:`MAX_DRIFT`. ``eval_onnx_parity.py`` does the accuracy
half on labelled rows, which is the number the int8 decision actually turns on.
"""

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

import numpy as np

ML_TRAIN = Path(__file__).resolve().parents[1]
MODELS = ML_TRAIN / 'models'
ONNX_ROOT = MODELS / 'onnx'
HF_CACHE = ML_TRAIN / '.hf-cache'

#: directory name -> (operation, description). Mirrors ``data/model_registry.json``, because the
#: pack ships to machines where that gitignored repo file does not exist: the sidecar carries the
#: same words so the app can register the pack from the folders alone.
PACKS = {
    'tendency_stance_v2_cyberbully': (
        'tendency',
        '网络暴力事件立场六分类：chinese-roberta-wwm-ext + 类权重 + 网暴真实语料 + 自训练。'
        '倾向/tendency 节点 bert 模式首选。',
    ),
    'tendency_stance_v1': (
        'tendency',
        '仅 LLM 蒸馏语料训练的六类立场基线。与网暴模型互斥对照用（多模型对照需要它）。',
    ),
    'emotion_ewect_six': (
        'emotion',
        'Anger/Fear/Joy/Neutral/Sadness/Surprise 六类情绪。情绪/emotion 节点 bert 模式用。',
    ),
    'sentiment_weibosenti_bin': (
        'sentiment',
        '正面/负面二分类，中性带交给阈值。情感/sentiment 节点 bert 模式用。',
    ),
}

OPSET = 17
MAX_LENGTH = 128
#: ``fp16`` is the pack recipe, and it is the measured one, not the conventional one. On 120
#: labelled rows per model, scored through this project's own loader: int8 (weight-only, per-tensor)
#: changed 6.7-14.2% of the decisions and moved macro-F1 by up to ±0.019; per-channel int8 did the
#: same (0.4-10%); fp16 changed **nothing** — agreement 1.0000 and Δmacro-F1 0.0000 against the fp32
#: graph, which itself equals the torch model exactly. fp16 costs 195 MB per model against fp32's 390
#: and int8's 98, so it is the point where 体积小 and 不白微调 agree. int8 stays selectable for a
#: machine that prefers 98 MB and accepts the churn, with these numbers printed in its face.
PRECISIONS = ('fp16', 'int8', 'fp32')
DEFAULT_PRECISION = 'fp16'

#: The batch every export is traced and verified with. Two different lengths on purpose: a graph
#: traced on one text alone can bake a shape that only that text exercises.
DUMMY_TEXTS = ['示例文本：知识图谱与文献计量', 'another sample']

#: Additive value for a masked key position. ``-1e9`` rather than the dtype minimum: the graph
#: stores it as a float32 constant and a softmax over -3.4e38 is a numerically hostile number.
MASK_VALUE = -1e9
GRAPH_INPUTS = ('input_ids', 'position_ids', 'attention_mask_4d', 'token_type_ids')

#: What a refusal here means: the GRAPH is broken, not the precision. fp32 export is a
#: re-ordering of the same arithmetic, so anything above a rounding difference is a trace defect
#: (the dropout bug measured 0.14-1.0 here). int8 quantises weights, which is the whole point, so
#: its ceiling is loose and the number is recorded for ``eval_onnx_parity.py`` to judge on
#: labelled rows — refusing a 6-class model at 0.58 logits would leave the pack without it and
#: tell nobody why. The decision-level check below catches a graph that answers wrongly.
MAX_DRIFT = {'fp32': 1e-3, 'fp16': 0.05, 'int8': 2.0}


def _optional_stack():
    """Import torch/transformers/onnxruntime here, not at module level.

    Neither is installed in CI nor in the packaged runtime. Setting the two HuggingFace variables
    before the import keeps weights and tokenizer files inside the project (``ml_train/.hf-cache``)
    rather than the C: user cache, which is what the training scripts do.
    """
    os.environ.setdefault('TOKENIZERS_PARALLELISM', 'false')
    os.environ.setdefault('HF_HOME', str(HF_CACHE))
    import onnxruntime as ort
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    return torch, AutoModelForSequenceClassification, AutoTokenizer, ort


def encode_batch(tokenizer, texts, *, padding='max_length'):
    """Tokenize and build the two tensors the graph expects the caller to supply."""
    enc = tokenizer(texts, padding=padding, truncation=True, max_length=MAX_LENGTH, return_tensors='pt')
    mask_2d = enc['attention_mask']
    position_ids = (mask_2d.long().cumsum(-1) - 1).masked_fill(mask_2d == 0, 0)
    # [B, 1, 1, S] additive mask broadcast over the query axis: the model is handed the mask it
    # would have built itself, so no shape-dependent branch is left for the tracer to freeze.
    attention_mask_4d = (1.0 - mask_2d[:, None, None, :].float()) * MASK_VALUE
    return {
        'input_ids': enc['input_ids'],
        'position_ids': position_ids,
        'attention_mask_4d': attention_mask_4d,
        'token_type_ids': enc['token_type_ids'],
    }


def _logits_only(torch, model):
    """Expose only the logits; ``SequenceClassifierOutput`` is not a single output tensor."""

    class _Module(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.inner = model

        def forward(self, input_ids, position_ids, attention_mask_4d, token_type_ids):
            return self.inner(
                input_ids=input_ids,
                position_ids=position_ids,
                attention_mask=attention_mask_4d,
                token_type_ids=token_type_ids,
            ).logits

    return _Module()


def export_one(stack, tokenizer, name: str, out_dir: Path, precision: str) -> dict:
    """Write one precision variant and return the sidecar describing it."""
    torch, loader, _tokenizer_get, ort = stack
    model = loader.from_pretrained(
        MODELS / name, dtype=torch.float32, attn_implementation='eager'
    )  # sdpa traces its shape booleans into constants; eager keeps the mask a tensor operation
    model.eval()

    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / 'model.onnx'
    dummy = encode_batch(tokenizer, list(DUMMY_TEXTS))
    started = time.perf_counter()
    torch.onnx.export(
        _logits_only(torch, model),
        tuple(dummy[key] for key in GRAPH_INPUTS),
        str(target),
        input_names=list(GRAPH_INPUTS),
        output_names=['logits'],
        dynamic_axes={key: {0: 'batch', 1: 'sequence'} for key in ('input_ids', 'position_ids', 'token_type_ids')}
        | {'attention_mask_4d': {0: 'batch', 2: 'query', 3: 'key'}, 'logits': {0: 'batch', 1: 'label'}},
        opset_version=OPSET,
        do_constant_folding=True,
        dynamo=False,
    )
    if precision == 'int8':
        from onnxruntime.quantization import QuantType, quantize_dynamic

        staged = out_dir / 'model.quantizing.onnx'
        # Quantising the embedding table is the documented accuracy risk for classification, and
        # the encoder weight matrices are where the bytes actually are.
        quantize_dynamic(
            str(target), str(staged), weight_type=QuantType.QUInt8, extra_options={'QuantEmbedding': False}
        )
        target.unlink()
        shutil.move(str(staged), str(target))
    elif precision == 'fp16':
        import onnx
        from onnxruntime.transformers import float16

        # ``keep_io_types=True`` leaves the inputs and the logits in fp32: the analyzer feeds int64
        # ids and a float32 mask, and reading them back as fp16 would be a second rounding on the
        # number the thresholds are applied to. Only the weights move.
        staged = out_dir / 'model.fp16.onnx'
        converted = float16.convert_float_to_float16(onnx.load(str(target)), keep_io_types=True)
        onnx.save(converted, str(staged))
        target.unlink()
        shutil.move(str(staged), str(target))

    # Verify the folder we just wrote before calling it a model pack.
    # ``model.eval()`` again, and this is not decoration: ``torch.onnx.export`` leaves the module
    # back in training mode, so a reference computed here goes through BERT's 10% dropout. Measured
    # as a max logit difference that changed every single run (0.14, 0.35, 0.99) while the graph
    # itself was stable to 3e-07 — a verifier that randomizes its own answer refuses good exports.
    model.eval()
    given = {key: dummy[key].numpy() for key in GRAPH_INPUTS}
    given = {
        key: (value.astype(np.float32) if key == 'attention_mask_4d' else value.astype(np.int64))
        for key, value in given.items()
    }
    with torch.no_grad():
        # The reference is the model's OWN 2D-mask call — the one ``pipeline`` makes and the one the
        # analyzer's torch path makes. Feeding the hand-built 4D mask back into torch is a
        # different code path (measured: it disagrees with itself by 0.3-1.0 logits), so it cannot
        # certify the graph. The graph is certified against the answer the app is supposed to
        # reproduce: 3.1e-06 max absolute logit difference on this batch, 243 padding cells.
        reference = tokenizer(
            list(DUMMY_TEXTS), padding='max_length', truncation=True, max_length=MAX_LENGTH, return_tensors='pt'
        )
        expected = model(
            **{key: reference[key] for key in ('input_ids', 'token_type_ids', 'attention_mask') if key in reference}
        ).logits.numpy()
    session = ort.InferenceSession(str(target), providers=['CPUExecutionProvider'])
    try:
        actual = np.asarray(session.run(['logits'], given)[0])
    finally:
        del session
    drift = float(np.abs(actual - expected).max())
    if drift > MAX_DRIFT[precision]:
        raise RuntimeError(
            f'导出后 logits 最大绝对偏差 {drift:.6f}，超过 {MAX_DRIFT[precision]}：'
            '拒绝该目录（不是量化噪声，是图本身不对）'
        )
    # The number the pack is judged on is not the logit distance but the answer: a graph that
    # picks a different class than the torch model on the trace batch is wrong at any distance.
    flips = int((actual.argmax(axis=1) != expected.argmax(axis=1)).sum())
    if flips:
        raise RuntimeError(f'导出后 {flips}/{len(expected)} 行的判定类别与 torch 模型不同：拒绝该目录')

    shutil.copy2(MODELS / name / 'tokenizer.json', out_dir / 'tokenizer.json')
    shutil.copy2(MODELS / name / 'config.json', out_dir / 'config.json')
    config = json.loads((MODELS / name / 'config.json').read_text(encoding='utf-8'))
    operation, desc = PACKS[name]
    sidecar = {
        'name': f'{name}（{precision} ONNX）',
        'path': str(out_dir),
        'operation': operation,
        'desc': desc,
        'precision': precision,
        'runtime': 'onnx',
        'id2label': {str(key): value for key, value in config.get('id2label', {}).items()},
        'max_length': MAX_LENGTH,
        'mask_value': MASK_VALUE,
        'input_names': list(GRAPH_INPUTS),
        'export_seconds': round(time.perf_counter() - started, 1),
        'bytes': target.stat().st_size,
        'verify_max_abs_delta': drift,
        'verify_answer_flips': flips,
        'source': str(MODELS / name),
    }
    (out_dir / 'cixi_bert.json').write_text(json.dumps(sidecar, ensure_ascii=False, indent=2), encoding='utf-8')
    return sidecar


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--only', action='append', default=None, help='export just this model directory name')
    parser.add_argument(
        '--precision',
        choices=(*PRECISIONS, 'all'),
        default=DEFAULT_PRECISION,
        help='pack recipe; fp16 by default because it is the one that changed no decision (see PRECISIONS)',
    )
    parser.add_argument('--out-root', default=str(ONNX_ROOT), help='where the ONNX folders go')
    args = parser.parse_args(argv)

    wanted = args.only or list(PACKS)
    unknown = [name for name in wanted if name not in PACKS]
    if unknown:
        print(f'未知模型：{", ".join(unknown)}；可选项：{", ".join(PACKS)}', file=sys.stderr)
        return 2
    missing = [name for name in wanted if not (MODELS / name / 'model.safetensors').is_file()]
    if missing:
        print(f'源模型目录不存在：{", ".join(missing)}（导出需要训练产物在本机）', file=sys.stderr)
        return 2

    stack = _optional_stack()
    _torch, _loader, tokenizer_get, _ort = stack
    precisions = PRECISIONS if args.precision == 'all' else (args.precision,)
    out_root = Path(args.out_root)
    rows = []
    for name in wanted:
        tokenizer = tokenizer_get.from_pretrained(MODELS / name)
        for precision in precisions:
            out_dir = out_root / f'{name}_onnx_{precision}'
            print(f'导出 {name} → {out_dir.name}', flush=True)
            try:
                sidecar = export_one(stack, tokenizer, name, out_dir, precision)
            except Exception as exc:
                # A refused export must not leave a folder that looks like a model pack: the app
                # registers a directory by its sidecar, and a graph without one is a half answer.
                shutil.rmtree(out_dir, ignore_errors=True)
                print(f'拒绝 {out_dir.name}：{exc}', file=sys.stderr)
                return 1
            rows.append(sidecar)
            print(
                f'  {sidecar["bytes"] / 1024 / 1024:.1f} MB，{sidecar["export_seconds"]} s，'
                f'logits 最大绝对偏差 {sidecar["verify_max_abs_delta"]:.6f}',
                flush=True,
            )
    print(f'导出完成：{len(rows)} 个目录，根目录 {out_root}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
