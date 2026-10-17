#!/usr/bin/env python3
"""native/_recon_card.py -- THROWAWAY reconnaissance for card selectors / card zones.

Not part of the build.  It only reads the compiled content image
(`tools/contentc/out/content.core.rdcf`) through the reference reader and
prints facts; it never writes anything and never touches the kernel.

    python native/_recon_card.py terms                 # who uses op forEachCardInZone / moveCardToZone
    python native/_recon_card.py fields                # union field table + raw slots per term
    python native/_recon_card.py selectors             # sel.* / card.* term census
    python native/_recon_card.py census                # kind census over the 62 card programs
    python native/_recon_card.py tree <card-id>        # full program tree of one card
    python native/_recon_card.py cards                 # per-card kind sets + verdict

Everything is recomputed from the image; no cached JSON dump is trusted.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "tools", "contentc"))

import rdcfmt as F            # noqa: E402
from reader import Rom        # noqa: E402

IMG = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "..", "tools", "contentc", "out", "content.core.rdcf")

ABSENT = (F.ABSENT16, F.NULL16)


# --------------------------------------------------------------- raw access
class Model(object):
    def __init__(self):
        self.rom = Rom(open(os.path.abspath(IMG), "rb").read())
        self.str = self.rom.string_at
        self.opnames = [d["name"] for d in self.rom.opcodes]
        self.cards = self._raw_cards()

    # ----- card rows, raw (so ABSENT / NULL stay distinguishable)
    def _raw_cards(self):
        blob = self.rom.sections[F.S_CARD]
        stride = F.row_stride("CARD")
        schema = F.ROW_SCHEMAS["CARD"]
        out = []
        for off in range(0, len(blob), stride):
            rec = {}
            for (name, fk, fl), sl in zip(schema,
                                          self.rom._row_slots(blob, off, schema)):
                rec[name] = (fk, fl, sl)
            rec["_index"] = len(out)
            out.append(rec)
        return out

    def card(self, cid):
        for c in self.cards:
            if self.str(c["Id"][2][0]) == cid:
                return c
        return None

    # ----- terms
    def op(self, tid):
        return self.rom.term_slots(tid)[0]

    def kind(self, tid):
        op = self.op(tid)
        d = self.rom.opcodes[op]
        if d["opclass"] == F.OPCLASS_IR:
            return d["name"]
        if op == F.OP_STR:
            return "_str"
        if op == F.OP_INT:
            return "_int"
        if op == F.OP_BOOL:
            return "_bool"
        if op == F.OP_NULL:
            return "_null"
        if op == F.OP_ARR:
            return "_arr"
        if op == F.OP_JSON:
            return "_json"
        return d["name"] or ("op%d" % op)

    def fields(self, tid):
        """[(name, field_kind, flags, raw_slots)] in declared order."""
        op, slots = self.rom.term_slots(tid)
        out, i = [], 0
        for name, fk, fl in self.rom.opcodes[op]["fields"]:
            w = F.FIELD_SLOTS[fk]
            out.append((name, fk, fl, list(slots[i:i + w])))
            i += w
        return out

    def slot_state(self, fk, sl):
        """'ABSENT' | 'NULL' | 'VALUE' -- which sentinel the raw slot holds."""
        if fk in (F.F_TERMLIST, F.F_STRLIST):
            return {F.LIST_ABSENT: "ABSENT", F.LIST_NULL: "NULL"}.get(sl[1], "VALUE")
        if fk == F.F_INT:
            return {F.ABSENT_INT: "ABSENT", F.NULL_INT: "NULL"}.get(sl[0], "VALUE")
        if fk == F.F_BOOL:
            return {F.BOOL_ABSENT: "ABSENT", F.BOOL_NULL: "NULL"}.get(sl[0], "VALUE")
        return {F.ABSENT16: "ABSENT", F.NULL16: "NULL"}.get(sl[0], "VALUE")

    def child_ids(self, tid):
        """Every term id this term points at, in declared field order."""
        op, _ = self.rom.term_slots(tid)
        if op in (0, 1, 2, 3, 5, 6, 7):
            return []
        ids = []
        for name, fk, fl, sl in self.fields(tid):
            if fk == F.F_TERM:
                if sl[0] not in ABSENT:
                    ids.append(sl[0])
            elif fk == F.F_TERMLIST:
                start, cnt = sl
                if cnt not in (F.LIST_ABSENT, F.LIST_NULL):
                    for j in range(cnt):
                        ids.append(self.rom.aux[start + j])
        if op == F.OP_ARR:
            pass
        return ids

    def scalar_text(self, fk, fl, sl):
        st = self.slot_state(fk, sl)
        if st != "VALUE":
            return st
        if fk in (F.F_STR, F.F_JSON):
            s = self.str(sl[0])
        elif fk == F.F_INT:
            v = sl[0]
            s = str(v - 65536 if v >= 32768 else v)
        elif fk == F.F_BOOL:
            s = {F.BOOL_FALSE: "false", F.BOOL_TRUE: "true"}.get(sl[0], str(sl[0]))
        elif fk == F.F_STRLIST:
            start, cnt = sl
            s = "[" + ", ".join(repr(self.str(self.rom.aux[start + j]))
                                for j in range(cnt)) + "]"
        else:
            s = str(sl)
        return s


# ------------------------------------------------------------------ helpers
KNOWN15 = {
    "node.applyStatus", "node.conditional", "node.createCardInstance",
    "node.dealDamage", "node.drawCards", "node.forEachCardInZone",
    "node.forEachTarget", "node.gainBlock", "node.gainResource", "node.heal",
    "node.loseResource", "node.moveCardToZone", "node.modifyStatusStacks",
    "node.sequence", "node.setCombatantCounter",
}


def card_program_root(m, cid_row):
    """term id of <card>.Program.Root, or None."""
    fk, fl, sl = cid_row["Program"]
    if sl[0] in ABSENT:
        return None, None
    env = sl[0]
    for name, f2, f3, sl2 in m.fields(env):
        if name == "Root":
            return env, (None if sl2[0] in ABSENT else sl2[0])
    return env, None


def reachable(m, root):
    """(set of term ids reachable incl. root, edge multiplicity dict)."""
    seen, mult, stack = set(), {root: 1}, [root]   # the root itself counts as one occurrence
    while stack:
        t = stack.pop()
        if t in seen:
            continue
        seen.add(t)
        for c in m.child_ids(t):
            mult[c] = mult.get(c, 0) + 1
            if c not in seen:
                stack.append(c)
    return seen, mult


def all_cards_with_roots(m):
    rows = []
    for c in m.cards:
        cid = m.str(c["Id"][2][0])
        env, root = card_program_root(m, c)
        rows.append((c["_index"], cid, env, root))
    return rows


# ----------------------------------------------------------------- sections
def cmd_terms(m):
    tgt = {"node.forEachCardInZone": 59, "node.moveCardToZone": 66}
    ops = {v: k for k, v in tgt.items()}
    hits = {}
    for tid in range(m.rom.n_terms):
        op = m.op(tid)
        if op in ops:
            hits.setdefault(op, []).append(tid)
    rows = all_cards_with_roots(m)
    reach = {}
    for idx, cid, env, root in rows:
        if root is not None:
            reach[idx] = reachable(m, root)[0]
    print("term total            : %d" % m.rom.n_terms)
    for op in sorted(hits):
        print("%-24s op=%-3d terms=%d  ids=%s"
              % (ops[op], op, len(hits[op]), hits[op]))
    print()
    for op in sorted(hits):
        for tid in hits[op]:
            owners = [cid for idx, cid, env, root in rows
                      if root is not None and tid in reach.get(idx, ())]
            print("%-24s term %-4d reachable from %d card program(s): %s"
                  % (ops[op], tid, len(owners), ", ".join(owners) or "-"))
    # also: any other place in the image?
    parents = {}
    for tid in range(m.rom.n_terms):
        for c in m.child_ids(tid):
            parents.setdefault(c, set()).add(tid)
    print()
    for op in sorted(hits):
        for tid in hits[op]:
            ps = sorted(parents.get(tid, ()))
            print("term %-4d (%s) direct parents: %s"
                  % (tid, ops[op],
                     ", ".join("t%d(%s)" % (p, m.kind(p)) for p in ps) or "ROOT"))


def cmd_fields(m):
    for op in (59, 66):
        name = m.opnames[op]
        d = m.rom.opcodes[op]
        print("=" * 78)
        print("op %d  %s  opclass=%d nfields=%d nslots=%d"
              % (op, name, d["opclass"], d["nfields"], d["nslots"]))
        for i, (fn, fk, fl) in enumerate(d["fields"]):
            print("  [%d] %-20s %-9s flags=%d (%s)"
                  % (i, fn, F.FIELD_NAMES[fk], fl,
                     {0: "bare", 1: "{value:}", 2: "{Value:}"}[fl]))
        ids = [t for t in range(m.rom.n_terms) if m.op(t) == op]
        print("  distinct terms: %d -> %s" % (len(ids), ids))
        for tid in ids:
            print("  --- term %d  raw slots %s" % (tid, m.rom.term_slots(tid)[1]))
            for fn, fk, fl, sl in m.fields(tid):
                st = m.slot_state(fk, sl)
                if fk in (F.F_TERM, F.F_TERMLIST):
                    if st == "ABSENT":
                        val = "(ABSENT 0xFFFF)"
                    elif st == "NULL":
                        val = "(NULL 0xFFFE)"
                    elif fk == F.F_TERM:
                        val = "t%d %s" % (sl[0], m.kind(sl[0]))
                    else:
                        start, cnt = sl
                        val = "[%s]" % ", ".join(
                            "t%d %s" % (self_id, m.kind(self_id))
                            for self_id in
                            [m.rom.aux[start + j] for j in range(cnt)])
                else:
                    val = m.scalar_text(fk, fl, sl)
                print("      %-20s %-8s raw=%-10s %s"
                      % (fn, F.FIELD_NAMES[fk], sl, val))
            print("      reader.py JSON: %r" % (m.rom.term(tid),))


def cmd_selectors(m):
    print("-- every IR opcode whose name starts with sel./card./cardInstance.")
    for op, d in enumerate(m.rom.opcodes):
        if d["opclass"] != F.OPCLASS_IR:
            continue
        if not d["name"].startswith(("sel.", "card.", "cardInstance.")):
            continue
        ids = [t for t in range(m.rom.n_terms) if m.op(t) == op]
        print("%-22s op=%-3d terms=%-3d fields=%s"
              % (d["name"], op, len(ids),
                 " ".join("%s:%s" % (n, F.FIELD_NAMES[k]) for n, k, _ in d["fields"])
                 or "(none)"))

    print()
    print("-- registered-in-C# card-selector vocabulary vs the image")
    for n in ["sel.deckCards", "sel.instance", "sel.lastAddedCard", "sel.matching",
              "sel.take", "sel.random", "sel.choose"]:
        ids = [t for t in range(m.rom.n_terms) if m.kind(t) == n]
        print("  %-20s terms=%d %s" % (n, len(ids), ids if ids else ""))

    print()
    print("-- per-term detail of the four")
    for n in ["sel.deckCards", "sel.matching", "sel.random", "sel.choose"]:
        for tid in range(m.rom.n_terms):
            if m.kind(tid) != n:
                continue
            print("  term %d = %s" % (tid, n))
            for fn, fk, fl, sl in m.fields(tid):
                st = m.slot_state(fk, sl)
                if fk == F.F_TERM:
                    val = ("(ABSENT)" if st == "ABSENT" else
                           "(NULL)" if st == "NULL" else
                           "t%d %s" % (sl[0], m.kind(sl[0])))
                else:
                    val = m.scalar_text(fk, fl, sl)
                print("      %-18s %-8s raw=%-8s %s" % (fn, F.FIELD_NAMES[fk], sl, val))
            print("      reader.py JSON: %r" % (m.rom.term(tid),))

    print()
    print("-- who references the four (direct parents, whole image)")
    parents = {}
    for tid in range(m.rom.n_terms):
        for c in m.child_ids(tid):
            parents.setdefault(c, set()).add(tid)
    rows = all_cards_with_roots(m)
    reach = {idx: reachable(m, root)[0]
             for idx, cid, env, root in rows if root is not None}
    for n in ["sel.deckCards", "sel.matching", "sel.random", "sel.choose"]:
        for tid in range(m.rom.n_terms):
            if m.kind(tid) != n:
                continue
            own = [cid for idx, cid, env, root in rows
                   if root is not None and tid in reach.get(idx, ())]
            ps = sorted(parents.get(tid, ()))
            print("  %-18s t%-4d parents=%s | in card programs: %s"
                  % (n, tid,
                     ",".join("t%d(%s)" % (p, m.kind(p)) for p in ps) or "-",
                     ", ".join(own) or "-"))


def cmd_census(m):
    rows = all_cards_with_roots(m)
    union, per_card = set(), []
    card_use = {}            # kind -> set of card ids
    for idx, cid, env, root in rows:
        if root is None:
            per_card.append((cid, None, {}))
            continue
        seen, _ = reachable(m, root)
        union |= seen
        kinds = {m.kind(t) for t in seen}
        for kk in kinds:
            card_use.setdefault(kk, set()).add(cid)
        per_card.append((cid, root, {k: 1 for k in kinds}))

    # edges inside the union (each parent->child sighting counted once), by kind
    edges = {}
    for p in union:
        for c in m.child_ids(p):
            if c in union:
                kk = m.kind(c)
                edges[kk] = edges.get(kk, 0) + 1
    ids = {}
    for t in union:
        ids[m.kind(t)] = ids.get(m.kind(t), 0) + 1

    print("card programs with a Root: %d / %d"
          % (sum(1 for _, r, _ in per_card if r is not None), len(per_card)))
    print()
    print("kind census over the UNION of all 62 card-program trees")
    print("%-26s %-10s %-9s %-8s %s"
          % ("kind", "in-15-node", "terms", "edges", "used-by-#cards"))
    for kk in sorted(ids, key=lambda x: (-ids[x], x)):
        print("%-26s %-10s %-9d %-8d %d"
              % (kk, "YES" if kk in KNOWN15 else "-", ids[kk],
                 edges.get(kk, 0), len(card_use[kk])))
    extra = sorted(k for k in ids if k not in KNOWN15)
    print()
    print("kinds outside the 15 node.* kinds: %d distinct -> %s" % (len(extra), extra))
    missing15 = sorted(KNOWN15 - set(ids))
    print("of the 15 node.* kinds, NOT present in any card program: %d -> %s"
          % (len(missing15), missing15))
    print()
    print("per-card kind set size (sorted by card id)")
    for cid, root, k in sorted(per_card, key=lambda x: x[0]):
        print("  %-30s root=t%-5s kinds=%d" % (cid, root, len(k)))


def print_tree(m, tid, prefix="", label="", depth=0, seen_depth=None):
    kind = m.kind(tid)
    print("%s%s t%d %s" % (prefix, label, tid, kind))
    ch = m.child_ids(tid)
    fields = m.fields(tid)
    # inline scalars
    for fn, fk, fl, sl in fields:
        if fk in (F.F_TERM, F.F_TERMLIST):
            continue
        st = m.slot_state(fk, sl)
        print("%s    .%s = %s%s" % (prefix, fn,
                                    m.scalar_text(fk, fl, sl),
                                    "  [%s]" % st if st != "VALUE" else ""))
    for fn, fk, fl, sl in fields:
        if fk == F.F_TERM:
            if sl[0] in ABSENT:
                print("%s    .%s = %s" % (prefix, fn,
                                          "ABSENT" if sl[0] == F.ABSENT16 else "NULL"))
            else:
                print_tree(m, sl[0], prefix + "    ", ".%s ->" % fn, depth + 1)
        elif fk == F.F_TERMLIST:
            if sl[1] in (F.LIST_ABSENT, F.LIST_NULL):
                print("%s    .%s = %s" % (prefix, fn,
                                          "ABSENT" if sl[1] == F.LIST_ABSENT else "NULL"))
            else:
                start, cnt = sl
                for j in range(cnt):
                    print_tree(m, m.rom.aux[start + j], prefix + "    ",
                               ".%s[%d] ->" % (fn, j), depth + 1)


def cmd_tree(m, cid):
    row = m.card(cid)
    if row is None:
        print("NOT FOUND: %s" % cid)
        return
    print("CARD[%d] %s" % (row["_index"], cid))
    for fn in sorted(row):
        if fn.startswith("_"):
            continue
        fk, fl, sl = row[fn]
        st = m.slot_state(fk, sl)
        if fk == F.F_TERM:
            val = ("(ABSENT)" if st == "ABSENT" else
                   "(NULL)" if st == "NULL" else
                   "t%d %s" % (sl[0], m.kind(sl[0])))
        else:
            val = m.scalar_text(fk, fl, sl)
        print("  %-28s %-8s raw=%-8s %s" % (fn, F.FIELD_NAMES[fk], sl, val))
    env, root = card_program_root(m, row)
    print()
    print("Program envelope t%s  Root=t%s" % (env, root))
    if root is not None:
        print_tree(m, root, "", "root")
    print()
    print("-- every other program-bearing field of this row (not the Program.Root tree)")
    for fn in sorted(row):
        if fn.startswith("_") or fn in ("Id", "PackageId", "NameKey",
                                         "DescriptionKey", "IsAction",
                                         "RetainInHandOnTurnEnd",
                                         "TurnEndHandDestinationZone",
                                         "PlayedCardDestinationZone", "extra"):
            continue
        fk, fl, sl = row[fn]
        if fk == F.F_TERM and sl[0] not in ABSENT:
            seen, _ = reachable(m, sl[0])
            print("  %-26s t%-5d kinds=%s"
                  % (fn, sl[0], sorted({m.kind(t) for t in seen})))
            for t in sorted(seen):
                if m.kind(t) in ("_arr", "_obj", "_wrap_lower", "_wrap_upper"):
                    continue
                print("      t%-5d %-26s %r" % (t, m.kind(t), m.rom.term(t)))


def cmd_cards(m):
    rows = all_cards_with_roots(m)
    unhandled_nodes = {"node.forEachCardInZone", "node.moveCardToZone"}
    for idx, cid, env, root in sorted(rows, key=lambda x: x[1]):
        if root is None:
            print("%-30s NO PROGRAM" % cid)
            continue
        seen, _ = reachable(m, root)
        kinds = {m.kind(t) for t in seen}
        bad = sorted(kinds & unhandled_nodes)
        extra = sorted(kinds - KNOWN15)
        print("%-30s root=t%-5s kinds=%-3d unhandled-node=%-38s outside-15=%s"
              % (cid, root, len(kinds), bad if bad else "-", extra))


def _table_rows(m):
    """[(table, row_index, id_string, [(field_name, root_term_id)])] for every entity row."""
    out = []
    for sname in ("CARD", "STATUS", "EACT", "ENCT", "REL"):
        blob = m.rom.sections[{"CARD": F.S_CARD, "STATUS": F.S_STAT,
                               "EACT": F.S_EACT, "ENCT": F.S_ENCT,
                               "REL": F.S_REL}[sname]]
        stride = F.row_stride(sname)
        schema = F.ROW_SCHEMAS[sname]
        for off in range(0, len(blob), stride):
            rec = {}
            for (name, fk, fl), sl in zip(schema,
                                          m.rom._row_slots(blob, off, schema)):
                roots = []
                if fk == F.F_TERM and sl[0] not in ABSENT:
                    roots.append(sl[0])
                elif fk == F.F_TERMLIST and sl[1] not in (F.LIST_ABSENT, F.LIST_NULL):
                    roots.extend(m.rom.aux[sl[0] + j] for j in range(sl[1]))
                for r in roots:
                    rec.setdefault(name, []).append(r)
            idx = off // stride
            rid = m.str(m.cards[idx]["Id"][2][0]) if sname == "CARD" else "#%d" % idx
            out.append((sname, idx, rid, rec))
    return out


def cmd_who(m, targets):
    rows = _table_rows(m)
    cache = {}

    def reach(r):
        if r not in cache:
            cache[r] = reachable(m, r)[0]
        return cache[r]

    for tid in targets:
        kind = m.kind(tid)
        print("=" * 70)
        print("term %d %s" % (tid, kind))
        hit = False
        for sname, idx, rid, rec in rows:
            for fname, roots in rec.items():
                if any(tid in reach(r) for r in roots):
                    print("  %-7s [%3d] %-30s field %s" % (sname, idx, rid, fname))
                    hit = True
        for key, r in sorted(m.rom.roots.items()):
            if tid in reach(r):
                print("  ROOT    %-30s" % key)
                hit = True
        if not hit:
            print("  (no entity row and no ROOT reaches it)")


def cmd_zones(m):
    print("-- every distinct (field name, string value) for string fields that look")
    print("   like a card-zone / placement across all IR terms")
    seen = {}
    for tid in range(m.rom.n_terms):
        op = m.op(tid)
        if op < F.OP_FIRST_DYNAMIC:
            continue
        for fn, fk, fl, sl in m.fields(tid):
            if fk != F.F_STR or sl[0] in ABSENT:
                continue
            if not any(w in fn for w in ("Zone", "Placement", "From", "To")):
                continue
            seen.setdefault((fn, m.str(sl[0])), set()).add(tid)
    for (fn, val) in sorted(seen):
        print("  %-18s = %-16r terms=%s" % (fn, val, sorted(seen[(fn, val)])))
    print()
    print("-- the CARD row zone strings")
    z = {}
    for c in m.cards:
        for f in ("TurnEndHandDestinationZone", "PlayedCardDestinationZone"):
            fk, fl, sl = c[f]
            if sl[0] not in ABSENT:
                z.setdefault((f, m.str(sl[0])), 0)
                z[(f, m.str(sl[0]))] += 1
    for k in sorted(z):
        print("  %-28s = %-16r cards=%d" % (k[0], k[1], z[k]))


def main():
    m = Model()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "terms"
    if cmd == "terms":
        cmd_terms(m)
    elif cmd == "fields":
        cmd_fields(m)
    elif cmd == "selectors":
        cmd_selectors(m)
    elif cmd == "census":
        cmd_census(m)
    elif cmd == "tree":
        for cid in sys.argv[2:]:
            cmd_tree(m, cid)
            print()
    elif cmd == "cards":
        cmd_cards(m)
    elif cmd == "who":
        cmd_who(m, [int(x) for x in sys.argv[2:]])
    elif cmd == "zones":
        cmd_zones(m)
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
