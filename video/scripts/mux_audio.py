"""Mux the generated ambient loop under a muted Remotion render.

Some Windows sandboxes refuse the temp WAV/MP4 writes Remotion's audio stage
needs. In that case render with ``--muted --disallow-parallel-encoding`` and
run this script; the video stream is copied, the audio is looped and trimmed.
"""

import argparse
import os
import shutil
import subprocess
import sys


def find_binary(env_name: str, name: str) -> str:
    override = os.environ.get(env_name, '').strip()
    if override and os.path.isfile(override):
        return override
    found = shutil.which(name)
    if found:
        return found
    sys.exit(f'{name} not found; set {env_name} to the executable path')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('video', help='muted render (mp4)')
    parser.add_argument('output', help='audio-muxed output (mp4)')
    parser.add_argument('--audio', default='public/audio/ambient.wav')
    parser.add_argument('--fade-out', type=float, default=4.0)
    args = parser.parse_args()

    ffmpeg = find_binary('CIXI_FFMPEG', 'ffmpeg')
    ffprobe = find_binary('CIXI_FFPROBE', 'ffprobe')
    duration = float(
        subprocess.check_output(
            [ffprobe, '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', args.video], text=True
        ).strip()
    )
    fade_start = max(0.0, duration - max(0.0, args.fade_out))
    filters = f'afade=t=out:st={fade_start:.2f}:d={args.fade_out:.2f}' if args.fade_out else 'anull'
    subprocess.run(
        [
            ffmpeg,
            '-y',
            '-loglevel',
            'error',
            '-i',
            args.video,
            '-stream_loop',
            '-1',
            '-i',
            args.audio,
            '-map',
            '0:v',
            '-map',
            '1:a',
            '-c:v',
            'copy',
            '-c:a',
            'aac',
            '-b:a',
            '128k',
            '-af',
            filters,
            '-shortest',
            args.output,
        ],
        check=True,
    )
    print(f'{args.output}: {duration:.1f}s with {args.audio}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
