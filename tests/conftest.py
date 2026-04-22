"""Shared pytest fixtures + path setup."""
import os
import sys
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
CONTRACT = os.path.join(ROOT, "contract")
FIXTURES = os.path.join(CONTRACT, "fixtures")
GOLDEN = os.path.join(CONTRACT, "golden")
DIST = os.path.join(ROOT, "dist")

# Make src/ importable so test files can `from extract import ...`
if SRC not in sys.path:
    sys.path.insert(0, SRC)


@pytest.fixture
def root_dir():
    return ROOT


@pytest.fixture
def src_dir():
    return SRC


@pytest.fixture
def fixtures_dir():
    return FIXTURES


@pytest.fixture
def golden_dir():
    return GOLDEN


@pytest.fixture
def dist_dir():
    return DIST
