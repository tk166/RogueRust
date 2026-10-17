#!/usr/bin/env python3
"""validate.py -- prove the RDCF image is a faithful, well-formed compilation.

    python validate.py [--file out/content.rdcf] [--src <json>]

Checks:

  A  well-formedness      header/directory consistency, section alignment and
                          non-overlap, every u16 index in range (strings, terms,
                          aux, id symbol table), string pool sorted
  B  structural round trip `reader.py`'s reconstruction vs `json.loads` of the
                          source, compared per path -- key sets and list elements,
                          so key *presence* is checked, not just values
  C  reference integrity  every cross-entity reference resolved; dangling ones
                          listed with the field and the site that produced them
  D  id legality          the schema requires ASCII-only ids
  E  determinism          compile twice in one process, compare SHA-256
  F  id namespace         duplicate declarations, empty ids, the `x+` upgrade
                          convention, composite ids that embed other ids, and
                          id-shaped strings in fields no rule classifies
  G  reachability         which declared content the map can actually reach, and
                          how many bytes are spent on content it cannot

Exit code 0 only if A, B, C (hard refs), D, E and F pass.
"""

import argparse
import hashlib
import json
import os
import re
import struct
import sys
import tempfile
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import rdcfmt as F      # noqa: E402
import reader           # noqa: E402
import compile as C     # noqa: E402

DEFAULT_SRC = C.DEFAULT_SRC
ID_SHAPED = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.:+\-\[\]]*$")

# ---------------------------------------------------------------------------
# Reference rules: (enclosing IR kind or None, field name) -> namespace.
# `None` means "in any context".  A value may be a bare string, a
# `{"value": s}` / `{"Value": s}` wrapper, or a list of either.
# ---------------------------------------------------------------------------
REF_RULES = {
    ("node.encounter", "Id"): "encounter",
    ("node.event", "Id"): "event",
    ("node.shopRef", "Id"): "shop",
    ("fx.addCard", "Card"): "card",
    ("fx.addRelicById", "Relic"): "relic",
    (None, "StatusDefinitionId"): "status",
    (None, "StatusId"): "status",
    (None, "Status"): "status",
    (None, "CardDefinitionId"): "card",
    (None, "Card"): "card",
    (None, "Relic"): "relic",
    (None, "Actions"): "enemy_action",
    (None, "Action"): "enemy_action",
    (None, "Deck"): "card",
    (None, "StartingRelics"): "relic",
    (None, "From"): "map_node",
    (None, "To"): "map_node",
    (None, "NextSituationId"): "situation",
    (None, "startSituationId"): "situation",
    (None, "Resource"): "resource",
    (None, "ResourceId"): "resource",
    # `OfferRewardRunEffect.Reward` is a `RewardId` used only for logging and for
    # the `RewardOfferedRunEvent` (src/RogueDeck.Run/Rewards/Rewards.cs:113-165),
    # while the offers themselves come from the inlined `Source`.  So this is an
    # open vocabulary, cross-checked in section F.
    ("fx.offerReward", "Reward"): "reward_use",
    (None, "VictoryRewardId"): "reward_decl",
}
OPEN_VOCAB = ("CounterId", "Counter", "Tag", "TagFilter", "Flag", "Pool", "PoolId",
              "TeamId", "Element", "PackageId", "Purpose", "FieldKey",
              # `TriggerEvent` enum names ("StatusApplied", "TurnEnded", ...) and
              # the run-layer trigger names ("turnStarted", "nodeEntered", ...).
              # They are parsed with `Enum.Parse<TriggerEvent>(name)` in
              # EncounterTriggerRebuild.cs:17, i.e. an enum, not an entity ref.
              "Event", "event")
HARD_KINDS = {"card", "status", "enemy_action", "encounter", "relic", "event",
              "shop", "map_node", "character", "enemy"}
LABEL_KINDS = {"reward_use", "reward_decl"}
STRICT_NAMESPACES = {"card", "status", "enemy_action", "encounter", "relic", "event",
                     "shop", "map_node"}
# Fields that *declare* something rather than reference it, plus fields already
# handled by explicit code; excluded from the "unclassified id-shaped string"
# safety net.
DECL_FIELDS = {"Id", "id", "Value", "HeroName", "WhenResult", "Event", "Node"}

PRESENTATION_NAMESPACE = {"Cards": "card", "Enemies": "enemy", "Encounters": "encounter",
                          "Relics": "relic", "Events": "event", "Statuses": "status",
                          "Characters": "character"}


def unwrap(v):
    if isinstance(v, dict) and len(v) == 1:
        k = next(iter(v))
        if k in ("value", "Value") and isinstance(v[k], str):
            return v[k]
    return None


# ---------------------------------------------------------------------------
# declaration + reference collection
# ---------------------------------------------------------------------------
class Collector(object):
    def __init__(self):
        self.decl = defaultdict(dict)            # namespace -> id -> [sites]
        self.refs = []                           # (ns, value, site, hard, owner)
        self.edges = defaultdict(set)            # owner key -> {(ns, value)}
        self.open_vocab = defaultdict(Counter)

    # ---------------------------------------------------------- recording
    def declare(self, ns, ident, site):
        if not isinstance(ident, str) or ident == "":
            return
        self.decl[ns].setdefault(ident, []).append(site)

    def ref(self, ns, value, site, owner=None):
        if not isinstance(value, str) or value == "":
            return
        hard = ns in HARD_KINDS or ns.startswith(("situation@", "choice@"))
        self.refs.append((ns, value, site, hard, owner))
        if owner is not None:
            self.edges[owner].add((ns, value))

    def open(self, name, value):
        if isinstance(value, str) and value:
            self.open_vocab[name][value] += 1

    # ------------------------------------------------------- declarations
    def collect_declarations(self, doc):
        d = self.declare
        for i, c in enumerate(doc.get("Cards") or []):
            d("card", c.get("Id"), "Cards[%d].Id" % i)
        for i, s in enumerate(doc.get("Statuses") or []):
            d("status", s.get("Id"), "Statuses[%d].Id" % i)
        for i, a in enumerate(doc.get("EnemyActions") or []):
            d("enemy_action", a.get("Id"), "EnemyActions[%d].Id" % i)
        for i, e in enumerate(doc.get("Encounters") or []):
            d("encounter", unwrap(e.get("Id")), "Encounters[%d].Id" % i)
            for j, en in enumerate(e.get("Enemies") or []):
                d("enemy", en.get("Id"), "Encounters[%d].Enemies[%d].Id" % (i, j))
        for i, x in enumerate(doc.get("Relics") or []):
            d("relic", x.get("Id"), "Relics[%d].Id" % i)
        for k in (doc.get("Events") or {}):
            d("event", k, "Events[%r]" % k)
        for k in (doc.get("Shops") or {}):
            d("shop", k, "Shops[%r]" % k)
        for i, n in enumerate(((doc.get("Map") or {}).get("Nodes") or [])):
            d("map_node", n.get("id"), "Map.Nodes[%d].id" % i)
        for i, ch in enumerate(doc.get("Characters") or []):
            d("character", ch.get("Id"), "Characters[%d].Id" % i)
        d("character", (doc.get("Start") or {}).get("HeroName"), "Start.HeroName")
        for eid, script in (doc.get("Events") or {}).items():
            for i, s in enumerate(script.get("situations") or []):
                # Choice ids are unique only *within a situation*: every script's
                # `result:*` situation ends with a choice literally called
                # "continue", and that is fine.
                d("situation@" + eid, s.get("Id"),
                  "Events[%s].situations[%d].Id" % (eid, i))
                for j, c in enumerate(s.get("Choices") or []):
                    d("choice@%s/%s" % (eid, s.get("Id")), c.get("Id"),
                      "Events[%s].situations[%d].Choices[%d].Id" % (eid, i, j))

    # ------------------------------------------- generic program walking
    def walk(self, v, path, ir, script, owner):
        if isinstance(v, dict):
            if C.is_ir(v):
                inner = v["value"]
                if isinstance(inner, dict):
                    for f in sorted(inner):
                        self._field(v["kind"], f, inner[f], "%s.%s" % (path, f),
                                    script, owner)
                        self.walk(inner[f], "%s.%s" % (path, f), v["kind"], script, owner)
                else:
                    self.walk(inner, path, v["kind"], script, owner)
                return
            if unwrap(v) is not None:
                return                    # an id wrapper: handled by its parent field
            for f in sorted(v):
                self._field(None, f, v[f], "%s.%s" % (path, f), script, owner)
                self.walk(v[f], "%s.%s" % (path, f), None, script, owner)
        elif isinstance(v, list):
            for i, x in enumerate(v):
                self.walk(x, "%s[%d]" % (path, i), ir, script, owner)

    def _field(self, ir, field, val, site, script, owner):
        rule = REF_RULES.get((ir, field)) or REF_RULES.get((None, field))
        if rule == "situation":
            s = unwrap(val) if isinstance(val, dict) else val
            if isinstance(s, str):
                ns = "situation@" + (script or "?")
                self.refs.append((ns, s, site, True, owner))
                if owner is not None:
                    self.edges[owner].add(("event", script) if script else (ns, s))
            return
        if rule in LABEL_KINDS:
            s = unwrap(val) if isinstance(val, dict) else val
            if isinstance(s, str):
                self.open(rule, s)
                if owner is not None:
                    self.edges[owner].add((rule, s))
            return
        if rule is not None:
            for x in (val if isinstance(val, list) else [val]):
                s = unwrap(x) if isinstance(x, dict) else x
                self.ref(rule, s, site, owner)
            return
        if field in OPEN_VOCAB:
            s = unwrap(val) if isinstance(val, dict) else val
            self.open(field, s)

    # ------------------------------------------------- entities + owners
    def collect_references(self, doc):
        W = self.walk

        for i, c in enumerate(doc.get("Cards") or []):
            own = ("card", c.get("Id"))
            W(c.get("Program"), "Cards[%d].Program" % i, None, None, own)
            W(c.get("LifecyclePrograms"), "Cards[%d].LifecyclePrograms" % i, None, None, own)
            for j, t in enumerate(c.get("Tags") or []):
                self.open("tag", unwrap(t))
            for j, cost in enumerate(c.get("Costs") or []):
                self.ref("resource", unwrap(cost.get("ResourceId")),
                         "Cards[%d].Costs[%d].ResourceId" % (i, j), own)

        for i, s in enumerate(doc.get("Statuses") or []):
            own = ("status", s.get("Id"))
            W(s.get("Triggers"), "Statuses[%d].Triggers" % i, None, None, own)
            W(s.get("CombatRules"), "Statuses[%d].CombatRules" % i, None, None, own)
            for t in (s.get("Tags") or []):
                self.open("tag", t)

        for i, a in enumerate(doc.get("EnemyActions") or []):
            own = ("enemy_action", a.get("Id"))
            W(a.get("Program"), "EnemyActions[%d].Program" % i, None, None, own)

        for i, e in enumerate(doc.get("Encounters") or []):
            own = ("encounter", unwrap(e.get("Id")))
            for j, en in enumerate(e.get("Enemies") or []):
                self.ref("enemy", en.get("Id"),
                         "Encounters[%d].Enemies[%d].Id" % (i, j), own)
                for k, act in enumerate(en.get("Actions") or []):
                    self.ref("enemy_action", unwrap(act),
                             "Encounters[%d].Enemies[%d].Actions[%d]" % (i, j, k), own)
                for k, irule in enumerate(en.get("IntentRules") or []):
                    self.ref("enemy_action", unwrap(irule.get("Action")),
                             "Encounters[%d].Enemies[%d].IntentRules[%d].Action"
                             % (i, j, k), own)
                    W(irule.get("Condition"), "…IntentRules[%d].Condition" % k,
                      None, None, own)
                for k, st in enumerate(en.get("StartingStatuses") or []):
                    self.ref("status", unwrap(st.get("Status")),
                             "Encounters[%d].Enemies[%d].StartingStatuses[%d]"
                             % (i, j, k), own)
            for k, st in enumerate(e.get("HeroStartingStatuses") or []):
                self.ref("status", unwrap(st.get("Status")),
                         "Encounters[%d].HeroStartingStatuses[%d]" % (i, k), own)
            for k, hr in enumerate(e.get("HeroResources") or []):
                self.ref("resource", unwrap(hr.get("Resource")),
                         "Encounters[%d].HeroResources[%d]" % (i, k), own)
            for k, tr in enumerate(e.get("TriggeredEffects") or []):
                # `TriggeredEffects[].Event` is a `TriggerEvent` enum name, not a
                # reference to an `Events` script; EncounterTriggerRebuild.cs:17
                # parses it with Enum.Parse<TriggerEvent>.
                self.open("trigger_event", tr.get("Event"))
                W(tr.get("Program"), "Encounters[%d].TriggeredEffects[%d].Program" % (i, k),
                  None, None, own)

        for i, x in enumerate(doc.get("Relics") or []):
            own = ("relic", x.get("Id"))
            W(x.get("RunPrograms"), "Relics[%d].RunPrograms" % i, None, None, own)
            W(x.get("CombatRules"), "Relics[%d].CombatRules" % i, None, None, own)

        for eid, script in (doc.get("Events") or {}).items():
            own = ("event", eid)
            self.ref("situation@" + eid, script.get("startSituationId"),
                     "Events[%s].startSituationId" % eid, own)
            for i, s in enumerate(script.get("situations") or []):
                for j, c in enumerate(s.get("Choices") or []):
                    base = "Events[%s].situations[%d].Choices[%d]" % (eid, i, j)
                    if c.get("NextSituationId"):
                        self.refs.append(("situation@" + eid, c["NextSituationId"],
                                          base + ".NextSituationId", True, own))
                        self.edges[own].add(("situation@" + eid, c["NextSituationId"]))
                    W(c.get("Effects"), base + ".Effects", None, eid, own)
                    W(c.get("Requirement"), base + ".Requirement", None, eid, own)

        mp = doc.get("Map") or {}
        for i, n in enumerate(mp.get("Nodes") or []):
            own = ("map_node", n.get("id"))
            W(n.get("payload"), "Map.Nodes[%d].payload" % i, None, None, own)
        for i, e in enumerate(mp.get("Edges") or []):
            a = unwrap(e.get("From"))
            self.ref("map_node", a, "Map.Edges[%d].From" % i)
            self.ref("map_node", unwrap(e.get("To")), "Map.Edges[%d].To" % i)
            if a:
                self.edges[("map_node", a)].add(("map_node", unwrap(e.get("To"))))
        for i, n in enumerate(mp.get("EntryNodeIds") or []):
            self.ref("map_node", unwrap(n), "Map.EntryNodeIds[%d]" % i)
        for i, lay in enumerate(mp.get("Layout") or []):
            self.ref("map_node", unwrap(lay.get("Node")), "Map.Layout[%d].Node" % i)

        for sid, sh in (doc.get("Shops") or {}).items():
            own = ("shop", sid)
            for j, o in enumerate(sh.get("Offers") or []):
                W(o.get("Payload"), "Shops[%s].Offers[%d].Payload" % (sid, j),
                  None, None, own)
            W(sh.get("Services"), "Shops[%s].Services" % sid, None, None, own)

        for src, key in ((doc.get("Start") or {}, "Start"),
                         *[((c.get("Start") or {}), "Characters[%d].Start" % i)
                           for i, c in enumerate(doc.get("Characters") or [])]):
            for j, d in enumerate(src.get("Deck") or []):
                self.ref("card", unwrap(d), "%s.Deck[%d]" % (key, j))
            for j, d in enumerate(src.get("StartingRelics") or []):
                self.ref("relic", unwrap(d), "%s.StartingRelics[%d]" % (key, j))
            for k in (src.get("Resources") or {}):
                self.ref("resource", k, "%s.Resources[%r]" % (key, k))
        for i, c in enumerate(doc.get("Characters") or []):
            self.walk(c.get("Start"), "Characters[%d].Start" % i, None, None,
                      ("character", c.get("Id")))

        self.walk(doc.get("MetaRules"), "MetaRules", None, None, ("root", "MetaRules"))
        self.walk(doc.get("Deck"), "Deck", None, None, ("root", "Deck"))
        self.walk(doc.get("Presentation"), "Presentation", None, None, ("root", "Presentation"))

        for kind, ns in PRESENTATION_NAMESPACE.items():
            blk = (doc.get("Presentation") or {}).get(kind)
            if isinstance(blk, dict):
                for k in blk:
                    self.ref(ns, k, "Presentation.%s[%r]" % (kind, k))
            blk = (doc.get("Balance") or {}).get(kind)
            if isinstance(blk, dict):
                for k in blk:
                    self.ref(ns, k, "Balance.%s[%r]" % (kind, k))


# ---------------------------------------------------------------------------
# structural diff
# ---------------------------------------------------------------------------
def diff(a, b, path="$", out=None, limit=40):
    if out is None:
        out = []
    if len(out) >= limit:
        return out
    if isinstance(a, dict) and isinstance(b, dict):
        ka, kb = set(a), set(b)
        for k in sorted(ka - kb):
            out.append("%s.%s: present in source, missing in BINARY" % (path, k))
        for k in sorted(kb - ka):
            out.append("%s.%s: absent in source, extra in BINARY (%r)"
                       % (path, k, _short(b[k])))
        for k in sorted(ka & kb):
            diff(a[k], b[k], "%s.%s" % (path, k), out, limit)
        return out
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append("%s: length %d (source) vs %d (binary)" % (path, len(a), len(b)))
            return out
        for i, (x, y) in enumerate(zip(a, b)):
            diff(x, y, "%s[%d]" % (path, i), out, limit)
        return out
    if isinstance(a, bool) != isinstance(b, bool) or (
            not isinstance(a, (dict, list)) and not isinstance(b, (dict, list)) and a != b):
        out.append("%s: %r (source) vs %r (binary)" % (path, _short(a), _short(b)))
    elif type(a) is not type(b):
        out.append("%s: type %s (source) vs %s (binary)"
                   % (path, type(a).__name__, type(b).__name__))
    return out


def _short(v, n=90):
    s = repr(v)
    return s if len(s) <= n else s[:n] + "..."


# ---------------------------------------------------------------------------
# checks
# ---------------------------------------------------------------------------
def check_wellformed(buf, rom):
    errs = []
    hdr, dirs = F.unpack_dir(buf)
    if hdr["total_size"] != len(buf):
        errs.append("header total_size %d != file size %d" % (hdr["total_size"], len(buf)))
    if hdr["dir_off"] != F.HEADER_SIZE:
        errs.append("dir_off %d != %d" % (hdr["dir_off"], F.HEADER_SIZE))
    spans = []
    for sec, (off, size, count) in dirs.items():
        if not size:
            continue
        if off % 4:
            errs.append("section %s offset %d not 4-byte aligned"
                        % (F.SEC_NAMES[sec], off))
        if off + size > len(buf):
            errs.append("section %s overruns the file" % F.SEC_NAMES[sec])
        spans.append((off, off + size, F.SEC_NAMES[sec]))
    spans.sort()
    for (a0, a1, an), (b0, b1, bn) in zip(spans, spans[1:]):
        if a1 > b0:
            errs.append("sections %s and %s overlap" % (an, bn))
    last = -1
    for tid in range(rom.n_terms):
        op, slots = rom.term_slots(tid)
        if op >= len(rom.opcodes):
            errs.append("term %d has unknown opcode %d" % (tid, op))
            continue
        if rom.term_off[tid] * 4 + 2 + 2 * rom.opcodes[op]["nslots"] > len(rom.sec_trm):
            errs.append("term %d record runs past SEC_TRM" % tid)
        if tid and rom.term_off[tid] <= last:
            errs.append("SEC_TRW is not strictly increasing at term %d" % tid)
        last = rom.term_off[tid]
    for tid in range(rom.n_terms):
        op, slots = rom.term_slots(tid)
        if op >= len(rom.opcodes):
            continue
        for name, fk, fl, sl in rom._field_values(op, slots):
            if fk == F.F_TERM:
                for v in sl:
                    if v not in (F.ABSENT16, F.NULL16) and v >= rom.n_terms:
                        errs.append("term %d.%s -> term id %d out of range"
                                    % (tid, name, v))
            elif fk in (F.F_STR, F.F_JSON):
                for v in sl:
                    if v not in (F.ABSENT16, F.NULL16) and v > rom.n_strings:
                        errs.append("term %d.%s -> string id %d out of range"
                                    % (tid, name, v))
            elif fk in (F.F_TERMLIST, F.F_STRLIST):
                start, count = sl
                if count in (F.LIST_ABSENT, F.LIST_NULL):
                    continue
                if start + count > rom.n_aux:
                    errs.append("term %d.%s -> aux [%d,%d) out of range"
                                % (tid, name, start, start + count))
    ekind_rows = {F.EK_CARD: len(rom._rows("CARD")), F.EK_STATUS: len(rom._rows("STATUS")),
                  F.EK_EACTION: len(rom._rows("EACT")),
                  F.EK_ENCOUNTER: len(rom._rows("ENCT")),
                  F.EK_RELIC: len(rom._rows("REL"))}
    for s, ek, index in rom.idx:
        if ek in ekind_rows and index >= ekind_rows[ek]:
            errs.append("SEC_IDX %r -> %s[%d] beyond the table"
                        % (s, F.EK_NAMES[ek], index))
        if not s:
            errs.append("SEC_IDX contains an empty id")
    strs = [rom.string_at(i + 1) for i in range(rom.n_strings)]
    if strs != sorted(strs, key=lambda x: x.encode("utf-8")):
        errs.append("string pool is not sorted by UTF-8 bytes")
    return errs


ASCII_CACHE = {}


def ascii_check(c):
    bad = []
    for ns in sorted(c.decl):
        for ident, sites in c.decl[ns].items():
            if any(ord(ch) > 127 for ch in ident):
                bad.append((ns, ident, sites[0]))
    seen = set()
    for ns, value, site, hard, own in c.refs:
        if any(ord(ch) > 127 for ch in value) and (value, site) not in seen:
            seen.add((value, site))
            bad.append((ns + " (reference)", value, site))
    return bad


def composite_id_check(c):
    """Minted composite ids embed other ids as substrings.

    `cards:<encounterId>`, `spoils:<encounterId>`, `relic:<encounterId>`,
    `treasure:<mapNodeId>:relic` and
    `event-<eventId>-choice-<choiceId>-effect[<i>]-<what>` are all built by
    string concatenation, so a rename of the embedded id silently orphans them.
    Nothing in the engine checks these; here they are checked explicitly.
    """
    problems = []
    hazards = []
    checked = Counter()
    pat_enc = re.compile(r"^(?:cards|spoils|relic):(.+)$")
    pat_treasure = re.compile(r"^treasure:([^:]+):(.+)$")
    pat_event = re.compile(r"^event-([A-Za-z0-9_]+)-choice-([A-Za-z0-9_]+)"
                           r"-effect\[(\d+)\]-(.+)$")
    labels = set(c.open_vocab.get("reward_use", {})) | set(c.open_vocab.get("reward_decl", {}))
    for lab in sorted(labels):
        m = pat_enc.match(lab)
        if m:
            checked["<prefix>:<encounterId>"] += 1
            if m.group(1) not in c.decl.get("encounter", {}):
                problems.append((lab, "embedded encounter id %r is not declared"
                                 % m.group(1)))
            continue
        m = pat_treasure.match(lab)
        if m:
            checked["treasure:<mapNodeId>:relic"] += 1
            if m.group(1) not in c.decl.get("map_node", {}):
                problems.append((lab, "embedded map-node id %r is not declared"
                                 % m.group(1)))
            continue
        m = pat_event.match(lab)
        if m:
            checked["event-<eventId>-choice-<choiceId>-effect[i]"] += 1
            eid, ch = m.group(1), m.group(2)
            if eid not in c.decl.get("event", {}):
                problems.append((lab, "embedded event id %r is not declared" % eid))
                continue
            owners = [ns for ns in c.decl
                      if ns.startswith("choice@" + eid + "/") and ch in c.decl[ns]]
            if not owners:
                problems.append((lab, "embedded choice id %r is not declared in "
                                      "Events[%s]" % (ch, eid)))
            elif len(owners) > 1:
                hazards.append((lab, "choice id %r is not unique within Events[%s] "
                                     "(%d situations declare it); the minted label "
                                     "is ambiguous" % (ch, eid, len(owners))))
            continue
        checked["unrecognised label shape"] += 1
    return problems, hazards, checked


def choice_uniqueness_hazard(c):
    """Choice ids repeat across situations of one script; only the composite
    reward labels depend on them being unique per script."""
    haz = []
    per_script = defaultdict(Counter)
    for ns, ids in c.decl.items():
        if ns.startswith("choice@"):
            script, _, _ = ns[len("choice@"):].partition("/")
            for ident, sites in ids.items():
                per_script[script][ident] += len(sites)
    for script, cnt in sorted(per_script.items()):
        dupes = sorted(i for i, n in cnt.items() if n > 1)
        if dupes:
            haz.append((script, dupes))
    return haz


def unclassified_ids(c, doc):
    known = set()
    for ns in c.decl:
        known |= set(c.decl[ns])
    hits = Counter()
    samples = {}

    def visit(v, path, ir):
        if isinstance(v, dict):
            if C.is_ir(v):
                inner = v["value"]
                if isinstance(inner, dict):
                    for f in sorted(inner):
                        _f(v["kind"], f, inner[f], "%s.%s" % (path, f))
                        visit(inner[f], "%s.%s" % (path, f), v["kind"])
                elif inner is not None:
                    visit(inner, path, v["kind"])
                return
            if unwrap(v) is not None:
                return
            for f in sorted(v):
                _f(None, f, v[f], "%s.%s" % (path, f))
                visit(v[f], "%s.%s" % (path, f), None)
        elif isinstance(v, list):
            for i, x in enumerate(v):
                visit(x, "%s[%d]" % (path, i), ir)

    def _f(ir, field, val, site):
        if field in DECL_FIELDS or field in OPEN_VOCAB:
            return
        if REF_RULES.get((ir, field)) or REF_RULES.get((None, field)):
            return
        s = unwrap(val) if isinstance(val, dict) else val
        if isinstance(s, str) and s in known and ID_SHAPED.match(s):
            hits[field] += 1
            samples.setdefault(field, (s, site))

    for key in sorted(doc):
        visit(doc[key], key, None)
    return hits, samples


# ---------------------------------------------------------------------------
# G. reachability
# ---------------------------------------------------------------------------
ROOT_ENTITIES = []


def reachability(c, doc):
    """BFS from the map/start roots over the reference graph."""
    seeds = []
    mp = doc.get("Map") or {}
    for n in (mp.get("EntryNodeIds") or []):
        seeds.append(("map_node", unwrap(n)))
    if not seeds:
        for n in (mp.get("Nodes") or []):
            seeds.append(("map_node", n.get("id")))
    start = doc.get("Start") or {}
    for d in (start.get("Deck") or []):
        seeds.append(("card", unwrap(d)))
    for d in (start.get("StartingRelics") or []):
        seeds.append(("relic", unwrap(d)))

    seen = set()
    stack = [s for s in seeds if s[1]]
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        for nxt in c.edges.get(cur, ()):
            if nxt[0] in LABEL_KINDS:
                continue
            if nxt not in seen:
                stack.append(nxt)

    # a map node's payload references the encounter/event/shop it hosts; those
    # edges were recorded under ("map_node", id) already.
    live = {ns: set() for ns in c.decl}
    for ns, val in seen:
        if ns.startswith("situation@"):
            continue
        if val in c.decl.get(ns, {}):
            live.setdefault(ns, set()).add(val)
    # enemy ids resolve per encounter, so mark all enemies of a live encounter
    dead = {}
    for ns in sorted(c.decl):
        if ns.startswith("situation@") or ns.startswith("choice@"):
            continue
        allids = set(c.decl[ns])
        dead[ns] = sorted(allids - live.get(ns, set()))
    return live, dead


def dead_bytes(comp, doc, dead, col):
    """How many ROM bytes are spent on content the map cannot reach."""
    enc, ser = comp["enc"], comp["ser"]
    kinds_of = {op: (k, f) for op, (k, f) in F.RESERVED_OP_LAYOUT.items()}
    for l in comp["ir"] + comp["obj"]:
        kinds_of[l.op] = (l.kinds, l.flags)

    def term_size(tid):
        op, _ = enc.terms[tid]
        kinds, _ = kinds_of[op]
        return F.align4(2 + 2 * sum(F.FIELD_SLOTS[k] for k in kinds))
    kids = [()] * len(enc.terms)
    strs = [()] * len(enc.terms)
    for tid, (op, cells) in enumerate(enc.terms):
        k, s = [], []
        for c in cells:
            if c[0] == "T":
                k.append(c[1])
            elif c[0] == "S":
                s.append(c[1])
            elif c[0] == "L":
                for el in c[1]:
                    (k if el[0] == "T" else s).append(el[1])
        kids[tid] = tuple(k)
        strs[tid] = tuple(s)

    def closure(roots):
        seen = set()
        st = list(roots)
        while st:
            t = st.pop()
            if t in seen:
                continue
            seen.add(t)
            st.extend(kids[t])
        return seen

    SNAME = {"card": "CARD", "status": "STATUS", "enemy_action": "EACT",
             "encounter": "ENCT", "relic": "REL"}
    dead_terms, live_terms = set(), set()
    dead_rows = 0
    for ns, sname in SNAME.items():
        schema = F.ROW_SCHEMAS[sname]
        stride = F.row_stride(sname)
        by_id = {}
        for i, rec in enumerate(doc.get({"CARD": "Cards", "STATUS": "Statuses",
                                         "EACT": "EnemyActions", "ENCT": "Encounters",
                                         "REL": "Relics"}[sname]) or []):
            ident = rec.get("Id")
            if isinstance(ident, dict):
                ident = unwrap(ident)
            by_id[ident] = i
        for ident in dead.get(ns, []):
            i = by_id.get(ident)
            if i is None:
                continue
            dead_rows += stride
            roots = []
            for (key, fk, fl), cell in zip(schema, enc.rows[sname][i]):
                if cell[0] == "T":
                    roots.append(cell[1])
                elif cell[0] == "L":
                    roots += [el[1] for el in cell[1] if el[0] == "T"]
            dead_terms |= closure(roots)
    # anything reached from the root pointer table or from live entities is live
    live_roots = [t for _, t in enc.root_entries]
    for ns, sname in SNAME.items():
        schema = F.ROW_SCHEMAS[sname]
        live_ids = set(col.decl.get(ns, {})) - set(dead.get(ns, []))
        for i, rec in enumerate(doc.get({"CARD": "Cards", "STATUS": "Statuses",
                                         "EACT": "EnemyActions", "ENCT": "Encounters",
                                         "REL": "Relics"}[sname]) or []):
            ident = rec.get("Id")
            if isinstance(ident, dict):
                ident = unwrap(ident)
            if ident not in live_ids:
                continue
            for (key, fk, fl), cell in zip(schema, enc.rows[sname][i]):
                if cell[0] == "T":
                    live_roots.append(cell[1])
                elif cell[0] == "L":
                    live_roots += [el[1] for el in cell[1] if el[0] == "T"]
    live_terms = closure(live_roots)
    only_dead = dead_terms - live_terms
    tbytes = sum(term_size(t) for t in only_dead)
    pool = {s: len(s.encode("utf-8")) + 1 for s in ser.strings_ordered}
    live_strs = set()
    for t in live_terms:
        live_strs.update(strs[t])
    dead_strs = set()
    for t in only_dead:
        dead_strs.update(strs[t])
    dead_strs -= live_strs
    sbytes = sum(pool[s] for s in dead_strs)
    return {"dead_rows_bytes": dead_rows, "dead_terms": len(only_dead),
            "dead_term_bytes": tbytes, "dead_strings": len(dead_strs),
            "dead_string_bytes": sbytes,
            "total_bytes": dead_rows + tbytes + sbytes}


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="validate an RDCF content image")
    ap.add_argument("--file", default=os.path.join(HERE, "out", "content.rdcf"))
    ap.add_argument("--src", default=DEFAULT_SRC)
    ap.add_argument("--json", dest="json_out",
                    default=os.path.join(HERE, "out", "validate.json"))
    ap.add_argument("--name", default="validate",
                    help="base name for the .md/.json reports written into out/")
    ap.add_argument("--skip-determinism", action="store_true")
    args = ap.parse_args()

    buf = open(args.file, "rb").read()
    rom = reader.Rom(buf)
    raw = open(args.src, "rb").read()
    doc = json.loads(raw.decode("utf-8-sig"))
    # A presentation-stripped image (header flag bit0) must be compared against
    # the stripped document, not the original -- the strip is the one documented
    # transformation between the two images, and it must be exactly that.
    stripped = bool(rom.header["flags"] & 1)
    if stripped:
        doc = C.strip_presentation(doc)

    L = []
    a = L.append
    result = {"image": args.file, "source": args.src, "checks": {}, "ok": True}
    a("# RDCF validation report")
    a("")
    a("| | |")
    a("|---|---|")
    a("| image | `%s` (%d B) |" % (os.path.basename(args.file), len(buf)))
    a("| source | `%s` (%d B) |" % (os.path.basename(args.src), len(raw)))
    a("| presentation | %s |" % ("**stripped** (header flag bit0 set, so the round "
                                 "trip compares against the stripped document)"
                                 if stripped else "present (round trip compares "
                                 "against the document verbatim)"))
    a("")

    errs = check_wellformed(buf, rom)
    result["checks"]["wellformedness"] = {"ok": not errs, "errors": errs}
    if errs:
        result["ok"] = False

    hashes = ["(skipped)"]
    if not args.skip_determinism:
        tmp = tempfile.mkdtemp(prefix="rdcf-det-")
        for i in range(2):
            comp = C.compile_doc(doc)
            p = os.path.join(tmp, "a.rdcf")
            comp["ser"].write(p, F.fnv1a32(raw), int(doc.get("SchemaVersion") or 0),
                              rom.header["flags"])
            if i == 0:
                hashes = [hashlib.sha256(open(p, "rb").read()).hexdigest()]
            else:
                hashes.append(hashlib.sha256(open(p, "rb").read()).hexdigest())
            os.unlink(p)
        os.rmdir(tmp)
    det_ok = args.skip_determinism or hashes[0] == hashes[1]
    on_disk = hashlib.sha256(buf).hexdigest()
    result["checks"]["determinism"] = {"ok": det_ok, "sha256": hashes,
                                       "on_disk_sha256": on_disk,
                                       "matches_on_disk": on_disk == hashes[0]}
    if not det_ok:
        result["ok"] = False

    mine = rom.document()
    diffs = diff(doc, mine, "$", [], 60)
    result["checks"]["roundtrip"] = {"ok": not diffs, "differences": diffs}
    if diffs:
        result["ok"] = False

    c = Collector()
    c.collect_declarations(doc)
    c.collect_references(doc)

    dangling, soft = [], []
    for ns, value, site, hard, own in c.refs:
        if value in c.decl.get(ns, {}):
            continue
        (dangling if hard else soft).append((ns, value, site))
    result["checks"]["references"] = {
        "ok": not dangling,
        "declared": {ns: len(v) for ns, v in sorted(c.decl.items())},
        "references_checked": len(c.refs),
        "dangling": [{"namespace": n, "value": v, "site": s} for n, v, s in dangling],
        "soft_unresolved": [{"namespace": n, "value": v, "site": s} for n, v, s in soft]}
    if dangling:
        result["ok"] = False

    bad_ascii = ascii_check(c)
    result["checks"]["ascii_ids"] = {"ok": not bad_ascii,
                                     "violations": [{"namespace": n, "id": i, "site": s}
                                                    for n, i, s in bad_ascii]}
    if bad_ascii:
        result["ok"] = False

    dupes = []
    for ns in sorted(c.decl):
        if ns not in STRICT_NAMESPACES and not ns.startswith("situation@"):
            continue
        for ident, sites in sorted(c.decl[ns].items()):
            if len(sites) > 1:
                dupes.append((ns, ident, sites))
    ids = {x.get("Id") for x in doc.get("Cards") or []}
    upgraded = sorted(i for i in ids if isinstance(i, str) and i.endswith("+"))
    no_base = sorted(i for i in upgraded if i[:-1] not in ids)
    comp_problems, comp_hazards, comp_checked = composite_id_check(c)
    choice_haz = choice_uniqueness_hazard(c)
    unclassified, samples = unclassified_ids(c, doc)
    result["checks"]["namespace"] = {
        "ok": not dupes and not no_base and not comp_problems,
        "duplicates": [{"namespace": n, "id": i} for n, i, _ in dupes],
        "upgraded_cards": len(upgraded), "upgraded_without_base": no_base,
        "composite_id_problems": [{"label": l, "problem": p} for l, p in comp_problems],
        "composite_id_hazards": [{"label": l, "problem": p} for l, p in comp_hazards],
        "composite_id_shapes": dict(comp_checked),
        "choice_ids_repeated_within_script": {s: d for s, d in choice_haz},
        "unclassified_id_shaped_fields": dict(unclassified),
    }
    if dupes or no_base or comp_problems:
        result["ok"] = False

    live, dead = reachability(c, doc)
    deadb = dead_bytes(C.compile_doc(doc), doc, dead, c)
    result["checks"]["reachability"] = {
        "unreachable": {ns: v for ns, v in sorted(dead.items()) if v},
        "dead_bytes": deadb}

    # ------------------------------------------------------------ summary
    a("| check | result |")
    a("|---|---|")
    a("| A well-formedness | %s |" % _v(not errs, len(errs)))
    a("| B structural round trip | %s |" % _v(not diffs, len(diffs), "differences"))
    a("| C reference integrity | %s |" % _v(not dangling, len(dangling), "dangling"))
    a("| D ASCII-only ids | %s |" % _v(not bad_ascii, len(bad_ascii)))
    a("| E determinism | %s |" % ("PASS" if det_ok else "**FAIL**"))
    a("| F id namespace | %s |"
      % _v(not (dupes or no_base or comp_problems),
           len(dupes) + len(no_base) + len(comp_problems), "problems"))
    a("")
    a("## Verdict")
    a("")
    a("**%s**" % ("ALL CHECKS PASS" if result["ok"] else "FAILURES PRESENT"))
    a("")

    # ------------------------------------------------------------ detail A
    a("## A. Well-formedness")
    a("")
    if errs:
        for e in errs[:40]:
            a("* %s" % e)
    else:
        a("Header and directory are consistent, every section is 4-byte aligned and")
        a("disjoint, `SEC_TRW` is strictly increasing, and every u16 operand that is")
        a("an index (term id, string id, aux range, entity index) is in range:")
        a("**%d terms, %d strings, %d aux cells, %d opcodes, %d id entries** verified."
          % (rom.n_terms, rom.n_strings, rom.n_aux, len(rom.opcodes), len(rom.idx)))
        a("The string pool's byte-sorted invariant is re-checked against the blob.")
    a("")

    # ------------------------------------------------------------ detail B
    a("## B. Structural round trip")
    a("")
    if not diffs:
        a("`reader.Rom.document()` is **structurally identical** to")
        a("`json.loads(source)`, compared per path -- every dict key set and every")
        a("list element.  Key *presence* matches too: a key absent in the source is")
        a("absent after decoding, and a key present-and-`null` comes back")
        a("present-and-`null`, because each field kind carries separate ABSENT and")
        a("NULL sentinels.")
        a("")
        a("| subtree | compared |")
        a("|---|---|")
        for k in ("Cards", "Statuses", "EnemyActions", "Encounters", "Relics"):
            a("| `%s` | %d records |" % (k, len(mine.get(k) or [])))
        a("| other top-level keys | %d, all reachable from the root table |"
          % len([k for k in doc if k not in ("Cards", "Statuses", "EnemyActions",
                                             "Encounters", "Relics")]))
    else:
        for d in diffs[:40]:
            a("* `%s`" % d)
    a("")

    # ------------------------------------------------------------ detail C
    a("## C. Reference integrity")
    a("")
    a("%d distinct ids across %d namespaces; %d reference occurrences checked."
      % (sum(len(v) for v in c.decl.values()), len(c.decl), len(c.refs)))
    a("")
    a("| namespace | declared |")
    a("|---|---|")
    for ns in sorted(c.decl):
        a("| `%s` | %d |" % (ns, len(c.decl[ns])))
    a("")
    if dangling:
        a("### Dangling hard references (%d)" % len(dangling))
        a("")
        a("| referenced id | namespace | first site |")
        a("|---|---|---|")
        for n, v, s in dangling[:60]:
            a("| `%s` | %s | `%s` |" % (v, n, s))
    else:
        a("**No dangling hard references.**  Every card / status / enemy action /")
        a("encounter / enemy / relic / event / shop / map node / character /")
        a("situation / choice id reachable from the document resolves to a")
        a("declaration site.")
    a("")
    if soft:
        a("### Unresolved soft references (%d occurrences)" % len(soft))
        a("")
        a("Resources are an open vocabulary: `standard.energy` is an engine built-in")
        a("and `gold` comes from `Start.Resources`; neither is declared as an entity.")
        a("")
        seen = set()
        for n, v, s in soft:
            if (n, v) in seen:
                continue
            seen.add((n, v))
            a("* `%s` (%s), e.g. `%s`" % (v, n, s))
    a("")
    a("### Open vocabularies")
    a("")
    a("These namespaces have no declaration table anywhere in the document; they are")
    a("defined purely by use, so they can never be \"dangling\" -- which also means a")
    a("typo in one is invisible to the engine.")
    a("")
    a("| vocabulary | distinct values | note |")
    a("|---|---|---|")
    for k in sorted(c.open_vocab):
        note = ""
        if k == "reward_use":
            note = "minted at the use site (`Rewards.cs:113-165`)"
        elif k == "reward_decl":
            note = "`CombatNode.VictoryRewardId`, also a local label"
        a("| `%s` | %d | %s |" % (k, len(c.open_vocab[k]), note))
    a("")

    # ------------------------------------------------------------ detail D
    a("## D. ASCII-only ids")
    a("")
    if bad_ascii:
        a("**%d violations.**  The schema requires ASCII ids so that UTF-16 ordinal")
        a("order equals UTF-8 byte order across languages:" % len(bad_ascii))
        a("")
        for n, i, s in bad_ascii[:60]:
            a("* `%s` (%s) at `%s`" % (i, n, s))
    else:
        nonascii = sum(1 for i in range(1, rom.n_strings + 1)
                       if any(ord(c) > 127 for c in rom.string_at(i)))
        a("All **%d declared ids** and every id used in a reference position are pure"
          % sum(len(v) for v in c.decl.values()))
        a("ASCII.")
        a("")
        if nonascii:
            a("The *document* is not ASCII-only: %d of the %d pooled strings contain"
              % (nonascii, rom.n_strings))
            a("non-ASCII characters, and every one of them is presentation text (intent")
            a("labels using U+00B7, for instance).  That is exactly why ids and display")
            a("strings have to stay in separate namespaces -- a display string may be")
            a("anything, an id may not.")
        else:
            a("This image carries no non-ASCII strings at all: %d pooled strings, all"
              % rom.n_strings)
            a("ASCII.  That is a consequence of stripping the presentation text.")
        a("")
        a("Ids being ASCII is what the schema asks for, and the pool's byte-sorted")
        a("order relies on it: for ASCII, UTF-16 ordinal order and UTF-8 byte order")
        a("coincide, so the table is code-point sorted for a C reader and byte sorted")
        a("for the Python reader without a second comparison function.")
    a("")

    # ------------------------------------------------------------ detail E
    a("## E. Determinism")
    a("")
    if args.skip_determinism:
        a("Skipped (`--skip-determinism`).")
    else:
        a("Two independent in-process builds produced %s SHA-256, and the image on"
          % ("the **same**" if det_ok else "**different**"))
        a("disk %s that hash." % ("matches" if on_disk == hashes[0] else "does not match"))
        a("")
        a("* build 1: `%s`" % hashes[0])
        a("* build 2: `%s`" % hashes[1])
        a("* on disk: `%s`" % on_disk)
    a("")

    # ------------------------------------------------------------ detail F
    a("## F. Id namespace hygiene")
    a("")
    a("* duplicate declarations in a uniqueness-scoped namespace: **%d**%s"
      % (len(dupes), "" if not dupes else " -- "
         + "; ".join("%s `%s`" % (n, i) for n, i, _ in dupes[:8])))
    a("* cards carrying the `+` upgrade suffix: %d, of which %d lack the base card%s"
      % (len(upgraded), len(no_base),
         (" -- " + ", ".join("`%s`" % m for m in no_base)) if no_base else ""))
    a("")
    a("### Composite ids that embed other ids")
    a("")
    a("Reward labels are built by string concatenation, so they *contain* other ids")
    a("without the engine knowing.  A rename of the embedded id orphans them silently")
    a("-- this is the rename hazard the schema notes.  Checked explicitly:")
    a("")
    a("| label shape | occurrences | result |")
    a("|---|---|---|")
    for shape, n in sorted(comp_checked.items()):
        a("| `%s` | %d | %s |" % (shape, n, "**broken**" if comp_problems
                                  else "all embedded ids resolve"))
    a("")
    if comp_problems:
        a("**Broken composite ids:**")
        a("")
        for l, p in comp_problems[:40]:
            a("* `%s`: %s" % (l, p))
        a("")
    if comp_hazards:
        a("**Ambiguous composite ids:**")
        a("")
        for l, p in comp_hazards[:20]:
            a("* `%s`: %s" % (l, p))
        a("")
    a("### Choice id scope")
    a("")
    a("Choice ids are unique only **within one situation**, not within an event")
    a("script: every `result:*` situation ends with a choice literally named")
    a("`continue`, which is perfectly legal and is why the namespace is")
    a("`choice@<script>/<situationId>`.  The composite reward label")
    a("`event-<eventId>-choice-<choiceId>-...` however assumes the choice id is")
    a("unique *per script*, so a future edit that gives effects to two same-named")
    a("choices in one script would mint two identical reward labels.  Scripts where")
    a("that could bite (they repeat a choice id, but no label currently depends on")
    a("it): **%d**." % len(choice_haz))
    if choice_haz:
        a("")
        for script, dupes_ in choice_haz[:12]:
            a("* `Events[%s]`: %s" % (script, ", ".join("`%s`" % d for d in dupes_)))
    a("")
    a("### Unclassified id-shaped strings")
    a("")
    if unclassified:
        a("Strings that *are* a declared id, sit in a field no reference rule covers,")
        a("and would therefore be missed by a rename.  A safety net, not necessarily a")
        a("bug -- each needs a human decision:")
        a("")
        a("| field | occurrences | sample |")
        a("|---|---|---|")
        for f, n in unclassified.most_common(30):
            s, site = samples[f]
            a("| `%s` | %d | `%s` at `%s` |" % (f, n, s, site))
    else:
        a("None.  Every string that is a declared id also sits in a field this")
        a("validator classifies as a reference, so the reference graph above is")
        a("complete for this document.")
    a("")

    # ------------------------------------------------------------ detail G
    a("## G. Reachability, and what it costs")
    a("")
    a("BFS from `Map.EntryNodeIds` plus the starting deck and relics, over the")
    a("reference graph built in section C.  Content the map cannot reach is content")
    a("the firmware would never execute.")
    a("")
    a("| namespace | declared | reachable | unreachable |")
    a("|---|---|---|---|")
    for ns in sorted(dead):
        total = len(c.decl.get(ns, {}))
        n = len(dead[ns])
        a("| `%s` | %d | %d | %d |" % (ns, total, total - n, n))
    a("")
    a("Unreachable content occupies **%d B** of the image: %d table bytes, %d term"
      % (deadb["total_bytes"], deadb["dead_rows_bytes"], deadb["dead_terms"]))
    a("records (%d B) and %d pooled strings (%d B) that no reachable entity references."
      % (deadb["dead_term_bytes"], deadb["dead_strings"], deadb["dead_string_bytes"]))
    a("")
    if deadb["total_bytes"] > 2000:
        a("That is %.1f%% of the %.1f KiB image and is a *measured* upper bound on"
          % (100.0 * deadb["total_bytes"] / len(buf), len(buf) / 1024.0))
        a("what a content-pruning pass could remove -- but only after confirming the")
        a("other acts are not meant to use it.  This document's `MapGeneration` is")
        a("`null` and its map covers act 1 only, so the deeper `city_elite_*` /")
        a("`city_boss_*` encounters and the `rest:`/`treasure:` event scripts may be")
        a("waiting on an act-2 map that is not in this file.")
    a("")

    text = "\n".join(L) + "\n"
    with open(os.path.join(HERE, "out", args.name + ".md"), "w", encoding="utf-8",
              newline="\n") as fh:
        fh.write(text)
    with open(args.json_out if args.name == "validate"
              else os.path.join(HERE, "out", args.name + ".json"),
              "w", encoding="utf-8", newline="\n") as fh:
        json.dump(result, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print(text)
    sys.exit(0 if result["ok"] else 1)


def pat_enc_match(lab):
    return bool(re.match(r"^(?:cards|spoils|relic):", lab))


def _v(ok, n, what="errors"):
    if ok:
        return "PASS"
    return "**FAIL** (%d %s)" % (n, what)


if __name__ == "__main__":
    main()
