import os
import sys
from pathlib import Path
from fastapi import Request, Response


def find_repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in (here.parent, *here.parents):
        if (parent / 'backend' / 'app').is_dir():
            return parent
    raise RuntimeError('backend package not found')


ROOT = find_repo_root()
BACKEND = ROOT / 'backend'
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.main import app  # noqa: E402,F401
