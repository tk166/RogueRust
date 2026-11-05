"""§226 (part 6): 内容侧 `Dual Wield` / `Dual Wield+`。

wiki（`Dual_Wield`）：1 费 Uncommon Skill —— "Choose an Attack or Power card. Create 1 copy of it.
Exhaust."；升级 "Create 2 copies."。副本**进手牌**，原件不动。

载体就是这一节新加的 `node.chooseCards`（`{OwnerSelector, FromZone, Min, Max, Copies,
RequireAnyTag}`），它把"Attack 或 Power"这个过滤在**有内容的那一层**算成收窄清单。
"""
import io
import json

CONTENT = 'tools/contentc/packages/sts/sts.roguedeck.json'
CHECK = 'native/sts_content_check.py'

SEL_SOURCE = {
    "kind": "sel.source",
    "value": {"Cardinality": "ZeroOrOne", "RequiredContextCapabilities": "Source"},
}


def dual_wield(copies, text, upgraded):
    return {
        "Id": "dual_wield+" if upgraded else "dual_wield",
        "PackageId": "sts",
        "NameKey": "Dual Wield+" if upgraded else "Dual Wield",
        "DescriptionKey": text,
        "Costs": [{"ResourceId": {"value": "standard.energy"}, "Amount": 1}],
        "Tags": [{"value": "skill"}],
        "Rarity": "Uncommon",
        "Program": {
            "Id": {"Value": "(unnamed)"},
            "Root": {
                "kind": "node.chooseCards",
                "value": {
                    "OwnerSelector": SEL_SOURCE,
                    "FromZone": "Hand",
                    "Min": 1,
                    "Max": 1,
                    # 每张选中的牌造几份 —— 基础 1、`+` 2（就是升级的全部内容）。
                    "Then": "Copy",
                    "Copies": copies,
                    # "Attack **或** Power"：过滤要读卡定义的 tag 表，所以由这个节点（拿得到内容）
                    # 算成 `PendingChoice::candidates` 交给内核守。
                    "RequireAnyTag": ["attack", "power"],
                    "ResultKey": None,
                },
            },
            "MaxNodeDepth": 64,
            "MaxProgramSteps": 1024,
        },
        "LifecyclePrograms": {},
        "RetainInHandOnTurnEnd": False,
        "TurnEndHandDestinationZone": "DiscardPile",
        # 落区 = **弃牌堆**。`native/wiki_cards/dual_wield.txt` 的 Infobox 里**没有** Exhaust，
        # 正文也只说 "add 1 copy (2 copies if upgraded) of that card into your hand" ——
        # 旧版 StS 里它才自我消耗，照 dump 走（§226 抓到的第一处错）。
        "PlayedCardDestinationZone": "DiscardPile",
    }


raw = io.open(CONTENT, encoding='utf-8').read()
data = json.loads(raw)
ids = {card['Id'] for card in data['Cards']}
assert 'dual_wield' not in ids

data['Cards'].append(dual_wield(1, "Choose an Attack or Power card. Create 1 copy of it. Exhaust.",
                                False))
data['Cards'].append(dual_wield(2, "Choose an Attack or Power card. Create 2 copies of it. Exhaust.",
                                True))
out = json.dumps(data, ensure_ascii=False, indent=2) + '\n'
assert out != raw
io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(out)

# ── checker：INV_CARDS 加两行 + 事实walk 认识 `node.chooseCards` ──────────────
src = io.open(CHECK, encoding='utf-8').read()

old = '''        elif kind == "node.repeat":'''
new = '''        elif kind == "node.chooseCards":
            # §226: "ask the player which cards, then copy them" as one fact. **Every** field that
            # decides the question is part of it -- "an Attack or Power" vs "any card" is exactly
            # the difference between Dual Wield and a card that does not exist yet.
            out.append(("chooseCopy", tgt(body["OwnerSelector"]), body["FromZone"],
                          tuple(body.get("RequireAnyTag") or ()),
                          body["Min"], body["Max"], body["Copies"]))
        elif kind == "node.repeat":'''
assert src.count(old) == 1
src = src.replace(old, new)

old = '''    "fiend_fire": {"Cost": 2, "Tags": ["attack"],'''
new = '''    # ---- §226：复制载体（Dual Wield） ----------------------------------------------------------
    "dual_wield": {"Cost": 1, "Tags": ["skill"],
                   "Facts": [("chooseCopy", "source", "Hand", ("attack", "power"), 1, 1, 1)],
                   "PlayedCardDestinationZone": "DiscardPile"},
    "dual_wield+": {"Cost": 1, "Tags": ["skill"],
                    "Facts": [("chooseCopy", "source", "Hand", ("attack", "power"), 1, 1, 2)],
                    "PlayedCardDestinationZone": "DiscardPile"},
    "fiend_fire": {"Cost": 2, "Tags": ["attack"],'''
assert src.count(old) == 1
src = src.replace(old, new)
io.open(CHECK, 'w', encoding='utf-8', newline='\n').write(src)
print('ok content')
