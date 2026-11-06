"""Recompute every number `docs/sts-wiki-gap.md` quotes, from the content and the code.

Why this exists: that document is a **gap list**, so almost every row is a number ("26 of 33
potions", "9 of 20 ascensions"). Numbers written into prose rot silently -- the code moves, the
prose does not, and the next reader believes the prose. So the prose points here, and this prints
the truth.

Usage (repo root):

    python -X utf8 native/gap_check.py

It reads:
  * `tools/contentc/packages/sts/sts.roguedeck.json` -- the authored content (ids, tags, tables);
  * `kernel/rd-run/src/state.rs`                     -- the Ascension rule constants;
  * `kernel/rd-core/src/status_catalog.rs`           -- which statuses are declared inert;
  * `tools/acceptance.ps1`                           -- the gate count.

It **does not** read the wiki: the wiki side of the comparison is a citation, and a script that
scrapes the wiki would go red every time somebody edits a page. The wiki numbers are quoted with
their URL, and the "we have" half is what this file measures.
"""

import io
import json
import re
from collections import Counter

CONTENT = "tools/contentc/packages/sts/sts.roguedeck.json"
STATE = "kernel/rd-run/src/state.rs"
CATALOG = "kernel/rd-core/src/status_catalog.rs"
ACCEPT = "tools/acceptance.ps1"


def read(path):
    return io.open(path, encoding="utf-8").read()


def main():
    doc = json.loads(read(CONTENT))

    print("== statuses ==")
    statuses = [s["Id"] for s in doc["Statuses"]]
    print(f"  {len(statuses)} in content: {', '.join(statuses)}")
    catalog = read(CATALOG)
    inert = re.search(r"pub fn is_declared_inert.*?matches!\(\s*status_id,\s*(.*?)\n    \)", catalog, re.S)
    if inert:
        # The `matches!` arm holds one **empty string**: "nothing is inert" has to be sayable, and
        # the rule needs somewhere to put the next one. So an empty id is not a status.
        # ⚠️ Strip `//` comments **first**: the arm's own comment says `"empty" must be sayable`, and
        # reading the raw match reported a status called "empty" -- the measurement was reading the
        # prose next to the code.
        body = re.sub(r"//[^" + chr(10) + r"]*", "", inert.group(1))
        ids = [i for i in re.findall(r'"([^"]*)"', body) if i]
        # §233：这张名单里出现过重复项（一个 id 被两个条目各写一次），而 "声明了 N 条" 应该数 名字 而不是 行数。
        ids = list(dict.fromkeys(ids))
        print(f"  declared inert: {len(ids)}"
              + (f" ({', '.join(ids)})" if ids else " -- every status in the content has a rule"))

    print("== cards ==")
    cards = doc["Cards"]
    upgraded = [c["Id"] for c in cards if c["Id"].endswith("+")]
    tags = Counter()
    for card in cards:
        for tag in card.get("Tags") or []:
            tags[tag.get("value") if isinstance(tag, dict) else tag] += 1
    print(f"  {len(cards)} rows = {len(cards) - len(upgraded)} base + {len(upgraded)} upgraded")
    print(f"  tag rows: {dict(sorted(tags.items()))}")
    print(f"  retain: {[c['Id'] for c in cards if c.get('RetainInHandOnTurnEnd')]}")

    print("== relics ==")
    relics = doc["Relics"]
    print(f"  {len(relics)}: {', '.join(r['Id'] for r in relics)}")
    print(f"  rarities: {dict(Counter(r.get('Rarity', '?') for r in relics))}")

    print("== potions ==")
    potions = doc["Potions"]
    print(f"  {len(potions)}: rarities {dict(Counter(p.get('Rarity', '?') for p in potions))}")
    effects = Counter(str(p.get("Effect", "")).split(":")[0] for p in potions)
    print(f"  effect vocabulary: {dict(sorted(effects.items()))}")

    print("== events ==")
    events = doc["UnknownRooms"]
    vocab = Counter()
    for event in events:
        for slot in (0, 1):
            effect = event.get(f"Effect{slot}")
            if effect:
                vocab[str(effect).split(":")[0]] += 1
    print(f"  {len(events)}: {', '.join(e['Id'] for e in events)}")
    print(f"  effect vocabulary: {dict(sorted(vocab.items()))}")


    print("== event effects (port-plan.md §188) ==")
    rooms = doc.get("UnknownRooms") or []
    base = sum(len(r.get("Effects0") or []) + len(r.get("Effects1") or []) for r in rooms)
    asc = sum(len(r.get("Effects0Asc") or []) + len(r.get("Effects1Asc") or []) for r in rooms)
    lists = sum(1 for r in rooms
                if len(r.get("Effects0") or []) + len(r.get("Effects1") or []) > 2)  # >1 option with 2 effects
    multi = [r["Id"] for r in rooms if len(r.get("Effects0") or []) > 1]
    print("  %d rooms, %d base effect(s) + %d A15-only effect(s)" % (len(rooms), base, asc))
    print("  options with more than one effect: %s" % (", ".join(multi) or "none"))
    print("  rooms with an A15 variant: %d / %d" % (
        sum(1 for r in rooms if r.get("Effects0Asc") or r.get("Effects1Asc")), len(rooms)))

    print("== encounters ==")
    tables = doc["EncounterTables"]
    for key in ("Weak", "Weak2", "Weak3", "Elite", "Elite2", "Elite3", "Boss", "Boss2", "Boss3"):
        listed = tables.get(key) or []
        print(f"  {key:7s} {len(listed)}: {', '.join(str(e) for e in listed)}")
    total = sum(len(tables.get(k) or []) for k in
                ("Weak", "Weak2", "Weak3", "Elite", "Elite2", "Elite3", "Boss", "Boss2", "Boss3"))
    print(f"  total {total}")

    print("== ascension ==")
    state = read(STATE)
    rules = re.findall(r"pub const A_([A-Z_]+): u8 = (\d+);", state)
    print(f"  {len(rules)} rules: " + ", ".join(f"A{level}({name})" for name, level in rules))
    # Which of them are actually *consulted*: a constant nobody reads is a rule nobody applies.
    # ⚠️ Scan the **whole kernel**, and count mentions anywhere rather than `at_least(A_NAME)`
    # literally: A7/A8/A9 are applied through `enemy_health_percent(kind)`, which passes a
    # **variable** to `at_least`, and A6 is applied from `rd-wasm`. A literal grep reported all
    # four as "never read" -- a metric that lies in the direction of "we do less than we do".
    import pathlib
    kernel = ""
    for path in pathlib.Path("kernel").rglob("*.rs"):
        kernel += path.read_text(encoding="utf-8", errors="replace")
    applied, unread = [], []
    for name, level in rules:
        mentions = kernel.count(chr(65) + chr(95) + name)  # 'A_' + name, no escapes
        (applied if mentions > 1 else unread).append((name, level))
    print(f"  consulted somewhere: {len(applied)} -- "
          + ", ".join(f"A{level}" for _, level in applied))
    if unread:
        print("  DECLARED BUT NEVER READ: " + ", ".join(f"A{lv}({n})" for n, lv in unread))


    # ── §187: the ascension **data** (A2/A3/A4 numbers and the A17/18/19 move sets) ──────────────
    # 这几条不是运行层常量，而是内容侧的数字 + 内核的一个条件，所以上面的 `A_*` 扫描看不到它们。
    # 一份"实现了 A2/3/4"的声明如果没人核对，它会在下一次内容变更后变成谎话。
    print("== ascension data (EACT.ProgramAsc, §187/§192) ==")
    # §192: `ProgramAsc` is a **list** `[{AscensionMin, Program}]`, so one action can appear at two
    # thresholds. Counting actions and counting variants are now two different numbers on purpose.
    variants = [a for a in doc.get("EnemyActions") or [] if a.get("ProgramAsc")]
    by_tier = {}
    total = 0
    for action in variants:
        for variant in action["ProgramAsc"]:
            by_tier.setdefault(variant["AscensionMin"], []).append(action["Id"])
            total += 1
    print("  %d action(s) with an ascension variant, %d variant(s) in total"
          % (len(variants), total))
    for tier in sorted(by_tier):
        ids = by_tier[tier]
        more = " (+%d repeated)" % (len(ids) - len(set(ids))) if len(ids) != len(set(ids)) else ""
        print("    A%-2s %s%s" % (tier, ", ".join(sorted(set(ids))), more))
    missing = [a["Id"] for a in doc.get("EnemyActions") or [] if not a.get("ProgramAsc")]
    print("  without a variant: %d action(s) (the content has not sourced them yet)" % len(missing))

    # §193: the spawn rolls (the wiki's "chosen at the start of combat" numbers).
    print("== spawn rolls (ENCT.Enemies[].Rolls, §193) ==")
    for encounter in doc.get("Encounters") or []:
        for record in encounter["Enemies"]:
            rolls = record.get("Rolls") or []
            if rolls:
                print("  %-14s %s" % (record["Id"], ", ".join(
                    "%s %d-%d @A%d" % (r["Key"], r["Min"], r["Max"], r.get("AscensionMin", 0))
                    for r in rolls)))

    # ── §195.9: 一段**可直接粘进文档**的计数区块 ────────────────────────────────────────────────
    # 为什么要有它：README / gap 里的"46 怪 / 120 动作 / 34 状态"这种数字，此前是**人抄**的，改一次内容
    # 就变成谎话，而没有任何闸门会红（审阅 §4.2 的第 2 条）。这里把它们变成"跑一次、贴一次"的产物。
    import json as _json
    import os as _os
    build = _json.loads(read(_os.path.join("tools", "contentc", "packages", "sts", "out",
                                            "build.json")))
    print("== pastable counts (`docs/sts-wiki-gap.md` §1) ==")
    print("  monsters %d / encounters %d / cards %d (base %d + plus %d) / statuses %d /"
          % (len(doc["Monsters"]), len(doc["Encounters"]), len(doc["Cards"]),
             sum(1 for c in doc["Cards"] if not c["Id"].endswith("+")),
             sum(1 for c in doc["Cards"] if c["Id"].endswith("+")),
             len(doc["Statuses"])))
    events = doc.get("EventTables") or {}
    # The event pools are **three** per-act lists (Events / Events2 / Events3); the old README said
    # "9 events" which was neither the sum nor any one pool.
    event_counts = [len(events.get(key) or []) for key in ("Events", "Events2", "Events3")]
    print("  enemy actions %d / relics %d / potions %d / events %d (%s) / start deck %d"
          % (len(doc["EnemyActions"]), len(doc["Relics"]), len(doc["Potions"]),
             sum(event_counts), "+".join(str(n) for n in event_counts),
             len(doc["Start"]["Deck"])))
    variants = sum(len(a["ProgramAsc"]) for a in doc["EnemyActions"] if a.get("ProgramAsc"))
    print("  ascension variants %d over %d actions"
          % (variants, sum(1 for a in doc["EnemyActions"] if a.get("ProgramAsc"))))
    if isinstance(build, dict):
        # `images` is `{variant: {file, bytes, sha256}}`, not a list.
        for variant, image in (build.get("images") or {}).items():
            print("  image %-6s %-26s %7d B" % (variant, image.get("file", "?"),
                                                image.get("bytes", 0)))

    print("== gates ==")
    accept = read(ACCEPT)
    names = re.findall(r"Invoke-Gate -Name '([a-z0-9-]+)'", accept)
    names.append("golden-baseline")  # registered as a plain object, not via Invoke-Gate
    print(f"  {len(names)}: {', '.join(sorted(names))}")


if __name__ == "__main__":
    main()
