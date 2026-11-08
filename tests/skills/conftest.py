"""The skill scripts are plain scripts, not a package: put their folders on the import path, as running them does."""
import sys
from pathlib import Path

SKILLS = Path(__file__).parents[2] / ".claude" / "skills"
for skill in ("deploy", "push", "release"):
    sys.path.insert(0, str(SKILLS / skill))
