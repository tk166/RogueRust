"""Scratch: exercise the NEW rich-state probes and show the canonical text they produce."""
import ctypes
import glob
import os
import re
import sys

ROOT = r"D:\Vibe\sts-tui"
PUB = os.path.join(ROOT, "native", "RogueDeck.Oracle", "bin", "x64", "Release",
                   "net10.0", "win-x64", "publish")

NEW = {
    "rd_oracle_probe_card_marks": 6,
    "rd_oracle_probe_combatant_counter": 5,
    "rd_oracle_probe_temporary_rule": 6,
    "rd_oracle_probe_set_aside": 2,
    "rd_oracle_probe_pending_status": 3,
    "rd_oracle_probe_global_status": 4,
}
BASE = {
    "rd_oracle_hash_len": 0, "rd_oracle_hash_char": 1,
    "rd_oracle_error_len": 0, "rd_oracle_error_char": 1,
    "rd_oracle_hash_input_len": 0, "rd_oracle_hash_input_char": 1, "rd_oracle_hash_input_ok": 0,
    "rd_oracle_probe_ok": 0, "rd_oracle_run_ex": 27,
}
KEY_RE = re.compile(r"^\s*([a-z_]+)=", re.M)
SUFFIX_RE = re.compile(r" (m:|mc:|msrc:|qat:|pend=)")


def load():
    for path in sorted(glob.glob(os.path.join(PUB, "*.dll"))):
        try:
            lib = ctypes.CDLL(path)
            getattr(lib, "rd_oracle_probe_card_marks")
        except (OSError, AttributeError):
            continue
        for name, arity in dict(BASE, **NEW).items():
            fn = getattr(lib, name)
            fn.restype = ctypes.c_int
            fn.argtypes = [ctypes.c_int] * arity
        return lib, path
    print("!! no library with the rich exports")
    sys.exit(1)


def rd(lib, lf, cf):
    return "".join(chr(cf(i)) for i in range(lf()))


def main():
    lib, path = load()
    print(f"lib = {path}\n")

    cases = [
        ("marks_1tag", "rd_oracle_probe_card_marks", (1, 0, 0, 0, 0, 12345)),
        ("marks_3tag", "rd_oracle_probe_card_marks", (3, 0, 0, 0, 0, 12345)),
        ("marks_spread", "rd_oracle_probe_card_marks", (1, 3, 0, 0, 0, 12345)),
        ("marks_counter_abs", "rd_oracle_probe_card_marks", (1, 0, 7, 0, 0, 12345)),
        ("marks_counter_rel", "rd_oracle_probe_card_marks", (1, 0, 7, 1, 0, 12345)),
        ("marks_src", "rd_oracle_probe_card_marks", (2, 1, 5, 0, 1, 12345)),
        ("counter_hero", "rd_oracle_probe_combatant_counter", (3, 0, 0, 0, 12345)),
        ("counter_both_rel", "rd_oracle_probe_combatant_counter", (3, 4, 1, 1, 12345)),
        ("tr_unlimited", "rd_oracle_probe_temporary_rule", (0, 0, 0, 0, 0, 12345)),
        ("tr_activations_fires", "rd_oracle_probe_temporary_rule", (2, 3, 0, 1, 0, 12345)),
        ("tr_oneshot_fires", "rd_oracle_probe_temporary_rule", (1, 1, 0, 1, 0, 12345)),
        ("tr_round", "rd_oracle_probe_temporary_rule", (3, 1, 0, 0, 0, 12345)),
        ("tr_turn", "rd_oracle_probe_temporary_rule", (4, 1, 0, 0, 1, 12345)),
        ("tr_ownerbound", "rd_oracle_probe_temporary_rule", (5, 0, 1, 0, 0, 12345)),
        ("tr_owner", "rd_oracle_probe_temporary_rule", (0, 0, 1, 0, 0, 12345)),
        ("aside_1", "rd_oracle_probe_set_aside", (1, 12345)),
        ("aside_2", "rd_oracle_probe_set_aside", (2, 12345)),
        ("pending_2", "rd_oracle_probe_pending_status", (3, 2, 12345)),
        ("pending_1", "rd_oracle_probe_pending_status", (1, 1, 12345)),
        ("global_2_3", "rd_oracle_probe_global_status", (2, 3, 1, 12345)),
        ("global_1_0", "rd_oracle_probe_global_status", (1, 0, 0, 12345)),
    ]

    seen = {}
    for name, fn, args in cases:
        rc = getattr(lib, fn)(*args)
        err = rd(lib, lib.rd_oracle_error_len, lib.rd_oracle_error_char)
        if rc < 0:
            print(f"---- {name}: rc={rc} ERR={err}")
            continue
        text = rd(lib, lib.rd_oracle_hash_input_len, lib.rd_oracle_hash_input_char)
        h = rd(lib, lib.rd_oracle_hash_len, lib.rd_oracle_hash_char)
        ok = lib.rd_oracle_hash_input_ok()
        keys = set(KEY_RE.findall(text))
        for m in SUFFIX_RE.finditer(text):
            keys.add(m.group(1))
        seen[name] = keys
        print(f"---- {name}  fn={fn}{args}")
        print(f"     hash={h[:16]} len={len(text)} input_ok={ok} keys={sorted(keys)}")
        print("     | " + text.replace("\n", "\n     | "))

    print("\n=== union of keys over the new probes ===")
    u = set()
    for k in seen.values():
        u |= k
    print("  " + " ".join(sorted(u)))

    print("\n=== which probe covers which watched token ===")
    for tok in ["dp", "s", "gs", "cnt", "tr", "queue", "aside", "m:", "mc:", "msrc:", "qat:", "pend="]:
        who = [n for n, ks in seen.items() if tok in ks]
        print(f"  {tok:<7} {'REACHABLE via ' + ', '.join(who[:4]) if who else 'ABSENT'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
