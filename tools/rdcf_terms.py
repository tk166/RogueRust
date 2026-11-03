"""§184: `rdcf-verify` learns to read the **term table**.

Why this exists (two bugs, both found the expensive way):
`§183` wrote a content field the dialect cannot express in that position --
`node.applyStatus.DurationTurns` is a **bare int**, and a term there is encoded as an `_json` cell.
Nothing complained: the JSON passed `sts_content_check.py` (which only reads the source document),
the byte-level gate passed (it checks `count x stride`, not what is *inside* a row), and the image
compiled. The failure surfaced later as `Ir(WrongKind("F_JSON"))` in an unrelated kernel test --
"add a card, an enemy trigger breaks".

`_json` (opcode 5, `F_JSON`) is the compiler's **last-resort escape hatch**: it is written exactly
when the document says something the declared field kind cannot hold. So for a *checked-in* image,
"there is no `_json` term" is a total, cheap, and very sharp statement.

What this module checks (all from the bytes, not from the compiler's own claims):
1. no term has opcode 5 (`_json`), and when one does, the message carries the **JSON text** and the
   term id -- the text instantly shows what the content tried to say;
2. every `F_TERM` / `F_TERMLIST` slot that is not a sentinel points at a real term record
   (an id shift -- §167's "right bytes under the wrong ids" -- fails here).

It does **not** try to validate semantics: that stays the kernel's job. It validates *shape*.
"""
import struct

# Format constants come from `rdcfmt` (one definition of the format, §167's rule); the code that
# interprets them is written here, independently of `contentc/reader.py` and `contentc/compile.py`.
import sys
import os

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "contentc"))
from rdcfmt import (  # noqa: E402  (path set up above)
    S_STR, S_STRO, S_OPD, S_OPF, S_TRM, S_TRW, FIELD_SLOTS, F_TERM, F_TERMLIST, F_JSON,
    ABSENT16, NULL16,
)

OP_JSON = 5
OPCLASS_IR = 0


def _sections(blob, header_bytes, n_entries):
    """(offset, bytes, count) per section id -- the same decode `rdcf_verify` already does."""
    out = []
    for i in range(n_entries):
        base = header_bytes + i * 12
        if base + 12 > len(blob):
            return out
        off, nbytes, count = struct.unpack_from("<III", blob, base)
        out.append((off, nbytes, count))
    return out


def _strings(blob, sections):
    str_blob = blob[sections[S_STR][0]:sections[S_STR][0] + sections[S_STR][1]]
    stro = blob[sections[S_STRO][0]:sections[S_STRO][0] + sections[S_STRO][1]]
    count = len(stro) // 4 - 1
    if count <= 0:
        return str_blob, ()
    offsets = struct.unpack_from("<%dI" % (count + 1), stro, 0)

    def at(sid):
        if sid == 0:
            return ""
        if sid > count:
            return "<string %d out of range>" % (sid,)
        a = offsets[sid - 1]
        b = offsets[sid]
        return str_blob[a:b - 1 if b > a else a].decode("utf-8", "replace")

    return at, count


def _opcodes(blob, sections):
    """opcode -> (nslots, [(field_name, kind, flags)]) -- read the way the format defines it."""
    opd = blob[sections[S_OPD][0]:sections[S_OPD][0] + sections[S_OPD][1]]
    opf = blob[sections[S_OPF][0]:sections[S_OPF][0] + sections[S_OPF][1]]
    n_ops = len(opd) // 8
    ops = []
    for op in range(n_ops):
        field_off, name_str, nfields, opclass = struct.unpack_from("<IHBB", opd, op * 8)
        kinds = []
        for i in range(nfields):
            base = field_off + i * 4
            if base + 4 > len(opf):
                break
            key_sid, kind, flags = struct.unpack_from("<HBB", opf, base)
            kinds.append((key_sid, kind, flags))
        ops.append({
            "name_sid": name_str,
            "nfields": nfields,
            "opclass": opclass,
            "kinds": kinds,
            "nslots": sum(FIELD_SLOTS[kind] for _, kind, _ in kinds),
        })
    return ops


def check_terms(blob, header_bytes, n_entries, failures):
    """The two shape checks. Returns (checks run, terms walked)."""
    sections = _sections(blob, header_bytes, n_entries)
    if len(sections) <= S_TRW:
        failures.append("段目录只有 %d 段，读不到 TRM/TRW" % (len(sections),))
        return 0, 0
    string_at, _ = _strings(blob, sections)
    ops = _opcodes(blob, sections)
    trm = blob[sections[S_TRM][0]:sections[S_TRM][0] + sections[S_TRM][1]]
    trw = blob[sections[S_TRW][0]:sections[S_TRW][0] + sections[S_TRW][1]]
    n_terms = len(trw) // 2
    if n_terms == 0:
        failures.append("TRW 是空的 —— 没有 term 说明镜像不是这个格式")
        return 0, 0
    offsets = struct.unpack_from("<%dH" % n_terms, trw, 0)

    ran = 0
    # ── 先查**字段声明**层面 ────────────────────────────────────────────────────────────────
    #
    # `F_JSON` 作为**字段种类**只允许出现在保留 opcode 5（`_json`）自己身上。它出现在别的
    # opcode 上，说明编译器的 knew 形状打架了：同一个字段在不同出现处一边是裸整数、一边是 term，
    # 于是整个字段退化成"原始 JSON"。内核的 `NodeRef::field()` 对 F_JSON **无条件**
    # `Err(WrongKind("F_JSON"))` ⇒ 这条内容一旦被任何程序读到就会炸，而**与那张卡无关的测试**
    # 先红（§183 就是这样炸的）。
    #
    # 这是真正的判据：只查 `_json` term 抓不到它 —— 单点注入时编译器会乖乖选 F_TERM。
    seen_bad = set()
    for op, descriptor in enumerate(ops):
        if op == OP_JSON:
            continue
        for key_sid, kind, _flags in descriptor["kinds"]:
            if kind != F_JSON:
                continue
            key = (op, key_sid)
            if key in seen_bad:
                continue
            seen_bad.add(key)
            failures.append(
                "opcode %d（%r）的字段 %r 被声明成 F_JSON：同一个字段在各处形状不一致"
                "（一边裸值、一边 term），编译器只能把它降级成原始 JSON。内核读这个字段会直接"
                " `WrongKind(\"F_JSON\")` —— 先把内容的形状统一。"
                % (op, string_at(descriptor["name_sid"]), string_at(key_sid))
            )
    ran += 1
    json_terms = []
    bad_ids = []
    for tid in range(n_terms):
        base = offsets[tid] * 4
        if base + 2 > len(trm):
            bad_ids.append((tid, "record offset %d is outside TRM" % (base,)))
            continue
        op = struct.unpack_from("<H", trm, base)[0]
        if op >= len(ops):
            bad_ids.append((tid, "opcode %d is not in OPD" % (op,)))
            continue
        if op == OP_JSON:
            slot = struct.unpack_from("<H", trm, base + 2)[0]
            json_terms.append((tid, string_at(slot)))
            continue
        nslots = ops[op]["nslots"]
        if nslots == 0:
            continue
        slots = struct.unpack_from("<%dH" % nslots, trm, base + 2)
        # Walk the slots *in field order* so each one can be attributed to its field name -- that is
        # what turns "a `_json` exists" into "this field said something the dialect cannot hold".
        index = 0
        for key_sid, kind, _flags in ops[op]["kinds"]:
            width = FIELD_SLOTS[kind]
            if kind in (F_TERM, F_TERMLIST):
                for slot_index in range(width):
                    value = slots[index + slot_index]
                    if value in (ABSENT16, NULL16):
                        continue
                    if kind == F_TERM and value >= n_terms:
                        bad_ids.append(
                            (tid, "%s.%s -> term %d out of %d"
                             % (string_at(ops[op]["name_sid"]), string_at(key_sid), value, n_terms))
                        )
                    if kind == F_TERMLIST:
                        continue
            index += width
    # A `TERMLIST` (aux_start, aux_count) is walked by the compiler's reader; here only the *direct*
    # term slots are pointer-checked, which is what catches id shifts between sections.

    if json_terms:
        tid, text = json_terms[0]
        more = "" if len(json_terms) == 1 else " (+%d more)" % (len(json_terms) - 1)
        failures.append(
            "镜像里有 %d 个 `_json` term%s：term %d = %r。`_json` 只在**源文档说的东西"
            "该字段装不下**时才会出现（例如 `DurationTurns` 是裸整数、`sel.allEnemies` 的 value "
            "是 `{}`）。内容门只读源 JSON，所以这是唯一能在这里拦住它的地方。"
            % (len(json_terms), more, tid, text[:160])
        )
    ran += 1
    if bad_ids:
        tid, why = bad_ids[0]
        failures.append(
            "term 槽指向不存在的记录（%d 处）：term %d %s —— 通常是段 id 位移（§167 的"
            "「对的字节、错的 id」）" % (len(bad_ids), tid, why)
        )
    ran += 1
    return ran, n_terms
