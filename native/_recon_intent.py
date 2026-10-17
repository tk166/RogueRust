#!/usr/bin/env python3
"""_recon_intent.py -- one-off recon for docs/spec/enemy-intent.md.

Measures the REAL core image: EACT row shape, Program root kinds, Intent shapes,
ENCT enemy roster shape, and how enemies reference enemy actions.

Read-only.  Writes nothing but stdout.
"""

import collections
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(os.path.dirname(HERE), "tools", "contentc")
sys.path.insert(0, TOOLS)

import rdcfmt as F          # noqa: E402
import reader as R          # noqa: E402

SEC_BY_TABLE = {"EACT": F.S_EACT, "ENCT": F.S_ENCT, "CARD": F.S_CARD,
                "STAT": F.S_STAT, "REL": F.S_REL}


def raw_cells(rom, table, index):
    blob = rom.sections[SEC_BY_TABLE[table]]
    stride = F.row_stride(table)
    schema = F.ROW_SCHEMAS[table]
    off = index * stride
    out = []
    i = off
    for _name, fk, _fl in schema:
        w = F.FIELD_SLOTS[fk]
        out.append(list(struct.unpack_from("<%dH" % w, blob, i)))
        i += 2 * w
    return out


def kind_of(term):
    if term is None:
        return "<null>"
    if isinstance(term, dict):
        if "kind" in term:
            return term["kind"]
        return "_obj(" + ",".join(sorted(term)) + ")"
    if isinstance(term, list):
        return "list"
    return "<scalar:%s>" % type(term).__name__


def unwrap(x):
    """`{"value": s}` / `{"Value": s}` -> s; anything else unchanged."""
    if isinstance(x, dict) and len(x) == 1:
        k = next(iter(x))
        if k in ("value", "Value"):
            return x[k]
    return x


def term_children(rom, tid, out, depth=0):
    """Walk a term's slot graph, collecting every reachable term id."""
    if tid in out or depth > 400:
        return
    op, slots = rom.term_slots(tid)
    out.add(tid)
    for s in slots:
        # A slot is a term id only if it lands in range AND decodes.
        # AUX / string / int slots may alias term ids, so filter by opcode validity.
        if s < rom.n_terms:
            try:
                term_children(rom, s, out, depth + 1)
            except Exception:
                pass


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(TOOLS, "out", "content.core.rdcf")
    rom = load = R.Rom(open(path, "rb").read())
    print("== image ==")
    print(json.dumps(rom.stats(), indent=1))

    eacts = rom._rows("EACT")
    encts = rom._rows("ENCT")
    print("\n== row counts / strides / cells ==")
    print("EACT rows: %d stride: %d cells: %d"
          % (len(eacts), F.row_stride("EACT"), len(F.EACT_ROW)))
    print("ENCT rows: %d stride: %d cells: %d"
          % (len(encts), F.row_stride("ENCT"), len(F.ENCT_ROW)))

    # ---------------------------------------------------------------- EACT cells
    print("\n== EACT: raw cell values, per cell (7 cells) ==")
    for ci, (name, fk, fl) in enumerate(F.EACT_ROW):
        c = collections.Counter()
        for i in range(len(eacts)):
            sl = raw_cells(rom, "EACT", i)[ci]
            v = sl[0]
            if v == 0xFFFF:
                c["ABSENT(0xFFFF)"] += 1
            elif v == 0xFFFE:
                c["NULL(0xFFFE)"] += 1
            else:
                c["value"] += 1
        print("  cell %d %-18s kind=%-6s flags=%d  %s"
              % (ci, name, F.FIELD_NAMES[fk], fl, dict(c)))

    print("\n== EACT: Program cell 5 -> root term kind ==")
    c = collections.Counter()
    for i in range(len(eacts)):
        sl = raw_cells(rom, "EACT", i)[5][0]
        c["<ABSENT>" if sl == 0xFFFF else ("<NULL>" if sl == 0xFFFE
                                           else kind_of(rom.term(sl)))] += 1
    for k, n in c.most_common():
        print("  %-56s %d" % (k, n))

    print("\n== EACT: Program envelope opcode + Root kind distribution ==")
    env_ops = collections.Counter()
    root_kinds = collections.Counter()
    prog_ids = collections.Counter()
    depth_vals = collections.Counter()
    steps_vals = collections.Counter()
    for i in range(len(eacts)):
        sl = raw_cells(rom, "EACT", i)[5][0]
        op, _ = rom.term_slots(sl)
        env_ops[(op, rom.opcodes[op]["name"])] += 1
        env = rom.term(sl)
        prog_ids[repr(unwrap(env.get("Id")))] += 1
        depth_vals[repr(env.get("MaxNodeDepth"))] += 1
        steps_vals[repr(env.get("MaxProgramSteps"))] += 1
        root_kinds[kind_of(env.get("Root"))] += 1
    for k, n in env_ops.most_common():
        print("  envelope op=%d name=%s  count=%d" % (k[0], k[1], n))
    print("  MaxNodeDepth values:", dict(sorted(depth_vals.items(), key=lambda x: (x[0] is None, x[0]))))
    print("  MaxProgramSteps values:", dict(sorted(steps_vals.items(), key=lambda x: (x[0] is None, x[0]))))
    print("  Root kind distribution:")
    for k, n in root_kinds.most_common():
        print("    %-30s %d" % (k, n))
    print("  distinct Program.Id strings: %d (dupes: %s)"
          % (len(prog_ids), [k for k, v in prog_ids.items() if v > 1][:5]))

    print("\n== EACT: Intent cell 4 ==")
    c = collections.Counter()
    for i in range(len(eacts)):
        sl = raw_cells(rom, "EACT", i)[4][0]
        if sl in (0xFFFF, 0xFFFE):
            c["<%s>" % ("ABSENT" if sl == 0xFFFF else "NULL")] += 1
        else:
            op, _ = rom.term_slots(sl)
            c["op=%d %s" % (op, rom.opcodes[op]["name"])] += 1
    for k, n in c.most_common():
        print("  %-40s %d" % (k, n))

    print("\n== EACT: Intent keys + Kind distribution ==")
    keys = collections.Counter()
    kinds = collections.Counter()
    for i in range(len(eacts)):
        it = eacts[i].get("Intent")
        if isinstance(it, dict):
            for k in it:
                keys[k] += 1
            kinds[it.get("Kind")] += 1
    print("  Intent keys:", dict(keys))
    for k, n in kinds.most_common():
        print("  Kind=%-10s %d" % (k, n))

    print("\n== EACT: extra cell 6 ==")
    c = collections.Counter()
    for i in range(len(eacts)):
        sl = raw_cells(rom, "EACT", i)[6][0]
        if sl in (0xFFFF, 0xFFFE):
            c["<%s>" % ("ABSENT" if sl == 0xFFFF else "NULL")] += 1
        else:
            c[json.dumps(rom.term(sl), sort_keys=True)[:100]] += 1
    for k, n in c.most_common(10):
        print("  %-50s %d" % (k, n))

    print("\n== EACT: PackageId / NameKey / DescriptionKey ==")
    print("  PackageId:", dict(collections.Counter(r.get("PackageId") for r in eacts)))
    print("  NameKey present:", sum(1 for r in eacts if "NameKey" in r))
    print("  DescriptionKey present:", sum(1 for r in eacts if "DescriptionKey" in r))

    print("\n== EACT: first 8 ids ==")
    for i in range(8):
        print("  [%d] %s" % (i, eacts[i].get("Id")))

    # ---------------------------------------------------------------- ENCT cells
    print("\n== ENCT: raw cell values, per cell (8 cells) ==")
    for ci, (name, fk, fl) in enumerate(F.ENCT_ROW):
        c = collections.Counter()
        for i in range(len(encts)):
            v = raw_cells(rom, "ENCT", i)[ci][0]
            if v == 0xFFFF:
                c["ABSENT"] += 1
            elif v == 0xFFFE:
                c["NULL16"] += 1
            elif fk == F.F_INT and v in (0x8000, 0x8001):
                c["INT_ABSENT" if v == 0x8000 else "INT_NULL"] += 1
            else:
                c["value"] += 1
        print("  cell %d %-22s kind=%-6s flags=%d  %s"
              % (ci, name, F.FIELD_NAMES[fk], fl, dict(c)))

    print("\n== ENCT[0] decoded ==")
    print(json.dumps(encts[0], indent=1, ensure_ascii=False)[:2500])

    # ---------------------------------------------------------------- enemies
    print("\n== ENCT: enemies per encounter ==")
    per = collections.Counter()
    total_enemies = 0
    for i in range(len(encts)):
        e = encts[i].get("Enemies")
        n = len(e) if isinstance(e, list) else 0
        per[n] += 1
        total_enemies += n
    print("  total enemy records: %d over %d encounters" % (total_enemies, len(encts)))
    print("  histogram:", dict(sorted(per.items())))

    print("\n== ENCT enemy record: keys ==")
    keys = collections.Counter()
    shapes = collections.Counter()
    for i in range(len(encts)):
        for el in encts[i].get("Enemies") or []:
            if isinstance(el, dict):
                shapes[kind_of(el)] += 1
                for k in el:
                    keys[k] += 1
    for k, n in shapes.most_common():
        print("  shape %-70s %d" % (k, n))
    for k, n in keys.most_common():
        print("  key %-22s %d" % (k, n))

    print("\n== ENCT enemies: Actions ==")
    act_len = collections.Counter()
    referenced_cycle = set()
    referenced_rule = set()
    bad_ref = set()
    all_ids = set(r.get("Id") for r in eacts)
    for i in range(len(encts)):
        for el in encts[i].get("Enemies") or []:
            if not isinstance(el, dict):
                continue
            for a in el.get("Actions") or []:
                s = unwrap(a)
                referenced_cycle.add(s)
                if s not in all_ids:
                    bad_ref.add(s)
            for rule in el.get("IntentRules") or []:
                if isinstance(rule, dict) and "Action" in rule:
                    s = unwrap(rule["Action"])
                    referenced_rule.add(s)
                    if s not in all_ids:
                        bad_ref.add(s)
    print("  distinct EACT ids named in Actions:", len(referenced_cycle))
    print("  distinct EACT ids named in IntentRules:", len(referenced_rule))
    print("  Actions-only (never a rule action):", len(referenced_cycle - referenced_rule))
    print("  rules-only (never in a cycle):", len(referenced_rule - referenced_cycle))
    print("  referenced ids that are NOT an EACT row:", len(bad_ref), sorted(bad_ref)[:5])
    never = all_ids - referenced_cycle - referenced_rule
    print("  EACT ids never referenced by anything:", len(never))
    print("   e.g.", sorted(never)[:10])
    print("  actions-per-enemy histogram:", dict(sorted(act_len.items())))

    print("\n== ENCT enemies: IntentRules ==")
    cond_kinds = collections.Counter()
    rule_prio = collections.Counter()
    enemies_with_rules = 0
    rules_per_enemy = collections.Counter()
    cond_keys = collections.Counter()
    for i in range(len(encts)):
        for el in encts[i].get("Enemies") or []:
            if not isinstance(el, dict):
                continue
            rules = el.get("IntentRules") or []
            rules_per_enemy[len(rules)] += 1
            if rules:
                enemies_with_rules += 1
            for rule in rules:
                rule_prio[rule.get("Priority")] += 1
                cond = rule.get("Condition")
                cond_kinds[kind_of(cond)] += 1
                if isinstance(cond, dict) and "kind" not in cond:
                    for k in cond:
                        cond_keys[k] += 1
    print("  enemies with >=1 rule: %d / %d" % (enemies_with_rules, total_enemies))
    print("  rules-per-enemy histogram:", dict(sorted(rules_per_enemy.items())))
    print("  Priority values:", dict(sorted(rule_prio.items())))
    print("  Condition kinds:")
    for k, n in cond_kinds.most_common():
        print("    %-34s %d" % (k, n))
    if cond_keys:
        print("  plain-object Condition keys:", dict(cond_keys))

    print("\n== ENCT enemies: MaxHealth / Position / StartingStatuses ==")
    mh = collections.Counter()
    pos = collections.Counter()
    ss = collections.Counter()
    for i in range(len(encts)):
        for el in encts[i].get("Enemies") or []:
            if not isinstance(el, dict):
                continue
            mh[el.get("MaxHealth")] += 1
            pos[json.dumps(el.get("Position"))] += 1
            ss[len(el.get("StartingStatuses") or [])] += 1
    print("  MaxHealth range: min=%s max=%s distinct=%d"
          % (min(x for x in mh if x is not None), max(x for x in mh if x is not None), len(mh)))
    print("  Position values:", dict(pos))
    print("  starting-status count histogram:", dict(sorted(ss.items())))

    # ---------------------------------------------------------------- encounters
    print("\n== ENCT: CardsDrawnPerTurn / TriggeredEffects ==")
    cdp = collections.Counter(encts[i].get("CardsDrawnPerTurn") for i in range(len(encts)))
    print("  CardsDrawnPerTurn:", dict(cdp))
    te = collections.Counter(len(encts[i].get("TriggeredEffects") or []) for i in range(len(encts)))
    print("  TriggeredEffects count histogram:", dict(sorted(te.items())))
    hr = collections.Counter(len(encts[i].get("HeroResources") or []) for i in range(len(encts)))
    print("  HeroResources count histogram:", dict(sorted(hr.items())))
    print("  HeroResources[0] of ENCT[0]:", json.dumps(encts[0].get("HeroResources")))
    print("  distinct encounter ids:", len(set(unwrap(e.get("Id")) for e in encts)))

    # ---------------------------------------------------------------- Weight reachability
    print("\n== is any _obj(Value,Weight) term reachable from EACT/ENCT? ==")
    wop = [op for op, d in enumerate(rom.opcodes)
           if d["name"] == "_obj" and [f[0] for f in d["fields"]] == ["Value", "Weight"]]
    weight_terms = set()
    for tid in range(rom.n_terms):
        o, _ = rom.term_slots(tid)
        if o in wop:
            weight_terms.add(tid)
    print("  _obj(Value,Weight) opcodes:", wop, " terms:", len(weight_terms))
    reach = set()
    for i in range(len(eacts)):
        sl = raw_cells(rom, "EACT", i)[5][0]
        if sl < rom.n_terms:
            term_children(rom, sl, reach)
    for i in range(len(encts)):
        for ci in (1, 2, 3, 4, 6):
            sl = raw_cells(rom, "ENCT", i)[ci][0]
            if sl < rom.n_terms:
                term_children(rom, sl, reach)
    print("  reachable terms from EACT.Program + ENCT cells:", len(reach))
    print("  of those that are _obj(Value,Weight):", len(reach & weight_terms))
    print("  (NOTE: slot/term aliasing makes this an OVER-approximation)")

    # ---------------------------------------------------------------- IDX
    print("\n== IDX ==")
    ek = collections.Counter()
    for s, e, idx in rom.idx:
        ek[F.EK_NAMES.get(e, e)] += 1
    print("  ", dict(ek))
    print("  lookup('a_very_official_line.shuffle_forward') ->",
          rom.lookup("a_very_official_line.shuffle_forward"))
    print("  lookup first 3 encounter ids ->",
          [rom.lookup(unwrap(encts[i].get("Id"))) for i in range(3)])

    # ---------------------------------------------------------------- intent IR
    print("\n== every IR kind whose name contains 'intent' ==")
    for op, d in enumerate(rom.opcodes):
        if d["opclass"] == F.OPCLASS_IR and "intent" in (d["name"] or "").lower():
            print("  op=%-4d %-30s fields=%s"
                  % (op, d["name"], [(f[0], F.FIELD_NAMES[f[1]]) for f in d["fields"]]))

    print("\n== condition opcodes reachable from IntentRules (with field lists) ==")
    cond_ops = set()
    for i in range(len(encts)):
        for el in encts[i].get("Enemies") or []:
            if not isinstance(el, dict):
                continue
            for rule in el.get("IntentRules") or []:
                cond = rule.get("Condition")
                if isinstance(cond, dict) and "kind" in cond:
                    for op, d in enumerate(rom.opcodes):
                        if d["name"] == cond["kind"]:
                            cond_ops.add(op)
    for op in sorted(cond_ops):
        d = rom.opcodes[op]
        print("  op=%-4d %-30s class=%d fields=%s"
              % (op, d["name"], d["opclass"],
                 [(f[0], F.FIELD_NAMES[f[1]]) for f in d["fields"]]))

    print("\n== all opcodes whose name starts with 'intent.' ==")
    for op, d in enumerate(rom.opcodes):
        if (d["name"] or "").startswith("intent."):
            print("  op=%-4d %-30s class=%d fields=%s"
                  % (op, d["name"], d["opclass"],
                     [(f[0], F.FIELD_NAMES[f[1]]) for f in d["fields"]]))


def walk(node, on_kind, on_key, depth=0):
    if depth > 200:
        return
    if isinstance(node, dict):
        if "kind" in node and isinstance(node["kind"], str):
            on_kind(node["kind"])
        for k, v in node.items():
            on_key(k)
            walk(v, on_kind, on_key, depth + 1)
    elif isinstance(node, list):
        for v in node:
            walk(v, on_kind, on_key, depth + 1)


def analyse(path, label):
    """Part 2: exact walk of the DECODED graph (no slot aliasing)."""
    rom = R.Rom(open(path, "rb").read())
    print("\n############ %s ############" % label)
    print("stats:", json.dumps(rom.stats()))
    eacts = rom._rows("EACT")
    encts = rom._rows("ENCT")

    kinds = collections.Counter()
    keys = collections.Counter()
    per_row_kinds = collections.Counter()
    suspicious = collections.Counter()
    for r in eacts:
        row_kinds = collections.Counter()
        row_keys = set()

        def k(x):
            row_kinds[x] += 1

        def kk(x):
            row_keys.add(x)

        walk(r.get("Program"), k, kk)
        kinds.update(row_kinds)
        keys.update(row_keys)
        for s in ("Weight", "Condition", "Cooldown", "Chance", "Probability",
                  "Weighted", "Round", "Turn", "MinRound", "MaxRound"):
            if s in row_keys:
                suspicious[s] += 1
        per_row_kinds[len(row_kinds)] += 1

    print("\n-- every IR kind at ANY depth of an EACT.Program (394 rows) --")
    for k2, n in kinds.most_common():
        print("  %-32s %d" % (k2, n))
    print("-- distinct kinds per program --", dict(sorted(per_row_kinds.items())))
    print("-- suspicious keys in programs --", dict(suspicious) or "none")
    print("-- every key in programs (%d) --" % len(keys))
    print("  ", ", ".join(sorted(keys)))

    n_cond = 0
    for r in eacts:
        found = []
        walk(r.get("Program"), lambda x: found.append(x), lambda _x: None)
        if "node.conditional" in found:
            n_cond += 1
    print("\n-- programs containing node.conditional at any depth --")
    print("  ", n_cond, "/", len(eacts))

    # enemy id reuse
    print("\n-- enemy ids: reused across encounters? --")
    id_enc = collections.defaultdict(list)
    per_enc_counts = collections.Counter()
    total = 0
    for i, e in enumerate(encts):
        enc_id = unwrap(e.get("Id"))
        for el in e.get("Enemies") or []:
            per_enc_counts[len(el.get("Actions") or [])] += 1
            total += 1
            id_enc[el.get("Id")].append(enc_id)
    print("  total enemy records:", total)
    print("  actions-per-enemy histogram:", dict(sorted(per_enc_counts.items())))
    print("  total action slots:", sum(k2 * v for k2, v in per_enc_counts.items()))
    dup = {k2: v for k2, v in id_enc.items() if len(v) > 1}
    print("  distinct enemy ids:", len(id_enc), " ids used by >1 encounter:", len(dup))
    for k2, v in list(dup.items())[:5]:
        print("    %-30s %s" % (k2, v[:4]))

    print("\n-- encounter-level extras --")
    print("  CardsDrawnPerTurn:",
          dict(collections.Counter(repr(e.get("CardsDrawnPerTurn")) for e in encts)))
    keys2 = collections.Counter()
    for e in encts:
        for k2 in e:
            keys2[k2] += 1
    print("  ENCT decoded keys:", dict(keys2))

    print("\n-- roots --")
    for k2 in sorted(rom.roots):
        v = rom.term(rom.roots[k2])
        print("  %-28s root-kind=%s" % (k2, (v.get("kind") if isinstance(v, dict)
                                            else type(v).__name__)))

    print("\n-- EACT Intent decoded shape --")
    shapes = collections.Counter()
    for r in eacts:
        it = r.get("Intent")
        shapes[json.dumps(sorted(it.keys()) if isinstance(it, dict) else it)] += 1
    for k2, n in shapes.most_common(5):
        print("  keys=%s  x%d" % (k2, n))
    print("-- EACT NameKey/DescriptionKey present --")
    print("  NameKey:", sum(1 for r in eacts if "NameKey" in r),
          " DescriptionKey:", sum(1 for r in eacts if "DescriptionKey" in r))


def part2():
    core = os.path.join(TOOLS, "out", "content.core.rdcf")
    full = os.path.join(TOOLS, "out", "content.rdcf")
    analyse(core, "CORE image (flags=1, presentation stripped)")
    if os.path.exists(full):
        analyse(full, "FULL image")


def part3():
    """Dump every IntentRule in the image, plus the cycling order of the 3 enemies that carry them."""
    rom = R.Rom(open(os.path.join(TOOLS, "out", "content.core.rdcf"), "rb").read())
    encts = rom._rows("ENCT")
    print("== every IntentRule in the core image ==")
    for i, e in enumerate(encts):
        enc = unwrap(e.get("Id"))
        for el in e.get("Enemies") or []:
            rules = el.get("IntentRules") or []
            if not rules:
                continue
            print("\n  encounter %-18s enemy %-24s maxHP=%s"
                  % (enc, el.get("Id"), el.get("MaxHealth")))
            print("    cycle:", [unwrap(a) for a in (el.get("Actions") or [])])
            for r in rules:
                print("    rule Priority=%-3s Action=%-34s Condition=%s"
                      % (r.get("Priority"), unwrap(r.get("Action")),
                         json.dumps(r.get("Condition"), ensure_ascii=False,
                                    sort_keys=True)))


def part4():
    """Where does node.setCombatantCounter live, and for which counter?"""
    rom = R.Rom(open(os.path.join(TOOLS, "out", "content.core.rdcf"), "rb").read())

    def scan(label, node, ctr):
        found = []

        def on_kind(k):
            found.append(k)

        def on_key(_k):
            pass

        def walk2(n, d=0):
            if d > 200:
                return
            if isinstance(n, dict):
                if n.get("kind") == "node.setCombatantCounter":
                    val = n.get("value") or {}
                    found.append("SET:%s" % json.dumps(val.get("CounterId"),
                                                        ensure_ascii=False))
                for v in n.values():
                    walk2(v, d + 1)
            elif isinstance(n, list):
                for v in n:
                    walk2(v, d + 1)

        walk2(node)
        for f in found:
            if isinstance(f, str) and f.startswith("SET:"):
                ctr[(label, f)] += 1

    ctr = collections.Counter()
    for i, r in enumerate(rom._rows("EACT")):
        scan("EACT.Program", r.get("Program"), ctr)
    for i, r in enumerate(rom._rows("CARD")):
        scan("CARD.Program", r.get("Program"), ctr)
        scan("CARD.LifecyclePrograms", r.get("LifecyclePrograms"), ctr)
    for i, r in enumerate(rom._rows("STATUS")):
        for k in ("Triggers", "PassiveModifiers", "CombatRules", "Prevention",
                  "Amplification", "Disclosure", "DeathPrevention", "DebuffBlock",
                  "IncomingStatusDelay", "extra"):
            scan("STATUS[%d].%s(%s)" % (i, k, r.get("Id")), r.get(k), ctr)
    for i, r in enumerate(rom._rows("ENCT")):
        enc = unwrap(r.get("Id"))
        scan("ENCT.%s.TriggeredEffects" % enc, r.get("TriggeredEffects"), ctr)
    for i, r in enumerate(rom._rows("REL")):
        scan("REL.%s" % r.get("Id"), r.get("RunPrograms"), ctr)
    for k in rom.roots:
        scan("ROOT.%s" % k, rom.term(rom.roots[k]), ctr)

    print("== node.setCombatantCounter sites ==")
    for (where, cnt), n in sorted(ctr.items()):
        print("  %-46s %-40s x%d" % (where, cnt, n))

    print("\n== 'queue_position' / 'signposted_route' / 'stolen_minute' anywhere? ==")
    for needle in ("queue_position", "signposted_route", "stolen_minute"):
        hits = []
        for i, r in enumerate(rom._rows("STATUS")):
            body = json.dumps(r, ensure_ascii=False)
            if needle in body:
                hits.append("STATUS[%d] %s" % (i, r.get("Id")))
        for i, r in enumerate(rom._rows("CARD")):
            body = json.dumps(r, ensure_ascii=False)
            if needle in body:
                hits.append("CARD[%d] %s" % (i, r.get("Id")))
        print("  %-20s -> %s" % (needle, hits[:6] or "NOT FOUND in STATUS/CARD rows"))


def part5():
    """Which enemy-action programs bump a counter, and how they are nested."""
    rom = R.Rom(open(os.path.join(TOOLS, "out", "content.core.rdcf"), "rb").read())

    def finds(n, out, d=0):
        if d > 200:
            return
        if isinstance(n, dict):
            if n.get("kind") == "node.setCombatantCounter":
                out.append(n)
            for v in n.values():
                finds(v, out, d + 1)
        elif isinstance(n, list):
            for v in n:
                finds(v, out, d + 1)

    print("== enemy-action programs containing node.setCombatantCounter ==")
    for i, r in enumerate(rom._rows("EACT")):
        out = []
        finds(r.get("Program"), out)
        for s in out:
            print("  EACT[%d] %-48s %s" % (i, r.get("Id"),
                                           json.dumps(s, ensure_ascii=False, sort_keys=True)))

    print("\n== which encounters name those actions ==")
    names = set()
    for i, r in enumerate(rom._rows("EACT")):
        out = []
        finds(r.get("Program"), out)
        if out:
            names.add(r.get("Id"))
    for e in rom._rows("ENCT"):
        enc = unwrap(e.get("Id"))
        for el in e.get("Enemies") or []:
            hits = [unwrap(a) for a in (el.get("Actions") or []) if unwrap(a) in names]
            if hits:
                print("  %-24s %-26s cycle=%s" % (enc, el.get("Id"), hits))


def part6():
    """Identifier lengths -- how big must an EnemyActionId / CombatantId be?"""
    rom = R.Rom(open(os.path.join(TOOLS, "out", "content.core.rdcf"), "rb").read())
    ids = [r.get("Id") for r in rom._rows("EACT")]
    ids = [i for i in ids if isinstance(i, str)]
    ids.sort(key=len)
    print("EACT ids: %d  longest=%d  %s" % (len(ids), len(ids[-1]), ids[-1]))
    print("  top 5:", [(len(x), x) for x in ids[-5:]])
    print("  > 40 bytes:", [x for x in ids if len(x) > 40])
    print("  > 40 count:", sum(1 for x in ids if len(x) > 40))

    enc_ids = [unwrap(e.get("Id")) for e in rom._rows("ENCT")]
    enc_ids.sort(key=len)
    print("ENCT ids: %d  longest=%d  %s" % (len(enc_ids), len(enc_ids[-1]), enc_ids[-1]))
    print("  > 40 count:", sum(1 for x in enc_ids if len(x) > 40))

    enemy_ids = set()
    for e in rom._rows("ENCT"):
        for el in e.get("Enemies") or []:
            enemy_ids.add(el.get("Id"))
    enemy_ids = sorted(x for x in enemy_ids if isinstance(x, str))
    enemy_ids.sort(key=len)
    print("enemy record ids: %d  longest=%d  %s"
          % (len(enemy_ids), len(enemy_ids[-1]), enemy_ids[-1]))
    print("  > 40 count:", sum(1 for x in enemy_ids if len(x) > 40))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "part2":
        part2()
    elif len(sys.argv) > 1 and sys.argv[1] == "part3":
        part3()
    elif len(sys.argv) > 1 and sys.argv[1] == "part4":
        part4()
    elif len(sys.argv) > 1 and sys.argv[1] == "part5":
        part5()
    elif len(sys.argv) > 1 and sys.argv[1] == "part6":
        part6()
    else:
        main()
