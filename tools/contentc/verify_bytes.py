#!/usr/bin/env python3
"""verify_bytes.py -- the byte-identity gate for the RDCF content image.

THE POINT
---------
Every cross-language oracle gate in this repo is pinned to `content.core.rdcf`:

    native/fight_diff.py:139      IMAGE = tools/contentc/out/content.core.rdcf
    native/gen_card_specs.py:51   IMAGE_REL = tools/contentc/out/content.core.rdcf
    (and, through card_specs.json, CARD_DIFF / coverage / ENEMY_DIFF / golden)

So a change to `compile.py` -- and there will be one, because StS Act 1 needs
event / potion / map / power entity tables -- can silently change the bytes of
the *old* content image.  When it does, none of those gates go red: they simply
compare the kernel against a different baseline from then on, and stay green
forever.  A gate that cannot fail is not a gate.

This script converts that silent drift into a loud, located failure:

    1. the source document must hash to the pinned SHA
    2. a FRESH compile with the current compiler, into a temp dir, must
       reproduce both image SHAs bit for bit
    3. the on-disk `out/` images must also equal the pinned SHAs
       (checked separately: (2) alone cannot see a stale `out/`, and (3) alone
        cannot see a compiler regression)

On failure it prints expected vs actual for every item and, for images, the
first differing byte offset with the section (and row, for the fixed-stride
entity tables) it lands in.  Exit code: 0 pass, 1 mismatch, 2 precondition
missing / compile failed -- the same convention as tools/acceptance.ps1.

    python verify_bytes.py             # the gate
    python verify_bytes.py --quiet     # only the verdict + failures
    python verify_bytes.py --repin     # DELIBERATELY rewrite expected_sha.txt
    python verify_bytes.py --src F     # compile F instead (debugging only)
    python verify_bytes.py --keep      # keep the temp compile dir for fc/bcompare

`--src` is for bisecting a failure; it does not weaken the gate, because the
source hash check still runs and is reported first (pass --ignore-source-pin to
silence it when you are intentionally compiling a mutated copy).
"""

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))          # repo root
PIN = os.path.join(HERE, "expected_sha.txt")
COMPILE = os.path.join(HERE, "compile.py")
OUT_DIR = os.path.join(HERE, "out")

sys.path.insert(0, HERE)
import rdcfmt as F  # noqa: E402


# --------------------------------------------------------------------- pin io
PIN_KEYS = ("source_path", "source_sha256", "source_bytes",
            "full_name", "full_sha256", "full_bytes",
            "core_name", "core_sha256", "core_bytes")


def read_pin(path=PIN):
    pin, seen = {}, set()
    if not os.path.exists(path):
        die_missing("pin file missing: %s\n  它是基线本身，不能在闸门里凭空生成。"
                    % path)
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip()
            if k not in PIN_KEYS:
                die_missing("pin file has unknown key %r (known: %s)"
                            % (k, ", ".join(PIN_KEYS)))
            if k in seen:
                die_missing("pin file repeats key %r -- refusing to guess which wins" % k)
            seen.add(k)
            pin[k] = v
    missing = [k for k in PIN_KEYS if k not in pin]
    if missing:
        die_missing("pin file is incomplete, missing: %s" % ", ".join(missing))
    for k in ("source_sha256", "full_sha256", "core_sha256"):
        pin[k] = pin[k].lower()
        if len(pin[k]) != 64 or any(c not in "0123456789abcdef" for c in pin[k]):
            die_missing("pin %s is not a 64-char lowercase hex SHA-256: %r" % (k, pin[k]))
    for k in ("source_bytes", "full_bytes", "core_bytes"):
        try:
            pin[k] = int(pin[k])
        except ValueError:
            die_missing("pin %s is not an integer: %r" % (k, pin[k]))
    return pin


def write_pin(pin, path=PIN):
    """Rewrite only the value side of the existing lines (keeps the prose)."""
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    for k in PIN_KEYS:
        needle = "\n%s = " % k
        i = text.find(needle)
        if i < 0:
            die_missing("cannot re-pin: line %r not found in %s" % (k, path))
        j = text.find("\n", i + 1)
        text = text[:i] + "\n%s = %s" % (k, pin[k]) + text[j:]
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


# ------------------------------------------------------------------- helpers
def die_missing(msg):
    sys.stderr.write("CONTENTC_BYTES ENV_MISSING\n%s\n" % msg)
    raise SystemExit(2)


def rel(path):
    """Repo-relative when possible; absolute otherwise (py can be run from anywhere)."""
    try:
        return os.path.relpath(path, ROOT)
    except ValueError:                          # different drive (e.g. a %TEMP% copy)
        return path


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


SEC_TO_SNAME = {F.S_CARD: "CARD", F.S_STAT: "STATUS", F.S_EACT: "EACT",
                F.S_ENCT: "ENCT", F.S_REL: "REL"}


def locate(path, off):
    """Describe what lives at byte `off` of an RDCF image."""
    with open(path, "rb") as fh:
        buf = fh.read()
    if off >= len(buf):
        return "past EOF (len %d)" % len(buf)
    if off < F.HEADER_SIZE:
        return "header byte %d" % off
    _, d = F.unpack_dir(buf)
    # the section directory itself is not described by itself; check it by range
    dir_end = F.HEADER_SIZE + F.NSEC * 12
    if off < dir_end:
        idx = (off - F.HEADER_SIZE) // 12
        return "section directory entry %d" % idx
    for sid in F.SEC_ORDER:
        o, n, _ = d.get(sid, (0, 0, 0))
        if n and o <= off < o + n:
            name = F.SEC_NAMES.get(sid, "?")
            inner = off - o
            sname = SEC_TO_SNAME.get(sid)
            if sname:
                stride = F.row_stride(sname)
                return "%s[%d] +%d (stride %d)" % (name, inner // stride,
                                                  inner % stride, stride)
            return "%s +%d" % (name, inner)
    # not covered by any payload: it is the 4-byte alignment padding that follows
    # the last section ending at or before this offset.
    prev, prev_end = "header", F.HEADER_SIZE + F.NSEC * 12
    for sid in F.SEC_ORDER:
        o, n, _ = d.get(sid, (0, 0, 0))
        if n and o + n <= off and o + n >= prev_end:
            prev, prev_end = F.SEC_NAMES.get(sid, "?"), o + n
    return "padding after %s (that section ends at %d)" % (prev, prev_end)


def first_diff(pin_path, new_path):
    """First *payload* difference, plus what moved in the header.

    Reporting the literal first differing byte is a trap:
      * header bytes 20..23 are `content_hash` = FNV-1a of the source file.  It
        moves whenever the *source* changes, so it shadows the interesting byte;
      * header bytes 8..11 are `total_size`, so *any* size change shows up at
        byte 8 before anything else.
    Both are consequences, not causes.  So the scan skips the header and the
    section directory (whose size is fixed by NSEC) and reports the first byte
    of real payload that moved, together with the size delta and the two header
    fields that are known to be derived.
    """
    with open(pin_path, "rb") as fh:
        ba = fh.read()
    with open(new_path, "rb") as fh:
        bb = fh.read()
    dir_end = F.HEADER_SIZE + F.NSEC * 12
    hdr = {"content_hash_moved": ba[20:24] != bb[20:24],
           "size_from": len(ba), "size_to": len(bb),
           "dir_moved": ba[F.HEADER_SIZE:dir_end] != bb[F.HEADER_SIZE:dir_end]}
    for i in range(dir_end, min(len(ba), len(bb))):
        if ba[i] != bb[i]:
            return i, ba[i], bb[i], hdr
    if len(ba) != len(bb):
        return min(len(ba), len(bb)), None, None, hdr   # one is a prefix
    return None, None, None, hdr


# --------------------------------------------------------------------- gate
def main():
    ap = argparse.ArgumentParser(description="RDCF content byte-identity gate")
    ap.add_argument("--pin", default=PIN)
    ap.add_argument("--src", default=None,
                    help="compile this document instead of the pinned one (debugging)")
    ap.add_argument("--ignore-source-pin", action="store_true",
                    help="do not fail when --src differs from the pinned source hash")
    ap.add_argument("--repin", action="store_true",
                    help="rewrite expected_sha.txt from a fresh compile (deliberate)")
    ap.add_argument("--keep", action="store_true", help="keep the fresh compile output")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    say = (lambda *a: None) if args.quiet else (lambda *a: print(*a))
    pin = read_pin(args.pin)
    src = os.path.abspath(os.path.join(ROOT, pin["source_path"])) \
        if args.src is None else os.path.abspath(args.src)
    if not os.path.exists(src):
        die_missing("source document missing: %s" % src)
    if not os.path.exists(COMPILE):
        die_missing("compiler missing: %s" % COMPILE)

    say("content byte-identity gate")
    say("  pin      : %s" % rel(args.pin))
    say("  source   : %s" % rel(src))
    say("  compiler : %s" % rel(COMPILE))

    problems = []          # (item, expected, actual)

    # ---- 1. source document -------------------------------------------------
    src_sha, src_len = sha256_file(src), os.path.getsize(src)
    if src_sha == pin["source_sha256"] and src_len == pin["source_bytes"]:
        say("  source   : %s ... ok (%d B)" % (src_sha[:16], src_len))
    else:
        problems.append(("source", "%s (%d B)" % (pin["source_sha256"][:16], pin["source_bytes"]),
                         "%s (%d B)" % (src_sha[:16], src_len)))
        if args.src is not None and args.ignore_source_pin:
            say("  source   : %s ... DIFFERS from pin (ignored by --ignore-source-pin)"
                % src_sha[:16])
            problems.pop()
        else:
            say("  source   : %s ... DIFFERS from pin" % src_sha[:16])

    # ---- 2. fresh compile ---------------------------------------------------
    tmp = tempfile.mkdtemp(prefix="rdcf-fresh-")
    try:
        cmd = [sys.executable, "-B", COMPILE, "--src", src, "--out-dir", tmp, "--quiet"]
        say("  compile  : %s" % rel(COMPILE))
        r = subprocess.run(cmd, cwd=HERE, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT)
        if r.returncode != 0:
            sys.stdout.write(r.stdout.decode("utf-8", "replace"))
            die_missing("fresh compile failed (exit %d) -- fix the compiler first; "
                        "byte identity cannot be judged" % r.returncode)

        images = {}
        for role in ("full", "core"):
            name = pin["%s_name" % role]
            fresh = os.path.join(tmp, name)
            ondisk = os.path.join(OUT_DIR, name)
            if not os.path.exists(fresh):
                die_missing("fresh compile did not produce %r (the compiler's output "
                            "names changed, or --no-core was implied)" % name)
            if not os.path.exists(ondisk):
                die_missing("checked-in image missing: %s\n  regenerate with: "
                            "python tools/contentc/build.py --package roguedeck" % ondisk)
            images[role] = {
                "name": name,
                "expect": pin["%s_sha256" % role],
                "expect_bytes": pin["%s_bytes" % role],
                "fresh": fresh, "fresh_sha": sha256_file(fresh),
                "fresh_bytes": os.path.getsize(fresh),
                "ondisk": ondisk, "ondisk_sha": sha256_file(ondisk),
            }

        # ---- 3. compare (inside the try: the fresh images are still on disk) --
        for role in ("full", "core"):
            im = images[role]
            say("")
            say("  %s (%s)" % (im["name"], role))
            say("    pinned : %s  %d B" % (im["expect"], im["expect_bytes"]))
            say("    fresh  : %s  %d B  %s"
                % (im["fresh_sha"], im["fresh_bytes"],
                   "ok" if im["fresh_sha"] == im["expect"] else "MISMATCH"))
            say("    out/   : %s  %s"
                % (im["ondisk_sha"], "ok" if im["ondisk_sha"] == im["expect"] else "MISMATCH"))
            if im["fresh_sha"] != im["expect"]:
                problems.append(("%s (fresh compile)" % im["name"],
                                 im["expect"], im["fresh_sha"]))
            if im["ondisk_sha"] != im["expect"]:
                problems.append(("%s (checked-in out/)" % im["name"],
                                 im["expect"], im["ondisk_sha"]))

            # where is the first difference?  (fresh vs pinned is what matters;
            # the pinned side is the checked-in file when it still matches)
            ref = im["ondisk"] if im["ondisk_sha"] == im["expect"] else None
            if ref and im["fresh_sha"] != im["expect"]:
                off, b_pin, b_new, hdr = first_diff(ref, im["fresh"])
                delta = hdr["size_to"] - hdr["size_from"]
                say("    size   : %d -> %d B (%+d)" % (hdr["size_from"], hdr["size_to"], delta))
                if hdr["content_hash_moved"]:
                    say("    header byte 20..23 (content_hash = FNV-1a of the source bytes) "
                        "moved -> the SOURCE document changed, not (only) the compiler")
                if off is None:
                    say("    no payload difference: the compiler is byte-stable and only "
                        "header/derived fields moved")
                else:
                    say("    first payload difference: byte %d (0x%X)" % (off, off))
                    say("      pinned %s = %s" % (locate(ref, off),
                                                  "EOF" if b_pin is None else "0x%02X" % b_pin))
                    say("      fresh  %s = %s" % (locate(im["fresh"], off),
                                                  "EOF" if b_new is None else "0x%02X" % b_new))
    finally:
        if not args.keep:
            shutil.rmtree(tmp, ignore_errors=True)
        else:
            say("")
            say("  kept     : %s" % tmp)

    # ---- deliberate re-pin --------------------------------------------------
    # Checked BEFORE the failure exit on purpose: re-pinning after an intended
    # compiler change is exactly the case where the pin *must* mismatch.
    if args.repin:
        if not args.ignore_source_pin and problems and problems[0][0] == "source":
            die_missing("refusing to re-pin: the source document itself changed. "
                        "Re-pin is for compiler changes, not for silently adopting new "
                        "content. Move the pin by hand after checking the source diff.")
        write_pin({"source_path": rel(src).replace("\\", "/"),
                   "source_sha256": src_sha, "source_bytes": src_len,
                   "full_name": pin["full_name"], "full_sha256": images["full"]["fresh_sha"],
                   "full_bytes": os.path.getsize(images["full"]["fresh"]),
                   "core_name": pin["core_name"], "core_sha256": images["core"]["fresh_sha"],
                   "core_bytes": os.path.getsize(images["core"]["fresh"])})
        print("REPINNED %s\n  full=%s\n  core=%s"
              % (rel(args.pin), images["full"]["fresh_sha"],
                 images["core"]["fresh_sha"]))
        return

    # ---- verdict ------------------------------------------------------------
    if problems:
        print("")
        print("!! CONTENTC_BYTES FAIL (%d problem(s))" % len(problems))
        print("   %-30s %-66s %s" % ("item", "expected", "actual"))
        for item, exp, act in problems:
            print("   %-30s %-66s %s" % (item, exp, act))
        print("")
        print("   每一条都意味着某个对拍闸门从此在比另一份内容：")
        print("     source 变了      -> 先确认是谁改了源文档（ref/ 是只读镜像）")
        print("     编译器变了       -> compile.py 改动了旧内容产物的字节，必须在改编译器的")
        print("                         同一个提交里要么修回去，要么显式 --repin 并说明理由")
        print("     out/ 陈旧        -> 跑 python tools/contentc/build.py --package roguedeck")
        raise SystemExit(1)

    say("")
    print("CONTENTC_BYTES PASS (2/2 images, 1/1 source)  full=%s core=%s"
          % (images["full"]["expect"][:16], images["core"]["expect"][:16]))


if __name__ == "__main__":
    main()
