"""Bisect which §173 addition breaks the `ritual` trigger (`Ir(WrongKind("F_TERM"))`).

Each step: start from the new document, drop one suspect, rebuild the sts image, run the one rd-core test.
"""
import io
import json
import os
import shutil
import subprocess
import sys

NEW = "native/_sts173.json"
SRC = os.path.join("tools", "contentc", "packages", "sts", "sts.roguedeck.json")
CARGO = r"C:\Users\TK11\.cargo\bin\cargo.exe"
TARGET = "D:/Vibe/sts-tui/kernel/target-mine"


def build_and_test(label, mutate):
    document = json.load(io.open(NEW, encoding="utf-8"))
    mutate(document)
    with io.open(SRC, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(document, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    build = subprocess.run([sys.executable, "-X", "utf8", "tools/contentc/build.py", "--package", "sts"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
    if build.returncode != 0:
        print(f"{label:38s} BUILD FAILED: {build.stderr.strip().splitlines()[-1:]}")
        return
    test = subprocess.run([CARGO, "test", "-p", "rd-core", "ritual_grants", "--release",
                           "--target-dir", TARGET, "--", "--test-threads=1"],
                          cwd="kernel", capture_output=True, text=True, encoding="utf-8",
                          errors="replace")
    ok = "test result: ok" in test.stdout
    print(f"{label:38s} {'PASS' if ok else 'FAIL'}")


def drop_actions(document, prefix):
    document["EnemyActions"] = [a for a in document["EnemyActions"]
                               if not a["Id"].startswith(prefix)]


def drop_monster_and_encounter(document, monster):
    document["Monsters"] = [m for m in document["Monsters"] if m["Id"] != monster]
    document["Encounters"] = [e for e in document["Encounters"]
                              if e["Id"]["Value"] not in
                              ("enc_" + monster, "enc_slavers" if monster == "taskmaster" else "")]


cases = [
    ("all three elites (baseline)", lambda d: None),
    ("no lagavulin", lambda d: (drop_actions(d, "lagavulin."),
                               drop_monster_and_encounter(d, "lagavulin"))),
    ("no book_of_stabbing", lambda d: (drop_actions(d, "book_of_stabbing."),
                                      drop_monster_and_encounter(d, "book_of_stabbing"))),
    ("no taskmaster", lambda d: (drop_actions(d, "taskmaster."),
                                drop_monster_and_encounter(d, "taskmaster"))),
    ("no wound card", lambda d: d.__setitem__("Cards", [c for c in d["Cards"] if c["Id"] != "wound"])),
]
for label, mutate in cases:
    build_and_test(label, mutate)
