"""Free-video-memory admission control for this one 8 GB laptop card.

``torch.cuda.mem_get_info`` is the same API on Windows, Linux and macOS and needs no external
executable, so this probe cannot accidentally spawn a console window or parse ``nvidia-smi`` text.
A machine without CUDA answers a named refusal instead of an empty number a trainer could mistake
for "unlimited memory".
"""

import argparse
import json
import sys

#: A 110M classifier with a 32-row batch and 512 tokens peaks around 2.5 GB; leave room for the OS
#: compositor (about 1.4 GB on this machine) and for allocator fragmentation.
MIN_TRAIN_FREE_MB = 4500
MIN_INFER_FREE_MB = 1500


class GpuUnavailableError(RuntimeError):
    """No usable CUDA device, or less free memory than the caller needs."""


def probe() -> dict:
    """``(available, free_mb, total_mb, device)`` for this process, without importing transformers."""
    try:
        import torch
    except ImportError as exc:
        raise GpuUnavailableError('torch is not installed; the GPU tier needs the optional stack') from exc
    if not torch.cuda.is_available():
        raise GpuUnavailableError(
            'CUDA is not available in this torch build; refusing instead of falling back silently'
        )
    free, total = torch.cuda.mem_get_info()
    return {
        'available': True,
        'free_mb': round(free / (1024 * 1024)),
        'total_mb': round(total / (1024 * 1024)),
        'device': torch.cuda.get_device_name(0),
    }


def require(kind: str = 'infer') -> dict:
    """Refuse by name when there is not enough free video memory for the requested job."""
    info = probe()
    floor = MIN_TRAIN_FREE_MB if kind == 'train' else MIN_INFER_FREE_MB
    if info['free_mb'] < floor:
        raise GpuUnavailableError(
            f'{info["device"]}: {info["free_mb"]} MiB free, need {floor} MiB for {kind}; '
            'close the other GPU application and retry'
        )
    info['required_mb'] = floor
    info['kind'] = kind
    return info


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kind', choices=('infer', 'train'), default='infer')
    args = parser.parse_args()
    try:
        print(json.dumps(require(args.kind), ensure_ascii=False, indent=2))
        return 0
    except GpuUnavailableError as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}, ensure_ascii=False, indent=2))
        return 1


if __name__ == '__main__':
    sys.exit(main())
