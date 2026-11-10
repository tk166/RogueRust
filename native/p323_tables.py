"""§323：把三名 Bandits 登记进内容门的五张“第二意见”表。

内容门刚刚把这五处**全都**指出来了（这正是它存在的理由）：
`quantity.monsters` / `roster.ids` / `encounters.ids` / `actions.ids` /
`asc.unknown` / `asc.unreviewed` / `asc.hp.*`。
"""

import io

PATH = 'native/sts_content_check.py'


def sub(t, old, new, label):
    n = t.count(old)
    assert n == 1, '%s: %d' % (label, n)
    return t.replace(old, new)


t = io.open(PATH, encoding='utf-8').read()

# ── 1. 怪物名单 ─────────────────────────────────────────────────────────────────
t = sub(t, """INV_MONSTERS = [""",
        """INV_MONSTERS = [
    # §323：Masked Bandits 的三名册外敌人（wiki `Masked_Bandits`）。HP 是**下界**：
    # Pointy 30（A7 34）/ Romeo 35-39（A7 37-41）/ Bear 38-42（A7 40-44）。
    ("pointy", 30, 30, ["pointy.special"]),
    ("romeo", 35, 39, ["romeo.mock", "romeo.agonizing_slash", "romeo.cross_slash"]),
    ("bear", 38, 42, ["bear.bear_hug", "bear.lunge", "bear.maul"]),""",
        'INV_MONSTERS')

# ── 2. 事件专属遭遇 ─────────────────────────────────────────────────────────────
t = sub(t, """    "enc_two_orb_walkers": (
        ["orb_walker", "orb_walker"],
        "Mysterious Sphere `[Open Sphere]`: \\"the player enters combat with the 2 Orb Walkers\\"",
    ),
}""",
        """    "enc_two_orb_walkers": (
        ["orb_walker", "orb_walker"],
        "Mysterious Sphere `[Open Sphere]`: \\"the player enters combat with the 2 Orb Walkers\\"",
    ),
    # §323：`Masked Bandits` 的 `[Fight!]` —— "the three bandits (Pointy, Romeo, and Bear)"。
    # ⚠️ wiki 明写它**不算精英**（对 Preserved Insect / Sling of Courage / Black Star /
    # Slaver's Collar 而言），所以事件里写的是 `Fight: "monster"`。
    "enc_masked_bandits": (
        ["pointy", "romeo", "bear"],
        "Masked Bandits `[Fight!]`: \\"the three bandits (Pointy, Romeo, and Bear)\\"",
    ),
}""",
        'INV_EVENT_ONLY')

# ── 3. 升阶变体 ────────────────────────────────────────────────────────────────
t = sub(t, """INV_ASC_VARIANTS = {""",
        """INV_ASC_VARIANTS = {
    # §323：Masked Bandits。Pointy 5×2 → A2 6×2；Romeo Agonizing 10→12（A2）、Weak 2→3（A17）、
    # Cross 15→17；Bear Lunge 9→10、Maul 18→20、Bear Hug 敏捷 -2 → A17 -4。
    'pointy.special': [(2, [('damage', 6, 'event'), ('damage', 6, 'event')])],
    'romeo.agonizing_slash': [
        (2, [('damage', 12, 'event'), ('status', 'standard.weak', 2, 'event')]),
        (17, [('damage', 12, 'event'), ('status', 'standard.weak', 3, 'event')]),
    ],
    'romeo.cross_slash': [(2, [('damage', 17, 'event')])],
    'bear.bear_hug': [(17, [('status', 'standard.dexterity', -4, 'event')])],
    'bear.lunge': [(2, [('damage', 10, 'event'), ('block', 9, 'source')])],
    'bear.maul': [(2, [('damage', 20, 'event')])],""",
        'INV_ASC_VARIANTS')

# ── 4. 升阶血量 ────────────────────────────────────────────────────────────────
t = sub(t, """INV_ASC_HP = {""",
        """INV_ASC_HP = {
    # §323：Pointy 30 → A7 34；Romeo 35-39 → 37-41；Bear 38-42 → 40-44（表里是下界）。
    'pointy': 34, 'romeo': 37, 'bear': 40,""",
        'INV_ASC_HP')

# ── 5. “没有升阶行”的豁免 ──────────────────────────────────────────────────────
t = sub(t, """INV_NO_ASC = {""",
        """INV_NO_ASC = {
    # §323：Romeo 的 Mock 是 "Does nothing."，wiki 没有 A 档。
    'romeo.mock': 'wiki Masked Bandits: Mock does nothing, no A-row',""",
        'INV_NO_ASC')

io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('five inventory tables updated')
