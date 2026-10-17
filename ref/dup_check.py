"""Quick check: does the document carry duplicate 'Children' views on effect nodes?

If a conditional/forEach node serializes both Children AND Then/Else (or Body), every
subtree appears twice per level and the file is exponentially redundant.
"""
import json, sys
from collections import Counter

path = r"D:\Vibe\sts-tui\ref\RogueDeck-Core\src\RogueDeck.Sandbox.Run\SampleContent\bureaucrats.roguedeck.json"
doc = json.load(open(path, encoding="utf-8"))
out = []
a = out.append

def enc(o):
    return len(json.dumps(o, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))

def is_node(d):
    return isinstance(d, dict) and isinstance(d.get("kind"), str) and "value" in d

keys_by_kind = {}
count = Counter()
def walk(x):
    if isinstance(x, dict):
        if is_node(x):
            k = x["kind"]
            count[k] += 1
            body = x["value"]
            ks = tuple(sorted(body.keys())) if isinstance(body, dict) else ("<not-object>",)
            keys_by_kind.setdefault(k, Counter())[ks] += 1
        for v in x.values():
            walk(v)
    elif isinstance(x, list):
        for it in x:
            walk(it)

walk(doc)
a("node kinds seen (raw scan, counts EVERY dict carrying a 'kind'): %d kinds, %d instances"
  % (len(count), sum(count.values())))
a("")
a("body key-sets per kind (how a kind is actually shaped in this document):")
for k, _ in count.most_common():
    for ks, n in keys_by_kind[k].most_common(6):
        a("  %-32s %-58s x%d" % (k, ",".join(ks), n))
a("")

# Now: total nodes reachable as a TREE, descending into every node-valued field,
# but visiting each *object* at most once by id() -> true graph node count.
seen = set()
tree_kinds = Counter()
dup_view = Counter()
def tree(x, parent_kind=None, field=None):
    if isinstance(x, dict):
        if is_node(x):
            if id(x) in seen:
                return
            seen.add(id(x))
            tree_kinds[x["kind"]] += 1
            if "Children" in x["value"] and any(
                k in x["value"] for k in ("Then", "Else", "Body", "Condition", "Left", "Right")):
                dup_view[x["kind"]] += 1
        for k, v in x.items():
            tree(v, x.get("kind") if is_node(x) else parent_kind, k)
    elif isinstance(x, list):
        for it in x:
            tree(it, parent_kind, field)

tree(doc)
a("unique node OBJECTS reachable by graph walk: %d" % sum(tree_kinds.values()))
a("  (raw scan counted %d dicts => %d are the SAME object reached twice, i.e. shared, not copied)"
  % (sum(count.values()), sum(count.values()) - sum(tree_kinds.values())))
a("")
a("kinds whose body carries BOTH Children and a named child field (duplicate view in the wire form):")
for k, n in dup_view.most_common():
    a("    %-32s x%d" % (k, n))
a("")

# Byte cost of the duplication: re-encode with every duplicate Children removed.
def prune(x):
    """Drop the walkable `Children` view everywhere it is NOT the node's own payload.

    Children is the payload only on the sequence-like nodes (their constructor takes it);
    everywhere else it is a second copy of nested node-valued fields already written."""
    if isinstance(x, dict):
        if is_node(x):
            body = {k: prune(v) for k, v in x["value"].items()}
            if x["kind"] not in ("node.sequence", "node.causalSequence", "node.chooseOptions"):
                body.pop("Children", None)
            return {"kind": x["kind"], "value": body}
        return {k: prune(v) for k, v in x.items()}
    if isinstance(x, list):
        return [prune(v) for v in x]
    return x

pruned = prune(doc)
a("compact document                    : %d B" % enc(doc))
a("compact, ALL redundant Children gone: %d B  (saves %d B, %.1f%%)"
  % (enc(pruned), enc(doc) - enc(pruned), 100.0 * (enc(doc) - enc(pruned)) / enc(doc)))
a("  in the file as written (x%.2f whitespace factor): about %d B of the %d-byte file"
  % (len(open(path, "rb").read()) / enc(doc),
     (enc(doc) - enc(pruned)) * len(open(path, "rb").read()) // enc(doc),
     len(open(path, "rb").read())))
a("")
pruned_count = Counter()
def walk2(x):
    if isinstance(x, dict):
        if is_node(x):
            pruned_count[x["kind"]] += 1
        for v in x.values():
            walk2(v)
    elif isinstance(x, list):
        for it in x:
            walk2(it)
walk2(pruned)
a("node instances in pruned doc: %d (was %d)" % (sum(pruned_count.values()), sum(count.values())))
a("top kinds after pruning: %s"
  % ", ".join("%s=%d" % kv for kv in pruned_count.most_common(14)))
a("")
a("per-section sizes after pruning:")
for k, v in pruned.items():
    a("    %-16s %9d B  (was %9d B)" % (k, enc(v), enc(doc[k])))

print("\n".join(out))
