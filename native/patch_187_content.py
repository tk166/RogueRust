"""§187 content, second attempt: **mutate the base program**, never author a node.

The first attempt wrote the ascension programs by hand and got two dialect facts wrong
(`createCardInstance` wants `ToZone`, not `Destination`; the target selector is `eventTarget`). That
is the §183 trap again: a hand-written node is a shape guess, and a wrong shape either fails to
compile or — worse — decodes as something the kernel reads differently.

So: deep-copy `action["Program"]["Root"]` and change only the **constants** the wiki gives us. If the
mutation cannot find the thing it is supposed to change, it **fails loudly** instead of writing a
variant that silently equals the base (an ascension that does nothing is a typo with no symptoms).

Thresholds (kind-based, see `port-plan.md` §187): normal 2 / elite 3 / boss 4 for damage numbers;
17/18/19 for move-set changes.

| action | what changes | wiki |
|---|---|---|
| `blue_slaver.stab` | damage 12 -> 13 @A2 | `Asc|2|13` |
| `blue_slaver.rake` | damage 7 -> 8 @A2 | `Asc|2|8` |
| `slaver_red.stab` | damage 13 -> 14 @A2 | `Asc|2|14` |
| `slaver_red.scrape` | damage 8 -> 9 @A2 | `Asc|2|9` |
| `lagavulin.attack` | damage 18 -> 20 @A3 | `Asc|3|20` |
| `book_of_stabbing.multi_stab` | per-hit 6 -> 7 @A3 **and** the count becomes `turn + 1` | `Asc|3|7×N`, `Asc|18|` N = turn + 1 |
| `book_of_stabbing.big_stab` | damage 21 -> 24 @A3 | `Asc|3|24` |
| `nemesis.tri_attack` | 3 hits of 6 -> 7 @A4 | `Asc|3|7×3` |
| `nemesis.tri_burn` | 3 Burns -> 5 @A19 | `Asc|18|5` |
| `reptomancer.big_bite` | damage 30 -> 34 @A4 | `Asc|3|34` |
| `reptomancer.snake_strike` | 2 hits of 13 -> 16 @A4 | `Asc|3|16×2` |
| `reptomancer.spawn_dagger` | 1 Dagger -> 2 @A19 | `Asc|18|2` |
| `taskmaster.scouring_whip` | 1 Wound -> 2 @A3 | `Asc|2|2` |

`multi_stab` is both: at A18 the *count* changes from "times used + 2" to "current turn + 1", which is
the elite's move-set change and the reason the expression `currentTurn` exists.
"""
import copy
import io
import json

SRC = "tools/contentc/packages/sts/sts.roguedeck.json"


def walk(node, visit):
    """Depth-first over a program tree (dicts/lists only)."""
    visit(node)
    if isinstance(node, dict):
        for value in node.values():
            walk(value, visit)
    elif isinstance(node, list):
        for value in node:
            walk(value, visit)


def count_kind(node, kind):
    found = []
    walk(node, lambda n: found.append(n) if isinstance(n, dict) and n.get("kind") == kind else None)
    return found


def set_damage(root, before, after):
    """Returns `None`: the tree is edited in place."""
    """Every `node.dealDamage` whose constant amount is `before` becomes `after`."""
    hits = 0
    for node in count_kind(root, "node.dealDamage"):
        amount = node["value"].get("Amount") or {}
        if amount.get("kind") == "const" and amount["value"]["Value"] == before:
            amount["value"]["Value"] = after
            hits += 1
    assert hits > 0, "no dealDamage with amount %d -- the base program moved" % before
    return hits


def set_card_count(root, before, after):
    made = 0
    for node in count_kind(root, "node.createCardInstance"):
        count = node["value"].get("Count") or {}
        if count.get("kind") == "const" and count["value"]["Value"] == before:
            count["value"]["Value"] = after
            made += 1
    assert made > 0, "no createCardInstance with count %d" % before
    return made


def multi_stab_at_18(root):
    """`N = current turn + 1` replaces `N = uses + 2` (the elite's A18 move set)."""
    repeats = count_kind(root, "node.repeat")
    assert len(repeats) == 1, len(repeats)
    repeat = repeats[0]["value"]
    repeat["Count"] = {
        "kind": "add",
        "value": {
            "Left": {
                "kind": "currentTurn",
                "value": {
                    "Selector": {
                        "kind": "sel.source",
                        "value": {
                            "Cardinality": "ZeroOrOne",
                            "RequiredContextCapabilities": "Source",
                        },
                    }
                },
            },
            "Right": {"kind": "const", "value": {"Value": 1}},
        },
    }
    # the per-hit damage is the *other* half of the same rule
    set_damage(repeat["Body"], 6, 7)


def two_daggers(root):
    spawns = count_kind(root, "node.createCombatant")
    assert len(spawns) == 1, len(spawns)
    twin = copy.deepcopy(spawns[0])
    parent = root
    if parent.get("kind") == "node.createCombatant":
        # wrap the single spawn into a sequence of two
        return {"kind": "node.sequence", "value": {"Children": [root, twin]}}
    raise AssertionError("spawn_dagger is expected to be a bare createCombatant")


def main():
    document = json.load(io.open(SRC, encoding="utf-8"))
    actions = {action["Id"]: action for action in document["EnemyActions"]}
    touched = 0
    for action_id, threshold, mutate in [
        ("blue_slaver.stab", 2, lambda root: set_damage(root, 12, 13)),
        ("blue_slaver.rake", 2, lambda root: set_damage(root, 7, 8)),
        ("slaver_red.stab", 2, lambda root: set_damage(root, 13, 14)),
        ("slaver_red.scrape", 2, lambda root: set_damage(root, 8, 9)),
        ("lagavulin.attack", 3, lambda root: set_damage(root, 18, 20)),
        ("book_of_stabbing.multi_stab", 3, multi_stab_at_18),
        ("book_of_stabbing.big_stab", 3, lambda root: set_damage(root, 21, 24)),
        ("nemesis.tri_attack", 4, lambda root: set_damage(root, 6, 7)),
        ("nemesis.tri_burn", 19, lambda root: set_card_count(root, 3, 5)),
        ("reptomancer.big_bite", 4, lambda root: set_damage(root, 30, 34)),
        ("reptomancer.snake_strike", 4, lambda root: set_damage(root, 13, 16)),
        ("reptomancer.spawn_dagger", 19, two_daggers),
        ("taskmaster.scouring_whip", 3, lambda root: set_card_count(root, 1, 2)),
    ]:
        action = actions[action_id]
        root = copy.deepcopy(action["Program"]["Root"])
        # ⚠️ 改写器**可以返回一个新根**（`two_daggers` 把单个 spawn 包成 sequence）。
        # 第一版丢了这个返回值，于是那一行的“变体”**与基础完全相同**——
        # 而闸门只看剧本能不能跑，看不出"什么都没变"。
        # 只有**真的返回了一棵树**才替换根（`two_daggers`可以包一层）。
        # ⚠️ 第二版写成 `mutate(root) or root`，而 `set_damage` 返回的是**命中次数**（一个 int）
        # —— 于是那些行的 `Root` 变成了一个整数，内容门在第一个字段上就跨了。
        rebuilt = mutate(root)
        if isinstance(rebuilt, dict):
            root = rebuilt
        envelope = copy.deepcopy(action["Program"])
        envelope["Root"] = root
        action["ProgramAsc"] = envelope
        action["AscensionMin"] = threshold
        touched += 1
        print("%-32s A%-2d" % (action_id, threshold))
    assert touched == 13, touched
    with io.open(SRC, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(document, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print("wired", touched, "variants by mutating the base programs")


if __name__ == "__main__":
    main()
