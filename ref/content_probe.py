"""
content_probe.py -- offline reconnaissance of a *.roguedeck.json content document.

Purpose: gather the numbers needed to design a compact binary ROM representation
of the content (esp. for embedded targets), i.e. answer "where do the 7.9 MB go?"
and "what shapes must the binary encoder handle?".

Run (this machine's shell swallows stdout of `& exe`, so use ProcessStartInfo):
    python content_probe.py [path-to-json] [--samples N]

Output: pure text to stdout (ASCII-safe structure, raw UTF-8 for sampled strings).
No third-party dependencies.
"""

import json
import os
import re
import sys
from collections import Counter, defaultdict

DEFAULT_PATH = (
    r"D:\Vibe\sts-tui\ref\RogueDeck-Core\src\RogueDeck.Sandbox.Run"
    r"\SampleContent\bureaucrats.roguedeck.json"
)

# ---------------------------------------------------------------- helpers

def enc(obj, indent=None):
    """Serialized size in bytes, UTF-8, no ASCII escaping (JSON is stored as UTF-8)."""
    if indent is None:
        s = json.dumps(obj, separators=(",", ":"), ensure_ascii=False)
    else:
        s = json.dumps(obj, indent=indent, ensure_ascii=False)
    return len(s.encode("utf-8"))


def pretty(obj, maxlen=2000, indent=2):
    s = json.dumps(obj, indent=indent, ensure_ascii=False)
    if len(s) > maxlen:
        s = s[:maxlen] + "\n  ...[truncated %d chars]" % (len(s) - maxlen)
    return s


def jtype(v):
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, (int, float)):
        return "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, list):
        return "array"
    if isinstance(v, dict):
        return "object"
    return type(v).__name__


def merge_type(old, new):
    """Merge two type labels for mixed-type detection."""
    if old is None:
        return new
    if old == new:
        return old
    return old + "|" + new


def is_program(v):
    """Heuristic: a value that smells like an effect-program node descriptor."""
    if not isinstance(v, dict):
        return False
    keys = {k.lower() for k in v}
    if "kind" in keys or "op" in keys or "type" in keys:
        return True
    return False


# ------------------------------------------------- per-entity statistics

class EntityStats:
    """Field statistics over a list of like-shaped records."""

    def __init__(self, name):
        self.name = name
        self.n = 0
        self.total = 0
        self.max_size = -1
        self.max_key = None
        self.sizes = []
        self.keys = Counter()          # top-level key -> count of records having it
        self.keytypes = {}             # top-level key -> merged type label
        self.keybytes = Counter()      # top-level key -> total bytes
        self.key_values = Counter()    # top-level key -> hashable value freq (scalars only)
        self.key_vals_multi = set()    # keys whose values are non-scalar (skip vocab listing)

    def add(self, key, rec):
        self.n += 1
        sz = enc(rec)
        self.total += sz
        self.sizes.append(sz)
        if sz > self.max_size:
            self.max_size = sz
            self.max_key = key
        if not isinstance(rec, dict):
            self.keytypes["<not-an-object>"] = jtype(rec)
            return
        for k, v in rec.items():
            self.keys[k] += 1
            self.keytypes[k] = merge_type(self.keytypes.get(k), jtype(v))
            kb = len(("\"%s\":" % k).encode("utf-8")) + enc(v)
            self.keybytes[k] += kb
            if isinstance(v, (str, int, float, bool)) or v is None:
                self.key_values[(k, str(v)[:60])] += 1
            else:
                self.key_values[(k, "<%s>" % jtype(v))] += 1
                self.key_vals_multi.add(k)

    def report(self, out, vocab_limit=12):
        a = out.append
        a("")
        a("### %s : n=%d  total=%d B  avg=%d B  median=%d B  max=%d B (key=%s)"
          % (self.name, self.n, self.total,
             self.total // max(1, self.n),
             sorted(self.sizes)[len(self.sizes) // 2] if self.sizes else 0,
             self.max_size, self.max_key))
        a("  fields (name | records-with | type | total bytes | share of section):")
        for k, cnt in self.keys.most_common():
            a("    %-28s %6d/%-6d %-14s %9d B  %5.1f%%"
              % (k, cnt, self.n, self.keytypes[k], self.keybytes[k],
                 100.0 * self.keybytes[k] / max(1, self.total)))
        return


# ------------------------------------------------------ program traversal

NODE_COUNT = Counter()      # "Kind" -> occurrences
NODE_PARENT = Counter()     # (parentKind, childKind)
NODE_FIELDS = defaultdict(Counter)
NODE_BYTES = Counter()
NODE_DEPTH = Counter()


def walk_program(node, depth=0, parent_kind=None, path=""):
    if depth > 24:
        return
    if isinstance(node, list):
        for it in node:
            walk_program(it, depth, parent_kind, path)
        return
    if not isinstance(node, dict):
        return
    kind = None
    for k in ("kind", "Kind", "op", "Op", "type", "Type"):
        if k in node and isinstance(node[k], str):
            kind = node[k]
            break
    if kind is not None:
        NODE_COUNT[kind] += 1
        NODE_BYTES[kind] += enc(node)
        NODE_DEPTH[min(depth, 8)] += 1
        for k, v in node.items():
            NODE_FIELDS[kind][k + ":" + jtype(v)] += 1
        if parent_kind:
            NODE_PARENT[(parent_kind, kind)] += 1
    for k, v in node.items():
        if isinstance(v, (dict, list)):
            walk_program(v, depth + 1, kind or parent_kind, path + "/" + k)


# ---------------------------------------------------------------- main

def main():
    args = [a for a in sys.argv[1:]]
    samples = 2
    if "--samples" in args:
        i = args.index("--samples")
        samples = int(args[i + 1])
        del args[i:i + 2]
    path = args[0] if args else DEFAULT_PATH

    raw = open(path, "rb").read()
    out = []
    a = out.append
    a("=" * 78)
    a("CONTENT PROBE: %s" % os.path.basename(path))
    a("path            : %s" % path)
    a("raw file bytes  : %d" % len(raw))
    a("BOM             : %s" % ("yes" if raw[:3] == b"\xef\xbb\xbf" else "no"))
    # line count (only meaningful if pretty printed)
    a("newline count   : %d" % raw.count(b"\n"))
    a("indent chars    : leading-space bytes = %d (%.1f%% of file)"
      % (sum(1 for c in raw if c == 0x20), 100.0 * raw.count(b" ") / len(raw)))
    a("=" * 78)

    # =====================================================================
    # PHASE 0 — RAW-FILE byte attribution (pretty printing is not free)
    # =====================================================================
    text = raw.decode("utf-8-sig")
    nch = len(text)
    ws = sum(1 for c in text if c in " \t\r\n")
    a("")
    a("RAW-FILE ATTRIBUTION (the compact size of a section is NOT what it costs on disk)")
    a("characters=%d  bytes=%d  (difference = %d, i.e. CRLF line endings)"
      % (nch, len(raw), len(raw) - nch))
    a("whitespace chars=%d (%.1f%%)  newlines=%d" % (ws, 100.0 * ws / nch, text.count("\n")))
    a("")

    def top_spans(t):
        i = t.index("{") + 1
        spans = []
        keypat = re.compile(r'"((?:[^"\\]|\\.)*)"\s*:')
        L = len(t)
        while i < L:
            while i < L and t[i] in " \t\r\n,":
                i += 1
            if i >= L or t[i] == "}":
                break
            m = keypat.match(t, i)
            if not m:
                break
            key = m.group(1)
            i = m.end()
            start = i
            depth, instr, esc = 0, False, False
            while i < L:
                c = t[i]
                if instr:
                    if esc:
                        esc = False
                    elif c == "\\":
                        esc = True
                    elif c == '"':
                        instr = False
                else:
                    if c == '"':
                        instr = True
                    elif c in "[{":
                        depth += 1
                    elif c in "]}":
                        depth -= 1
                        if depth == 0:
                            i += 1
                            break
                    elif c == "," and depth == 0:
                        break
                i += 1
            spans.append((key, t[start:i]))
            while i < L and t[i] in " \t\r\n,":
                i += 1
        return spans

    a("%-16s %11s %8s %9s %8s %9s %9s" % ("section", "raw bytes", "%file", "compact",
                                           "raw/cmp", "lines", "indent%"))
    rows0 = []
    for key, body in top_spans(text):
        try:
            comp = enc(json.loads(body))
        except Exception:
            comp = -1
        indent = sum(1 for c in body if c in " \t\r\n")
        rawb = len(body.encode("utf-8")) + len(key) + 3
        rows0.append((rawb, key, comp, len(body.encode('utf-8')), indent, body.count("\n")))
    for rawb, key, comp, vb, indent, lines in sorted(rows0, reverse=True):
        a("%-16s %11d %7.2f%% %9d %8s %9d %8.2f%%"
          % (key, rawb, 100.0 * rawb / len(raw), comp,
             ("%.2f" % (vb / comp)) if comp > 0 else "-", lines,
             100.0 * indent / max(1, vb)))
    a("")
    # nesting depth profile
    depth = maxd = 0
    instr = esc = False
    hist = Counter()
    for c in text:
        if instr:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                instr = False
            continue
        if c == '"':
            instr = True
        elif c in "[{":
            depth += 1
            maxd = max(maxd, depth)
        elif c in "]}":
            hist[depth] += 1
            depth -= 1
    a("max JSON nesting depth: %d" % maxd)

    # =====================================================================
    # PHASE 1 — top-level keys
    # =====================================================================
    doc = json.loads(text)
    a("")
    a("TOP-LEVEL KEYS (22 expected)")
    a("%-16s %-9s %-11s %9s %8s  %s" % ("key", "type", "count", "bytes", "share", "note"))
    top = []
    for k, v in doc.items():
        b = len(("\"%s\":" % k).encode("utf-8")) + enc(v)
        n = len(v) if isinstance(v, (list, dict)) else 1
        top.append((b, k, v, n))
    grand = enc(doc)
    for b, k, v, n in sorted(top, reverse=True):
        a("%-16s %-9s %-11d %9d B %7.2f%%" % (k, jtype(v), n, b, 100.0 * b / grand))
    a("%-16s %-9s %-11s %9d B %7.2f%%" % ("<sum>", "", "", sum(t[0] for t in top),
                                          100.0 * sum(t[0] for t in top) / grand))
    a("")
    a("re-serialized total (compact, utf-8, no escapes) : %d B" % grand)
    a("raw on disk                                      : %d B" % len(raw))
    a("overhead (indentation/whitespace/escapes)        : %d B (%.1f%%)"
      % (len(raw) - grand, 100.0 * (len(raw) - grand) / len(raw)))

    # white-space accounting: how much is pure structural pretty-printing
    minified = json.dumps(doc, separators=(",", ":"), ensure_ascii=True)
    a("minified w/ ascii-escapes                        : %d B" % len(minified))
    a("non-ascii chars in file (approx, utf8 extra B)   : %d"
      % (len(raw.decode("utf-8-sig").encode("utf-8")) - len(raw.decode("utf-8-sig"))))
    del minified

    # ------------------------------------------------ per-section detail
    SECTION_SPECS = [
        ("Cards", "Card"),
        ("Statuses", "Status"),
        ("Relics", "Relic"),
        ("EnemyActions", "EnemyAction"),
        ("Encounters", "Encounter"),
        ("Events", "Event"),
        ("Consumables", "Consumable"),
        ("CombatResources", "CombatResource"),
        ("Shreds", "Shred"),
        ("Recipes", "Recipe"),
        ("Characters", "Character"),
        ("MetaRules", "MetaRule"),
        ("Balance", "BalanceField"),
        ("Presentation", "PresentationField"),
    ]

    stats = {}
    a("")
    a("#" * 78)
    a("# 1. BIGGEST RECORDS PER SECTION (who really fills the file)")
    a("#" * 78)
    for key, label in SECTION_SPECS:
        sec = doc.get(key)
        if isinstance(sec, list) and sec:
            recs = [(("[%d]" % i), r) for i, r in enumerate(sec)]
        elif isinstance(sec, dict) and sec:
            recs = [(k, v) for k, v in sec.items()]
        else:
            continue
        st = EntityStats("%s (top-level %s)" % (label, key))
        for rk, r in recs:
            st.add(rk, r)
        stats[key] = st
        st.report(out)
        biggest = sorted(recs, key=lambda t: enc(t[1]), reverse=True)[:6]
        a("  largest %d of %d:" % (len(biggest), len(recs)))
        for rk, r in biggest:
            name = ""
            if isinstance(r, dict):
                name = str(r.get("id") or r.get("Id") or r.get("name") or r.get("Name") or "")
            a("    %-9s %9d B  %s" % (rk, enc(r), name))
        # share of the whole document
        a("  => section share of document: %.2f%%"
          % (100.0 * st.total / grand))

    # ------------------------------- nested collections needing own stats
    a("")
    a("#" * 78)
    a("# 1b. NESTED COLLECTIONS (sub-records inside the top-level sections)")
    a("#" * 78)
    nested = [
        ("Encounters", "enemies/enemy list", lambda e: e.get("Enemies") or e.get("enemyIds")),
        ("Cards", "<inline programs>", None),
    ]
    # discover arrays of objects that live inside records
    nest_acc = {}

    def scan_nested(prefix, node, depth=0):
        if depth > 6:
            return
        if isinstance(node, dict):
            for k, v in node.items():
                if isinstance(v, list) and v and isinstance(v[0], dict) and not is_program(v[0]):
                    name = "%s/%s" % (prefix, k)
                    if name not in nest_acc:
                        nest_acc[name] = EntityStats(name)
                    st = nest_acc[name]
                    for i, it in enumerate(v):
                        st.add("[%d]" % i, it)
                scan_nested(prefix + "/" + k, v, depth + 1)
        elif isinstance(node, list) and node and isinstance(node[0], dict):
            scan_nested(prefix + "[]", node[0], depth + 1)

    for key in doc:
        scan_nested(key, doc[key])
    ranked = sorted(nest_acc.values(), key=lambda s: -s.total)[:14]
    for st in ranked:
        st.report(out)
        a("  => share of document: %.2f%%" % (100.0 * st.total / grand))

    # ------------------------------------------------ big string inventory
    a("")
    a("#" * 78)
    a("# 1c. STRING BUDGET (where the bytes literally are)")
    a("#" * 78)
    KEY_COUNT = Counter()
    KEY_BYTES = Counter()
    SC = {"str_bytes": 0, "str_count": 0, "num": 0, "bool": 0, "null": 0}
    STR_POOL = Counter()
    KEY_POOL_STR = Counter()

    def walk_all(node):
        if isinstance(node, dict):
            for k, v in node.items():
                KEY_COUNT[k] += 1
                KEY_BYTES[k] += len(("\"%s\":" % k).encode("utf-8"))
                KEY_POOL_STR[k] += 1
                walk_all(v)
        elif isinstance(node, list):
            for it in node:
                walk_all(it)
        elif isinstance(node, str):
            SC["str_count"] += 1
            SC["str_bytes"] += len(json.dumps(node, ensure_ascii=False).encode("utf-8"))
            STR_POOL[node] += 1
        elif isinstance(node, bool):
            SC["bool"] += 1
        elif node is None:
            SC["null"] += 1
        else:
            SC["num"] += 1

    walk_all(doc)
    STR_COUNT = SC["str_count"]
    STR_BYTES = SC["str_bytes"]
    NUM_COUNT = SC["num"]
    BOOL_COUNT = SC["bool"]
    NULL_COUNT = SC["null"]
    a("scalars: strings=%d (%d B incl quotes, %.1f%% of file)  numbers=%d  bools=%d  nulls=%d"
      % (STR_COUNT, STR_BYTES, 100.0 * STR_BYTES / grand, NUM_COUNT, BOOL_COUNT, NULL_COUNT))
    a("object keys: distinct=%d  occurrences=%d  key-name bytes=%d (%.1f%%)"
      % (len(KEY_COUNT), sum(KEY_COUNT.values()), sum(KEY_BYTES.values()),
         100.0 * sum(KEY_BYTES.values()) / grand))
    a("distinct key names (all): %d" % len(KEY_COUNT))
    a("")
    a("top 30 key names by total bytes:")
    for k, b in KEY_BYTES.most_common(30):
        a("    %-30s x%-7d %9d B" % (k, KEY_COUNT[k], b))
    a("")
    a("strings: distinct=%d  total=%d  pool bytes if dedup'd=%d (saves %d B)"
      % (len(STR_POOL), STR_COUNT,
         sum(len(json.dumps(s, ensure_ascii=False).encode("utf-8")) for s in STR_POOL),
         STR_BYTES - sum(len(json.dumps(s, ensure_ascii=False).encode("utf-8")) for s in STR_POOL)))
    a("")
    a("top 25 strings by total bytes (value_text x count):")
    for s, c in sorted(STR_POOL.items(), key=lambda kv: -(len(kv[0]) * kv[1]))[:25]:
        disp = s.replace("\n", "\\n")
        a("    x%-5d len=%-5d tot=%8d B  %s" % (c, len(s), len(s.encode("utf-8")) * c,
                                               disp[:90]))
    a("")
    a("longest 15 single string values:")
    for s, c in sorted(STR_POOL.items(), key=lambda kv: -len(kv[0]))[:15]:
        a("    len=%-6d x%-4d %s" % (len(s), c, s.replace("\n", "\\n")[:100]))

    # string length histogram
    hist = Counter()
    for s, c in STR_POOL.items():
        L = len(s)
        b = ("0" if L == 0 else "1-7" if L <= 7 else "8-15" if L <= 15 else
             "16-31" if L <= 31 else "32-63" if L <= 63 else "64-127" if L <= 127 else
             "128-255" if L <= 255 else "256+")
        hist[b] += c
    a("string-length histogram (occurrences): %s"
      % ", ".join("%s=%d" % kv for kv in
                  sorted(hist.items(), key=lambda kv: ["0", "1-7", "8-15", "16-31",
                                                       "32-63", "64-127", "128-255",
                                                       "256+"].index(kv[0]))))

    # ------------------------------------------------ effect programs
    a("")
    a("#" * 78)
    a("# 3. EFFECT-PROGRAM NODES (kind/op/type discriminators found anywhere)")
    a("#" * 78)
    # collect every dict anywhere and classify by discriminator key presence
    def walk_disc(node, depth=0, parent=None):
        if isinstance(node, dict):
            kind = None
            for k in ("kind", "Kind", "op", "Op", "type", "Type"):
                if k in node and isinstance(node[k], str):
                    kind = node[k]
                    break
            if kind is not None:
                NODE_COUNT[kind] += 1
                NODE_BYTES[kind] += enc(node)
                NODE_DEPTH[min(depth, 8)] += 1
                for k, v in node.items():
                    NODE_FIELDS[kind][k + ":" + jtype(v)] += 1
                if parent:
                    NODE_PARENT[(parent, kind)] += 1
            for k, v in node.items():
                walk_disc(v, depth + 1, kind or parent)
        elif isinstance(node, list):
            for it in node:
                walk_disc(it, depth + 1, parent)

    walk_disc(doc)
    a("distinct discriminator values: %d ; total nodes: %d ; total node bytes: %d (%.1f%%)"
      % (len(NODE_COUNT), sum(NODE_COUNT.values()), sum(NODE_BYTES.values()),
         100.0 * sum(NODE_BYTES.values()) / grand))
    a("")
    a("%-34s %8s %10s %10s %8s  fields" % ("kind", "count", "bytes", "avg B", "depth"))
    for k, c in NODE_COUNT.most_common():
        depths = "?"
        a("%-34s %8d %10d %10d %8s  %s"
          % (k, c, NODE_BYTES[k], NODE_BYTES[k] // c, depths,
             ",".join(sorted(x.split(":")[0] for x in NODE_FIELDS[k]))[:110]))

    a("")
    a("discriminator key usage: which key carries the node kind")
    disc_keys = Counter()
    def walk_disc_key(node):
        if isinstance(node, dict):
            for k in ("kind", "Kind", "op", "Op", "type", "Type"):
                if k in node and isinstance(node[k], str):
                    disc_keys[k] += 1
                    break
            for v in node.values():
                walk_disc_key(v)
        elif isinstance(node, list):
            for it in node:
                walk_disc_key(it)
    walk_disc_key(doc)
    for k, c in disc_keys.most_common():
        a("    %-10s %d" % (k, c))

    a("")
    a("depth histogram of program nodes: %s"
      % ", ".join("%d:%d" % kv for kv in sorted(NODE_DEPTH.items())))
    a("")
    a("top 30 parent -> child kind pairs:")
    for (p, c), n in NODE_PARENT.most_common(30):
        a("    %-26s -> %-26s %d" % (p, c, n))

    # ------------------------------------------------------------- samples
    a("")
    a("#" * 78)
    a("# SAMPLES (first/largest of each entity kind)")
    a("#" * 78)
    for key, label in SECTION_SPECS:
        sec = doc.get(key)
        if isinstance(sec, list) and sec:
            recs = [(("[%d]" % i), r) for i, r in enumerate(sec)]
        elif isinstance(sec, dict) and sec:
            recs = list(sec.items())
        else:
            continue
        recs.sort(key=lambda t: enc(t[1]))
        picks = []
        if recs:
            picks.append(("smallest", recs[0]))
            picks.append(("median", recs[len(recs) // 2]))
            picks.append(("largest", recs[-1]))
        if len(recs) > 3:
            picks.append(("first", [(("[%d]" % i), r) for i, r in enumerate(sec)][0]
                          if isinstance(sec, list) else list(sec.items())[0]))
        seen = set()
        for tag, (rk, r) in picks[:max(1, samples + 1)]:
            if rk in seen:
                continue
            seen.add(rk)
            a("")
            a("---- %s %s %s (%d B) ----" % (label, rk, tag, enc(r)))
            a(pretty(r, maxlen=2600))

    # -------------------------------------------------- reference scanning
    a("")
    a("#" * 78)
    a("# 4. REFERENCE / FOREIGN-KEY SCAN")
    a("#" * 78)
    id_index = {}
    for key, label in SECTION_SPECS:
        sec = doc.get(key)
        items = sec if isinstance(sec, list) else (
            [{"id": k, **(v if isinstance(v, dict) else {"value": v})}
             for k, v in sec.items()] if isinstance(sec, dict) else [])
        for it in items:
            if isinstance(it, dict) and isinstance(it.get("id"), str):
                id_index.setdefault(it["id"], []).append(key)
    a("ids declared (top-level sections only): %d distinct" % len(id_index))
    a("")
    a("dangling-looking string values that mention a known id, by field:")
    hit_fields = Counter()
    miss_fields = Counter()
    all_str = Counter()

    def scan_refs(node, field=None):
        if isinstance(node, dict):
            for k, v in node.items():
                scan_refs(v, k)
        elif isinstance(node, list):
            for it in node:
                scan_refs(it, field)
        elif isinstance(node, str):
            all_str[field] += 1
    scan_refs(doc)
    a("string-valued fields (count of string leaves) top 30:")
    for k, c in all_str.most_common(30):
        a("    %-34s %d" % (k, c))

    # =====================================================================
    # PHASE 2 — program trees walked properly, encounter breakdown, schemas
    # =====================================================================
    a("")
    a("#" * 78)
    a("# 3b. PROGRAM TREES (walked as trees: no double counting of nested nodes)")
    a("#" * 78)

    def is_node(d):
        return isinstance(d, dict) and isinstance(d.get("kind"), str) and "value" in d

    PROGRAM_ROOTS = []          # (ownerSection, ownerId, slot, rootNode)
    own_bytes = Counter()       # kind -> bytes excluding nested children
    node_count = Counter()
    max_depth_seen = [0]

    def walk_node(node, depth):
        """Returns (node_count, total_bytes_including_children). Adds own_bytes for this node."""
        nonlocal walk_node
        if not is_node(node):
            return 0, enc(node)
        kind = node["kind"]
        max_depth_seen[0] = max(max_depth_seen[0], depth)
        node_count[kind] += 1
        body = node["value"]
        kids = []
        if isinstance(body, dict):
            for k, v in body.items():
                if k in ("Children", "Then", "Else", "Body", "Program", "Effect",
                         "Options", "Branches", "Steps", "InstalledProgram"):
                    if isinstance(v, list) and v and is_node(v[0]):
                        kids.extend(v)
                    elif is_node(v):
                        kids.append(v)
        total = 0
        kid_total = 0
        for c in kids:
            n, b = walk_node(c, depth + 1)
            total += b
            kid_total += b
        # own bytes = the whole node minus the nested child subtrees
        own_bytes[kind] += enc(node) - kid_total
        return 1, enc(node)

    def scan_programs(sec, node, path=""):
        if isinstance(node, dict):
            if is_node(node):
                PROGRAM_ROOTS.append((sec, path, node))
                return
            for k, v in node.items():
                scan_programs(sec, v, path + "/" + k)
        elif isinstance(node, list):
            for i, it in enumerate(node):
                scan_programs(sec, it, path + "[%d]" % i)

    for key in doc:
        scan_programs(key, doc[key])

    for sec, path, root in PROGRAM_ROOTS:
        walk_node(root, 0)

    a("program ROOTS found (a {kind,value} node whose parent is a plain object): %d"
      % len(PROGRAM_ROOTS))
    a("total effect nodes reached: %d   max nesting depth: %d"
      % (sum(node_count.values()), max_depth_seen[0]))
    a("")
    a("root kinds: %s"
      % ", ".join("%s=%d" % kv for kv in node_count.most_common(0)))
    rootk = Counter(r[2]["kind"] for r in PROGRAM_ROOTS)
    for k, c in rootk.most_common():
        a("    root %-28s %d" % (k, c))
    a("")
    a("per-kind OWN bytes (excludes nested subtrees) — the binary encoder's real target:")
    a("%-34s %9s %14s %10s" % ("kind", "count", "own bytes", "avg own"))
    tot_own = sum(own_bytes.values())
    for k, b in own_bytes.most_common():
        a("%-34s %9d %14d %10d   %5.1f%%"
          % (k, node_count[k], b, b // max(1, node_count[k]), 100.0 * b / max(1, tot_own)))
    a("%-34s %9d %14d" % ("<TOTAL>", sum(node_count.values()), tot_own))
    a("=> program own-bytes are %.1f%% of the compact document" % (100.0 * tot_own / grand))
    a("")
    a("program roots by owning top-level section:")
    owners = Counter(r[0] for r in PROGRAM_ROOTS)
    for k, c in owners.most_common():
        a("    %-16s %d" % (k, c))

    # ------------------------------------------- encounter / event breakdown
    a("")
    a("#" * 78)
    a("# 1d. ENCOUNTER + EVENT BREAKDOWN (what inside them is big)")
    a("#" * 78)
    enc_sub = Counter()
    enc_list = doc["Encounters"]
    for e in enc_list:
        for k, v in e.items():
            enc_sub[k] += len(("\"%s\":" % k).encode("utf-8")) + enc(v)
    a("Encounters total %d B; by sub-key:" % sum(enc_sub.values()))
    for k, b in enc_sub.most_common():
        a("    %-26s %9d B  %5.1f%% of section" % (k, b, 100.0 * b / sum(enc_sub.values())))
    a("")
    a("TriggeredEffects entries: %d across %d encounters"
      % (sum(len(e.get("TriggeredEffects") or []) for e in enc_list),
         sum(1 for e in enc_list if e.get("TriggeredEffects"))))
    te_kinds = Counter()
    for e in enc_list:
        for t in (e.get("TriggeredEffects") or []):
            te_kinds[json.dumps(t.get("Event"), ensure_ascii=False) if "Event" in t else "<no Event>"] += 1
    a("TriggeredEffects by 'Event' value: %s"
      % ", ".join("%s=%d" % kv for kv in te_kinds.most_common(12)))
    te_fields = EntityStats("Encounter.TriggeredEffects[]")
    for e in enc_list:
        for t in (e.get("TriggeredEffects") or []):
            te_fields.add("x", t)
    te_fields.report(out)
    a("")
    a("largest encounter's TriggeredEffects root kinds:")
    biggest = max(enc_list, key=lambda e: enc(e))
    bk = Counter()
    for t in (biggest.get("TriggeredEffects") or []):
        bk[t.get("Event")] += 1
    a("    %s : %d triggers, events=%s" % (biggest.get("Id"), len(biggest.get("TriggeredEffects") or []),
                                           dict(bk)))

    # Encounter.Enemies schema
    en = EntityStats("Encounter.Enemies[]")
    for e in enc_list:
        for t in (e.get("Enemies") or []):
            en.add("x", t)
    en.report(out)
    hr = EntityStats("Encounter.HeroResources[]")
    for e in enc_list:
        for t in (e.get("HeroResources") or []):
            hr.add("x", t)
    hr.report(out)
    hs = EntityStats("Encounter.HeroStartingStatuses[]")
    for e in enc_list:
        for t in (e.get("HeroStartingStatuses") or []):
            hs.add("x", t)
    hs.report(out)

    ev = EntityStats("Event.situations[]")
    evc = EntityStats("Event.situations[].Choices[]")
    for eid, script in (doc.get("Events") or {}).items():
        for s in (script.get("situations") or []):
            ev.add(eid, s)
            for c in (s.get("Choices") or []):
                evc.add(eid, c)
    ev.report(out)
    evc.report(out)
    a("")
    a("choice Requirement occurrences: %d/%d ; Costs: %d/%d"
      % (sum(1 for s in (doc.get("Events") or {}).values() for sit in (s.get("situations") or [])
             for c in (sit.get("Choices") or []) if c.get("Requirement") is not None),
         evc.n,
         sum(1 for s in (doc.get("Events") or {}).values() for sit in (s.get("situations") or [])
             for c in (sit.get("Choices") or []) if c.get("Costs") is not None),
         evc.n))

    # ------------------------------------------- EnemyActions[].Intent
    a("")
    a("#" * 78)
    a("# 2b. EnemyActions[].Intent SCHEMA")
    a("#" * 78)
    intent = EntityStats("EnemyAction.Intent")
    ikinds = Counter()
    for act in doc["EnemyActions"]:
        i = act.get("Intent") or {}
        intent.add("x", i)
        ikinds[i.get("Kind")] += 1
    intent.report(out)
    a("Intent.Kind distribution: %s" % ", ".join("%s=%d" % kv for kv in ikinds.most_common()))

    # ------------------------------------------- tiny top-level sections
    a("")
    a("#" * 78)
    a("# 2c. SMALL TOP-LEVEL SECTIONS IN FULL (they are cheap to carry verbatim)")
    a("#" * 78)
    for key in ("SchemaVersion", "Deck", "Start", "MetaRules", "Characters", "ShredRules",
                "Balance", "MapGeneration", "Workbenches", "Recipes", "Map"):
        if key not in doc:
            continue
        v = doc[key]
        if key == "Map" and enc(v) > 4000:
            a("")
            a("---- %s (%d B, truncated) ----" % (key, enc(v)))
            a(pretty({k: (v[k] if not isinstance(v[k], (list, dict)) else
                          (v[k][:3] if isinstance(v[k], list) else dict(list(v[k].items())[:6])))
                      for k in v}, maxlen=3000))
            continue
        a("")
        a("---- %s (%d B) ----" % (key, enc(v)))
        a(pretty(v, maxlen=2200))

    # Map structure stats
    mp = doc.get("Map") or {}
    a("")
    a("Map sub-keys: %s"
      % ", ".join("%s=%s(%d B)" % (k, jtype(v), enc(v)) for k, v in mp.items()))
    if isinstance(mp.get("Nodes"), list):
        nodetypes = Counter()
        payloadkinds = Counter()
        for n in mp["Nodes"]:
            nodetypes[n.get("type")] += 1
            p = n.get("payload") or {}
            payloadkinds[(p.get("kind") if isinstance(p, dict) else None)] += 1
        a("Map.Nodes: %d nodes; by type: %s" % (len(mp["Nodes"]), dict(nodetypes)))
        a("Map.Nodes payload kinds: %s" % dict(payloadkinds))
    if isinstance(mp.get("Edges"), list):
        a("Map.Edges: %d" % len(mp["Edges"]))

    # Shops
    shops = doc.get("Shops") or {}
    a("")
    a("Shops keys: %s" % list(shops.keys()))
    for sid, s in shops.items():
        a("---- shop %s (%d B) ----" % (sid, enc(s)))
        a(pretty(s, maxlen=1500))

    # Presentation per-subsection bytes (the flat answer, not per id)
    a("")
    a("Presentation sub-section byte totals:")
    pres = doc.get("Presentation") or {}
    for k, v in sorted(pres.items(), key=lambda kv: -enc(kv[1])):
        n = len(v) if isinstance(v, (list, dict)) else 1
        a("    %-14s %-8s n=%-5d %8d B  avg=%d B"
          % (k, jtype(v), n, enc(v), enc(v) // max(1, n)))
    # and: how many are non-null / carry anything
    def pres_nonempty(v):
        return sum(1 for x in (v.values() if isinstance(v, dict) else [])
                   if any(y is not None for y in x.values())) if isinstance(v, dict) else 0
    for k in ("Cards", "Enemies", "Encounters", "Relics", "Statuses", "Events"):
        if isinstance(pres.get(k), dict):
            d = pres[k]
            nonempty = sum(1 for x in d.values() if any(y is not None for y in x.values()))
            a("    %-14s entries=%-5d with-any-field=%-5d (flavor-only=%d)"
              % (k, len(d), nonempty,
                 sum(1 for x in d.values() if set(x) <= {"FlavorText"} and x.get("FlavorText"))))

    # =====================================================================
    # PHASE 3 — the reference graph (who names whom)
    # =====================================================================
    a("")
    a("#" * 78)
    a("# 4b. DECLARED IDS + FOREIGN-KEY TRACE")
    a("#" * 78)

    declared = {}          # id -> kind
    def declare(i, kind):
        if isinstance(i, str) and i:
            declared.setdefault(i, kind)

    for c in doc.get("Cards") or []:
        declare(c.get("Id"), "Card")
        declare((c.get("Id") or "") + "+", "Card(upgrade)")
    for s in doc.get("Statuses") or []:
        declare(s.get("Id"), "Status")
    for ea in doc.get("EnemyActions") or []:
        declare(ea.get("Id"), "EnemyAction")
    for e in doc.get("Encounters") or []:
        declare((e.get("Id") or {}).get("Value"), "Encounter")
    for k in (doc.get("Events") or {}):
        declare(k, "Event")
    for r in doc.get("Relics") or []:
        declare(r.get("Id"), "Relic")
    for k in (doc.get("Shops") or {}):
        declare(k, "Shop")
    for ch in doc.get("Characters") or []:
        declare(ch.get("Id"), "Character")
    for n in ((doc.get("Map") or {}).get("Nodes") or []):
        declare(n.get("id"), "MapNode")
    for k in (doc.get("Workbenches") or {}):
        declare(k, "Workbench")
    for s in doc.get("Shreds") or []:
        declare(s.get("Id"), "Shred")
    # synthetic ids the content itself mints (reward tables, pool entries)
    for c in doc.get("Cards") or []:
        declare("card-" + str(c.get("Id")), "RewardEntry(synthetic)")

    a("declared ids: %d" % len(declared))
    bykind = Counter(declared.values())
    for k, c in bykind.most_common():
        a("    %-24s %d" % (k, c))

    # Walk and record every string leaf with its field name; classify.
    ref_by_field = defaultdict(Counter)     # field -> kind of the referenced entity
    unknown_by_field = defaultdict(Counter)  # field -> unknown string samples
    id_shaped = re.compile(r"^[a-z0-9_]+(\.[a-z0-9_]+)?$")

    def scan_leaves(node, field=None, parent_kind=None):
        if isinstance(node, dict):
            for k, v in node.items():
                scan_leaves(v, k, parent_kind)
        elif isinstance(node, list):
            for it in node:
                scan_leaves(it, field, parent_kind)
        elif isinstance(node, str):
            if node in declared:
                ref_by_field[field][declared[node]] += 1
            elif id_shaped.match(node) and len(node) > 3 and field not in (
                    "kind", "Cardinality", "RequiredContextCapabilities", "Op", "type",
                    "Polarity", "StackingBehavior", "TurnEndHandDestinationZone",
                    "PlayedCardDestinationZone", "ToZone", "FromZone", "Kind", "Element",
                    "Zone", "Axis", "Scope", "Pipeline", "Operation", "RestrictDamageKind",
                    "DamageKind", "LifecycleState", "CombatResult", "MovementMode",
                    "Placement", "Event", "WhenResult", "trigger", "event", "Rule"):
                unknown_by_field[field][node] += 1
    scan_leaves(doc)

    a("")
    a("field -> referenced entity kinds (only fields that actually reference something):")
    rows = []
    for f, c in ref_by_field.items():
        rows.append((sum(c.values()), f, c))
    for tot, f, c in sorted(rows, reverse=True)[:45]:
        a("    %-30s %5d refs -> %s" % (f, tot, dict(c)))

    a("")
    a("fields holding id-SHAPED strings that are NOT declared ids (synthetic / local / dangling):")
    rows = sorted(((sum(c.values()), f, c) for f, c in unknown_by_field.items()), reverse=True)
    for tot, f, c in rows[:25]:
        sample = ", ".join(list(c)[:4])
        a("    %-30s %5d distinct=%-5d  e.g. %s" % (f, tot, len(c), sample))

    # How many references does one card have? - impact analysis for a rename.
    a("")
    a("RENAME IMPACT: every place the literal string of a declared id occurs (field -> count)")
    a("(a rename must rewrite all of them; string identity is the ONLY link)")
    # duplicate declarations inside a section (a compiler must reject or define these)
    a("")
    a("DUPLICATE IDS inside one section (would collide in a u16 id table):")
    for key in ("Cards", "Statuses", "EnemyActions", "Relics", "Events", "Characters"):
        sec = doc.get(key)
        seq = sec if isinstance(sec, list) else (
            [{"Id": k} for k in sec] if isinstance(sec, dict) else [])
        ids = []
        for it in seq:
            i = it.get("Id") if isinstance(it, dict) else None
            if isinstance(i, dict):
                i = i.get("Value")
            ids.append(i)
        dup = [k for k, v in Counter(ids).items() if v > 1]
        a("    %-14s n=%-5d distinct=%-5d duplicates=%s" % (key, len(ids), len(set(ids)), dup or "none"))
    cards = doc.get("Cards") or []
    plus = [c.get("Id") for c in cards if str(c.get("Id")).endswith("+")]
    a("    Cards: %d total, %d upgraded ('+' suffix), %d base"
      % (len(cards), len(plus), len(cards) - len(plus)))
    base = {str(c.get("Id")).rstrip("+") for c in cards}
    a("    Cards: %d distinct base ids; %d have an upgraded variant"
      % (len(base), sum(1 for b in base if b + "+" in {str(c.get('Id')) for c in cards})))

    # How many references does one card have? - impact analysis for a rename.
    a("")
    a("RENAME IMPACT: every place one declared id's literal string occurs (field -> count)")
    a("(a rename must rewrite all of them; string identity is the ONLY link)")
    probe_ids = []
    for c in (doc.get("Cards") or [])[:1]:
        probe_ids.append(c.get("Id"))                      # a card
    for e in (doc.get("Encounters") or [])[:2]:
        probe_ids.append((e.get("Id") or {}).get("Value"))  # an encounter
    for s in (doc.get("Statuses") or [])[:1]:
        probe_ids.append(s.get("Id"))                       # a status
    for r in (doc.get("Relics") or [])[:1]:
        probe_ids.append(r.get("Id"))                       # a relic
    for pid in probe_ids:
        spots = Counter()
        def count_occurrences(node, field=None):
            if isinstance(node, dict):
                for k, v in node.items():
                    count_occurrences(v, k)
            elif isinstance(node, list):
                for it in node:
                    count_occurrences(it, field)
            elif isinstance(node, str) and node == pid:
                spots[field or "<root>"] += 1
        count_occurrences(doc)
        a("    %-32s total=%-4d %s" % (pid, sum(spots.values()),
                                       ", ".join("%s×%d" % kv for kv in spots.most_common())))

    # =====================================================================
    # PHASE 4 — which SECTION owns which node kind (who pays for the bytes)
    # =====================================================================
    a("")
    a("#" * 78)
    a("# 3c. NODE KIND x OWNING SECTION (which part of the document pays)")
    a("#" * 78)
    owner_kind = Counter()      # (section, kind) -> count
    owner_kind_bytes = Counter()

    def walk_owner(node, sec, depth=0):
        if isinstance(node, dict):
            if is_node(node):
                k = node["kind"]
                owner_kind[(sec, k)] += 1
                owner_kind_bytes[(sec, k)] += enc(node)
            for k2, v in node.items():
                walk_owner(v, sec, depth + 1)
        elif isinstance(node, list):
            for it in node:
                walk_owner(it, sec, depth + 1)

    for secname in doc:
        walk_owner(doc[secname], secname)

    a("%-16s %-32s %8s %12s" % ("section", "kind", "count", "bytes"))
    for (s, k), c in owner_kind_bytes.most_common(35):
        a("%-16s %-32s %8d %12d" % (s, k, owner_kind[(s, k)], c))
    a("")
    a("bytes by owning section (node trees only):")
    sec_bytes = Counter()
    for (s, k), b in owner_kind_bytes.items():
        sec_bytes[s] += b
    for s, b in sec_bytes.most_common():
        a("    %-16s %12d B" % (s, b))

    # The single biggest program: its node-kind histogram
    a("")
    a("BIGGEST SINGLE PROGRAM (the file's hot spot):")
    biggest = None
    for e in (doc.get("Encounters") or []):
        for tr in (e.get("TriggeredEffects") or []):
            p = tr.get("Program")
            if p is None:
                continue
            if biggest is None or enc(p) > biggest[0]:
                biggest = (enc(p), (e.get("Id") or {}).get("Value"), tr.get("Event"), p)
    if biggest:
        a("    encounter=%s event=%s program=%d B" % (biggest[1], biggest[2], biggest[0]))
        hist = Counter()
        def hist_node(n):
            if isinstance(n, dict):
                if is_node(n):
                    hist[n["kind"]] += 1
                for v in n.values():
                    hist_node(v)
            elif isinstance(n, list):
                for it in n:
                    hist_node(it)
        hist_node(biggest[3])
        a("    nodes=%d : %s" % (sum(hist.values()),
                                 ", ".join("%s=%d" % kv for kv in hist.most_common(10))))

    # ---------------- structural duplication: is the same body written twice?
    a("")
    a("STRUCTURAL DUPLICATION (identical subtrees written more than once):")
    import hashlib as _h

    def canon(o):
        return json.dumps(o, separators=(",", ":"), sort_keys=True, ensure_ascii=False)

    # (a) whole TriggeredEffects programs
    prog_hash = Counter()
    prog_bytes = {}
    for e in (doc.get("Encounters") or []):
        for tr in (e.get("TriggeredEffects") or []):
            p = tr.get("Program")
            if p is None:
                continue
            h = _h.sha1(canon(p).encode("utf-8")).hexdigest()
            prog_hash[h] += 1
            prog_bytes[h] = enc(p)
    dup = {h: c for h, c in prog_hash.items() if c > 1}
    wasted = sum(prog_bytes[h] * (c - 1) for h, c in dup.items())
    a("    encounter TriggeredEffects programs: %d distinct bodies, %d instances"
      % (len(prog_hash), sum(prog_hash.values())))
    a("    duplicated bodies: %d groups, %d redundant copies, %d B of identical JSON"
      % (len(dup), sum(c - 1 for c in dup.values()), wasted))
    if dup:
        top = sorted(dup.items(), key=lambda kv: -prog_bytes[kv[0]] * (kv[1] - 1))[:5]
        for h, c in top:
            a("        x%d  %d B each" % (c, prog_bytes[h]))

    # (b) every node subtree, across the ENTIRE document
    subtree = Counter()
    subtree_bytes = {}
    def hash_nodes(n):
        if isinstance(n, dict):
            if is_node(n):
                h = _h.sha1(canon(n).encode("utf-8")).hexdigest()
                subtree[h] += 1
                subtree_bytes[h] = enc(n)
            for v in n.values():
                hash_nodes(v)
        elif isinstance(n, list):
            for it in n:
                hash_nodes(it)
    hash_nodes(doc)
    dup2 = {h: c for h, c in subtree.items() if c > 1}
    wasted2 = sum(subtree_bytes[h] * (c - 1) for h, c in dup2.items())
    a("    all nodes: %d distinct subtrees, %d instances; %d duplicate groups"
      % (len(subtree), sum(subtree.values()), len(dup2)))
    a("    redundant bytes if every distinct subtree were stored once: %d B" % wasted2)
    a("    (total node-subtree bytes in the document: %d B)"
      % sum(subtree_bytes[h] * c for h, c in subtree.items()))

    # (c) THE ROM NUMBER: intern every distinct subtree once, children as 4-byte refs.
    #     cost = sum over distinct subtrees of (own fields, encoded) + 4 B per child edge.
    def node_arity(n):
        if not is_node(n):
            return 0
        body = n.get("value")
        k = 0
        if isinstance(body, dict):
            for kk, vv in body.items():
                if isinstance(vv, list) and vv and is_node(vv[0]):
                    k += len(vv)
                elif is_node(vv):
                    k += 1
        return k

    def own_enc(n):
        """Encode the node with every nested child replaced by null (so only its own fields count)."""
        def strip(x):
            if is_node(x):
                return None
            if isinstance(x, dict):
                return {k: strip(v) for k, v in x.items()}
            if isinstance(x, list):
                return [strip(v) for v in x]
            return x
        if isinstance(n, dict):
            return enc({k: strip(v) for k, v in n.items()})
        return enc(n)

    distinct = {}
    def collect(n):
        if is_node(n):
            h = _h.sha1(canon(n).encode("utf-8")).hexdigest()
            if h not in distinct:
                distinct[h] = n
        if isinstance(n, dict):
            for v in n.values():
                collect(v)
        elif isinstance(n, list):
            for it in n:
                collect(it)
    collect(doc)

    own_total = 0
    edge_total = 0
    for h, n in distinct.items():
        own_total += own_enc(n)
        edge_total += node_arity(n)
    a("")
    a("ROM ESTIMATE (every distinct effect-node shape stored ONCE, children as 4-B refs):")
    a("    distinct node shapes        : %d" % len(distinct))
    a("    own-field JSON bytes        : %d B" % own_total)
    a("    child edges                 : %d  x 4 B = %d B" % (edge_total, edge_total * 4))
    a("    => node table JSON-equivalent: %d B  (vs %d B of node subtrees in the file)"
      % (own_total + edge_total * 4, sum(subtree_bytes[h] * c for h, c in subtree.items())))
    a("    node-instance table         : %d instances x 2 B (u16 into the shape table) = %d B"
      % (sum(subtree.values()), sum(subtree.values()) * 2))

    # (d) distinct whole effect programs (the usual unit a content compiler interns)
    prog_distinct = {}
    def collect_prog(x):
        if isinstance(x, dict):
            if "Root" in x and "Id" in x and isinstance(x.get("Root"), dict):
                h = _h.sha1(canon(x["Root"]).encode("utf-8")).hexdigest()
                prog_distinct.setdefault(h, x)
            for v in x.values():
                collect_prog(v)
        elif isinstance(x, list):
            for it in x:
                collect_prog(it)
    collect_prog(doc)
    a("")
    a("distinct ROOT node trees in the whole document: %d (bytes once: %d B)"
      % (len(prog_distinct), sum(enc(v) for v in prog_distinct.values())))

    # =====================================================================
    # PHASE 5 — REDUNDANT `Children` VIEWS (the single biggest waste)
    # =====================================================================
    a("")
    a("#" * 78)
    a("# 5. REDUNDANT `Children` VIEWS (walkable second copy of nested nodes)")
    a("#" * 78)
    a("Every effect node exposes a `Children` view so the tree can be walked. On the")
    a("sequence-like nodes it IS the payload; on every other kind it is a second copy of")
    a("nested node-valued fields the node already writes (Then/Else/Body/Amount/TargetSelector).")
    a("See src/RogueDeck.Core/Combat/Serialization/CombatJson.cs:166-193.")
    a("")
    dupk = Counter()
    bothk = Counter()
    def scan_dup(x):
        if isinstance(x, dict):
            if is_node(x):
                body = x["value"]
                if isinstance(body, dict) and "Children" in body:
                    dupk[x["kind"]] += 1
                    if any(k in body for k in ("Then", "Else", "Body", "Condition",
                                               "Amount", "TargetSelector", "Left", "Right")):
                        bothk[x["kind"]] += 1
            for v in x.values():
                scan_dup(v)
        elif isinstance(x, list):
            for it in x:
                scan_dup(it)
    scan_dup(doc)
    a("nodes carrying a `Children` key            : %d" % sum(dupk.values()))
    a("of which Children duplicates named fields   : %d" % sum(bothk.values()))
    for k, n in bothk.most_common(12):
        a("    %-32s %d" % (k, n))

    KEEP = ("node.sequence", "node.causalSequence", "node.chooseOptions")

    def prune(x):
        if isinstance(x, dict):
            if is_node(x):
                body = {k: prune(v) for k, v in x["value"].items()}
                if x["kind"] not in KEEP:
                    body.pop("Children", None)
                return {"kind": x["kind"], "value": body}
            return {k: prune(v) for k, v in x.items()}
        if isinstance(x, list):
            return [prune(v) for v in x]
        return x

    pruned = prune(doc)
    a("")
    a("compact document                     : %d B" % grand)
    a("compact, redundant Children removed  : %d B  (saves %d B, %.1f%%)"
      % (enc(pruned), grand - enc(pruned), 100.0 * (grand - enc(pruned)) / grand))
    a("  as written on disk (x%.2f whitespace factor): ~%d B of %d"
      % (len(raw) / grand, (grand - enc(pruned)) * len(raw) // grand, len(raw)))
    pc = Counter()
    def cnt2(x):
        if isinstance(x, dict):
            if is_node(x):
                pc[x["kind"]] += 1
            for v in x.values():
                cnt2(v)
        elif isinstance(x, list):
            for it in x:
                cnt2(it)
    cnt2(pruned)
    a("node instances: %d -> %d" % (sum(node_count.values()) if node_count else -1,
                                    sum(pc.values())))
    a("per-section compact size before -> after:")
    for k in doc:
        if enc(doc[k]) != enc(pruned[k]):
            a("    %-16s %9d -> %9d B" % (k, enc(doc[k]), enc(pruned[k])))

    # ----------------------------------------------------------- writes
    txt = "\n".join(out)
    print(txt)


if __name__ == "__main__":
    main()
