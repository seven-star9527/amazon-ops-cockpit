"""Explicit installation into an external venv; never modify global packages."""
import argparse
import shutil
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from b_ops.paths import data_root


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', type=Path)
    parser.add_argument('--test', action='store_true')
    args = parser.parse_args()
    target = data_root(args.data_dir) / 'venvs' / 'readonly-v1'
    if target == ROOT or ROOT in target.parents:
        parser.error('venv must be outside the installed skill')
    if sys.version_info < (3, 11):
        parser.error('Python 3.11 or newer is required')
    uv = shutil.which('uv')
    if not (target / 'pyvenv.cfg').exists():
        venv.EnvBuilder(with_pip=not bool(uv)).create(target)
    python = target / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
    installer = [uv, 'pip', 'install', '--python', str(python)] if uv else [str(python), '-m', 'pip', 'install']
    requirement = ROOT / 'runtime' / ('requirements-test.txt' if args.test else 'requirements-runtime.txt')
    subprocess.run([*installer, '-r', str(requirement)], check=True)
    print(python)


if __name__ == '__main__':
    main()
