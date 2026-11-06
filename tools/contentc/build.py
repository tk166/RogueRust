#!/usr/bin/env python3
"""build.py -- build one content *package* (or all of them) into its own images.

WHY: there is more than one content package in this repo now.

    roguedeck   the RogueDeck sample content.  EVERY cross-language oracle gate
                is pinned to its images (`tools/contentc/out/content.core.rdcf`),
                and `tools/contentc/expected_sha.txt` freezes their bytes.
                Do not let it move.
    sts         Slay the Spire Act 1 (Ironclad).  Currently a skeleton -- two
                hand-written statuses and nothing else -- so that "a second
                package travels the whole chain" is a fact you can re-run, not a
                claim in a plan document.

LAYOUT (all paths below are relative to the repository root):

    tools/contentc/packages/<pkg>/package.json      the package manifest
    tools/contentc/packages/<pkg>/<src>             its source document, if owned
    tools/contentc/packages/<pkg>/out/              its images, if owned here

    tools/contentc/out/                             roguedeck's images (historic
                                                    location -- the kernel gates
                                                    hardcode this path, so it must
                                                    not move)

    tools/contentc/packages/roguedeck/package.json:
        src       -> ref/RogueDeck-Core/src/.../bureaucrats.roguedeck.json
        out_dir   -> tools/contentc/out
        full_name -> content.rdcf        core_name -> content.core.rdcf

    tools/contentc/packages/sts/package.json:
        src       -> tools/contentc/packages/sts/sts.roguedeck.json
        out_dir   -> tools/contentc/packages/sts/out
        full_name -> content.sts.rdcf    core_name -> content.sts.core.rdcf

`compile.py` is unchanged in behaviour for the defaults: `--full-name` /
`--core-name` only rename the two output files.  That is deliberate -- the
package layer must not be able to alter bytes, and `expected_sha.txt` proves it.

USAGE
-----
    python tools/contentc/build.py --list
    python tools/contentc/build.py --package roguedeck     # must not move the pin
    python tools/contentc/build.py --package sts
    python tools/contentc/build.py --all

Exit codes: 0 built, 1 build failed, 2 environment / manifest problem.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
COMPILE = os.path.join(HERE, "compile.py")
PKG_ROOT = os.path.join(HERE, "packages")

MANIFEST_KEYS = ("package", "src", "out_dir", "full_name", "core_name")


def die(msg):
    sys.stderr.write("CONTENTC_BUILD ENV_MISSING\n%s\n" % msg)
    raise SystemExit(2)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_packages():
    if not os.path.isdir(PKG_ROOT):
        die("no packages directory: %s" % PKG_ROOT)
    out = {}
    for name in sorted(os.listdir(PKG_ROOT)):
        man = os.path.join(PKG_ROOT, name, "package.json")
        if not os.path.exists(man):
            continue
        with open(man, "r", encoding="utf-8") as fh:
            try:
                m = json.load(fh)
            except ValueError as e:
                die("%s is not valid JSON: %s" % (man, e))
        missing = [k for k in MANIFEST_KEYS if k not in m]
        if missing:
            die("%s is missing %s" % (man, ", ".join(missing)))
        if m["package"] != name:
            die("%s declares package %r but lives in .../%s/"
                % (man, m["package"], name))
        if name in out:
            die("duplicate package %r" % name)
        out[name] = m
    if not out:
        die("no package manifests under %s" % PKG_ROOT)
    return out


def build(name, m, dry_run=False):
    src = os.path.normpath(os.path.join(ROOT, m["src"]))
    out_dir = os.path.normpath(os.path.join(ROOT, m["out_dir"]))
    if not os.path.exists(src):
        die("package %r: source document missing: %s" % (name, src))
    if dry_run:
        print("  %-10s %s -> %s" % (name, m["src"], m["out_dir"]))
        return 0
    os.makedirs(out_dir, exist_ok=True)
    # §249: `--deny-json-fallback` is **not** optional.  A single (opcode, field) that
    # falls back to `F_JSON` silently breaks every *other* program sharing that opcode
    # at runtime, so it must fail the build while the culprit is still named.
    cmd = [sys.executable, "-B", COMPILE, "--src", src, "--out-dir", out_dir,
           "--full-name", m["full_name"], "--core-name", m["core_name"], "--quiet",
           "--deny-json-fallback"]
    r = subprocess.run(cmd, cwd=HERE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if r.returncode != 0:
        sys.stdout.write(r.stdout.decode("utf-8", "replace"))
        return 1
    images = {}
    for role in ("full", "core"):
        f = os.path.join(out_dir, m["%s_name" % role])
        if not os.path.exists(f):
            die("package %r: compiler did not produce %s" % (name, f))
        images[role] = {"file": m["%s_name" % role], "bytes": os.path.getsize(f),
                        "sha256": sha256_file(f)}
    src_sha = sha256_file(src)
    print("  %-10s %-24s %8d B  %s" % (name, images["full"]["file"],
                                       images["full"]["bytes"],
                                       images["full"]["sha256"]))
    print("  %-10s %-24s %8d B  %s" % ("", images["core"]["file"],
                                       images["core"]["bytes"],
                                       images["core"]["sha256"]))
    print("  %-10s %-24s %8d B  %s" % ("", "(source)", os.path.getsize(src),
                                       src_sha))
    # Only unpinned packages get a build.json.  A pinned package's identity is
    # already recorded once, in expected_sha.txt; a second machine-written copy
    # that nobody re-writes on a plain `compile.py` run would be a stale truth.
    if not m.get("pinned_by"):
        with open(os.path.join(out_dir, "build.json"), "w", encoding="utf-8",
                  newline="\n") as fh:
            json.dump({"package": name,
                       "description": m.get("description", ""),
                       "src": {"path": m["src"].replace("\\", "/"),
                               "bytes": os.path.getsize(src), "sha256": src_sha},
                       "images": images,
                       "compiler": {"path": "tools/contentc/compile.py",
                                    "sha256": sha256_file(COMPILE)}}, fh, indent=2)
            fh.write("\n")
    return 0


def main():
    ap = argparse.ArgumentParser(description="build RDCF content packages")
    ap.add_argument("--package", action="append", default=[],
                    help="package name (repeatable)")
    ap.add_argument("--all", action="store_true", help="build every package")
    ap.add_argument("--list", action="store_true", help="list packages and exit")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    pkgs = load_packages()
    if args.list or (not args.package and not args.all):
        print("content packages under %s" % os.path.relpath(PKG_ROOT, ROOT))
        print("  %-10s %-9s %-24s %-24s %s"
              % ("name", "status", "full image", "core image", "pinned by"))
        for name, m in sorted(pkgs.items()):
            print("  %-10s %-9s %-24s %-24s %s"
                  % (name, m.get("status", "?"), m["full_name"], m["core_name"],
                     m.get("pinned_by") or "-"))
            print("  %-10s %s" % ("", m.get("description", "")))
        if args.list:
            return
        print("\n(no --package/--all given: nothing built)")
        return

    names = sorted(pkgs) if args.all else args.package
    unknown = [n for n in names if n not in pkgs]
    if unknown:
        die("unknown package(s): %s (known: %s)" % (", ".join(unknown),
                                                    ", ".join(sorted(pkgs))))
    print("building %d package(s)" % len(names))
    bad = 0
    for n in names:
        bad += build(n, pkgs[n], dry_run=args.dry_run)
    if bad:
        print("CONTENTC_BUILD FAIL (%d package(s))" % bad)
        raise SystemExit(1)
    print("CONTENTC_BUILD OK (%d package(s))" % len(names))


if __name__ == "__main__":
    main()
