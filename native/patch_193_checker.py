"""§193 checker: the spawn-roll vocabulary, pinned against the wiki and against the programs.

Three things are added, and each one closes a hole that the "0 damage" shape would otherwise leave:

1. `amount()` learns `combatantCounter`, so a damage node that reads a counter is a **fact**
   (`("counter", "roll.bite", "source")` as the amount) instead of `("expr", "combatantCounter")`.
   That keeps `program_facts` exhaustive -- an amount kind nobody pinned still raises.
2. `INV_ROLLS` is the independent second copy of the wiki's ranges
   (`native/wiki_asc/louse.txt:28`, `native/wiki_asc/darkling.txt:32`), with the "chosen at the
   start of combat" shape: `Key` + `Min` + `Max` + optional `AscensionMin`, exactly the tiers the
   wiki states.
3. The **cross-check**: every counter read in an action program must be a counter that the record
   which lists that action actually rolls. Without it the two halves of one number could drift --
   program reads `roll.bite`, record rolls `bite`, and the damage is silently 0 in every fight while
   the checker says both halves are fine (the §161.3 "one vocabulary known in two places" shape).

Plus `INV_UNWIRED`: `louse_green.*` has actions but no enemy record. That is a *fact about this
content* that must stay true or be fixed -- it is what keeps "don't convert the green bite" honest.
"""
import io

P = "native/sts_content_check.py"
src = io.open(P, encoding="utf-8").read()


def sub(old, new, what=""):
    global src
    assert src.count(old) == 1, "%s: %d occurrences of %r" % (what, src.count(old), old[:70])
    src = src.replace(old, new)


# ---------------------------------------------------------------- 1. amount()
sub('''def amount(expr):
    if expr.get("kind") == "const":
        return expr["value"]["Value"]
    return ("expr", expr.get("kind"))''',
'''def amount(expr):
    if expr.get("kind") == "const":
        return expr["value"]["Value"]
    if expr.get("kind") == "combatantCounter":
        # §193: a damage/gain whose size is a **counter**. Spelled with its key *and* the selector,
        # so "the wrong unit's counter" is a visible fact and not an interchangeable number.
        return ("counter", expr["value"]["CounterId"], tgt(expr["value"]["Selector"]))
    return ("expr", expr.get("kind"))''', what="amount()")

# ---------------------------------------------------------------- 2. the two actions + the unwired pair
sub('''    "darkling.nip": ("Attack", [("damage", 7, "event")]),''',
'''    # §193: `N = Number between (7-11;{{Asc|2|9-13}}), chosen at the start of combat` -- the amount
    # is a counter the fight rolls at spawn, not a constant (the range lives in `INV_ROLLS`).
    "darkling.nip": ("Attack", [("damage", ("counter", "roll.nip", "source"), "event")]),''',
    what="darkling.nip")

sub('''    "louse_red.bite": ("Attack", [("damage", 6, "event")]),''',
'''    # §193: `N = Number between (5-7;{{Asc|2|6-8}}), chosen at the start of combat`.
    "louse_red.bite": ("Attack", [("damage", ("counter", "roll.bite", "source"), "event")]),''',
    what="louse_red.bite")

# ---------------------------------------------------------------- 3. INV_ROLLS + INV_UNWIRED, before the ascension check
anchor = "def check_ascension_variants(doc):"
if anchor not in src:
    raise SystemExit("check_ascension_variants not found -- the file moved, fix this patch")
tables = '''# §193: the wiki's damage ranges, as an **independent second copy**.
#
#   native/wiki_asc/louse.txt:28      Deals N damage. N between (5-7;{{Asc|2|6-8}}), chosen at the
#                                     start of combat.
#   native/wiki_asc/darkling.txt:32   Deals N damage. N between (7-11;{{Asc|2|9-13}}), chosen at
#                                     the start of combat.
#
# enemy record id: [(Key, Min, Max, AscensionMin), ...]  -- `AscensionMin` absent = the base range.
INV_ROLLS = {
    "louse_red": [("roll.bite", 5, 7, 0), ("roll.bite", 6, 8, 2)],
    "darkling": [("roll.nip", 7, 11, 0), ("roll.nip", 9, 13, 2)],
}

# §193: actions that exist in `EACT` but that **no enemy record lists**. They must not be converted
# to a counter read -- a counter nobody rolls reads 0, and 0 damage is a landmine that the
# ENEMY_DIFF harness cannot see (it runs every `EACT` row against a synthesised `<prefix>` enemy).
# The day one of these gets a record, this table goes red and forces the roll to be written too.
INV_UNWIRED = {"louse_green.bite", "louse_green.grow"}


'''
sub(anchor, tables + anchor + '', what="INV_ROLLS insertion")

# ---------------------------------------------------------------- 4. the check itself, right after check_actions
check = '''def check_spawn_rolls(doc):
    """§193: 每条计数器读取都必须被**列出这条动作的那个敌人的**掷骰覆盖。"""
    print("[7b] spawn rolls (port-stage/§193)")
    records = {}
    for encounter in doc.get("Encounters") or []:
        for record in encounter["Enemies"]:
            records.setdefault(record["Id"], []).append(record)

    # ① 记录侧的形态：只有表里的敌人掷骰，而且范围/档位逐个对得上。
    for record_id, group in records.items():
        for record in group:
            rolls = record.get("Rolls")
            if rolls is None:
                fail("roll." + record_id, "the record has no `Rolls` key (shape drift)")
                continue
            got = [(r["Key"], r["Min"], r["Max"], r.get("AscensionMin", 0)) for r in rolls]
            want = INV_ROLLS.get(record_id, [])
            if got != want:
                fail("roll." + record_id, "%r, inv says %r" % (got, want))
            # 值域必须能被一次 `shuffled_pick_index` 覆盖（下标是 u8），而且 Min 不许比 Max 大。
            for key, low, high, threshold in got:
                if high < low:
                    fail("roll." + record_id, "`%s`: Max %d < Min %d" % (key, high, low))
                if high - low + 1 > 255:
                    fail("roll." + record_id,
                         "`%s`: %d values do not fit the u8 pick index" % (key, high - low + 1))
                if threshold < 0:
                    fail("roll." + record_id, "`%s`: negative AscensionMin" % key)
            # 同一个 Key 的阈值必须严格升序（与 `ProgramAsc` 同一条规矩：顺序不参与判定，
            # 但"两行同阈值"选谁都是猜）。
            by_key = {}
            for key, _, _, threshold in got:
                by_key.setdefault(key, []).append(threshold)
            for key, thresholds in by_key.items():
                if thresholds != sorted(set(thresholds)):
                    fail("roll." + record_id,
                         "`%s`: thresholds %r are not strictly ascending/unique" % (key, thresholds))
    unknown = sorted(record_id for record_id in INV_ROLLS if record_id not in records)
    if unknown:
        fail("roll.unknown", "inventory names enemies that are not in the content: %s" % unknown)

    # ② 程序侧：每个计数器读取都必须是**列这条动作的记录**掷过的键。
    actions = {a["Id"]: a for a in doc.get("EnemyActions") or []}
    readers = 0
    for record_id, group in records.items():
        for record in group:
            rolled = {r["Key"] for r in record.get("Rolls") or []}
            for action_id in record["Actions"]:
                action_id = action_id["value"] if isinstance(action_id, dict) else action_id
                program = actions.get(action_id)
                if program is None:
                    fail("roll." + action_id, "record lists an action that is not in EACT")
                    continue
                for fact in program_facts(program["Program"]["Root"]):
                    # 事实的形状是 ("damage", amount, target)；amount 是 3 元组才是计数器读取。
                    if fact[0] not in ("damage", "block", "heal"):
                        continue
                    size = fact[1]
                    if not isinstance(size, tuple) or size[0] != "counter":
                        continue
                    readers += 1
                    if size[2] != "source":
                        fail("roll." + action_id,
                             "reads a counter from `%s`, not from itself" % size[2])
                    if size[1] not in rolled:
                        fail("roll." + action_id,
                             "reads `%s` but `%s` never rolls it (damage would be 0)" % (size[1], record_id))

    # ③ 反向：没有敌人记录的动作**不许**读计数器（见 `INV_UNWIRED` 的理由）。
    listed = set()
    for record in records.values():
        for action_ids in record:
            for action_id in action_ids["Actions"]:
                listed.add(action_id["value"] if isinstance(action_id, dict) else action_id)
    for action_id, action in actions.items():
        if action_id in listed:
            continue
        for fact in program_facts(action["Program"]["Root"]):
            if fact[0] in ("damage", "block", "heal") and isinstance(fact[1], tuple) \\
                    and fact[1][0] == "counter":
                fail("roll.unwired." + action_id,
                     "unreachable action reads a counter nobody rolls")
    for action_id in INV_UNWIRED:
        if action_id in listed:
            fail("roll.wired." + action_id,
                 "this action now has an enemy record -- give it a roll and drop it from INV_UNWIRED")
    ok("spawn rolls", "%d ranges over %d enemies, %d counter reads wired"
       % (sum(len(v) for v in INV_ROLLS.values()), len(INV_ROLLS), readers))


'''
sub("def check_statuses(doc):", check + "def check_statuses(doc):", what="check_spawn_rolls")

# ⑤ call it (right after the ascension-variant check, which is the section it extends)
sub("    check_ascension_variants(doc)", "    check_ascension_variants(doc)\n    check_spawn_rolls(doc)",
    what="call site")

io.open(P, "w", encoding="utf-8", newline="").write(src)
print("checker patched for §193")
