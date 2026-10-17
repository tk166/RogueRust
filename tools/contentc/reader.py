#!/usr/bin/env python3
"""reader.py -- reference reader for RDCF content images (Python side).

Pure stdlib.  This is the *specification by construction* of the format: it
decodes an image back into the same Python structure that `json.loads` would
produce from the source document, and `validate.py` compares the two.

    python reader.py <image.rdcf> [--dump-json FILE] [--stats]
                                   [--opcodes] [--term N] [--string N]
                                   [--find <id>] [--entity <kind> <index>]
                                   [--table <NAME>]

As the kernel-side contract:
  * `Rom.header` / `Rom.sections`  -- the directory
  * `Rom.opcode(op)`               -- (name, nfields, opclass, [(field, kind, flags)])
  * `Rom.term_slots(tid)`          -- raw u16 slots for a term (no decoding)
  * `Rom.aux` / `Rom.string_at(sid)`
  * `Rom.entity(kind, index)`      -- one decoded row
  * `Rom.lookup(id_string)`        -- (entity_kind, index) or None, via SEC_IDX
`term_slots` is what a C interpreter would use: it never builds Python objects,
it just points at the record.
"""

import argparse
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import rdcfmt as F  # noqa: E402


class Rom(object):
    def __init__(self, buf):
        self.buf = buf
        self.header, self.dir = F.unpack_dir(buf)
        if self.header["total_size"] != len(buf):
            raise ValueError("header says %d bytes, file is %d"
                             % (self.header["total_size"], len(buf)))
        self.sections = {}
        for sec, (off, size, count) in self.dir.items():
            self.sections[sec] = buf[off:off + size] if size else b""
        self._load_strings()
        self._load_opcodes()
        self._load_terms()
        self._load_aux()
        self._load_roots()
        self._load_idx()

    # ------------------------------------------------------------- loading
    def _load_strings(self):
        blob = self.sections[F.S_STR]
        stro = self.sections[F.S_STRO]
        self.n_strings = len(stro) // 4 - 1
        self.str_off = struct.unpack_from("<%dI" % (self.n_strings + 1), stro, 0) \
            if self.n_strings >= 0 else (0,)
        self.str_blob = blob

    def string_at(self, sid):
        """sid 0 is the empty string; 1..n index the pool."""
        if sid == 0:
            return ""
        if sid > self.n_strings:
            raise ValueError("string id %d out of range" % sid)
        a = self.str_off[sid - 1]
        b = self.str_off[sid]
        return self.str_blob[a:b - 1 if b > a else a].decode("utf-8")

    def _load_opcodes(self):
        opd = self.sections[F.S_OPD]
        opf = self.sections[F.S_OPF]
        n = len(opd) // 8
        self.opcodes = []
        for i in range(n):
            off, name, nfields, opclass = struct.unpack_from("<IHBB", opd, 8 * i)
            fields = []
            for j in range(nfields):
                ns, fk, fl = struct.unpack_from("<HBB", opf, off + 4 * j)
                fields.append((self.string_at(ns) if ns else "", fk, fl))
            self.opcodes.append({"name": self.string_at(name) if name else "",
                                 "opclass": opclass, "fields": fields,
                                 "nfields": nfields})
        for op in range(n):
            d = self.opcodes[op]
            d["nslots"] = sum(F.FIELD_SLOTS[fk] for _, fk, _ in d["fields"])

    def _load_terms(self):
        self.sec_trm = self.sections[F.S_TRM]
        trw = self.sections[F.S_TRW]
        self.n_terms = len(trw) // 2
        self.term_off = struct.unpack_from("<%dH" % self.n_terms, trw, 0) \
            if self.n_terms else ()

    def term_slots(self, tid):
        """(op, [u16 slots]) for a term -- no decoding, the raw record."""
        if tid >= self.n_terms:
            raise ValueError("term id %d out of range" % tid)
        base = self.term_off[tid] * 4
        op = struct.unpack_from("<H", self.sec_trm, base)[0]
        n = self.opcodes[op]["nslots"]
        if n:
            return op, list(struct.unpack_from("<%dH" % n, self.sec_trm, base + 2))
        return op, []

    def _load_aux(self):
        b = self.sections[F.S_AUX]
        self.n_aux = len(b) // 2
        self.aux = list(struct.unpack_from("<%dH" % self.n_aux, b, 0)) if self.n_aux else []

    def _load_roots(self):
        b = self.sections[F.S_ROOT]
        self.roots = {}
        for i in range(len(b) // 4):
            k, t = struct.unpack_from("<HH", b, 4 * i)
            self.roots[self.string_at(k)] = t

    def _load_idx(self):
        b = self.sections[F.S_IDX]
        self.idx = []
        self.id_map = {}
        for i in range(len(b) // 8):
            sid, ek, fl, index, rsvd = struct.unpack_from("<HBBHH", b, 8 * i)
            s = self.string_at(sid)
            self.idx.append((s, ek, index))
            self.id_map.setdefault(s, (ek, index))
        self.rows_cache = {}

    # ------------------------------------------------------------ decoding
    def _field_values(self, op, slots):
        """Decode slots into a list of (name, kind, flags, value_or_OMIT)."""
        d = self.opcodes[op]
        out = []
        i = 0
        for name, fk, fl in d["fields"]:
            w = F.FIELD_SLOTS[fk]
            out.append((name, fk, fl, slots[i:i + w]))
            i += w
        return out

    def _wrap(self, s, fl):
        if fl == F.FLAG_WRAP_LOWER:
            return {"value": s}
        if fl == F.FLAG_WRAP_UPPER:
            return {"Value": s}
        return s

    def _scalar(self, fk, fl, slots):
        """Returns (present, value).  present=False means "key absent"."""
        if fk in (F.F_TERMLIST, F.F_STRLIST):
            start, count = slots
            if count == F.LIST_ABSENT:
                return False, None
            if count == F.LIST_NULL:
                return True, None
            if fk == F.F_STRLIST:
                return True, [self._wrap(self.string_at(self.aux[start + j]), fl)
                              for j in range(count)]
            return True, [self.term(self.aux[start + j]) for j in range(count)]
        v = slots[0]
        if fk == F.F_STR or fk == F.F_JSON:
            if v == F.ABSENT16:
                return False, None
            if v == F.NULL16:
                return True, None
            if fk == F.F_JSON:
                return True, json.loads(self.string_at(v))
            return True, self._wrap(self.string_at(v), fl)
        if fk == F.F_INT:
            if v == F.ABSENT_INT:
                return False, None
            if v == F.NULL_INT:
                return True, None
            return True, struct.unpack("<h", struct.pack("<H", v))[0]
        if fk == F.F_BOOL:
            if v == F.BOOL_ABSENT:
                return False, None
            if v == F.BOOL_NULL:
                return True, None
            return True, (v == F.BOOL_TRUE)
        if fk == F.F_TERM:
            if v == F.ABSENT16:
                return False, None
            if v == F.NULL16:
                return True, None
            return True, self.term(v)
        raise KeyError(fk)

    def term(self, tid):
        """Decode a term into plain Python data (the JSON-equivalent shape)."""
        op, slots = self.term_slots(tid)
        if op == F.OP_NULL:
            return None
        if op == F.OP_STR:
            return self.string_at(slots[0])
        if op == F.OP_INT:
            return struct.unpack("<h", struct.pack("<H", slots[0]))[0]
        if op == F.OP_BOOL:
            return slots[0] == F.BOOL_TRUE
        if op == F.OP_WRAP_LOWER:
            return {"value": self.string_at(slots[0])}
        if op == F.OP_WRAP_UPPER:
            return {"Value": self.string_at(slots[0])}
        if op == F.OP_JSON:
            return json.loads(self.string_at(slots[0]))
        if op == F.OP_ARR:
            return self._scalar(F.F_TERMLIST, 0, slots)[1]
        d = self.opcodes[op]
        body = {}
        for name, fk, fl, sl in self._field_values(op, slots):
            present, val = self._scalar(fk, fl, sl)
            if present:
                body[name] = val
        if d["opclass"] == F.OPCLASS_IR:
            return {"kind": d["name"], "value": body}
        return body                       # a plain-object shape

    # ------------------------------------------------------------- entities
    def _rows(self, sname):
        if sname in self.rows_cache:
            return self.rows_cache[sname]
        sec = {"CARD": F.S_CARD, "STATUS": F.S_STAT, "EACT": F.S_EACT,
               "ENCT": F.S_ENCT, "REL": F.S_REL}[sname]
        blob = self.sections[sec]
        schema = F.ROW_SCHEMAS[sname]
        stride = F.row_stride(sname)
        rows = []
        for off in range(0, len(blob), stride):
            rec = {}
            slots = self._row_slots(blob, off, schema)
            for (name, fk, fl), sl in zip(schema, slots):
                if name == "extra":
                    present, val = self._scalar(fk, fl, sl)
                    if present and isinstance(val, dict):
                        for k, v in val.items():
                            rec[k] = v
                    continue
                present, val = self._scalar(fk, fl, sl)
                if present:
                    rec[name] = val
            rows.append(rec)
        self.rows_cache[sname] = rows
        return rows

    def _row_slots(self, blob, off, schema):
        out = []
        i = off
        for name, fk, fl in schema:
            w = F.FIELD_SLOTS[fk]
            vals = struct.unpack_from("<%dH" % w, blob, i)
            out.append(list(vals))
            i += 2 * w
        return out

    def entity(self, sname, index):
        return self._rows(sname)[index]

    def lookup(self, id_string):
        return self.id_map.get(id_string)

    # ------------------------------------------------------------- document
    def document(self):
        doc = {}
        for name, sname in (("Cards", "CARD"), ("Statuses", "STATUS"),
                            ("EnemyActions", "EACT"), ("Encounters", "ENCT"),
                            ("Relics", "REL")):
            doc[name] = self._rows(sname)
        for key, tid in self.roots.items():
            doc[key] = self.term(tid)
        return doc

    # ---------------------------------------------------------------- stats
    def stats(self):
        return {
            "format_version": self.header["version"],
            "flags": self.header["flags"],
            "total_size": self.header["total_size"],
            "schema_version": self.header["schema_version"],
            "content_hash": "0x%08X" % self.header["content_hash"],
            "strings": self.n_strings,
            "opcodes": len(self.opcodes),
            "terms": self.n_terms,
            "aux_cells": self.n_aux,
            "roots": len(self.roots),
            "id_index": len(self.idx),
            "cards": len(self._rows("CARD")),
            "statuses": len(self._rows("STATUS")),
            "enemy_actions": len(self._rows("EACT")),
            "encounters": len(self._rows("ENCT")),
            "relics": len(self._rows("REL")),
        }


# ===========================================================================
#  CLI
# ===========================================================================

def main():
    ap = argparse.ArgumentParser(description="read an RDCF content image")
    ap.add_argument("image")
    ap.add_argument("--dump-json", metavar="FILE")
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--opcodes", action="store_true")
    ap.add_argument("--term", type=int)
    ap.add_argument("--string", type=int)
    ap.add_argument("--find")
    ap.add_argument("--entity", nargs=2, metavar=("TABLE", "INDEX"))
    ap.add_argument("--table", metavar="NAME",
                    choices=["CARD", "STATUS", "EACT", "ENCT", "REL"])
    args = ap.parse_args()

    rom = Rom(open(args.image, "rb").read())

    if args.dump_json:
        with open(args.dump_json, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(rom.document(), fh, ensure_ascii=False, indent=1)
        print("wrote %s" % args.dump_json)
        return

    if args.opcodes:
        print("%4s %-22s %-6s %6s %6s  fields" % ("op", "name", "class", "nf", "nslots"))
        for op, d in enumerate(rom.opcodes):
            if not d["fields"] and d["opclass"] == 0 and op >= F.OP_FIRST_DYNAMIC:
                continue
            print("%4d %-22s %-6s %6d %6d  %s"
                  % (op, d["name"] or "-",
                     "IR" if d["opclass"] == F.OPCLASS_IR else "gen",
                     d["nfields"], d["nslots"],
                     " ".join("%s:%s%s" % (n or "-", F.FIELD_NAMES[k],
                                           "" if not fl else
                                           "(w)" if fl == F.FLAG_WRAP_LOWER else "(W)")
                              for n, k, fl in d["fields"])))
        return

    if args.string is not None:
        print(repr(rom.string_at(args.string)))
        return

    if args.term is not None:
        op, slots = rom.term_slots(args.term)
        print("term %d: op=%d (%s) slots=%s"
              % (args.term, op, rom.opcodes[op]["name"], slots))
        s = json.dumps(rom.term(args.term), ensure_ascii=False)
        print(s[:4000] + ("..." if len(s) > 4000 else ""))
        return

    if args.find:
        hit = rom.lookup(args.find)
        if hit is None:
            print("NOT FOUND: %s" % args.find)
            sys.exit(2)
        print("%s -> %s[%d]" % (args.find, F.EK_NAMES.get(hit[0], hit[0]), hit[1]))
        return

    if args.entity:
        sname, index = args.entity[0].upper(), int(args.entity[1])
        print(json.dumps(rom.entity(sname, index), ensure_ascii=False, indent=1))
        return

    if args.table:
        for i, rec in enumerate(rom._rows(args.table)):
            print("[%d] %s" % (i, json.dumps(rec, ensure_ascii=False)[:200]))
        return

    st = rom.stats()
    print("image            : %s (%d B)" % (args.image, st["total_size"]))
    print("format version   : %d   flags=%d   schema_version=%d"
          % (st["format_version"], st["flags"], st["schema_version"]))
    print("content hash     : %s" % st["content_hash"])
    print("sections         :")
    for sec in F.SEC_ORDER:
        off, size, count = rom.dir[sec]
        if not size:
            continue
        print("  %-6s off=%-8d bytes=%-8d count=%d" % (F.SEC_NAMES[sec], off, size, count))
    print("strings          : %d (%d B blob)" % (st["strings"], len(rom.str_blob)))
    print("opcodes          : %d" % st["opcodes"])
    print("terms            : %d" % st["terms"])
    print("aux cells        : %d" % st["aux_cells"])
    print("id index         : %d" % st["id_index"])
    print("entities         : cards=%d statuses=%d enemy_actions=%d encounters=%d relics=%d"
          % (st["cards"], st["statuses"], st["enemy_actions"],
             st["encounters"], st["relics"]))
    print("roots            : %s" % ", ".join(sorted(rom.roots)))


if __name__ == "__main__":
    main()
