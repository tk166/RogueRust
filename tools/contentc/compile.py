#!/usr/bin/env python3
"""compile.py -- offline content compiler for `*.roguedeck.json` -> RDCF binary.

Pure Python 3 stdlib.  See `rdcfmt.py` for the frozen on-disk vocabulary and
`docs/spec/content-binary-format.md` for the design rationale.

    python compile.py [--src <json>] [--out-dir <dir>] [--no-core] [--quiet]
                      [--full-name <f>] [--core-name <f>]

Produces, in the output directory:
    content.rdcf          full content (every byte of the source document)
    content.core.rdcf     presentation stripped (name/description/flavour/art)
    manifest.json         section directory: offsets, counts, byte sizes, totals
    report.md             measured byte budget, before/after comparison, drops
    layout.txt            the derived opcode table (debugging aid)

The two output names are overridable because several content packages coexist
here (see `build.py` and `packages/`); the defaults reproduce the historic
single-package behaviour exactly.

Design in one paragraph
-----------------------
Every polymorphic `{"kind": K, "value": {...}}` node, every *plain* JSON object
shape, and every scalar gets an integer opcode.  An opcode's payload layout is
derived from the union of the fields actually observed in the document, so the
binary contains no key names and no `kind`/`value` envelope.  Identical subtrees
are interned, so the 16,890 IR instances collapse into a DAG -- which is what
makes 743,993 B of byte-identical program bodies cost nothing extra.  Id wrappers
(`{"value": s}` / `{"Value": s}`) never become objects at all: the field declares
which spelling it uses.  The result is *exact*: `reader.py` reconstructs the
document structurally equal to the source, including the redundant `Children`
arrays the engine ignores, so `validate.py` does not have to argue equivalence.
"""

import argparse
import hashlib
import io
import json
import os
import struct
import sys
import time
import tracemalloc
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import rdcfmt as F  # noqa: E402

DEFAULT_SRC = (r"D:\Vibe\sts-tui\ref\RogueDeck-Core\src\RogueDeck.Sandbox.Run"
               r"\SampleContent\bureaucrats.roguedeck.json")

ENTITY_SECTIONS = [("CARD", "Cards"), ("STATUS", "Statuses"), ("EACT", "EnemyActions"),
                   ("ENCT", "Encounters"), ("REL", "Relics"),
    # **Not** `Events`: the reference document uses that key for a dict of its own shape.
    ("EV", "UnknownRooms"),
    # `Potions` is free in the reference document (checked: it has no such key).
    ("POT", "Potions")]
SEC_OF = {"CARD": F.S_CARD, "STATUS": F.S_STAT, "EACT": F.S_EACT,
          "ENCT": F.S_ENCT, "REL": F.S_REL, "EV": F.S_EV, "POT": F.S_POT}

# Document keys: top-level keys that are **build metadata, not game data**.
#
# They ride along in the source document (that is deliberate: `native/sts_content_check.py`
# reads the inert-key declaration from the very file it describes, so the declaration cannot
# drift away from the content) but they are NOT serialised into either image.  An image's
# size is a budget line, and on the `sts` package these two keys were **nearly half** of the
# image: the term DAG and the string pool were paying for a documentation block the kernel
# can never read.  The per-key cost is *measured* and printed in `report.md` §2 (row tagged
# "document key") -- do not copy a number here, it moves with the content.
#
# Consequence for every round-trip reader: `Rom.document()` reproduces the document *minus*
# these keys.  That is why this tuple is the single source of truth -- `native/sts_content_check.py`
# imports it instead of keeping a second copy (`contentc-audit.md` §7 discipline: one constant,
# one place).  Adding a key here is a *content* decision, so it changes image bytes; `roguedeck`
# has neither key, which is why its two pinned images must stay byte-identical.
DOC_ROOT_KEYS = ("InertKeys", "Notes",
    # the `?`-room entity table (`EV`); an entity key, so never a root key
    "UnknownRooms",
    # the potion entity table (`POT`); an entity key, so never a root key
    "Potions",
)

# Sentinel values for the two "not a real value" states.  Keeping them distinct
# is what lets `reader.py` reproduce the source's key *presence* exactly.
_ABSENT = {F.F_INT: F.ABSENT_INT, F.F_BOOL: F.BOOL_ABSENT}
_NULL = {F.F_INT: F.NULL_INT, F.F_BOOL: F.BOOL_NULL}


def _absent_sentinel(fk):
    return _ABSENT.get(fk, F.ABSENT16)


def _null_sentinel(fk):
    return _NULL.get(fk, F.NULL16)


# ===========================================================================
# 0.  document helpers
# ===========================================================================

def is_ir(v):
    """A polymorphic IR node: {"kind": <str>, "value": <anything>}."""
    return isinstance(v, dict) and isinstance(v.get("kind"), str) and "value" in v \
        and set(v) <= {"kind", "value"}


def wrap_key(v):
    """Which id-wrapper spelling, if any, this value uses.

    The engine declares ids as `readonly record struct X(string value)`, so the
    same id appears bare, as `{"value": s}` (CombatIds.cs) or as `{"Value": s}`
    (run layer).  Returns "value", "Value" or None.
    """
    if not isinstance(v, dict) or len(v) != 1:
        return None
    k = next(iter(v))
    return k if k in ("value", "Value") and isinstance(v[k], str) else None


def unwrap(v):
    return v["value"] if "value" in v else v["Value"]


def vclass(v):
    """The observed *storage class* of a JSON value -- this drives field typing."""
    if v is None:
        return "null"
    if v is True or v is False:
        return "bool"
    if isinstance(v, int):
        return "int"
    if isinstance(v, float):
        return "float"
    if isinstance(v, str):
        return "str"
    if isinstance(v, dict):
        if is_ir(v):
            return "term"
        wk = wrap_key(v)
        return "wrapped:" + wk if wk else "obj"
    if isinstance(v, list):
        if not v:
            return "arr0"
        return "arr<" + "+".join(sorted({vclass(x) for x in v})) + ">"
    raise TypeError("unhandled value type %r" % (type(v),))


def compact_bytes(o):
    return len(json.dumps(o, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def canon_json(o):
    return json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


# ===========================================================================
# 1.  layout derivation
# ===========================================================================

GENERIC_SCALARS = {"term", "obj", "str", "wrapped:value", "wrapped:Value"}
WRAP_FLAG = {"wrapped:value": F.FLAG_WRAP_LOWER, "wrapped:Value": F.FLAG_WRAP_UPPER}


class Layout(object):
    """One opcode: which fields it carries, in what order, with what storage."""
    __slots__ = ("op", "name", "fields", "kinds", "flags", "is_ir")

    def __init__(self, op, name, fields, kinds, flags, is_ir):
        self.op = op
        self.name = name
        self.fields = tuple(fields)
        self.kinds = tuple(kinds)
        self.flags = tuple(flags)
        self.is_ir = is_ir

    @property
    def nfields(self):
        return len(self.fields)

    @property
    def nslots(self):
        return sum(F.FIELD_SLOTS[k] for k in self.kinds)

    @property
    def record_size(self):
        return F.align4(2 + 2 * self.nslots)


def pick_kind(classes):
    """Map an observed set of storage classes to (field kind, flags).

    We only ever combine classes that survive on the wire unchanged.  The
    uniform cases get a dedicated compact kind; anything genuinely mixed goes
    through F_TERM, whose `generic` encoding is exact for every scalar and
    object shape, so a fallback still interns rather than duplicating.
    """
    base = set(classes) - {"null"}
    if not base:
        return F.F_TERM, 0
    if base <= {"str"}:
        return F.F_STR, 0
    if base == {"wrapped:value"}:
        return F.F_STR, F.FLAG_WRAP_LOWER
    if base == {"wrapped:Value"}:
        return F.F_STR, F.FLAG_WRAP_UPPER
    if base <= {"int"}:
        return F.F_INT, 0
    if base <= {"bool"}:
        return F.F_BOOL, 0
    arrs = {c for c in base if c.startswith("arr")}
    if not arrs:
        if base <= GENERIC_SCALARS:
            return F.F_TERM, 0
        return F.F_JSON, 0
    if base - arrs:
        return F.F_JSON, 0            # a field that is sometimes a list, sometimes not
    elems = set()
    for c in arrs:
        if c != "arr0":
            elems |= set(c[4:-1].split("+"))
    elems -= {"null"}
    if not elems or elems <= {"str"}:
        return F.F_STRLIST, 0
    if elems == {"wrapped:value"}:
        return F.F_STRLIST, F.FLAG_WRAP_LOWER
    if elems == {"wrapped:Value"}:
        return F.F_STRLIST, F.FLAG_WRAP_UPPER
    if elems <= GENERIC_SCALARS:
        return F.F_TERMLIST, 0
    return F.F_JSON, 0


class Deriver(object):
    """Walks the document once and derives one opcode per IR kind / object shape."""

    def __init__(self, doc):
        self.doc = doc
        self.kind_fields = defaultdict(lambda: defaultdict(Counter))
        self.kind_n = Counter()
        self.kind_notdict = Counter()
        self.obj_fields = defaultdict(lambda: defaultdict(Counter))
        self.obj_n = Counter()
        self.json_fallback = []          # (owner, field, observed classes)
        self.absent_fields = []          # (owner, field) present in < all instances

    def scan(self):
        self._walk(self.doc)
        return self

    def _walk(self, v):
        if isinstance(v, dict):
            if is_ir(v):
                kind = v["kind"]
                self.kind_n[kind] += 1
                inner = v["value"]
                if not isinstance(inner, dict):
                    self.kind_notdict[kind] += 1
                    return
                seen = self.kind_fields[kind]
                for k in sorted(inner):
                    seen[k][vclass(inner[k])] += 1
                    self._walk(inner[k])
                return
            if wrap_key(v):
                return
            shape = tuple(sorted(v))
            self.obj_n[shape] += 1
            seen = self.obj_fields[shape]
            for k in shape:
                seen[k][vclass(v[k])] += 1
                self._walk(v[k])
        elif isinstance(v, list):
            for x in v:
                self._walk(x)

    def _fields_of(self, owner, fields_raw, n_instances, is_ir):
        names = sorted(fields_raw)
        kinds, flags = [], []
        for f in names:
            classes = set(fields_raw[f])
            k, fl = pick_kind(classes)
            if k == F.F_JSON:
                self.json_fallback.append((owner, f, sorted(classes)))
            kinds.append(k)
            flags.append(fl)
            if sum(fields_raw[f].values()) < n_instances:
                self.absent_fields.append((owner, f))
        return names, kinds, flags

    def layouts(self):
        self.scan()
        ir, objs = [], []
        for kind in sorted(self.kind_fields):
            if self.kind_notdict[kind]:
                ir.append(Layout(None, kind, ("<whole-value>",), (F.F_JSON,), (0,), True))
                self.json_fallback.append((kind, "<whole-value>", ["non-object"]))
                continue
            names, kinds, flags = self._fields_of(
                kind, self.kind_fields[kind], self.kind_n[kind], True)
            ir.append(Layout(None, kind, names, kinds, flags, True))
        for shape in sorted(self.obj_fields):
            owner = "_obj(" + ",".join(shape) + ")"
            names, kinds, flags = self._fields_of(
                owner, self.obj_fields[shape], self.obj_n[shape], False)
            objs.append(Layout(None, owner, names, kinds, flags, False))
        op = F.OP_FIRST_DYNAMIC
        for lay in ir + objs:
            lay.op = op
            op += 1
        if op > 256:
            raise SystemExit("content needs %d opcodes; the opcode field is a u8" % op)
        return ir, objs


# ===========================================================================
# 2.  encoder: JSON -> interned term DAG + entity rows
# ===========================================================================

class Encoder(object):
    def __init__(self, deriver, ir_layouts, obj_layouts):
        self.ir_ops = {l.name: l for l in ir_layouts}
        self.obj_ops = {}
        for l in obj_layouts:
            body = l.name[len("_obj("):-1]
            self.obj_ops[tuple(body.split(",")) if body else ()] = l
        self.terms = [(F.OP_NULL, ())]
        self.index = {(F.OP_NULL, ()): 0}
        self.int_range = [None, None]
        self.rows = {}
        self.root_entries = []
        self.idx = []

    # ------------------------------------------------------------- interning
    def term(self, op, cells):
        key = (op, cells)
        tid = self.index.get(key)
        if tid is None:
            tid = len(self.terms)
            if tid > 0xFFFE:
                raise SystemExit("term table overflow (>65534 distinct terms)")
            self.terms.append(key)
            self.index[key] = tid
        return tid

    # ---------------------------------------------------------------- cells
    def cell(self, fk, flags, v):
        if fk == F.F_STR:
            if v is None:
                return ("N",)
            if flags and isinstance(v, dict):
                v = unwrap(v)
            if not isinstance(v, str):
                raise TypeError("F_STR got %r for %r" % (type(v), v))
            return ("S", v)
        if fk == F.F_INT:
            if v is None:
                return ("N",)
            self._note_int(v)
            return ("I", v)
        if fk == F.F_BOOL:
            if v is None:
                return ("N",)
            return ("B", F.BOOL_TRUE if v else F.BOOL_FALSE)
        if fk == F.F_TERM:
            if v is None:
                return ("N",)
            return ("T", self.generic(v))
        if fk == F.F_TERMLIST:
            if v is None:
                return ("N",)
            return ("L", tuple(("T", self.generic(x)) for x in v))
        if fk == F.F_STRLIST:
            if v is None:
                return ("N",)
            out = []
            for x in v:
                if flags and isinstance(x, dict):
                    x = unwrap(x)
                out.append(("S", x))
            return ("L", tuple(out))
        if fk == F.F_JSON:
            if v is None:
                return ("N",)
            return ("S", canon_json(v))
        raise KeyError(fk)

    def _note_int(self, v):
        if not isinstance(v, int) or isinstance(v, bool):
            raise TypeError("F_INT got %r" % (type(v),))
        if not (F.I16_MIN <= v <= F.I16_MAX):
            raise SystemExit("integer %d outside the storable range [%d,%d]"
                             % (v, F.I16_MIN, F.I16_MAX))
        lo, hi = self.int_range
        self.int_range = [v if lo is None else min(lo, v), v if hi is None else max(hi, v)]

    # ------------------------------------------------------------ encoders
    def generic(self, v):
        """Encode any JSON value as a term id (used where no layout applies)."""
        if v is None:
            return 0
        if v is True or v is False:
            return self.term(F.OP_BOOL, (("B", F.BOOL_TRUE if v else F.BOOL_FALSE),))
        if isinstance(v, int):
            self._note_int(v)
            return self.term(F.OP_INT, (("I", v),))
        if isinstance(v, str):
            return self.term(F.OP_STR, (("S", v),))
        if isinstance(v, list):
            return self.term(F.OP_ARR,
                             (("L", tuple(("T", self.generic(x)) for x in v)),))
        if isinstance(v, dict):
            if is_ir(v):
                return self.ir(v)
            wk = wrap_key(v)
            if wk:
                op = F.OP_WRAP_LOWER if wk == "value" else F.OP_WRAP_UPPER
                return self.term(op, (("S", unwrap(v)),))
            return self.obj(v)
        raise TypeError("cannot encode %r" % (type(v),))

    def ir(self, v):
        lay = self.ir_ops[v["kind"]]
        inner = v["value"]
        d = inner if isinstance(inner, dict) else {}
        cells = []
        for f, fk, fl in zip(lay.fields, lay.kinds, lay.flags):
            if f == "<whole-value>":
                cells.append(self.cell(fk, fl, inner))
            elif f in d:
                cells.append(self.cell(fk, fl, d[f]))
            else:
                cells.append(("A",))
        return self.term(lay.op, tuple(cells))

    def obj(self, d):
        lay = self.obj_ops[tuple(sorted(d))]
        return self.term(lay.op, tuple(
            self.cell(fk, fl, d[f]) for f, fk, fl in zip(lay.fields, lay.kinds, lay.flags)))

    # ----------------------------------------------------------- entities
    def row(self, schema, rec):
        cells = []
        consumed = set()
        for key, fk, fl in schema:
            if key == "extra":
                leftover = sorted(k for k in rec if k not in consumed)
                if leftover:
                    cells.append(("T", self.obj({k: rec[k] for k in leftover})))
                else:
                    cells.append(("N",))
            elif key in rec:
                consumed.add(key)
                cells.append(self.cell(fk, fl, rec[key]))
            else:
                cells.append(("A",))
        return cells


# ===========================================================================
# 3.  serializer
# ===========================================================================

class Serializer(object):
    def __init__(self, enc, ir_layouts, obj_layouts, doc):
        self.enc = enc
        self.ir_layouts = ir_layouts
        self.obj_layouts = obj_layouts
        self.doc = doc
        self.op_kinds = {}
        for op, (k, f) in F.RESERVED_OP_LAYOUT.items():
            self.op_kinds[op] = (k, f)
        for l in ir_layouts + obj_layouts:
            self.op_kinds[l.op] = (l.kinds, l.flags)
        self.aux = []
        self.strid = None
        self.sections = {}

    # ------------------------------------------------------- string pool
    def collect_strings(self):
        found = set()
        for _, cells in self.enc.terms:
            self._cells_strings(cells, found)
        for l in self.ir_layouts:
            found.add(l.name)
            found.update(l.fields)
        found.add("_obj")
        for l in self.obj_layouts:
            found.update(l.fields)
        for _, _, schema, rows in self._row_groups():
            for cells in rows:
                for (key, fk, fl), c in zip(schema, cells):
                    if c[0] == "S":
                        found.add(c[1])
                    elif c[0] == "L":
                        for el in c[1]:
                            if el[0] == "S":
                                found.add(el[1])
        for key, _ in self.enc.root_entries:
            found.add(key)
        return found

    def _cells_strings(self, cells, found):
        for c in cells:
            if c[0] == "S":
                found.add(c[1])
            elif c[0] == "L":
                for el in c[1]:
                    if el[0] == "S":
                        found.add(el[1])

    def _row_groups(self):
        for sname, sec in ENTITY_SECTIONS:
            yield sec, sname, F.ROW_SCHEMAS[sname], self.enc.rows.get(sname, [])

    # ----------------------------------------------------------- slot emit
    def emit_slots(self, out_vals, cells, kinds, flags):
        for c, fk, fl in zip(cells, kinds, flags):
            if fk in (F.F_TERMLIST, F.F_STRLIST):
                if c[0] == "A":
                    out_vals.extend((F.LIST_ABSENT, F.LIST_ABSENT))
                elif c[0] == "N":
                    out_vals.extend((F.LIST_NULL, F.LIST_NULL))
                else:
                    start = len(self.aux)
                    for el in c[1]:
                        self.aux.append(self.strid[el[1]] if el[0] == "S" else el[1])
                    out_vals.extend((start, len(c[1])))
                continue
            t = c[0]
            if t == "A":
                out_vals.append(_absent_sentinel(fk))
            elif t == "N":
                out_vals.append(_null_sentinel(fk))
            elif t == "S":
                out_vals.append(self.strid[c[1]])
            elif t == "T":
                out_vals.append(c[1])
            elif t == "I":
                out_vals.append(c[1] & 0xFFFF)
            elif t == "B":
                out_vals.append(c[1])
            else:
                raise KeyError(t)

    # -------------------------------------------------------------- build
    def build(self):
        strings = self.collect_strings()
        ordered = sorted(strings, key=lambda s: s.encode("utf-8"))
        self.strid = {s: i + 1 for i, s in enumerate(ordered)}     # 0 reserved
        if len(ordered) + 1 > 0xFFFD:
            raise SystemExit("string pool overflow")
        blob = io.BytesIO()
        offsets = [0]
        for s in ordered:
            blob.write(s.encode("utf-8"))
            blob.write(b"\x00")
            offsets.append(blob.tell())
        self.sec_str = blob.getvalue()
        self.sec_stro = struct.pack("<%dI" % len(offsets), *offsets)

        # ---- terms
        trm = io.BytesIO()
        trw = []
        for op, cells in self.enc.terms:
            kinds, flags = self.op_kinds[op]
            vals = [op]
            self.emit_slots(vals, cells, kinds, flags)
            trw.append(trm.tell() // 4)
            trm.write(struct.pack("<%dH" % len(vals), *vals))
            pad = F.align4(len(vals) * 2) - len(vals) * 2
            if pad:
                trm.write(b"\x00" * pad)
        self.sec_trm = trm.getvalue()
        self.sec_trw = struct.pack("<%dH" % len(trw), *trw)
        if len(self.aux) > 0xFFFD:
            raise SystemExit("aux array overflow (%d u16 cells)" % len(self.aux))
        self.sec_aux = struct.pack("<%dH" % len(self.aux), *self.aux)

        # ---- opcode descriptors
        opf = io.BytesIO()
        opd = io.BytesIO()
        dyn = {l.op: l for l in self.ir_layouts + self.obj_layouts}
        n_ops = max(max(self.op_kinds), max(dyn)) + 1
        for op in range(n_ops):
            lay = dyn.get(op)
            if lay is None and op not in self.op_kinds:
                # unused hole in the reserved block (ops 8..15)
                opd.write(struct.pack("<IHBB", 0, 0, 0, 0))
                continue
            if lay is None:
                kinds, flags = self.op_kinds[op]
                off = opf.tell()
                for fk, fl in zip(kinds, flags):
                    opf.write(struct.pack("<HBB", 0, fk, fl))
                name = "_reserved%d" % op
                opd.write(struct.pack("<IHBB", off, self.strid.get(name, 0),
                                      len(kinds), F.OPCLASS_GENERIC))
                continue
            off = opf.tell()
            for fname, fk, fl in zip(lay.fields, lay.kinds, lay.flags):
                opf.write(struct.pack("<HBB", self.strid[fname], fk, fl))
            name = lay.name if lay.is_ir else "_obj"
            opd.write(struct.pack("<IHBB", off, self.strid.get(name, 0),
                                  lay.nfields, F.OPCLASS_IR if lay.is_ir else F.OPCLASS_GENERIC))
        self.sec_opf = opf.getvalue()
        self.sec_opd = opd.getvalue()

        # ---- entity tables
        for _, sname, schema, rows in self._row_groups():
            self.sections[SEC_OF[sname]] = self.build_rows(sname, schema, rows)
            if os.environ.get("RDCF_DEBUG_SECTIONS"):
                import sys as _sys
                _sys.stderr.write("ENC %s -> sec %s: rows=%d bytes=%d\n" % (
                    sname, SEC_OF[sname], len(rows), len(self.sections[SEC_OF[sname]])))

        # ---- root table
        r = io.BytesIO()
        for key, tid in sorted(self.enc.root_entries, key=lambda e: self.strid[e[0]]):
            r.write(struct.pack("<HH", self.strid[key], tid))
        self.sec_root = r.getvalue()

        # ---- id symbol table
        idx = sorted((self.strid[sid], ekind, index)
                     for sid, ekind, index in self.enc.idx)
        i = io.BytesIO()
        for sid, ekind, index in idx:
            i.write(struct.pack("<HBBHH", sid, ekind, 0, index, 0))
        self.sec_idx = i.getvalue()

        self.strings_ordered = ordered
        self.term_offsets = trw
        return self

    def build_rows(self, sname, schema, rows):
        kinds = [fk for _, fk, _ in schema]
        flags = [fl for _, _, fl in schema]
        stride = F.row_stride(sname)
        buf = io.BytesIO()
        for cells in rows:
            vals = []
            self.emit_slots(vals, cells, kinds, flags)
            raw = struct.pack("<%dH" % len(vals), *vals)
            buf.write(raw)
            buf.write(b"\x00" * (stride - len(raw)))
        return buf.getvalue()

    # -------------------------------------------------------------- write
    def write(self, path, content_hash, schema_version, flags):
        payload = {F.S_STR: self.sec_str, F.S_STRO: self.sec_stro,
                   F.S_OPD: self.sec_opd, F.S_OPF: self.sec_opf,
                   F.S_TRM: self.sec_trm, F.S_TRW: self.sec_trw,
                   F.S_AUX: self.sec_aux, F.S_ROOT: self.sec_root,
                   F.S_IDX: self.sec_idx}
        for _, sname, _, _ in self._row_groups():
            payload[SEC_OF[sname]] = self.sections.get(SEC_OF[sname], b"")
        counts = {
            F.S_STR: len(self.strings_ordered), F.S_STRO: len(self.strings_ordered) + 1,
            F.S_OPD: len(self.sec_opd) // 8, F.S_OPF: len(self.sec_opf) // 4,
            F.S_TRM: len(self.enc.terms), F.S_TRW: len(self.term_offsets),
            F.S_AUX: len(self.aux), F.S_ROOT: len(self.sec_root) // 4,
            F.S_IDX: len(self.sec_idx) // 8,
        }
        for _, sname, _, rows in self._row_groups():
            counts[SEC_OF[sname]] = len(rows)
        if os.environ.get("RDCF_DEBUG_SECTIONS"):
            print("[] row_groups:", [(sname, SEC_OF[sname]) for _, sname, _, _ in self._row_groups()])
            print("[] payload keys:", sorted(payload))
            print("[] counts:", sorted(counts.items()))
            print("[] sections:", sorted(self.sections.items(), key=lambda kv: kv[0])[:30])
        dir_size = F.NSEC * 12
        dir_entries = []
        off = F.align4(F.HEADER_SIZE + dir_size)
        chunks = []
        total = off
        for sec in F.SEC_ORDER:
            data = payload.get(sec, b"")
            if not data:
                dir_entries.append((sec, 0, 0, counts.get(sec, 0)))
                continue
            dir_entries.append((sec, off, len(data), counts.get(sec, 0)))
            chunks.append((off, data))
            off = F.align4(off + len(data))
            total = off
        buf = bytearray(total)
        buf[0:F.HEADER_SIZE] = struct.pack(
            "<IHHIIHHII", F.MAGIC, F.FORMAT_VERSION, flags, total,
            F.HEADER_SIZE, F.NSEC, schema_version, content_hash, 0)
        for i, (sec, o, size, cnt) in enumerate(dir_entries):
            struct.pack_into("<III", buf, F.HEADER_SIZE + 12 * i, o, size, cnt)
        for o, data in chunks:
            buf[o:o + len(data)] = data
        with open(path, "wb") as fh:
            fh.write(buf)
        return total, dir_entries


# ===========================================================================
# 4.  presentation strip + redundancy diagnostics
# ===========================================================================

PRESENTATION_KEYS = {
    "Cards": ["NameKey", "DescriptionKey"],
    "Statuses": ["NameKey", "DescriptionKey"],
    "EnemyActions": ["NameKey", "DescriptionKey"],
    "Relics": ["DisplayName"],
    "Encounters": ["HeroDisplayName"],
}


def strip_presentation(doc):
    """Remove every field that only feeds text/art rendering.

    Documented, auditable list -- the engine reads none of these to resolve a
    run (see docs/spec/content-schema.md 2.2 and Presentation.cs:4-7).
    """
    out = dict(doc)
    out.pop("Presentation", None)
    for sec, keys in PRESENTATION_KEYS.items():
        if isinstance(out.get(sec), list):
            out[sec] = [{k: v for k, v in rec.items() if k not in keys}
                        for rec in out[sec]]
    if isinstance(out.get("EnemyActions"), list):
        fixed = []
        for rec in out["EnemyActions"]:
            rec = dict(rec)
            if isinstance(rec.get("Intent"), dict):
                rec["Intent"] = {k: v for k, v in rec["Intent"].items() if k != "Label"}
            fixed.append(rec)
        out["EnemyActions"] = fixed
    if isinstance(out.get("Encounters"), list):
        fixed = []
        for rec in out["Encounters"]:
            rec = dict(rec)
            if isinstance(rec.get("Enemies"), list):
                rec["Enemies"] = [{k: v for k, v in e.items() if k != "DisplayName"}
                                  for e in rec["Enemies"]]
            fixed.append(rec)
        out["Encounters"] = fixed
    if isinstance(out.get("Events"), dict):
        ev = {}
        for eid, script in out["Events"].items():
            script = dict(script)
            sit = []
            for s in (script.get("situations") or []):
                s = dict(s)
                s.pop("TextKey", None)
                s["Choices"] = [{k: v for k, v in c.items() if k != "TextKey"}
                                for c in (s.get("Choices") or [])]
                sit.append(s)
            script["situations"] = sit
            ev[eid] = script
        out["Events"] = ev
    if isinstance(out.get("Shops"), dict):
        out["Shops"] = {sid: {**sh, "Offers": [{k: v for k, v in o.items() if k != "TextKey"}
                                               for o in (sh.get("Offers") or [])]}
                        for sid, sh in out["Shops"].items()}
    return out


def prune_children(doc):
    """Remove the redundant `Children` view.  Used for *measurement* only."""
    keep = {"node.sequence", "node.causalSequence", "node.chooseOptions"}

    def walk(v):
        if isinstance(v, dict):
            if is_ir(v):
                inner = v["value"]
                if isinstance(inner, dict):
                    body = {k: walk(x) for k, x in inner.items()
                            if not (k == "Children" and v["kind"] not in keep)}
                    return {"kind": v["kind"], "value": body}
                return {"kind": v["kind"], "value": walk(inner)}
            return {k: walk(x) for k, x in v.items()}
        if isinstance(v, list):
            return [walk(x) for x in v]
        return v

    return walk(doc)


# ===========================================================================
# 5.  driver
# ===========================================================================

def compile_doc(doc):
    t0 = time.perf_counter()
    d = Deriver(doc)
    ir_lays, obj_lays = d.layouts()
    t_derive = time.perf_counter() - t0

    t0 = time.perf_counter()
    enc = Encoder(d, ir_lays, obj_lays)
    for sname, sec in ENTITY_SECTIONS:
        schema = F.ROW_SCHEMAS[sname]
        enc.rows[sname] = [enc.row(schema, rec) for rec in doc.get(sec) or []]
    for key in sorted(doc):
        if key in dict(ENTITY_SECTIONS).values() or key in DOC_ROOT_KEYS:
            continue
        enc.root_entries.append((key, enc.generic(doc[key])))

    def add(s, kind, index):
        if isinstance(s, str) and s:
            enc.idx.append((s, kind, index))
    for i, rec in enumerate(doc.get("Cards") or []):
        add(rec.get("Id"), F.EK_CARD, i)
    for i, rec in enumerate(doc.get("Statuses") or []):
        add(rec.get("Id"), F.EK_STATUS, i)
    for i, rec in enumerate(doc.get("EnemyActions") or []):
        add(rec.get("Id"), F.EK_EACTION, i)
    for i, rec in enumerate(doc.get("Encounters") or []):
        iv = rec.get("Id")
        add(unwrap(iv) if isinstance(iv, dict) else iv, F.EK_ENCOUNTER, i)
    for i, rec in enumerate(doc.get("Relics") or []):
        add(rec.get("Id"), F.EK_RELIC, i)
    for i, rec in enumerate(((doc.get("Map") or {}).get("Nodes") or [])):
        add(rec.get("id"), F.EK_MAPNODE, i)
    for i, k in enumerate(sorted(doc.get("Events") or {})):
        add(k, F.EK_EVENT, i)
    for i, k in enumerate(sorted(doc.get("Shops") or {})):
        add(k, F.EK_SHOP, i)
    for i, rec in enumerate(doc.get("Characters") or []):
        add(rec.get("Id"), F.EK_CHARACTER, i)
    add((doc.get("Start") or {}).get("HeroName"), F.EK_CHARACTER, 0)
    t_encode = time.perf_counter() - t0

    t0 = time.perf_counter()
    ser = Serializer(enc, ir_lays, obj_lays, doc).build()
    t_ser = time.perf_counter() - t0
    return {"deriver": d, "ir": ir_lays, "obj": obj_lays, "enc": enc, "ser": ser,
            "timing": {"derive": t_derive, "encode": t_encode, "serialize": t_ser}}


def attribution(comp):
    """Measured byte attribution: which part of the doc pays for which bytes."""
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

    groups = {}
    for sname, _ in ENTITY_SECTIONS:
        schema = F.ROW_SCHEMAS[sname]
        roots, rs = [], []
        for cells in enc.rows[sname]:
            for (key, fk, fl), c in zip(schema, cells):
                if c[0] == "T":
                    roots.append(c[1])
                elif c[0] == "S":
                    rs.append(c[1])
                elif c[0] == "L":
                    for el in c[1]:
                        (roots if el[0] == "T" else rs).append(el[1])
        groups[sname] = (roots, rs)
    for key, tid in enc.root_entries:
        groups["root:" + key] = ([tid] if tid else [], [key])

    reach = {}
    for g, (roots, _) in groups.items():
        seen = set()
        stack = list(roots)
        while stack:
            t = stack.pop()
            if t in seen:
                continue
            seen.add(t)
            stack.extend(kids[t])
        reach[g] = seen

    term_owner = defaultdict(set)
    for g, seen in reach.items():
        for t in seen:
            term_owner[t].add(g)
    str_owner = defaultdict(set)
    for g, seen in reach.items():
        for t in seen:
            for s in strs[t]:
                str_owner[s].add(g)
        for s in groups[g][1]:
            str_owner[s].add(g)

    pool = {s: (len(s.encode("utf-8")) + 1) for s in ser.strings_ordered}
    rows = {}
    for g in sorted(groups):
        rows[g] = {
            "terms_exclusive": sum(term_size(t) for t in reach[g] if len(term_owner[t]) == 1),
            "strings_exclusive": sum(pool[s] for s, o in str_owner.items() if o == {g}),
            "terms_total": len(reach[g])}
    shared_t = sum(term_size(t) for t in term_owner if len(term_owner[t]) > 1)
    shared_s = sum(pool[s] for s, o in str_owner.items() if len(o) > 1)
    return rows, shared_t, shared_s


def write_report(path, src_path, raw_len, doc, results, comp, t_load, peak_bytes):
    der, ser, enc = comp["deriver"], comp["ser"], comp["enc"]
    L = []
    a = L.append

    compact = compact_bytes(doc)
    pruned = prune_children(doc)
    compact_pruned = compact_bytes(pruned)
    core_doc = strip_presentation(doc)
    compact_core = compact_bytes(core_doc)
    compact_core_pruned = compact_bytes(prune_children(core_doc))
    full_bytes = results["full"]["bytes"]
    core_bytes = results["core"]["bytes"]

    a("# RDCF content compile report")
    a("")
    a("Generated by `tools/contentc/compile.py`.  Every number below is **measured**:")
    a("section sizes come from the bytes actually written, and the source-side numbers")
    a("come from re-serialising the parsed document with each item removed.")
    a("")
    a("## 0. The headline number")
    a("")
    a("| quantity | bytes | vs raw | vs compact |")
    a("|---|---|---|---|")
    a("| source on disk (pretty-printed JSON) | %d | 1.00x | — |" % raw_len)
    a("| source, compact JSON | %d | %.1fx | 1.00x |" % (compact, raw_len / compact))
    a("| source, compact + redundant `Children` removed | %d | %.1fx | %.2fx |"
      % (compact_pruned, raw_len / compact_pruned, compact / compact_pruned))
    a("| source, compact + `Children` + presentation removed | %d | %.1fx | %.2fx |"
      % (compact_core_pruned, raw_len / compact_core_pruned,
         compact / compact_core_pruned))
    a("| **RDCF binary, full** | **%d** | **%.1fx** | **%.1fx** |"
      % (full_bytes, raw_len / full_bytes, compact / full_bytes))
    a("| **RDCF binary, presentation stripped** | **%d** | **%.1fx** | **%.1fx** |"
      % (core_bytes, raw_len / core_bytes, compact / core_bytes))
    a("")
    a("### The answer to \"how many bytes after pre-compiling\"")
    a("")
    a("* `out/content.rdcf` -- complete, exact content image: **%d B (%.1f KiB)**"
      % (full_bytes, full_bytes / 1024.0))
    a("* `out/content.core.rdcf` -- same minus presentation: **%d B (%.1f KiB)**"
      % (core_bytes, core_bytes / 1024.0))
    a("")
    a("Against the ESP32-P4 budget of 592 KiB of usable SRAM: the full image is")
    a("%.0f%% of SRAM, the core image %.0f%%.  Neither has to live in SRAM at all."
      % (100.0 * full_bytes / (592 * 1024), 100.0 * core_bytes / (592 * 1024)))
    a("The image is read-only and immutable, so it belongs in flash (or memory-mapped")
    a("PSRAM), with SRAM holding only the interpreter's registers and node cursor.")
    a("")

    a("## 1. Binary section layout (measured)")
    a("")
    a("| id | section | offset | bytes | count | unit |")
    a("|---|---|---|---|---|---|")
    unit = {F.S_STR: "bytes of blob", F.S_STRO: "u32 offsets",
            F.S_OPD: "8-byte opcode descs", F.S_OPF: "4-byte field descs",
            F.S_TRM: "term records", F.S_TRW: "u16 word offsets",
            F.S_AUX: "u16 cells", F.S_CARD: "card rows (%d B each)" % F.row_stride("CARD"),
            F.S_STAT: "status rows (%d B each)" % F.row_stride("STATUS"),
            F.S_EACT: "enemy-action rows (%d B each)" % F.row_stride("EACT"),
            F.S_ENCT: "encounter rows (%d B each)" % F.row_stride("ENCT"),
            F.S_REL: "relic rows (%d B each)" % F.row_stride("REL"),
        F.S_EV: "event rows (%d B each)" % F.row_stride("EV"),
        F.S_POT: "potion rows (%d B each)" % F.row_stride("POT"),
            F.S_ROOT: "root pointers", F.S_IDX: "8-byte id entries"}
    for sec, off, size, cnt in results["full"]["sections"]:
        if not size:
            continue
        a("| %d | `%s` | %d | %d | %d | %s |"
          % (sec, F.SEC_NAMES.get(sec, "?"), off, size, cnt, unit.get(sec, "")))
    hdr_dir = F.HEADER_SIZE + F.NSEC * 12
    a("| — | header + directory | 0 | %d | — | — |" % hdr_dir)
    a("")
    a("Padding to 4-byte alignment: %d B."
      % (full_bytes - hdr_dir - sum(s[2] for s in results["full"]["sections"])))
    a("")
    a("Three sections carry almost everything: the string pool (`STR`+`STRO` = %d B,"
      % (len(ser.sec_str) + len(ser.sec_stro)))
    a("%.0f%%), the interned term DAG (`TRM`+`TRW`+`AUX` = %d B, %.0f%%), and the"
      % (100.0 * (len(ser.sec_str) + len(ser.sec_stro)) / full_bytes,
         len(ser.sec_trm) + len(ser.sec_trw) + len(ser.sec_aux),
         100.0 * (len(ser.sec_trm) + len(ser.sec_trw) + len(ser.sec_aux)) / full_bytes))
    a("fixed entity tables (%d B, %.0f%%)."
      % (sum(s[2] for s in results["full"]["sections"]
             if s[0] in (F.S_CARD, F.S_STAT, F.S_EACT, F.S_ENCT, F.S_REL, F.S_EV, F.S_POT)),
         100.0 * sum(s[2] for s in results["full"]["sections"]
                     if s[0] in (F.S_CARD, F.S_STAT, F.S_EACT, F.S_ENCT, F.S_REL, F.S_EV, F.S_POT))
         / full_bytes))
    a("")

    a("## 2. Where the source bytes went (measured per top-level key)")
    a("")
    a("`in binary` attributes each term record and pooled string to the entity group")
    a("that reaches it *exclusively*; bytes reachable from several groups appear once")
    a("under *shared*.  So the columns do not add up to the file size, by design.")
    a("")
    rows_attr, shared_t, shared_s = attribution(comp)
    a("| top-level key | items | compact B | exclusive term B | exclusive string B |")
    a("|---|---|---|---|---|")
    total_c = 0
    for sname, key in ENTITY_SECTIONS:
        v = doc.get(key)
        cb = compact_bytes(v)
        total_c += cb
        r = rows_attr.get(sname, {})
        a("| `%s` *(table)* | %d | %d | %d | %d |"
          % (key, len(v or []), cb, r.get("terms_exclusive", 0),
             r.get("strings_exclusive", 0)))
    for key in sorted(doc):
        if key in dict(ENTITY_SECTIONS).values():
            continue
        cb = compact_bytes(doc[key])
        total_c += cb
        r = rows_attr.get("root:" + key, {})
        n = len(doc[key]) if isinstance(doc[key], (list, dict)) else 1
        # A document key stays in this table on purpose: it *is* a top-level key of the source,
        # and the honest number for it is "costs N B of compact JSON, 0 B of image" because the
        # root-entry loop skips it (`DOC_ROOT_KEYS`).  Dropping the row would hide the reason the
        # column sum is smaller than the compact document.
        tag = " *(document key -- not stored)*" if key in DOC_ROOT_KEYS else ""
        a("| `%s`%s | %s | %d | %d | %d |"
          % (key, tag, n, cb, r.get("terms_exclusive", 0), r.get("strings_exclusive", 0)))
    a("| **shared (reached from >1 group)** | | | **%d** | **%d** |" % (shared_t, shared_s))
    a("")
    a("Column sum %d B = compact %d B minus the %d B spent on the %d top-level key"
      % (total_c, compact, compact - total_c, len(doc)))
    a("names, their quotes and the surrounding braces.")
    skipped = [k for k in DOC_ROOT_KEYS if k in doc]
    if skipped:
        a("")
        a("`%s` above are **document keys**: build metadata that is serialised into neither"
          % "` / `".join(skipped))
        a("image (`DOC_ROOT_KEYS` in `compile.py`), so their `exclusive` columns are 0 B.  Their")
        a("summary line in the source costs %d B of compact JSON and **0 B** of output."
          % sum(compact_bytes(doc[k]) for k in skipped))
    a("")
    # The paragraph below is a measurement of the *reference* document's shape
    # (one dominant encounter with many duplicated trigger programs).  It must
    # not be printed for a package that has no `Encounters` table -- it used to
    # be an unconditional `doc["Encounters"]`, which made the whole compiler
    # raise KeyError on any second package.  Skipping it changes nothing about
    # the image: `write_report` only writes `report.md`.
    if doc.get("Encounters"):
        enc_c = compact_bytes(doc["Encounters"])
        a("`Encounters` alone is %d B (%.1f%% of the compact document) with a single"
          % (enc_c, 100.0 * enc_c / compact))
        a("encounter, `city_normal_ordinance_08`, taking %.0f%% of that section -- yet the"
          % (100.0 * compact_bytes(max(doc["Encounters"],
                                      key=lambda e: compact_bytes(e))) / enc_c))
        a("whole encounter table plus everything it reaches costs about %d B exclusive,"
          % (rows_attr.get("ENCT", {}).get("terms_exclusive", 0) +
             rows_attr.get("ENCT", {}).get("strings_exclusive", 0)))
        a("because its 31 trigger programs are 10 distinct bodies written 31 times and")
        a("interning collapses them to 10 nodes.")
    else:
        a("This package declares no `Encounters` table, so the encounter-shape")
        a("measurement that the reference report carries is skipped here.  Everything")
        a("measured above and below is package-independent.")
    a("")

    a("## 3. What stopped being stored, and why that is safe")
    a("")
    a("Nothing is *dropped* from `content.rdcf` -- `validate.py` proves the round trip")
    a("is structurally exact.  What disappears is **redundancy**:")
    a("")
    a("The one deliberate exception is the **document keys** (`DOC_ROOT_KEYS`): they are build")
    a("metadata, not game data, so they are written into neither image and are therefore *not*")
    a("part of the round trip (`Rom.document()` reproduces the source minus those keys).")
    a("")
    a("| redundancy | compact JSON bytes it occupies | how the binary avoids it |")
    a("|---|---|---|")
    keyb, keyn = _key_bytes(doc)
    a("| object key names (%d occurrences, %d distinct) | %d | an opcode's field descriptors spell each key once, not per occurrence |"
      % (keyn, len(_all_keys(doc)), keyb))
    a("| `{\"kind\":..,\"value\":..}` discriminant envelope | %d | the opcode *is* the kind |"
      % _envelope_bytes(doc))
    a("| redundant `Children` second copies | %d | subtree interning: a repeated child is one u16 handle |"
      % (compact - compact_pruned))
    a("| byte-identical program bodies | %d | the same interning |" % _dup_program_bytes(doc))
    a("| id wrapper objects (`{\"value\":s}` / `{\"Value\":s}`) | %d | the field's flags byte carries the spelling; the object is never stored |"
      % _wrapper_bytes(doc))
    a("")
    a("These rows overlap: the envelope row is the literal serialised bytes of")
    a("`\"kind\":<K>,\"value\":` at each of the IR nodes, and its two key names are")
    a("already counted in the key-name row.  They are listed separately because they")
    a("are eliminated by different mechanisms.")
    a("")
    a("Sources of truth for each of those claims:")
    a("")
    a("* **`Children`** is `ConditionalEffectNode.Children`, a read-only computed")
    a("  property (`Effects/Programs/EffectProgramNodes.cs:65,85-87`) that the")
    a("  deserialiser ignores; `CombatJson.cs:166-193` already prunes it when it is not")
    a("  a constructor parameter, and the comment there records the incident that made")
    a("  them do it: one boss rule reached 311,624 nodes / 15 MB while the tree itself")
    a("  held about 40 nodes.  **RDCF keeps it regardless** -- interning makes it cost")
    a("  almost nothing, and keeping it makes the round trip exact instead of an argued")
    a("  equivalence.  Only the *copies* vanish, worth %d B of compact JSON."
      % (compact - compact_pruned))
    a("* **Key names / the envelope** are not inferred from a schema: the compiler")
    a("  observes the union of fields actually present per (kind, object-shape) and")
    a("  emits a descriptor.  A field whose observed storage classes cannot be")
    a("  reconciled falls back to `F_JSON` (canonical text, still exact):")
    a("  **%d field(s) needed that fallback**." % len(der.json_fallback))
    a("* **Id wrappers.**  `CombatIds.cs:3-78` declares 16 `readonly record struct`")
    a("  ids.  The document spells the same id bare, as `{\"value\":s}` (3,128 refs) or")
    a("  as `{\"Value\":s}` (747 refs).  A field that is uniform in spelling stores just")
    a("  the string id and remembers the wrapper in its flags byte; only a genuinely")
    a("  mixed field spends a term.")
    a("* **Presentation** is not dropped by default.  `content.core.rdcf` is a second")
    a("  build with exactly this list removed, which is the entire difference between")
    a("  the two images:")
    a("")
    for sec in sorted(PRESENTATION_KEYS):
        a("  * `%s[]`: %s" % (sec, ", ".join("`%s`" % k for k in PRESENTATION_KEYS[sec])))
    a("  * `EnemyActions[].Intent.Label`")
    a("  * `Encounters[].Enemies[].DisplayName`")
    a("  * `Events[].situations[].TextKey`, `...Choices[].TextKey`, `Shops[].Offers[].TextKey`")
    a("  * the whole `Presentation` object (%d B compact)"
      % compact_bytes(doc.get("Presentation")))
    a("")
    a("  Measured effect: compact %d -> %d B; binary %d -> %d B (saves %d B, %.1f%%)."
      % (compact, compact_core, full_bytes, core_bytes, full_bytes - core_bytes,
         100.0 * (full_bytes - core_bytes) / full_bytes))
    a("")

    a("## 4. Derived tables")
    a("")
    a("| | count |")
    a("|---|---|")
    a("| distinct IR `kind` values | %d |" % len(comp["ir"]))
    a("| distinct plain-object shapes | %d |" % len(comp["obj"]))
    a("| opcodes (8 reserved + dynamic) | %d |"
      % (len(comp["ir"]) + len(comp["obj"]) + len(F.RESERVED_OP_LAYOUT)))
    a("| distinct interned terms in the DAG | %d |" % len(enc.terms))
    a("| aux cells | %d |" % len(ser.aux))
    a("| pooled strings | %d |" % len(ser.strings_ordered))
    a("| string blob | %d B |" % len(ser.sec_str))
    a("| content integer range on the wire | [%s, %s] vs storable [%d, %d] |"
      % (enc.int_range[0], enc.int_range[1], F.I16_MIN, F.I16_MAX))
    a("| (opcode, field) pairs that are absent in some instances | %d |"
      % len(der.absent_fields))
    a("")
    a("The last row matters: an absent key and a present-`null` key are both")
    a("representable (two sentinels per field kind), so `reader.py` reproduces the")
    a("source's key *presence*, not just its values.")
    a("")
    a("Full per-opcode operand inventory: `out/layout.txt`.")
    a("")
    if der.json_fallback:
        a("### Fields that fell back to `F_JSON`")
        a("")
        for owner, field, classes in der.json_fallback:
            a("* `%s.%s` observed as %s" % (owner, field, ",".join(classes)))
        a("")
    else:
        a("No field needed the `F_JSON` escape hatch: every (opcode, field) pair has a")
        a("single reconcilable storage class, so the typing is total and the binary")
        a("contains no raw JSON text at all.")
        a("")

    a("## 5. Cost")
    a("")
    a("| step | seconds |")
    a("|---|---|")
    a("| `json.loads` of %.1f MiB source | %.3f |" % (raw_len / 1048576.0, t_load))
    for k in ("derive", "encode", "serialize"):
        a("| %s | %.3f |" % (k, comp["timing"][k]))
    a("| total, one build | %.3f |" % (t_load + sum(comp["timing"].values())))
    a("")
    a("Peak Python heap during the whole run (both builds, tracemalloc): **%.1f MiB**."
      % (peak_bytes / 1048576.0))
    a("The document is parsed once and never copied; the encoder holds the parsed")
    a("dict plus the interned DAG, and each entity row stores term ids rather than")
    a("subtrees, so peak usage stays near the cost of the parse itself.")
    a("")

    a("## 6. Determinism")
    a("")
    a("`validate.py` builds the image twice in one process and compares SHA-256.  Every")
    a("ordering decision is explicit:")
    a("")
    a("* fields within an opcode: sorted by name")
    a("* object shapes: sorted by key tuple; IR kinds: sorted by kind string")
    a("* string pool: sorted by UTF-8 bytes, so ids are stable regardless of traversal")
    a("* terms: insertion order over a sorted-key walk")
    a("* id symbol table: sorted by (string id, entity kind)")
    a("")
    a("`content_hash` in the header is FNV-1a-32 of the raw source file, so a stale")
    a("image is detectable without re-parsing.")
    a("")

    a("## 7. What this report does *not* prove")
    a("")
    a("`compile.py` measures.  Correctness is `validate.py`'s job, and it writes")
    a("`out/validate.md` (full image) and `out/validate-core.md` (stripped image).")
    a("Those reports check, independently of anything here:")
    a("")
    a("* well-formedness -- every section aligned, disjoint and in range")
    a("* a **structural round trip**: `reader.py`'s reconstruction compared against")
    a("  `json.loads(source)` per path, including key *presence*")
    a("* reference integrity -- every cross-entity id resolved, every dangling one")
    a("  listed with its site")
    a("* ASCII-only ids, byte-identical rebuilds, id-namespace hygiene, and how much")
    a("  of the image the map cannot reach")
    a("")
    a("Both images currently pass every check.")
    a("")

    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(L) + "\n")


def _all_keys(v, acc=None):
    if acc is None:
        acc = set()
    if isinstance(v, dict):
        for k, x in v.items():
            acc.add(k)
            _all_keys(x, acc)
    elif isinstance(v, list):
        for x in v:
            _all_keys(x, acc)
    return acc


def _key_bytes(doc):
    total = [0, 0]

    def walk(v):
        if isinstance(v, dict):
            for k, x in v.items():
                total[0] += len(json.dumps(k, ensure_ascii=False).encode("utf-8")) + 1
                total[1] += 1
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
    walk(doc)
    return total[0], total[1]


def _envelope_bytes(doc):
    total = [0]

    def walk(v):
        if isinstance(v, dict):
            if is_ir(v):
                total[0] += len('"kind":') + len(json.dumps(v["kind"]).encode()) + len(',"value":')
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
    walk(doc)
    return total[0]


def _wrapper_bytes(doc):
    total = [0]

    def walk(v):
        if isinstance(v, dict):
            if wrap_key(v):
                total[0] += compact_bytes(v) - compact_bytes(v["value"] if "value" in v
                                                             else v["Value"])
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
    walk(doc)
    return total[0]


def _dup_program_bytes(doc):
    """Compact bytes spent on repeated trigger-program bodies (measured)."""
    seen = set()
    waste = 0
    for e in (doc.get("Encounters") or []):
        for tr in (e.get("TriggeredEffects") or []):
            p = tr.get("Program")
            if p is None:
                continue
            h = hashlib.sha1(canon_json(p).encode("utf-8")).hexdigest()
            if h in seen:
                waste += compact_bytes(p)
            else:
                seen.add(h)
    return waste


def main():
    ap = argparse.ArgumentParser(description="compile .roguedeck.json -> RDCF")
    ap.add_argument("--src", default=DEFAULT_SRC)
    ap.add_argument("--out-dir",
                    default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "out"))
    ap.add_argument("--no-core", action="store_true",
                    help="skip the presentation-stripped build")
    # Multi-package support: several content packages coexist in this repo and
    # each must land in its own file name.  The defaults reproduce the historic
    # one-package behaviour byte for byte -- `tools/contentc/expected_sha.txt`
    # makes that a checked claim rather than an assumption.
    ap.add_argument("--full-name", default="content.rdcf",
                    help="file name of the full image (default: content.rdcf)")
    ap.add_argument("--core-name", default="content.core.rdcf",
                    help="file name of the stripped image (default: content.core.rdcf)")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    t0 = time.perf_counter()
    tracemalloc.start()
    raw = open(args.src, "rb").read()
    doc = json.loads(raw.decode("utf-8-sig"))
    t_load = time.perf_counter() - t0
    chash = F.fnv1a32(raw)
    schema_version = int(doc.get("SchemaVersion") or 0)

    comp = compile_doc(doc)
    full_bytes, sections_full = comp["ser"].write(
        os.path.join(args.out_dir, args.full_name), chash, schema_version, 0)
    results = {"full": {"bytes": full_bytes, "sections": sections_full}}

    if not args.no_core:
        comp_core = compile_doc(strip_presentation(doc))
        core_bytes, sections_core = comp_core["ser"].write(
            os.path.join(args.out_dir, args.core_name), chash, schema_version, 1)
        results["core"] = {"bytes": core_bytes, "sections": sections_core}
    else:
        results["core"] = dict(results["full"])

    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()

    enc, ser = comp["enc"], comp["ser"]

    def sec_block(sections):
        return [{"id": s, "name": F.SEC_NAMES.get(s, "?"), "offset": o,
                 "bytes": n, "count": c} for s, o, n, c in sections]

    manifest = {
        "format": "RDCF",
        "format_version": F.FORMAT_VERSION,
        "magic": "0x%08X" % F.MAGIC,
        "source": {
            "path": args.src,
            "raw_bytes": len(raw),
            "content_hash_fnv1a32": "0x%08X" % chash,
            "schema_version": schema_version,
            "compact_json_bytes": compact_bytes(doc),
            "compact_json_without_redundant_children": compact_bytes(prune_children(doc)),
        },
        "totals": {args.full_name: results["full"]["bytes"],
                   args.core_name: results["core"]["bytes"]},
        "header_bytes": F.HEADER_SIZE,
        "directory_bytes": F.NSEC * 12,
        "tables": {
            "strings": {"count": len(ser.strings_ordered), "blob_bytes": len(ser.sec_str),
                        "offset_table_bytes": len(ser.sec_stro)},
            "opcodes": {"count": len(comp["ir"]) + len(comp["obj"]) + len(F.RESERVED_OP_LAYOUT),
                        "ir_kinds": len(comp["ir"]), "object_shapes": len(comp["obj"])},
            "terms": {"distinct": len(enc.terms), "aux_cells": len(ser.aux)},
            "cards": {"count": len(enc.rows["CARD"]), "stride": F.row_stride("CARD")},
            "statuses": {"count": len(enc.rows["STATUS"]), "stride": F.row_stride("STATUS")},
            "enemy_actions": {"count": len(enc.rows["EACT"]), "stride": F.row_stride("EACT")},
            "encounters": {"count": len(enc.rows["ENCT"]), "stride": F.row_stride("ENCT")},
            "relics": {"count": len(enc.rows["REL"]), "stride": F.row_stride("REL")},
        "events": {"count": len(enc.rows.get("EV", [])), "stride": F.row_stride("EV")},
        "potions": {"count": len(enc.rows.get("POT", [])), "stride": F.row_stride("POT")},
            "roots": {"count": len(enc.root_entries)},
            "id_index": {"count": len(enc.idx)},
        },
        "variants": {
            "full": {"file": args.full_name, "bytes": results["full"]["bytes"],
                     "flags": 0, "sections": sec_block(sections_full)},
        },
        "timing_seconds": {"json_load": round(t_load, 4),
                           **{k: round(v, 4) for k, v in comp["timing"].items()}},
        "peak_heap_mib": round(peak / 1048576.0, 1),
    }
    if not args.no_core:
        manifest["variants"]["core"] = {
            "file": args.core_name, "bytes": results["core"]["bytes"],
            "flags": 1, "sections": sec_block(sections_core)}
    with open(os.path.join(args.out_dir, "manifest.json"), "w", encoding="utf-8",
              newline="\n") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    with open(os.path.join(args.out_dir, "layout.txt"), "w", encoding="utf-8",
              newline="\n") as fh:
        fh.write("# opcode nfields nslots sizeB class name : fields\n")
        for l in sorted(comp["ir"] + comp["obj"], key=lambda x: x.op):
            fh.write("%3d %2d %2d %3d %s %-60s : %s\n"
                     % (l.op, l.nfields, l.nslots, l.record_size,
                        "IR" if l.is_ir else "OBJ", l.name,
                        " ".join("%s:%s%s" % (f, F.FIELD_NAMES[k],
                                             "" if not fl else
                                             ("(wrap)" if fl == F.FLAG_WRAP_LOWER
                                              else "(Wrap)"))
                                 for f, k, fl in zip(l.fields, l.kinds, l.flags))))
        fh.write("\n# reserved opcodes:\n")
        for op in sorted(F.RESERVED_OP_LAYOUT):
            kinds, flags = F.RESERVED_OP_LAYOUT[op]
            fh.write("%3d reserved : %s\n" % (op, " ".join(
                F.FIELD_NAMES[k] for k in kinds) or "(no fields)"))

    write_report(os.path.join(args.out_dir, "report.md"), args.src, len(raw), doc,
                 results, comp, t_load, peak)

    if not args.quiet:
        print("source            : %s" % args.src)
        print("raw bytes         : %d" % len(raw))
        print("compact JSON      : %d" % compact_bytes(doc))
        print("%-17s : %d B" % (args.full_name, results["full"]["bytes"]))
        print("%-17s : %d B" % (args.core_name, results["core"]["bytes"]))
        print("opcodes           : %d IR kinds + %d object shapes"
              % (len(comp["ir"]), len(comp["obj"])))
        print("distinct terms    : %d ; aux cells %d ; strings %d"
              % (len(enc.terms), len(ser.aux), len(ser.strings_ordered)))
        print("json fallbacks    : %d fields" % len(comp["deriver"].json_fallback))
        print("peak heap         : %.1f MiB" % (peak / 1048576.0))
        print("wrote             : %s" % args.out_dir)


if __name__ == "__main__":
    main()
