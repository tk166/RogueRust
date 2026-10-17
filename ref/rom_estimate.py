"""rom_estimate.py -- size a compact binary ROM for a *.roguedeck.json document.

The model is explicit and crude but MEASURED field-by-field, not guessed:

  * every object key name disappears (opcode + fixed field order per kind)
  * every string becomes a u16 index into one string pool
  * every id becomes a u16 index into the same pool
  * enum-valued strings ("ZeroOrOne", "GreaterOrEqual", "DiscardPile", ...) become 1 byte
  * ints become 2 bytes (i16), bools 1 byte
  * nested nodes are 2-byte references into a node array (children written after parents)
  * derived properties (selector Cardinality / RequiredContextCapabilities,
    ExpressionProgram Id/MaxNodeDepth/MaxProgramSteps) are dropped
  * the Presentation manifest and the localisation keys go to a separate, droppable blob

Run it and compare with the raw/compact JSON sizes.
"""
import json, re, sys
from collections import Counter, defaultdict

PATH = (sys.argv[1] if len(sys.argv) > 1 else
        r"D:\Vibe\sts-tui\ref\RogueDeck-Core\src\RogueDeck.Sandbox.Run\SampleContent\bureaucrats.roguedeck.json")

raw = open(PATH, "rb").read()
text = raw.decode("utf-8-sig")
doc = json.loads(text)

out = []
a = out.append


def enc(o, ind=None):
    return len(json.dumps(o, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


# ---------------------------------------------------------------- knowledge

# enum-valued strings: known value sets seen in the document
ENUM_VALUES = set()
for name in ("Cardinality", "Op", "Polarity", "StackingBehavior", "TurnEndHandDestinationZone",
             "PlayedCardDestinationZone", "ToZone", "FromZone", "Kind", "DamageKind",
             "LifecycleState", "CombatResult", "MovementMode", "Placement", "Scope",
             "Pipeline", "Operation", "RestrictDamageKind", "WhenResult", "event",
             "trigger", "Zone", "Axis", "Relative"):
    pass  # populated below by collecting the actual values per field
ENUM_FIELDS = {"Cardinality", "Op", "Polarity", "StackingBehavior", "TurnEndHandDestinationZone",
               "PlayedCardDestinationZone", "ToZone", "FromZone", "Kind", "DamageKind",
               "LifecycleState", "CombatResult", "MovementMode", "Placement", "Scope",
               "Pipeline", "Operation", "RestrictDamageKind", "WhenResult", "event",
               "trigger", "Axis", "Relative", "Event"}
enum_values = set()
for f in ENUM_FIELDS:
    pass

# Derived / redundant keys dropped outright (verified against the engine sources):
#  - Cardinality / RequiredContextCapabilities are computed properties of the selector's TYPE
#    (43 concrete selector classes registered in CombatJson.RegisterSelectors), so they carry
#    no information at all.
#  - MaxNodeDepth / MaxProgramSteps are engine guards with fixed defaults.
#  - Children is a SECOND COPY of nested node-valued fields on every kind whose constructor
#    does not take it (CombatJson.WriteChildrenOnlyWhereTheyAreRead); on the sequence-like
#    kinds it IS the payload.
SEQUENCE_KINDS = {"node.sequence", "node.causalSequence", "node.chooseOptions"}
DERIVED_KEYS = {"Cardinality", "RequiredContextCapabilities", "MaxNodeDepth", "MaxProgramSteps",
                "WhenResult", "Priority", "ResultKey", "AliveOnly", "MaxIterations", "MaxCount"}

# Presentation + localisation: engine-invisible, shipped in a droppable sidecar.
PRESENTATION_ROOTS = {"Presentation"}
TEXT_KEYS = {"NameKey", "DescriptionKey", "TextKey", "DisplayName", "FlavorText", "Art",
             "Icon", "Rarity", "Frame", "Color", "Sound", "Vfx", "SummonDisplayName"}


def collect_enum_values(node, field=None, sink=None):
    if isinstance(node, dict):
        for k, v in node.items():
            collect_enum_values(v, k, sink)
    elif isinstance(node, list):
        for it in node:
            collect_enum_values(it, field, sink)
    elif isinstance(node, str) and field in ENUM_FIELDS:
        sink.add(node)


xsink = set()
collect_enum_values(doc, None, xsink)
ENUM_VALUES = xsink
a("enum-valued strings observed (become 1 byte): %d distinct -> %s"
  % (len(ENUM_VALUES), ", ".join(sorted(ENUM_VALUES))[:150]))

# ---------------------------------------------------------- string accounting
str_fields = Counter()      # field name -> count
str_bytes = 0
scalar_hist = Counter()
node_count = Counter()

def is_node(d):
    return isinstance(d, dict) and isinstance(d.get("kind"), str) and "value" in d


# Everything that is not a "node.*/fx.*/tpl.*/meta.*/reward.*/intent.*" opcode is an
# expression / selector / payload, laid out in its own array.
def IS_EXPR(kind):
    return not (kind.startswith("node.") or kind.startswith("fx.") or kind.startswith("tpl.")
                or kind.startswith("meta.") or kind.startswith("reward.")
                or kind.startswith("intent."))


def survey(node, field=None, in_pres=False):
    global str_bytes
    if isinstance(node, dict):
        for k, v in node.items():
            survey(v, k, in_pres or k in PRESENTATION_ROOTS)
    elif isinstance(node, list):
        for it in node:
            survey(it, field, in_pres)
    elif isinstance(node, str):
        str_fields[field] += 1
        str_bytes += len(node.encode("utf-8"))
        scalar_hist["string"] += 1
    elif isinstance(node, bool):
        scalar_hist["bool"] += 1
    elif node is None:
        scalar_hist["null"] += 1
    else:
        scalar_hist["number"] += 1


survey(doc)
a("scalars: %s" % dict(scalar_hist))

# ============================ THE MODEL ===================================

BITS = {"opcode": 1, "node_ref": 2, "int": 2, "bool": 1, "enum": 1, "str_ref": 2,
        "list_count": 1}

node_bytes = 0
node_instances = 0
expr_bytes = 0
expr_instances = 0
list_bytes = 0
scalar_field_bytes = 0
pres_bytes = 0


def size_scalar(v, field):
    if isinstance(v, str):
        if field in ENUM_FIELDS and v in ENUM_VALUES:
            return BITS["enum"]
        return BITS["str_ref"]
    if isinstance(v, bool):
        return BITS["bool"]
    if v is None:
        return 0
    return BITS["int"]


def size_value(v, field=None, in_pres=False, depth=0):
    """Bytes this value costs in the binary form, excluding nested node subtrees
    (which are emitted separately and referenced)."""
    global list_bytes
    if is_node(v):
        return BITS["node_ref"]
    if isinstance(v, dict):
        return sum(size_value(x, k, in_pres, depth + 1) for k, x in v.items())
    if isinstance(v, list):
        if v and is_node(v[0]):
            return BITS["node_ref"] * len(v) + (BITS["list_count"] if len(v) > 1 else 0)
        n = sum(size_value(x, field, in_pres, depth + 1) for x in v)
        return n + (BITS["list_count"] if v else 0)
    return size_scalar(v, field)


def emit(x, in_pres=False):
    global node_bytes, node_instances, expr_bytes, expr_instances, pres_bytes
    if isinstance(x, dict):
        if is_node(x):
            kind = x["kind"]
            body = x["value"]
            drop_children = kind not in SEQUENCE_KINDS
            if not in_pres:
                node_instances += 1
                if kind.startswith("node.") or kind.startswith("fx.") or kind.startswith("tpl.") \
                        or kind.startswith("meta.") or kind.startswith("reward.") or kind.startswith("intent."):
                    node_count[kind] += 1
            cost = BITS["opcode"]
            if isinstance(body, dict):
                for k, v in body.items():
                    if k in DERIVED_KEYS or (k == "Children" and drop_children):
                        continue
                    cost += size_value(v, k, in_pres)
            if in_pres:
                pres_bytes += cost
            elif IS_EXPR(kind):
                expr_bytes += cost
                expr_instances += 1
            else:
                node_bytes += cost
            if isinstance(body, dict):
                for k, v in body.items():
                    if k in DERIVED_KEYS or (k == "Children" and drop_children):
                        continue
                    emit(v, in_pres)
            return
        for k, v in x.items():
            if k in PRESENTATION_ROOTS:
                pres_bytes += enc(v)  # measured directly: never enters the ROM
                continue
            emit(v, in_pres)
    elif isinstance(x, list):
        for it in x:
            emit(it, in_pres)


BEFORE = (node_bytes, node_instances, expr_bytes, expr_instances)
node_bytes = node_instances = expr_bytes = expr_instances = pres_bytes = 0
emit(doc)

# string pool: distinct strings minus enums minus presentation-only strings
pres_strings = set()
def collect_pres_strings(node, in_pres=False, field=None):
    if isinstance(node, dict):
        for k, v in node.items():
            collect_pres_strings(v, in_pres or k in PRESENTATION_ROOTS, k)
    elif isinstance(node, list):
        for it in node:
            collect_pres_strings(it, in_pres, field)
    elif isinstance(node, str):
        if in_pres or field in ("NameKey", "DescriptionKey", "TextKey", "FlavorText",
                                "Art", "Icon", "Rarity", "Frame", "Color", "Sound", "Vfx"):
            pres_strings.add(node)
collect_pres_strings(doc)

all_strings = set()
def collect_all(node):
    if isinstance(node, dict):
        for v in node.values():
            collect_all(v)
    elif isinstance(node, list):
        for it in node:
            collect_all(it)
    elif isinstance(node, str):
        all_strings.add(node)
collect_all(doc)

core_strings = all_strings - pres_strings - ENUM_VALUES
core_pool = sum(len(s.encode("utf-8")) + 1 for s in core_strings)
pres_pool = sum(len(s.encode("utf-8")) + 1 for s in pres_strings)

a("")
a("=" * 74)
a("BINARY ROM ESTIMATE (see rom_estimate.py for the model)")
a("=" * 74)
a("%-46s %10s" % ("layer", "bytes"))
a("%-46s %10d" % ("effect/effect-node opcodes (%d instances)" % node_instances, node_bytes))
a("%-46s %10d" % ("expression + selector opcodes (%d)" % expr_instances, expr_bytes))
a("%-46s %10d" % ("string pool, CORE (%d distinct)" % len(core_strings), core_pool))
a("%-46s %10d" % ("platform/tables/rounding overhead (est. 15%)",
                   int(0.15 * (node_bytes + expr_bytes + core_pool))))
core_total = node_bytes + expr_bytes + core_pool + int(0.15 * (node_bytes + expr_bytes + core_pool))
a("%-46s %10d" % ("CORE ROM TOTAL", core_total))
a("")
a("%-46s %10d" % ("presentation sidecar (manifest, measured JSON size)", pres_bytes))
a("%-46s %10d" % ("presentation + localisation string pool (%d distinct)" % len(pres_strings), pres_pool))
a("%-46s %10d" % ("PRESENTATION TOTAL (droppable)", pres_bytes + pres_pool))
a("%-46s %10d" % ("CORE + PRESENTATION", core_total + pres_bytes + pres_pool))
a("")
a("reference points: raw file %d B ; compact JSON %d B" % (len(raw), enc(doc)))
a("reduction core-only: %.1fx vs compact, %.1fx vs raw"
  % (enc(doc) / core_total, len(raw) / core_total))
a("")
a("node opcodes by kind (top 25):")
for k, n in node_count.most_common(25):
    a("    %-34s %6d" % (k, n))
a("")
a("distinct strings: all=%d core=%d presentation=%d enum=%d"
  % (len(all_strings), len(core_strings), len(pres_strings), len(ENUM_VALUES)))
a("core string pool bytes: %d ; longest core string %d ; avg %.1f"
  % (core_pool, max((len(s) for s in core_strings), default=0),
     core_pool / max(1, len(core_strings))))

print("\n".join(out))
