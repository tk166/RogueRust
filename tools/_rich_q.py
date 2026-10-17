"""Scratch: when does the queue= line actually disappear? (variant sweep, queue_on_play=1)"""
import ctypes
import glob
import os
import sys

PUB = r"D:\Vibe\sts-tui\native\RogueDeck.Oracle\bin\x64\Release\net10.0\win-x64\publish"
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
            getattr(lib, "rd_oracle_run_ex")
        except (OSError, AttributeError):
            continue
        for name, n in (("rd_oracle_run_ex", 27), ("rd_oracle_hash_input_len", 0),
                        ("rd_oracle_hash_input_char", 1), ("rd_oracle_hash_len", 0),
                        ("rd_oracle_hash_char", 1), ("rd_oracle_error_len", 0),
                        ("rd_oracle_error_char", 1), ("rd_oracle_queue_count", 0)):
            fn = getattr(lib, name)
            fn.restype = ctypes.c_int
            fn.argtypes = [ctypes.c_int] * n
        return lib
    sys.exit(1)


def rd(lib, lf, cf):
    return "".join(chr(cf(i)) for i in range(lf()))


def main():
    lib = load()
    base = dict(hero_hp=30, card_damage=13, card_hits=1, card_damage_target=1, card_kind=0,
                card_block=0, card_block_target=1, card_ward=0, card_cost=1, queue_on_play=1,
                enemy_hp=200, enemy_damage=1, enemy_count=1,
                hero_strength=0, hero_vulnerable=0, hero_weak=0, hero_dexterity=0, hero_frail=0,
                enemy_strength=0, enemy_vulnerable=0, enemy_weak=0, enemy_dexterity=0,
                enemy_frail=0, draw_per_turn=5, deck_size=3, seed=12345, variant=0)
    for variant in range(8):
        base["variant"] = variant
        rc = lib.rd_oracle_run_ex(*[base[a] for a in RUN_EX_ARGS])
        text = rd(lib, lib.rd_oracle_hash_input_len, lib.rd_oracle_hash_input_char)
        h = rd(lib, lib.rd_oracle_hash_len, lib.rd_oracle_hash_char)
        q = [ln for ln in text.split("\n") if ln.startswith("queue=")]
        print(f"variant={variant} rc={rc} queue_count={lib.rd_oracle_queue_count()} "
              f"hash={h[:12]} queue_lines={q}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
