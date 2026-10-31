"""Check local Markdown links across the maintained documentation (not historical meeting notes)."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
paths = [ROOT / "README.md", ROOT / "CONTRIBUTING.md", ROOT / "AGENTS.md"]
paths += list((ROOT / "docs").rglob("*.md"))
paths += list((ROOT / "backend").rglob("README.md"))
paths += list((ROOT / "apps").rglob("README.md"))
errors = []
for path in paths:
    if "node_modules" in path.parts:
        continue
    for link in re.findall(r"\[[^\]]*\]\(([^\s)]+)(?:\s+[^)]*)?\)", path.read_text()):
        if "://" in link or link.startswith(("#", "mailto:")):
            continue
        target = link.split("#", 1)[0]
        if target and not (path.parent / target).exists():
            errors.append(f"{path.relative_to(ROOT)} -> {link}")
if errors:
    raise SystemExit("Broken documentation links:\n" + "\n".join(errors))
print("Local documentation links OK.")
