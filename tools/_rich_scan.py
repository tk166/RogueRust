"""Scratch: which canonical-text keys are reachable through the EXISTING oracle ABI?

Run with miniforge base python. Prints, per scenario, the sorted set of
`key=` heads found in the pre-hash canonical text, so the "missing keys"
gap can be measured before any new export is written.
"""
import ctypes
import glob
import os
import re
import sys

ROOT = r"D:\Vibe\sts-tui"
PUB = os.path.join(ROOT, "native", "RogueDeck.Oracle", "bin", "x64", "Release",
                   "net10.0", "win-x64", "publish")

INT_FUNCS = {
    "rd_oracle_run": 6,
    "rd_oracle_hash_len": 0, "rd_oracle_hash_char": 1,
    "rd_oracle_error_len": 0, "rd_oracle_error_char": 1,
    "rd_oracle_run_ex": 27,
    "rd_oracle_hash_input_len": 0, "rd_oracle_hash_input_char": 1, "rd_oracle_hash_input_ok": 0,
    "rd_oracle_text_len": 0, "rd_oracle_text_char": 1, "rd_oracle_probe_ok": 0,
    "rd_oracle_probe_shuffle_pile": 2, "rd_oracle_probe_expr": 4,
    "rd_oracle_probe_conditional": 3, "rd_oracle_probe_repeat": 3,
    "rd_oracle_probe_program_steps": 2, "rd_oracle_probe_for_each": 7,
    "rd_oracle_probe_decree": 10, "rd_oracle_probe_reshuffle": 3,
    "rd_oracle_probe_trigger_order": 4, "rd_oracle_probe_snapshot": 1,
    "rd_oracle_probe_turn": 6, "rd_oracle_probe_intercept": 2,
    "rd_oracle_probe_pre_down": 3,
}

RUN_EX_ARGS = [
    "hero_hp", "card_damage", "card_hits", "card_damage_target", "card_kind",
    "card_block", "card_block_target", "card_ward", "card_cost", "queue_on_play",
    "enemy_hp", "enemy_damage", "enemy_count",
    "hero_strength", "hero_vulnerable", "hero_weak", "hero_dexterity", "hero_frail",
    "enemy_strength", "enemy_vulnerable", "enemy_weak", "enemy_dexterity", "enemy_frail",
    "draw_per_turn", "deck_size", "seed", "variant",
]


def load():
    for path in sorted(glob.glob(os.path.join(PUB, "*.dll"))):
        try:
            lib = ctypes.CDLL(path)
            getattr(lib, "rd_oracle_run")
            getattr(lib, "rd_oracle_run_ex")
        except (OSError, AttributeError):
            continue
        for name, arity in INT_FUNCS.items():
            fn = getattr(lib, name)
            fn.restype = ctypes.c_int
            fn.argtypes = [ctypes.c_int] * arity
        return lib, path
    print("!! no library")
    sys.exit(1)


def read_str(lib, lf, cf):
    return "".join(chr(cf(i)) for i in range(lf()))


def text_of(lib):
    return read_str(lib, lib.rd_oracle_hash_input_len, lib.rd_oracle_hash_input_char)


def hash_of(lib):
    return read_str(lib, lib.rd_oracle_hash_len, lib.rd_oracle_hash_char)


def err_of(lib):
    return read_str(lib, lib.rd_oracle_error_len, lib.rd_oracle_error_char)


def defaults(**kw):
    d = dict(hero_hp=30, card_damage=6, card_hits=1, card_damage_target=1, card_kind=0,
             card_block=0, card_block_target=1, card_ward=0, card_cost=1, queue_on_play=0,
             enemy_hp=12, enemy_damage=5, enemy_count=1,
             hero_strength=0, hero_vulnerable=0, hero_weak=0, hero_dexterity=0, hero_frail=0,
             enemy_strength=0, enemy_vulnerable=0, enemy_weak=0, enemy_dexterity=0, enemy_frail=0,
             draw_per_turn=5, deck_size=3, seed=12345, variant=0)
    d.update(kw)
    return d


KEY_RE = re.compile(r"^\s*([a-z_]+)=", re.M)
SUFFIX_RE = re.compile(r" (m:|mc:|msrc:|qat:)")


def keys_of(text):
    ks = set(KEY_RE.findall(text))
    for m in SUFFIX_RE.finditer(text):
        ks.add(m.group(1))
    return ks


def main():
    lib, path = load()
    print(f"lib = {path}")

    scenarios = []

    def add_ex(name, **kw):
        inp = defaults(**kw)
        rc = lib.rd_oracle_run_ex(*[inp[a] for a in RUN_EX_ARGS])
        scenarios.append((name, rc, inp))

    def add_probe(name, fn, *args):
        rc = getattr(lib, fn)(*args)
        scenarios.append((name, rc, list(args)))

    add_ex("ex_baseline")
    add_ex("ex_block", card_hits=0, card_damage=0, card_block=6, card_block_target=0, card_cost=0)
    add_ex("ex_ward", card_block=5, card_block_target=0, card_ward=3, card_cost=0)
    add_ex("ex_status", hero_strength=2, hero_dexterity=1, enemy_vulnerable=1)
    add_ex("ex_queue", queue_on_play=1, card_damage=13, enemy_hp=200)
    add_ex("ex_queue_endturn", queue_on_play=1, card_damage=13, enemy_hp=200, variant=6)
    add_probe("pr_shuffle_pile", "rd_oracle_probe_shuffle_pile", 6, 12345)
    add_probe("pr_expr", "rd_oracle_probe_expr", 4, 3, 4, 0)
    add_probe("pr_conditional", "rd_oracle_probe_conditional", 1, 7, 3)
    add_probe("pr_repeat", "rd_oracle_probe_repeat", 3, 8, 4)
    add_probe("pr_program_steps", "rd_oracle_probe_program_steps", 0, 64)
    add_probe("pr_for_each", "rd_oracle_probe_for_each", 2, 0, 3, 20, 12, 12, 12345)
    add_probe("pr_decree", "rd_oracle_probe_decree", 1, 1, 3, 3, 5, 6, 1, 200, 12345, 2)
    add_probe("pr_reshuffle", "rd_oracle_probe_reshuffle", 6, 3, 12345)
    add_probe("pr_trigger_order", "rd_oracle_probe_trigger_order", 0, 0, 0, 12345)
    add_probe("pr_snapshot", "rd_oracle_probe_snapshot", 12345)
    add_probe("pr_turn", "rd_oracle_probe_turn", 20, 12, 6, 10, 12345, 2)
    add_probe("pr_intercept", "rd_oracle_probe_intercept", 0, 12345)
    add_probe("pr_pre_down", "rd_oracle_probe_pre_down", 0, 1, 12345)

    allkeys = {}
    rows = []
    for name, rc, args in scenarios:
        if rc < 0:
            rows.append((name, rc, set(), err_of(lib)[:70]))
            continue
        t = text_of(lib)
        ks = keys_of(t)
        rows.append((name, rc, ks, ""))
        for k in ks:
            allkeys.setdefault(k, []).append(name)

    print()
    for name, rc, ks, err in rows:
        print(f"  {name:<20} rc={rc:<5} keys={len(ks):<3} {err}")
        if ks:
            print(f"      {' '.join(sorted(ks))}")

    print("\n=== key -> scenarios ===")
    for k in sorted(allkeys):
        print(f"  {k:<10} {len(allkeys[k]):>2}  {', '.join(allkeys[k][:6])}")

    watch = ["dp", "s", "gs", "cnt", "tr", "queue", "aside", "m:", "mc:", "msrc:", "qat:"]
    print("\n=== watched (missing-key) probe ===")
    for k in watch:
        print(f"  {k:<6} {'REACHABLE' if k in allkeys else 'absent   '} "
              f"{', '.join(allkeys.get(k, [])[:4])}")

    print("\n=== samples ===")
    for name in ("ex_ward", "ex_queue", "ex_status"):
        lib.rd_oracle_run_ex(*[defaults(**dict(
            ex_ward=dict(card_block=5, card_block_target=0, card_ward=3, card_cost=0),
            ex_queue=dict(queue_on_play=1, card_damage=13, enemy_hp=200),
            ex_status=dict(hero_strength=2, hero_dexterity=1, enemy_vulnerable=1))[name])[a]
            for a in RUN_EX_ARGS])
        print(f"---- {name} ----")
        print(text_of(lib))
    return 0


if __name__ == "__main__":
    sys.exit(main())
