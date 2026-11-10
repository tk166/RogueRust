"""§339 内容侧：Moai 的 OR、Tomb 的反向资格 + 选项互斥。

## Moai Head（八轮 Review 2.2）

wiki: *"It can only be encountered if the player either has Golden Idol, **or** their HP is at or
below 50%."* 现状只有 `health_percent at_most 50` ⇒ 满血 + 持有 Golden Idol 的玩家遇不到。

改成 `RequiresAny`（组内 OR）—— 见 `run_expr.rs` 的 §339。

## Tomb of Lord Red Mask（八轮 Review 2.3）

现状两处都错，而且**互相掩盖**：

1. **事件级** `Requires: relic has red_mask` ⇒ **没有**面具的玩家永远遇不到这个事件，
   而 wiki 里"献出全部金币换 Red Mask"正是**获得**这件遗物的唯一途径之一 ⇒ 死内容。
   wiki 里这个事件的出现**没有任何条件**（Act 3 事件池的普通一员）。
2. **选项级** `Offer all Gold` 只查 `gold at_least 1`，不查"没有面具" ⇒ 持有面具的玩家
   既能 `[Don the Red Mask]`（+222 金）又能再献一次金币拿**第二个** Red Mask。

wiki 的两屏是互斥的：有面具 ⇒ `[Don the Red Mask] / [Leave]`；没面具 ⇒
`[Locked] Requires: Red Mask / [Offer: X Gold] / [Leave]`。所以我们给
`Offer all Gold` 加 `relic lacks red_mask`（`PRESENCE_OPS` 本来就认 `lacks`）。
"""

import io
import json

PATH = 'tools/contentc/packages/sts/sts.roguedeck.json'


def load():
    return json.load(io.open(PATH, encoding='utf-8'))


def save(doc):
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')


doc = load()

# ── ① Moai Head：事件级 AND → OR ──────────────────────────────────────────────
moai = None
for entry in doc['EventTables']['Events3']:
    if entry.get('Id') == 'the_moai_head':
        moai = entry
assert moai is not None, 'the_moai_head 不在 Events3 里'
assert moai.get('Requires') == [
    {'Kind': 'health_percent', 'Op': 'at_most', 'Amount': 50}
], '现状变了：%r' % (moai.get('Requires'),)
# 删掉 AND 那一组，换成 OR 组（wiki 的 "either … or …"）。
del moai['Requires']
moai['RequiresAny'] = [
    {'Kind': 'health_percent', 'Op': 'at_most', 'Amount': 50},
    {'Kind': 'relic', 'Op': 'has', 'Id': 'golden_idol'},
]

# ── ② Tomb of Lord Red Mask：事件级条件**整个删掉** ───────────────────────────
tomb = None
for entry in doc['EventTables']['Events3']:
    if entry.get('Id') == 'tomb_of_lord_red_mask':
        tomb = entry
assert tomb is not None, 'tomb_of_lord_red_mask 不在 Events3 里'
assert tomb.get('Requires') == [
    {'Kind': 'relic', 'Op': 'has', 'Id': 'red_mask'}
], '现状变了：%r' % (tomb.get('Requires'),)
del tomb['Requires']

# ── ③ 选项级互斥：`Offer all Gold` 只在**没有**面具时可用 ────────────────────
node = None
for event in doc['EventNodes']:
    if event.get('Id') == 'tomb_of_lord_red_mask':
        node = event
assert node is not None, 'tomb_of_lord_red_mask 不在 EventNodes 里'
offer = None
for option in node['Options']:
    if option.get('Label') == 'Offer all Gold':
        offer = option
assert offer is not None, 'Offer all Gold 选项不见了'
assert offer.get('Requires') == [
    {'Kind': 'gold', 'Op': 'at_least', 'Amount': 1}
], '现状变了：%r' % (offer.get('Requires'),)
offer['Requires'] = [
    {'Kind': 'gold', 'Op': 'at_least', 'Amount': 1},
    # ★ 与 `[Don the Red Mask]` 互斥：两屏在 wiki 里是二选一，不是"都能点"。
    {'Kind': 'relic', 'Op': 'lacks', 'Id': 'red_mask'},
]

save(doc)
print('content: moai RequiresAny, tomb unconditional, offer lacks red_mask')
