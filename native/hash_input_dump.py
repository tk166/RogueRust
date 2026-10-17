"""取某个具体 case 的规范文本 + 哈希（给 Rust 侧做字节级对拍）。用法：
  python hash_input_dump.py [variant seed hero_hp card_damage enemy_hp enemy_damage]
默认那条 = variant=0, seed=1, hero_hp=30, card_damage=6, enemy_hp=12, enemy_damage=5
"""
import ctypes
import glob
import os
import sys

PUBLISH = r"D:\Vibe\sts-tui\native\RogueDeck.Oracle\bin\x64\Release\net10.0\win-x64\publish"


def load():
    for path in sorted(glob.glob(os.path.join(PUBLISH, "*.dll"))):
        try:
            lib = ctypes.CDLL(path)
            getattr(lib, "rd_oracle_run")
        except (OSError, AttributeError):
            continue
        for name, n in [("rd_oracle_run", 6), ("rd_oracle_hash_len", 0), ("rd_oracle_hash_char", 1),
                        ("rd_oracle_hash_input_len", 0), ("rd_oracle_hash_input_char", 1),
                        ("rd_oracle_hash_input_ok", 0), ("rd_oracle_error_len", 0),
                        ("rd_oracle_error_char", 1)]:
            fn = getattr(lib, name)
            fn.restype = ctypes.c_int
            fn.argtypes = [ctypes.c_int] * n
        return lib
    sys.exit("no lib")


def main():
    args = [int(x) for x in sys.argv[1:]] or [0, 1, 30, 6, 12, 5]
    variant, seed, hero_hp, card_dmg, enemy_hp, enemy_dmg = args
    lib = load()
    n = lib.rd_oracle_run(hero_hp, card_dmg, enemy_hp, enemy_dmg, seed, variant)
    if n < 0:
        err = "".join(chr(lib.rd_oracle_error_char(i)) for i in range(lib.rd_oracle_error_len()))
        sys.exit("run failed: " + err)

    def read(ln, ch):
        return "".join(chr(ch(i)) for i in range(ln()))

    text = read(lib.rd_oracle_hash_input_len, lib.rd_oracle_hash_input_char)
    digest = read(lib.rd_oracle_hash_len, lib.rd_oracle_hash_char)
    print(f"# rd_oracle_run(hero_hp={hero_hp}, card_damage={card_dmg}, enemy_hp={enemy_hp}, "
          f"enemy_damage={enemy_dmg}, seed={seed}, variant={variant})")
    print(f"# hash_input_ok={lib.rd_oracle_hash_input_ok()}  len={len(text)}  sha256={digest}")
    sys.stdout.write(text)
    sys.stdout.write("\n--- end of hash input (the final '\\n' above IS part of it) ---\n")
    print(repr(text[-30:]))


if __name__ == "__main__":
    main()
