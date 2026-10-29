"""Resolve mutable data independently of the installed skill."""
import os
from pathlib import Path


def data_root(value=None):
    configured = value or os.getenv('AMAZON_OPS_DATA_DIR')
    if configured:
        target = Path(configured).expanduser().resolve()
        installed = Path(__file__).resolve().parents[2]
        if target == installed or installed in target.parents:
            raise ValueError("data directory must be outside the installed skill")
        return target
    base = Path(os.getenv('LOCALAPPDATA') or Path.home() / '.local' / 'share')
    return (base / 'amazon-ops-cockpit').resolve()
