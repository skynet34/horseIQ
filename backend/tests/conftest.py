import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from horseiq.db import init_db, make_engine  # noqa: E402


@pytest.fixture
def engine(tmp_path):
    eng = make_engine(f"sqlite:///{(tmp_path / 't.db').as_posix()}")
    init_db(eng)
    return eng
