"""§192: the content checker learns the variant **list** shape, plus the second Jaw Worm tier.

`INV_ASC_VARIANTS` was `{action: (threshold, facts)}`. It is now `{action: [(threshold, facts), …]}`
so one action can be pinned at two thresholds -- which is the whole reason the format changed.

The check gets four new judgements, all of them things the old single-slot table could not state:

  1. the content's thresholds for an action are **exactly** the inventory's (no extra, no missing);
  2. they are **strictly ascending and unique** (the kernel picks "largest eligible", so an
     out-of-order or duplicated list would silently change which tier fires);
  3. no variant tells the same story as the **base** or as **another variant** (a tier that does
     nothing is the §190 failure mode: the fight runs, the numbers look plausible, the difficulty
     never moved);
  4. an empty list is red ("I meant to have a tier").
"""
import ast
import io

P = "native/sts_content_check.py"
src = io.open(P, encoding="utf-8").read()


def fmt(fact):
    """One fact tuple, spelled the way the file already spells them (`repr` per part)."""
    return "(" + ", ".join(repr(part) for part in fact) + ")"


# ---------------------------------------------------------------- 1. the table, as data
start = src.index("INV_ASC_VARIANTS = {")
end = src.index("\n}\n", start) + len("\n}\n")
literal = src[start:end]
table = ast.literal_eval(literal[literal.index("{"):])
assert len(table) == 48, len(table)

converted = {}
for key, value in table.items():
    assert isinstance(value, tuple) and len(value) == 2, key
    converted[key] = [value]

# The second tier, from the wiki's single line (`native/wiki_asc/jaw_worm.txt:30`):
#   Gains (3;Asc|2|4;Asc|17|5) Strength.  Gains (6;Asc|17|9) Block.
bellow = converted["jaw_worm.bellow"]
# The A2 tier is the whole program (both nodes), not just the changed one.
assert bellow == [(2, [("status", "standard.strength", 4, "source"),
                       ("block", 6, "source")])], bellow
bellow.append((17, [("status", "standard.strength", 5, "source"),
                    ("block", 9, "source")]))

lines = ["INV_ASC_VARIANTS = {",
         "    # action id: [(AscensionMin, facts), ...] —— §192 起是**列表**：一个动作可以有两个档位",
         "    # （`jaw_worm.bellow` 的 Strength 在 A2 升、Block 在 A17 升）。单档位的动作仍然只写一项。",
         "    # 每一行都是 wiki 的数字；出处见 `native/wiki_asc/<monster>.txt`。"]
for key in sorted(converted):
    entries = converted[key]
    if len(entries) == 1:
        threshold, facts = entries[0]
        lines.append("    %r: [(%d, [%s])]," % (key, threshold, ", ".join(fmt(f) for f in facts)))
    else:
        lines.append("    %r: [" % key)
        for threshold, facts in entries:
            lines.append("        (%d, [%s])," % (threshold, ", ".join(fmt(f) for f in facts)))
        lines.append("    ],")
lines.append("}")
src = src[:start] + "\n".join(lines) + "\n" + src[end:]

# ---------------------------------------------------------------- 2. the check body
check_start = src.index("def check_ascension_variants(doc):")
check_end = src.index("def check_statuses(doc):")
body = '''def check_ascension_variants(doc):
    """§187/§192：**每一条**升档节目都必须被上面那张表钉住，且与基础节目、别的变体**都不同**。"""
    print("[7] ascension variants (port-plan.md §187/§192)")
    actions = {a["Id"]: a for a in doc.get("EnemyActions") or []}
    total = 0
    for aid, entries in INV_ASC_VARIANTS.items():
        action = actions.get(aid)
        if action is None:
            fail("asc." + aid, "action missing")
            continue
        variants = action.get("ProgramAsc")
        if variants is None:
            fail("asc." + aid, "no ProgramAsc")
            continue
        if not isinstance(variants, list) or not variants:
            fail("asc." + aid, "ProgramAsc must be a non-empty **list** (%r)" % (variants,))
            continue
        # 阈值：内容写的这几个必须**正好**是表里那几个（多一个 = 没人钉过的档位）。
        thresholds = []
        for index, variant in enumerate(variants):
            keys = set(variant) if isinstance(variant, dict) else set()
            if keys != {"AscensionMin", "Program"}:
                fail("asc." + aid, "variant[%d] keys %r" % (index, sorted(keys)))
                break
            thresholds.append(variant["AscensionMin"])
        if len(thresholds) != len(variants):
            continue
        if sorted(thresholds) != [t for t, _ in entries]:
            fail("asc." + aid, "thresholds %r, inv says %r"
                 % (thresholds, [t for t, _ in entries]))
            continue
        if thresholds != sorted(set(thresholds)):
            fail("asc." + aid, "thresholds %r are not strictly ascending/unique -- the kernel "
                               "picks the largest eligible, so order must not be load-bearing"
                 % (thresholds,))
        # 事实：每个档位各自与表比；而且**没有两个档位讲同一个故事**。
        seen = [program_facts(action["Program"]["Root"])]
        for variant, (threshold, facts) in zip(variants, entries):
            got = program_facts(variant["Program"]["Root"])
            if got != facts:
                fail("asc." + aid + ".A%d" % threshold,
                     "facts %s, inv says %s" % (got, facts))
            if got in seen:
                fail("asc." + aid + ".A%d" % threshold,
                     "identical to the base or to an earlier variant -- this tier does nothing")
            seen.append(got)
            total += 1
    # 反向：内容里有而表里没有的变体也不行（"没人钉过的数字"）。
    unknown = sorted(aid for aid, action in actions.items()
                     if action.get("ProgramAsc") and aid not in INV_ASC_VARIANTS)
    if unknown:
        fail("asc.unknown", "variants not pinned by the inventory: %s" % unknown)
    ok("ascension variants", "%d variants over %d actions pinned (A2/A3/A4 + A17-A19)"
       % (total, len(INV_ASC_VARIANTS)))


'''
src = src[:check_start] + body + src[check_end:]
io.open(P, "w", encoding="utf-8", newline="").write(src)
print("checker patched: 49 variants over 48 actions")
