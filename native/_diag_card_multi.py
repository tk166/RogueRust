#!/usr/bin/env python3
"""_diag_card_multi.py -- 把 `CARD_MULTI` 的单格分叉定位到**哪一行规范文本**。

用法（位置参数）：

    python native/_diag_card_multi.py <卡行号> <变体号> [--full]

它做两件事：

1. 跑 `rd-fightdump --cards-multi --text`，把第 `<卡行号>*2+<变体号>` 个块的规范文本取出来；
2. 跑 `rd_oracle_card_multi_run(<卡行号>, <变体号>)`，取 C# 侧的 `rd_oracle_hash_input`；
3. **逐行对差**（`--full` 时把两边整段打出来）。

`fight_diff.py` 只说"step2 之后这两个哈希不同"；这一步说"第 11 行 `exec_num` 是 3 还是 4"。
2026-10-19 定 `shredder_drawer` / `doubt` 两处不一致就是这样落地的（`step0.chain` 差 1）。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fight_diff as fd  # noqa: E402

ROOT = fd.ROOT
INDEX = int(sys.argv[1]) if len(sys.argv) > 1 else 4
VARIANT = int(sys.argv[2]) if len(sys.argv) > 2 else 1

oracle = fd.Oracle()
mirror = fd.Mirror(fd.IMAGE)
spec = fd.load_spec(oracle, mirror)
card = spec["cards"][INDEX]
print("card", card["id"], "variant", VARIANT)

lines = fd.run_rust_dump(["--cards-multi", "--text"])
info, blocks = fd.parse_rust([line for line in lines if not line.startswith("text=") and line != "text-end"],
                             block_key="cardmulti")

# blocks are in order; text= lines follow each block's `final` line.
raw_texts = []
current = None
collecting = False
for line in lines:
    if line.startswith("=== STDERR"):
        break
    if line.startswith("cardmulti="):
        current = {"text": []}
        raw_texts.append(current)
        collecting = False
        continue
    if line.startswith("final "):
        collecting = True
        continue
    if collecting and line.startswith("text="):
        current["text"].append(line[len("text="):])
        continue
    if collecting and line == "text-end":
        collecting = False

position = INDEX * len(fd.MULTI_VARIANTS) + VARIANT
rust_text = "\n".join(raw_texts[position]["text"]) + "\n"

code = oracle.card_multi_run(INDEX, VARIANT)
if code <= 0:
    print("oracle error:", oracle.error())
    sys.exit(1)
csharp_text = oracle.hash_input()

left = rust_text.splitlines()
right = csharp_text.splitlines()
print(f"rust lines={len(left)} csharp lines={len(right)}")
shown = 0
for i in range(max(len(left), len(right))):
    a = left[i] if i < len(left) else "<missing>"
    b = right[i] if i < len(right) else "<missing>"
    if a != b:
        print(f"line {i}:")
        print(f"  rust   {a}")
        print(f"  csharp {b}")
        shown += 1
        if shown >= 12:
            print("...")
            break
if shown == 0:
    print("canonical texts are identical?!")
    print("rust final hash:", blocks[position]["steps"][-1]["hash"])
    print("csharp hash     :", oracle.hash())

if "--full" in sys.argv:
    print("=" * 30, "RUST")
    for i, line in enumerate(left):
        print(f"{i:3} {line}")
    print("=" * 30, "CSHARP")
    for i, line in enumerate(right):
        print(f"{i:3} {line}")
