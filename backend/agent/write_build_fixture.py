"""Writes every guide's participant attributes, as Build.attributes() publishes them, into the glasses' unit test
resources (android/app/src/test/resources/build_attributes/<guide>.properties, plus guides.txt listing them), so
BuildAttributesFixtureTest checks that the glasses read what the agent sends. Run after changing a task file or
Build.attributes(): `python write_build_fixture.py` in backend/agent."""

import glob
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))
from guide import Build, load_guide  # noqa: E402

out = Path(__file__).parents[2] / "android/app/src/test/resources/build_attributes"
out.mkdir(parents=True, exist_ok=True)
names = []
for p in sorted(glob.glob(str(Path(__file__).parent / "guides/*"))):
    guide = load_guide(p)
    names.append(guide.name)
    attrs = Build(guide, "fixture").attributes()
    # java.util.Properties: one key=value per line, newlines in a value written as \n.
    lines = [f"{k}={v.replace(chr(10), chr(92) + 'n')}" for k, v in sorted(attrs.items())]
    (out / f"{guide.name}.properties").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
(out / "guides.txt").write_text("\n".join(names) + "\n", encoding="utf-8", newline="\n")
print(f"{len(names)} guides written to {out}")
