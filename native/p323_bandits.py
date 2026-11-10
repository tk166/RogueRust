"""§323 `masked_bandits` 的三名册外敌人 + 遭遇 + 事件。

wiki 数值（Masked Bandits / Pointy / Romeo / Bear）：

| 敌人 | HP | A7 | 招式 |
|---|---|---|---|
| Pointy | 30 | 34 | Pointy Special 5×2（A2 6×2），每回合都用 |
| Romeo | 35-39 | 37-41 | Mock（什么都不做，第 1 回合）→ Agonizing Slash（10 + 2 Weak；A2 12，A17 Weak 3）/ Cross Slash（15；A2 17）交替 |
| Bear | 38-42 | 40-44 | Bear Hug（-2 敏捷；A17 -4，第 1 回合）→ Lunge（9 + 9 格挡；A2 10）/ Maul（18；A2 20）交替 |

模式用 `last_move` 计数器表达（与 `slaver_red` 同一套：动作末尾把 `prev_move ← last_move`、
`last_move ← N`，`IntentRules` 按 `last_move` 分派）。

⚠️ 两处刻意的简化（写进 `docs/port-plan.md`）：
1. Romeo 的 **A17 三段循环**（Mock → Agonizing → Cross → Cross）没做：我们只有 A2 的数值变体，
   循环仍是两段。A17 只改 Weak 层数（3 层）。
2. wiki 明写这场战斗**不算精英**（对 `Preserved Insect` / `Sling of Courage` / `Black Star` /
   `Slaver's Collar` 而言），所以 `Fight: "monster"` —— 与 `Mysterious Sphere`（真精英）不同。
"""

import io
import json

PATH = 'tools/contentc/packages/sts/sts.roguedeck.json'


# ── 节目节点构造器（形状照抄现成的 `slaver_red` / `jaw_worm` / `lagavulin`）────────────
def sel_target():
    return {"kind": "sel.eventTarget",
            "value": {"Cardinality": "ZeroOrOne",
                      "RequiredContextCapabilities": "EventTarget"}}


def sel_source():
    return {"kind": "sel.source",
            "value": {"Cardinality": "ZeroOrOne",
                      "RequiredContextCapabilities": "Source"}}


def const(n):
    return {"kind": "const", "value": {"Value": n}}


def damage(n):
    return {"kind": "node.dealDamage",
            "value": {"TargetSelector": sel_target(), "Amount": const(n),
                      "ResultKey": None, "IgnoresBlock": False, "Element": None}}


def block(n):
    return {"kind": "node.gainBlock",
            "value": {"TargetSelector": sel_source(), "Amount": const(n), "ResultKey": None}}


def apply(status, n):
    return {"kind": "node.applyStatus",
            "value": {"TargetSelector": sel_target(),
                      "StatusDefinitionId": {"value": status}, "Stacks": const(n),
                      "DurationTurns": 0, "Charges": 0, "ResultKey": None}}


def modify(status, delta):
    return {"kind": "node.modifyStatusStacks",
            "value": {"TargetSelector": sel_target(),
                      "StatusDefinitionId": {"value": status}, "Delta": const(delta),
                      "ResultKey": None}}


def repeat(count, body):
    return {"kind": "node.repeat", "value": {"Count": const(count), "Body": body,
                                             "MaxCount": 32}}


def counter(cid):
    return {"kind": "combatantCounter",
            "value": {"Selector": sel_source(), "CounterId": cid}}


def set_counter(cid, amount):
    return {"kind": "node.setCombatantCounter",
            "value": {"TargetSelector": sel_source(), "CounterId": {"value": cid},
                      "Amount": amount, "Relative": False, "ResultKey": None}}


def seq(children):
    return {"kind": "node.sequence", "value": {"Children": children}}


def mark_move(n):
    """把 `prev_move ← last_move`、`last_move ← n` 追加到节目尾部（与现成的敌人同序）。"""
    return [set_counter("prev_move", counter("last_move")), set_counter("last_move", const(n))]


def program(root):
    return {"Id": {"Value": "(unnamed)"}, "Root": root,
            "MaxNodeDepth": 64, "MaxProgramSteps": 1024}


def action(action_id, name, description, intent_kind, intent_label, root, variants=()):
    row = {
        "Id": action_id,
        "PackageId": "sts",
        "NameKey": name,
        "DescriptionKey": description,
        "Intent": {"Kind": intent_kind, "Label": intent_label},
        "Program": program(root),
    }
    if variants:
        row["ProgramAsc"] = [{"AscensionMin": level, "Program": program(v)}
                             for level, v in variants]
    return row


WEAK = "standard.weak"
DEX = "standard.dexterity"


def main():
    doc = json.load(io.open(PATH, encoding='utf-8'))
    have = {m["Id"] for m in doc["Monsters"]}
    assert not ({"pointy", "romeo", "bear"} & have), 'already patched'

    # ── 招式 ──────────────────────────────────────────────────────────────────────
    actions = [
        # Pointy：每回合 5×2（A2 6×2）。
        action("pointy.special", "Pointy Special", "Pointy Special - 5x2 damage",
               "Attack", "Pointy Special - 5x2 damage",
               seq([repeat(2, damage(5))] + mark_move(0)),
               variants=[(2, seq([repeat(2, damage(6))] + mark_move(0)))]),
        # Romeo：Mock → (Agonizing / Cross) 交替。
        action("romeo.mock", "Mock", "Mock - nothing", "Unknown", "Mock",
               seq(mark_move(0))),
        action("romeo.agonizing_slash", "Agonizing Slash",
               "Agonizing Slash - 10 damage, 2 Weak",
               "Attack", "Agonizing Slash - 11 damage, 2 Weak",
               seq([damage(10), apply(WEAK, 2)] + mark_move(1)),
               variants=[
                   (2, seq([damage(12), apply(WEAK, 2)] + mark_move(1))),
                   # A17：同伤害、Weak 变 3 层。
                   (17, seq([damage(12), apply(WEAK, 3)] + mark_move(1))),
               ]),
        action("romeo.cross_slash", "Cross Slash", "Cross Slash - 15 damage",
               "Attack", "Cross Slash - 16 damage",
               seq([damage(15)] + mark_move(2)),
               variants=[(2, seq([damage(17)] + mark_move(2)))]),
        # Bear：Bear Hug → (Lunge / Maul) 交替。
        action("bear.bear_hug", "Bear Hug", "Bear Hug - -2 Dexterity", "Debuff",
               "Bear Hug - -2 Dexterity",
               seq([modify(DEX, -2)] + mark_move(0)),
               variants=[(17, seq([modify(DEX, -4)] + mark_move(0)))]),
        action("bear.lunge", "Lunge", "Lunge - 9 damage, 9 Block", "AttackDefend",
               "Lunge - 10 damage, 9 Block",
               seq([damage(9), block(9)] + mark_move(1)),
               variants=[(2, seq([damage(10), block(9)] + mark_move(1)))]),
        action("bear.maul", "Maul", "Maul - 18 damage", "Attack", "Maul - 19 damage",
               seq([damage(18)] + mark_move(2)),
               variants=[(2, seq([damage(20)] + mark_move(2)))]),
    ]

    def rule(condition, action_id, priority):
        return {"Condition": condition, "Action": {"value": action_id},
                "Priority": priority}

    def round_is(n):
        return {"kind": "intent.round", "value": {"Op": "Equal", "Round": n}}

    def last_move_is(n):
        return {"kind": "intent.selfHasCounter",
                "value": {"Counter": {"value": "last_move"}, "Op": "Equal", "Value": n}}

    romeo_rules = [
        rule(dict(round_is(1)), "romeo.mock", 75),
        rule(dict(last_move_is(0)), "romeo.agonizing_slash", 60),
        rule(dict(last_move_is(1)), "romeo.cross_slash", 60),
        rule(dict(last_move_is(2)), "romeo.agonizing_slash", 60),
    ]
    bear_rules = [
        rule(dict(round_is(1)), "bear.bear_hug", 75),
        rule(dict(last_move_is(0)), "bear.lunge", 60),
        rule(dict(last_move_is(1)), "bear.maul", 60),
        rule(dict(last_move_is(2)), "bear.lunge", 60),
    ]

    monsters = [
        {"Id": "pointy", "NameKey": "Pointy", "HpMin": 30, "HpMax": 30, "MaxHealth": 30,
         "Actions": [{"value": "pointy.special"}], "StartingStatuses": [], "IntentRules": []},
        {"Id": "romeo", "NameKey": "Romeo", "HpMin": 35, "HpMax": 39, "MaxHealth": 35,
         "Actions": [{"value": "romeo.mock"}, {"value": "romeo.agonizing_slash"},
                     {"value": "romeo.cross_slash"}],
         "StartingStatuses": [], "IntentRules": romeo_rules},
        {"Id": "bear", "NameKey": "Bear", "HpMin": 38, "HpMax": 42, "MaxHealth": 38,
         "Actions": [{"value": "bear.bear_hug"}, {"value": "bear.lunge"},
                     {"value": "bear.maul"}],
         "StartingStatuses": [], "IntentRules": bear_rules},
    ]

    def enemy(monster, asc_hp):
        return {
            "Id": monster["Id"],
            "MaxHealth": monster["MaxHealth"],
            "Actions": monster["Actions"],
            "StartingStatuses": [],
            "Position": None,
            "IntentRules": monster["IntentRules"],
            "DisplayName": monster["NameKey"],
            "Rolls": [],
            "Counters": [],
            "Spawn": True,
            "MaxHealthAsc": [{"AscensionMin": 7, "MaxHealth": asc_hp}],
        }

    encounter = {
        "Id": {"Value": "enc_masked_bandits"},
        "Enemies": [enemy(monsters[0], 34), enemy(monsters[1], 37), enemy(monsters[2], 40)],
        "HeroResources": [{"Resource": {"value": "standard.energy"}, "Current": 3, "Max": 3}],
        "HeroStartingStatuses": [],
        "TriggeredEffects": [],
        "HeroDisplayName": None,
        "CardsDrawnPerTurn": None,
    }

    # ── 事件 ──────────────────────────────────────────────────────────────────────
    event = [
        {
            'Id': 'masked_bandits',
            'TextKey': ('Three figures in oversized red masks block the path. "Pay up to pass! A '
                        'reasonable fee... all of it, ha ha!"'),
            'Options': [
                {
                    'Label': 'Pay (all Gold)',
                    'Effects': [{'Effect': 'gold_all', 'Amount': 0}],
                    'Next': 'masked_bandits.paid',
                },
                {
                    'Label': 'Fight!',
                    # wiki：这场**不算精英**（对 Preserved Insect / Sling of Courage /
                    # Black Star / Slaver's Collar 而言），所以档位是 `monster`。
                    'Effects': [{'Effect': 'nothing', 'Amount': 0}],
                    'Fight': 'monster',
                    'Encounter': 'MaskedBandits',
                    'After': 'masked_bandits.won',
                    'Next': '',
                },
            ],
        },
        {
            'Id': 'masked_bandits.paid',
            'TextKey': ('"Hehehe.. thanks for the gold! Oh, I love gold." They count it twice and '
                        'let you by.'),
            'Options': [{'Label': 'Leave', 'Effects': [{'Effect': 'nothing', 'Amount': 0}],
                         'Next': ''}],
        },
        {
            'Id': 'masked_bandits.won',
            'TextKey': 'The masks lie in the dust. One of them still fits.',
            'Options': [{
                'Label': 'Take the mask',
                # wiki：常规卡牌奖励 + 25-35 金币 + Red Mask。金币走 `gold_random`（区间已在用），
                # 遗物走 `relic:<id>`（§279）。
                'Effects': [{'Effect': 'gold_random:25:35', 'Amount': 0},
                            {'Effect': 'relic:red_mask', 'Amount': 0}],
                'Next': '',
            }],
        },
    ]

    doc['EnemyActions'].extend(actions)
    doc['Monsters'].extend(monsters)
    doc['Encounters'].append(encounter)
    doc['EncounterTables']['MaskedBandits'] = [{'Id': 'enc_masked_bandits'}]
    doc['EventNodes'].extend(event)
    doc['EventTables']['Events2'].append({'Id': 'masked_bandits'})
    doc['UnknownRooms'].append({'Id': 'masked_bandits', 'NameKey': 'Masked Bandits',
                                'Entry': 'masked_bandits'})

    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    print('actions %d monsters %d encounters %d events %d'
          % (len(doc['EnemyActions']), len(doc['Monsters']), len(doc['Encounters']),
             len(doc['EventNodes'])))


main()
