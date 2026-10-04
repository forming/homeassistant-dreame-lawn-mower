"""Make the repository root importable so ``custom_components`` resolves."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

pytest_plugins = ["pytest_homeassistant_custom_component"]
