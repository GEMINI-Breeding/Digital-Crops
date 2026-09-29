#!/bin/bash
# Show that this project is the upstream SyntheticAutotuning twin plus I/O-only additions.
#
# usage: bash scripts/diff_against_inbox.sh [upstream dir]
#   upstream dir defaults to image-to-l-system's read-only copy, <repo>/inbox/SyntheticAutotuning, found from this
#   project's location (Digital-Crops is the submodule submodules/Digital-Crops of that repository) or $TWIN_UPSTREAM.
#
# What it prints
#   1. every snapshot file that differs from upstream, other than main.cpp and CMakeLists.txt (expected: none),
#      and the files that exist only here (expected: this script, README_DIGITAL_CROPS.md);
#   2. CMakeLists.txt: the diff (expected: BASE_DIRECTORY -> this repository's libs/Helios, comments dropped);
#   3. main.cpp: the number of upstream lines kept, changed and added, and then EVERY upstream line that is not
#      kept verbatim, with its line number. Those lines are the whole of the change to upstream code; all other
#      differences are added lines. Each block of added lines is listed with the function it sits in (diff -p).
# Exit status 1 when a file other than main.cpp / CMakeLists.txt differs, so it can run as a check.
set -u
HERE=$(cd "$(dirname "$0")/.." && pwd)
UP=${1:-${TWIN_UPSTREAM:-$(cd "$HERE/../../../.." 2>/dev/null && pwd)/inbox/SyntheticAutotuning}}
[ -f "$UP/main.cpp" ] || { echo "upstream copy not found: $UP (pass it as the first argument)"; exit 2; }
echo "project : $HERE"
echo "upstream: $UP"
status=0

echo; echo "== 1. snapshot files (config, calib, scripts, spectra, twin, syn2real, documents)"
for d in config calib scripts spectra twin syn2real; do
    diff -rq -x '__pycache__' -x '*.pyc' -x 'diff_against_inbox.sh' "$UP/$d" "$HERE/$d" && echo "  $d/: identical" || status=1
done
for f in config.h TWIN_DESIGN.md HANDOFF_plant_model_lessons.md HANDOFF_vulkan_nan.md PHASE1_FINDINGS.md leaf_labeller.html; do
    cmp -s "$UP/$f" "$HERE/$f" && echo "  $f: identical" || { echo "  $f: DIFFERS"; status=1; }
done

echo; echo "== 2. CMakeLists.txt"
diff "$UP/CMakeLists.txt" "$HERE/CMakeLists.txt"

echo; echo "== 3. main.cpp"
python3 - "$UP/main.cpp" "$HERE/main.cpp" <<'PYEOF'
import difflib, sys
a = open(sys.argv[1]).read().splitlines(); b = open(sys.argv[2]).read().splitlines()
sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
kept = sum(i2 - i1 for op, i1, i2, _, _ in sm.get_opcodes() if op == "equal")
removed = [(i + 1, a[i]) for op, i1, i2, _, _ in sm.get_opcodes() if op in ("replace", "delete") for i in range(i1, i2)]
added = sum(j2 - j1 for op, _, _, j1, j2 in sm.get_opcodes() if op in ("replace", "insert"))
print(f"  upstream lines {len(a)}: kept verbatim {kept}, not kept {len(removed)}; lines added here {added}")
print("  upstream lines not kept verbatim (moved into helper functions or replaced):")
for n, line in removed:
    print(f"    {n:5d}: {line}")
PYEOF
echo; echo "  blocks of added lines, with their enclosing function:"
diff -p -U0 "$UP/main.cpp" "$HERE/main.cpp" | grep '^@@' | sed 's/^/    /'
exit $status
