"""§184 negative control: the term-shape check must FAIL on the two bugs of §183.

A gate that has never been red is a gate nobody knows the shape of (§177's lesson about the
`UnitsFloor` that had never bound). This script:

1. copies the sts package to a scratch directory,
2. injects bug ① (`DurationTurns` as a term instead of a bare int),
3. rebuilds into that scratch dir and runs `rdcf_verify.py` against it -- **must be red**, and the
   message must carry the JSON text,
4. restores bug ② (`sel.allEnemies` with a cardinality object) -- also must be red,
5. cleans up and re-runs the untouched build -- **must be green**.

Everything happens under `native/_negctl_184/`; `packages/sts` is never touched, so a crash in the
middle cannot leave the repo in a half-edited state (the §183 lesson about `open(..., "w")`).
"""
import io
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRATCH = os.path.join(HERE, "_negctl_184")
PYTHON = sys.executable


def build(document, out_dir):
    """Compile one source document into `out_dir`.

    `build.py` has no `--out` (it reads both paths from the package manifest), so this calls the
    compiler directly with the same flags `build.py` passes -- a scratch copy must never overwrite
    the checked-in image.
    """
    return subprocess.run(
        [PYTHON, "-B", os.path.join(ROOT, "tools", "contentc", "compile.py"),
         "--src", document, "--out-dir", out_dir,
         "--full-name", "content.sts.rdcf", "--core-name", "content.sts.core.rdcf", "--quiet"],
        cwd=os.path.join(ROOT, "tools", "contentc"), capture_output=True,
    )


def text_of(result):
    """Subprocess output as text. The local console is GBK, so never assume UTF-8 (§1)."""
    raw = (result.stdout or b"") + (result.stderr or b"")
    return raw.decode("utf-8", "replace")


def verify(out_dir):
    return subprocess.run(
        [PYTHON, os.path.join(ROOT, "tools", "rdcf_verify.py"),
         os.path.join(out_dir, "manifest.json")],
        cwd=ROOT, capture_output=True,
    )


def main():
    source = os.path.join(ROOT, "tools", "contentc", "packages", "sts")
    if os.path.isdir(SCRATCH):
        shutil.rmtree(SCRATCH)
    os.makedirs(SCRATCH)

    fail = 0
    # ---- baseline: the untouched document must be green -------------------------------------
    package = os.path.join(SCRATCH, "sts")
    shutil.copytree(source, package)
    out = os.path.join(SCRATCH, "out")
    built = build(os.path.join(package, "sts.roguedeck.json"), out)
    if built.returncode != 0:
        print("!! baseline build failed:\n" + text_of(built)[-2000:])
        return 2
    res = verify(out)
    green = "RDCF_VERIFY PASS" in text_of(res)
    print("baseline:", "GREEN (correct)" if green else "RED (the check is broken)")
    if not green:
        print(text_of(res)[-2000:])
        fail += 1

    # ---- bug ①: DurationTurns written as a term ---------------------------------------------
    path = os.path.join(package, "sts.roguedeck.json")
    original = io.open(path, encoding="utf-8").read()
    doc = json.loads(original)
    # **Exactly one** occurrence, on purpose: with a single `applyStatus` written as a term the
    # compiler would quietly declare that opcode's field F_TERM and every reader would cope -- the
    # bug needs *mixed* shapes (sixteen cards write the bare int, one writes a term), because that is
    # when the field kind degrades to `F_JSON` and the kernel refuses to read it at all.
    injected = [0]  # a list, because `global` inside a nested function means module scope

    def inject(node):
        if isinstance(node, dict):
            if node.get("kind") == "node.applyStatus" and injected[0] == 0:
                node["value"]["DurationTurns"] = {"kind": "const", "value": {"Value": 0}}
                injected[0] += 1
            for value in node.values():
                inject(value)
        elif isinstance(node, list):
            for value in node:
                inject(value)

    for card in doc["Cards"]:
        inject(card["Program"]["Root"])
        if injected[0]:
            break
    assert injected[0] == 1, injected[0]
    io.open(path, "w", encoding="utf-8", newline="\n").write(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
    )
    built = build(os.path.join(package, "sts.roguedeck.json"), out)
    if built.returncode != 0:
        print("!! bug ① did not even compile -- that would make the check untested:",
              text_of(built)[-1500:])
        fail += 1
    else:
        res = verify(out)
        res = verify(out)
        out_text = text_of(res)
        red = "RDCF_VERIFY FAIL" in out_text or res.returncode != 0
        # The message has to **name the shape**, not just say "fail": a gate that reds without
        # telling you which term is wrong is a gate you debug from scratch every time.
        # The message must name **both** the mechanism and the field: "F_JSON" alone leaves you
        # grepping sixteen cards for the one that disagreed.
        mentions = "F_JSON" in out_text
        names_it = "DurationTurns" in out_text and "node.applyStatus" in out_text
        print("bug ① (DurationTurns as a term):",
              "RED (correct)" if red else "GREEN -- THE CHECK IS BLIND",
              "| names the JSON text:", mentions and names_it)
        if not (red and mentions and names_it):
            for line in out_text.splitlines():
                if "F_JSON" in line or "FAIL" in line:
                    print("   ", line.strip()[:300])
            fail += 1

    # ---- back to the original document -----------------------------------------------------
    io.open(path, "w", encoding="utf-8", newline="\n").write(original)
    built = build(os.path.join(package, "sts.roguedeck.json"), out)
    if built.returncode != 0:
        print("!! rebuild after the first injection failed")
        return 2

    # ---- bug ②: sel.allEnemies with a cardinality object -----------------------------------
    doc = json.loads(original)

    def first_all_enemies(node, out):
        if isinstance(node, dict):
            if node.get("kind") == "sel.allEnemies":
                out.append(node)
            for value in node.values():
                first_all_enemies(value, out)
        elif isinstance(node, list):
            for value in node:
                first_all_enemies(value, out)
        return out

    selector = first_all_enemies(doc, [])[0]
    assert selector["kind"] == "sel.allEnemies", selector["kind"]
    selector["value"] = {"Cardinality": "Many"}
    io.open(path, "w", encoding="utf-8", newline="\n").write(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
    )
    built = build(os.path.join(package, "sts.roguedeck.json"), out)
    if built.returncode != 0:
        print("!! bug ② did not compile:",
              text_of(built)[-1500:])
        fail += 1
    else:
        res = verify(out)
        red = "RDCF_VERIFY FAIL" in text_of(res) or res.returncode != 0
        print("bug ② (sel.allEnemies with a cardinality object):",
              "RED (correct)" if red else "GREEN -- THE CHECK IS BLIND")
        if not red:
            print(res.stdout[-1800:])
            fail += 1

    # ---- cleanup + final green -------------------------------------------------------------
    io.open(path, "w", encoding="utf-8", newline="\n").write(original)
    built = build(os.path.join(package, "sts.roguedeck.json"), out)
    res = verify(out) if built.returncode == 0 else built
    final_green = "RDCF_VERIFY PASS" in text_of(res)
    print("after cleanup:", "GREEN (correct)" if final_green else "RED")
    if not final_green:
        fail += 1

    shutil.rmtree(SCRATCH, ignore_errors=True)
    print("\nNEGCTL_184", "PASS" if fail == 0 else "FAIL (%d)" % fail)
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
