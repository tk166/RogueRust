"""rdcfmt.py -- RDCF (RogueDeck Content Format) v1: on-disk constants + tiny helpers.

This module holds *only* the frozen on-disk vocabulary shared by `compile.py`
(writer) and `reader.py` (reader).  It has no I/O beyond `struct`.

================================================================================
WHY A SEPARATE FORMAT AT ALL
================================================================================
The source document is 7.91 MiB of pretty-printed `System.Text.Json` (the engine
defaults to `WriteIndented = true`).  For an ESP32-P4 with 592 KiB of usable
SRAM we cannot ship JSON, and we cannot afford the parse.  RDCF is the offline
pre-compiled form: fixed-width entity tables, a deduplicated string pool, and a
**content-addressed** DAG of effect-program terms.

================================================================================
FILE LAYOUT
================================================================================
Little-endian throughout.  Every section starts on a 4-byte boundary.

  [0]  Header          32 B
  [32] Section dir     NSEC * 12 B   (u32 offset, u32 size, u32 count)
  [..] Section payloads, in section-id order, each 4-byte aligned.

Section ids (SEC_*):
   0 STR    string blob, NUL-terminated UTF-8, sorted by UTF-8 bytes
   1 STRO   u32[n_str+1] byte offsets into STR
   2 OPD    opcode descriptors, 8 B each
   3 OPF    per-field descriptors, 4 B each (referenced by OPD.field_off)
   4 TRM    term records (variable length, 4-byte aligned)
   5 TRW    u16[n_terms] word offset (byte_offset / 4) of each term record
   6 AUX    u16[] auxiliary slots (list bodies, referenced by term slots)
   7 CARD   card rows
   8 STAT   status rows
   9 EACT   enemy-action rows
  10 ENCT   encounter rows
  11 REL    relic rows
  12 ROOT   root pointer table: u32 { u16 key_str, u16 term_id }
  13 IDX    entity id symbol table: 8 B { u16 str_id, u8 ekind, u8 flags, u16 index, u16 rsvd }
  14..19    reserved

STRO is u32 rather than u16 because the blob is ~85 KiB; a firmware-side variant
that drops the presentation strings brings it under the u16 reach.

================================================================================
HEADER (32 B)
================================================================================
  u32 magic          'RDCF' as little-endian u32 == 0x46434452
  u16 version        FORMAT_VERSION
  u16 flags          bit0 = presentation stripped
  u32 total_size     bytes of the whole file
  u32 dir_off        == 32
  u16 nsec           == NSEC
  u16 schema_version the document's own `SchemaVersion`
  u32 content_hash   FNV-1a-32 of the *raw source JSON bytes*
  u32 reserved

================================================================================
OPCODE DESCRIPTOR (8 B, one per opcode)
================================================================================
  u32 field_off      byte offset into SEC_OPF
  u16 name_str       string id of the opcode's name (the IR `kind` string, or
                     "_obj" for a plain-object shape)
  u8  nfields        number of logical fields (= length of the SEC_OPF run)
  u8  opclass        0 = IR node (`kind`/`value` envelope), 1 = generic JSON

The record's slot count is *derived* from the field kinds via FIELD_SLOTS, so
the reader never needs a second width field.

SEC_OPF holds `nfields` 4-byte field descriptors:

  u16 name_str       string id of the JSON key this field came from
  u8  field_kind     one of F_*
  u8  flags          FLAG_WRAP_* (see below)

This is why no key name appears a second time anywhere in the file: a key costs
4 bytes *once per opcode that declares it*, not once per occurrence.

Opcodes 0..15 are reserved and fixed:

  0  _null        nfields=0
  1  _str         [F_STR]
  2  _int         [F_INT]
  3  _bool        [F_BOOL]
  4  _arr         [F_TERMLIST]
  5  _json        [F_JSON]                        raw-text escape hatch
  6  _wrap_lower  [F_STR]                         emits {"value": <s>}
  7  _wrap_upper  [F_STR]                         emits {"Value": <s>}
  8..15           reserved

Opcodes >= 16 are assigned deterministically: first every IR `kind` string in
sorted order, then every *plain-object shape* (its sorted key tuple) in sorted
order.  Plain objects get their own opcode so that e.g. `{"Value":..,"Weight":..}`
costs one record instead of a generic key/value pair list.

================================================================================
TERM RECORD
================================================================================
  u16 op
  u16 slot[nslots]        operand slots, meaning given by the opcode's field kinds
  pad to a multiple of 4 bytes

A term's identity is content-addressed: identical (op, slot...) tuples intern to
a single record.  Term ids are u16 indices into the record table; SEC_TRW maps a
term id to its byte offset / 4.  `_null` is term id 0, so 0 is a valid,
always-present term.

================================================================================
ID WRAPPERS, AND WHY THEY ARE FREE
================================================================================
The engine declares ids as `readonly record struct X(string value)`, so the same
id appears in the document in three spellings: bare (`"Id":"red_tape"`), as
`{"value":"paperwork"}` (lower case, `CombatIds.cs`) or as `{"Value":"city_easy_02"}`
(upper case, run layer).  Rather than spend a term on a one-key object, a field
declares *which* spelling it uses in its flags byte; the wrapper object is then
never stored.  A field whose wrapper spelling is not uniform across the document
falls back to F_TERM, whose generic encoding keeps both spellings exact.

  FLAG_WRAP_LOWER = 1   the JSON value is `{"value": <string>}`
  FLAG_WRAP_UPPER = 2   the JSON value is `{"Value": <string>}`
  flags 0               the JSON value is a bare string

The flags apply to F_STR (a scalar id) and to F_STRLIST (each element).

================================================================================
FIELD KINDS AND THEIR SLOT ENCODINGS
================================================================================
Every slot is a u16.  For each field kind, two sentinels are reserved so that
"key absent" and "key present and null" stay distinguishable -- this is what
makes the round trip *exact* rather than merely equivalence-preserving.

  F_STR      = 1  1 slot   string id;  ABSENT=0xFFFF, NULL=0xFFFE
  F_INT      = 2  1 slot   i16;  ABSENT=0x8000 (-32768), NULL=0x8001 (-32767)
  F_BOOL     = 3  1 slot   0=ABSENT, 1=false, 2=true, 3=NULL
  F_TERM     = 4  1 slot   term id;  ABSENT=0xFFFF, NULL=0xFFFE
  F_TERMLIST = 5  2 slots  (aux_start, aux_count) into SEC_AUX; a count of
                           0xFFFF marks ABSENT and 0xFFFE marks NULL.
                           Elements are term ids.
  F_STRLIST  = 6  2 slots  as above, elements are string ids
  F_JSON     = 7  1 slot   string id of canonical JSON text (last-resort escape)

F_INT's sentinels cost the values -32768 and -32767; the compiler validates that
no content integer falls outside [-32766, 32767].

================================================================================
ENTITY ROWS
================================================================================
Rows are fixed-width records of `ncells` u16 cells, padded to `row_stride()`
bytes (align4(2*ncells)).  Each cell is written with the same slot encoding as a
term field, so ABSENT/NULL stay distinguishable and the round trip is exact --
including for booleans, which is why `RetainInHandOnTurnEnd` is a real F_BOOL
cell rather than a bit in a packed flag word (a packed bit could not tell
"absent" from "present and false").
"""

import struct

MAGIC = 0x46434452          # b'RDCF'
# 2: `CARD` gained a `Rarity` cell (stride unchanged -- the cell fits the existing padding).
# A schema change must be visible to a reader that has a *fixed* cell table, otherwise an old
# image decodes as garbage instead of failing.
FORMAT_VERSION = 3
HEADER_SIZE = 32
NSEC = 20

# ------------------------------------------------------------------ sections
S_STR, S_STRO, S_OPD, S_OPF, S_TRM, S_TRW, S_AUX = 0, 1, 2, 3, 4, 5, 6
S_CARD, S_STAT, S_EACT, S_ENCT, S_REL = 7, 8, 9, 10, 11
S_EV = 15
S_ROOT, S_IDX = 12, 13
S_TAGS = 14
SEC_NAMES = {
    S_STR: "STR", S_STRO: "STRO", S_OPD: "OPD", S_OPF: "OPF", S_TRM: "TRM",
    S_TRW: "TRW", S_AUX: "AUX", S_CARD: "CARD", S_STAT: "STAT", S_EACT: "EACT",
    S_ENCT: "ENCT", S_REL: "REL", S_EV: "EV", S_ROOT: "ROOT", S_IDX: "IDX", S_TAGS: "TAGS",
}
# Every section the writer can emit, **in section-id order**.
#
# ⚠️ Two invariants live in this list, and both are silent when broken:
#   * a table added to `ROW_SCHEMAS` but not here is counted and never written;
#   * `compile.py` writes the directory **by position** (`enumerate(dir_entries)`), so a section id
#     must equal its index here. Inserting `S_EV = 15` between `S_REL` (11) and `S_ROOT` (12) shifted
#     ROOT/IDX/TAGS down one slot: the image kept the right *bytes* under the wrong *ids*, and the
#     kernel read 0 events while the manifest said 4.
SEC_ORDER = [S_STR, S_STRO, S_OPD, S_OPF, S_TRM, S_TRW, S_AUX,
             S_CARD, S_STAT, S_EACT, S_ENCT, S_REL, S_ROOT, S_IDX, S_TAGS, S_EV]

# --------------------------------------------------------------- field kinds
F_STR, F_INT, F_BOOL, F_TERM, F_TERMLIST, F_STRLIST, F_JSON = 1, 2, 3, 4, 5, 6, 7

FIELD_NAMES = {F_STR: "STR", F_INT: "INT", F_BOOL: "BOOL", F_TERM: "TERM",
               F_TERMLIST: "TERMLIST", F_STRLIST: "STRLIST", F_JSON: "JSON"}
FIELD_SLOTS = {F_STR: 1, F_INT: 1, F_BOOL: 1, F_TERM: 1,
               F_TERMLIST: 2, F_STRLIST: 2, F_JSON: 1}

FLAG_WRAP_LOWER = 1
FLAG_WRAP_UPPER = 2
WRAP_KEY = {0: None, FLAG_WRAP_LOWER: "value", FLAG_WRAP_UPPER: "Value"}

ABSENT16 = 0xFFFF
NULL16 = 0xFFFE
ABSENT_INT = 0x8000          # -32768 as u16
NULL_INT = 0x8001            # -32767 as u16
BOOL_ABSENT, BOOL_FALSE, BOOL_TRUE, BOOL_NULL = 0, 1, 2, 3
LIST_ABSENT = 0xFFFF
LIST_NULL = 0xFFFE
I16_MIN, I16_MAX = -32766, 32767

# ------------------------------------------------------------------- opcodes
OP_NULL, OP_STR, OP_INT, OP_BOOL, OP_ARR, OP_JSON = 0, 1, 2, 3, 4, 5
OP_WRAP_LOWER, OP_WRAP_UPPER = 6, 7
OP_FIRST_DYNAMIC = 16

OPCLASS_IR = 0
OPCLASS_GENERIC = 1

# reserved opcode -> (field kinds, flags)
RESERVED_OP_LAYOUT = {
    OP_NULL: ((), ()),
    OP_STR: ((F_STR,), (0,)),
    OP_INT: ((F_INT,), (0,)),
    OP_BOOL: ((F_BOOL,), (0,)),
    OP_ARR: ((F_TERMLIST,), (0,)),
    OP_JSON: ((F_JSON,), (0,)),
    OP_WRAP_LOWER: ((F_STR,), (FLAG_WRAP_LOWER,)),
    OP_WRAP_UPPER: ((F_STR,), (FLAG_WRAP_UPPER,)),
}

# ------------------------------------------------------------- entity kinds
(EK_CARD, EK_STATUS, EK_EACTION, EK_ENCOUNTER, EK_RELIC,
 EK_MAPNODE, EK_EVENT, EK_SHOP, EK_CHARACTER) = (1, 2, 3, 4, 5, 6, 7, 8, 9)
EK_NAMES = {
    EK_CARD: "card", EK_STATUS: "status", EK_EACTION: "enemy_action",
    EK_ENCOUNTER: "encounter", EK_RELIC: "relic", EK_MAPNODE: "map_node",
    EK_EVENT: "event", EK_SHOP: "shop", EK_CHARACTER: "character",
}

# -------------------------------------------------------------- row schemas
# (json key, field kind, flags).  The last cell is always the `extra` catch-all,
# an `_obj` term holding any key the schema does not know, so a schema addition
# on the content side can never silently lose data.
CARD_ROW = [
    ("Id", F_STR, 0), ("Program", F_TERM, 0), ("Tags", F_TERM, 0),
    ("Costs", F_TERM, 0), ("LifecyclePrograms", F_TERM, 0),
    ("PlayCondition", F_TERM, 0), ("QueueOnPlay", F_TERM, 0),
    ("RetainInHandOnTurnEnd", F_BOOL, 0), ("IsAction", F_BOOL, 0),
    ("NameKey", F_STR, 0), ("DescriptionKey", F_STR, 0), ("PackageId", F_STR, 0),
    ("TurnEndHandDestinationZone", F_STR, 0), ("PlayedCardDestinationZone", F_STR, 0),
    # `inv:§3.5`: rewards and merchant prices are both **by rarity**. The 16th cell costs nothing in
    # layout (`align4(2*15) == align4(2*16) == 32`); what it costs is a format version bump.
    ("Rarity", F_STR, 0),
    ("extra", F_TERM, 0),
]
STATUS_ROW = [
    ("Id", F_STR, 0), ("NameKey", F_STR, 0), ("DescriptionKey", F_STR, 0),
    ("PackageId", F_STR, 0), ("Polarity", F_STR, 0), ("StackingBehavior", F_STR, 0),
    ("Tags", F_TERM, 0), ("Triggers", F_TERM, 0), ("PassiveModifiers", F_TERM, 0),
    ("CombatRules", F_TERM, 0),
    ("DeathPrevention", F_TERM, 0), ("DebuffBlock", F_TERM, 0),
    ("IncomingStatusDelay", F_TERM, 0), ("Disclosure", F_TERM, 0),
    ("Prevention", F_TERM, 0), ("Amplification", F_TERM, 0),
    ("UsesStacks", F_BOOL, 0), ("UsesDuration", F_BOOL, 0), ("UsesCharges", F_BOOL, 0),
    ("extra", F_TERM, 0),
]
EACT_ROW = [
    ("Id", F_STR, 0), ("NameKey", F_STR, 0), ("DescriptionKey", F_STR, 0),
    ("PackageId", F_STR, 0), ("Intent", F_TERM, 0), ("Program", F_TERM, 0),
    ("extra", F_TERM, 0),
]
ENCT_ROW = [
    ("Id", F_STR, FLAG_WRAP_UPPER), ("Enemies", F_TERM, 0),
    ("HeroResources", F_TERM, 0), ("HeroStartingStatuses", F_TERM, 0),
    ("TriggeredEffects", F_TERM, 0), ("HeroDisplayName", F_STR, 0),
    ("CardsDrawnPerTurn", F_INT, 0), ("extra", F_TERM, 0),
]
REL_ROW = [
    ("Id", F_STR, 0), ("DisplayName", F_STR, 0), ("RunPrograms", F_TERM, 0),
    ("CombatRules", F_TERM, 0), ("extra", F_TERM, 0),
]
EV_ROW = [
    ("Id", F_STR, 0), ("NameKey", F_STR, 0), ("DescriptionKey", F_STR, 0),
    # Two choices as **fixed cells** (no TERM walk): the effect is a closed vocabulary word.
    ("Label0", F_STR, 0), ("Effect0", F_STR, 0), ("Amount0", F_INT, 0),
    ("Label1", F_STR, 0), ("Effect1", F_STR, 0), ("Amount1", F_INT, 0),
    ("extra", F_TERM, 0),
]

ROW_SCHEMAS = {"CARD": CARD_ROW, "STATUS": STATUS_ROW, "EACT": EACT_ROW,
               "ENCT": ENCT_ROW, "REL": REL_ROW, "EV": EV_ROW}


def align4(n):
    return (n + 3) & ~3


def row_stride(name):
    return align4(2 * len(ROW_SCHEMAS[name]))


def fnv1a32(data):
    h = 0x811C9DC5
    for b in data:
        h ^= b
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


def pack_u16(v):
    return struct.pack("<H", v & 0xFFFF)


def unpack_header(buf):
    if len(buf) < HEADER_SIZE:
        raise ValueError("file shorter than header")
    (magic, version, flags, total, dir_off, nsec,
     schema, chash, rsvd) = struct.unpack_from("<IHHIIHHII", buf, 0)
    if magic != MAGIC:
        raise ValueError("bad magic 0x%08X (expected 0x%08X)" % (magic, MAGIC))
    return {"magic": magic, "version": version, "flags": flags, "total_size": total,
            "dir_off": dir_off, "nsec": nsec, "schema_version": schema,
            "content_hash": chash, "reserved": rsvd}


def unpack_dir(buf):
    hdr = unpack_header(buf)
    out = {}
    for i in range(hdr["nsec"]):
        off, size, count = struct.unpack_from("<III", buf, hdr["dir_off"] + 12 * i)
        out[i] = (off, size, count)
    return hdr, out
