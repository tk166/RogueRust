"""§311（五·真）：Spheric Guardian 的清单条目。

清单是**独立口径**：`INV_ACTIONS` 是 "动作 → (意图, 事实)" 的字典，`INV_MONSTERS` 是
"怪物 → (HP 上下界, 动作表)"。事实里**不含** `prev_move/last_move` 那对记账
（`split_history` 会把它剥掉，§195.5）。
"""
import io

CHECK = 'D:/Vibe/sts-tui/native/sts_content_check.py'

PATCHES = [
    ('    "monsters": 50,', '    "monsters": 51,'),
    ('INV_MONSTERS = [',
     '''INV_MONSTERS = [
    # §311: Act 2 的 Spheric Guardian —— 20 血（wiki 的 `Powers` 列另有三条：Artifact 3 /
    # Block 40 / Barricade；后两条不进这张表 —— Block 走 encounter 的 `StartingBlock`，
    # Barricade 是状态）。
    ("spheric_guardian", 20, 20,
     ["spheric_guardian.activate", "spheric_guardian.debuff_attack",
      "spheric_guardian.slam", "spheric_guardian.harden"]),'''),
    ('INV_ACTIONS = {',
     '''INV_ACTIONS = {
    # §311: Spheric Guardian（wiki `Spheric Guardian` 页 + `Module:Enemies/data`）。
    # Activate 25 Block；Debuff Attack 10 + 5 Frail；Slam 10×2；Harden 10 + 15 Block。
    "spheric_guardian.activate": ("Defend", [("block", 25, "source")]),
    "spheric_guardian.debuff_attack": ("Attack", [("damage", 10, "event"),
                                                  ("status", "standard.frail", 5, "event")]),
    "spheric_guardian.slam": ("Attack", [("damage", 10, "event"), ("damage", 10, "event")]),
    "spheric_guardian.harden": ("Attack", [("damage", 10, "event"), ("block", 15, "source")]),'''),
    ('INV_NO_ASC = {',
     '''INV_NO_ASC = {
    # §311: wiki 的 `Activate | Gains 25 Block` 只有一行，没有 A 档。
    'spheric_guardian.activate': 'wiki Spheric Guardian: Activate has no A-row', '''),
    ('INV_ASC_VARIANTS = {',
     '''INV_ASC_VARIANTS = {
    # §311: Spheric Guardian 的三招从 A2 起伤害 +1（wiki 的 `{{Asc|2|11}}`）。
    'spheric_guardian.debuff_attack': [(2, [('damage', 11, 'event'),
                                            ('status', 'standard.frail', 5, 'event')])],
    'spheric_guardian.slam': [(2, [('damage', 11, 'event'), ('damage', 11, 'event')])],
    'spheric_guardian.harden': [(2, [('damage', 11, 'event'), ('block', 15, 'source')])],'''),
]


def main():
    text = io.open(CHECK, encoding='utf-8').read()
    for old, new in PATCHES:
        assert text.count(old) == 1, (old[:50], text.count(old))
        text = text.replace(old, new)
    io.open(CHECK, 'w', encoding='utf-8', newline='\n').write(text)
    print('inventories extended')


main()
