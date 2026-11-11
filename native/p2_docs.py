"""port-plan §356 + README：P2 第一步（WASM 适配器）。"""

import io

PLAN = 'docs/port-plan.md'
README = 'README.md'


def edit(path, old, new, label):
    t = io.open(path, encoding='utf-8').read()
    assert t.count(old) == 1, '%s: 命中 %d 次' % (label, t.count(old))
    io.open(path, 'w', encoding='utf-8', newline='\n').write(t.replace(old, new))


t = io.open(PLAN, encoding='utf-8').read()
anchor = '''### 残留

- **操作栏按整条带子预留**'''
assert t.count(anchor) == 1

addition = '''---

## §356 P2 第一步：WASM 适配器（`WasmHost` / `SnapshotReader` / `ActionDispatcher` / `GameStore`）

真的 wasm 装进来了。**没改内核、没改旧 `web/`**，主页面暂时仍吃 Mock（换数据源是第二步）。

| 文件 | 职责 |
|---|---|
| `wasm/host.ts` | **唯一**碰 `instance.exports` 的地方：装载校验（导出/长度/哨兵/指纹）、读文本、读观察、动作表、`step` |
| `wasm/snapshot.ts` | **纯函数**解码 148 格 → `CombatSnapshot`（不碰 wasm，所以能用合成向量穷举测） |
| `wasm/store.ts` | `GameStore` + `dispatch()`：前后各读一次观察向量并**比对**，把 `unchanged` 一起返回 |
| `p2probe.ts` / `p2.html` | 接线探针页：只做 ABI，不画 3D（与渲染分离，红了能看出坏在哪一层） |

**"拒绝不产生成功演出"不是靠信任内核** —— `dispatch()` 当场比对前后两条向量（§纪律 8）。

### 单一构建产物

`web-next` **不自己编译** wasm：`scripts/sync-wasm.mjs` 把 `web/rd_wasm.wasm`（唯一产物）复制进
`public/` 与 `dist/`，并记 sha256 到 `public/wasm.json`；闸门 28 断言 manifest 与源文件**同一份**。
`rd_wasm.wasm` 与 `wasm.json` 都不入库。

### 观察向量布局（148 格）与两条"空槽 vs 0"

头部 0–11 / 英雄状态 12–16 / 敌人 6×8 = 17–64 / 敌人状态 6×5 = 65–94 / 手牌 10×4 = 95–134 /
牌堆 5 = 135–139 / 保留 8 = 140–147。

1. **敌人槽 `-1` 才是"没有这个敌人"**，`alive = 0` 是"有但死了"；混起来会渲染出血量 0 的幽灵敌人。
   解码器额外校验"header 报的敌人数 == 扫出来的"，不符就 `RangeError`。
2. **没有战斗会话时整条向量是 0**（不是 -1）⇒ `snapshot()` 先问 `rd_env_active_slot() !== -3`，
   没有会话**拒绝解码**。

### 三个坑（都留了注释）

1. **`_into` 的参数顺序每个函数都不一样**：`rd_env_card_name_into(index, ptr)` vs
   `rd_run_boss_id_into(ptr)` vs `rd_run_deck_id_into(index, ptr)`。写死一种必然有一半调反
   （症状：`_into` 返回 -1，把槽位当成了指针）⇒ 改成传**闭包**。
2. **`memory` 是对象不是函数**："导出必须是函数"的检查对每一份 wasm 都报缺 `memory`。
3. **走到战斗不能"看到节点就 `begin_node`"**：`pending` 九档，第一版卡在 `pending = 7`（祝福选牌）。
   照 `ui_abi_dump.mjs` 的 `walkToFightNode` + `settleHere` 移植。

### 闸门 28 `ui-wasm`（10 条断言）

装载校验 / manifest 与源文件同 sha / 开局走到战斗 / 起手 5 张 80 血 3 能量 2 敌 / 费用不是 -1 /
**只有被指的敌人掉血**（28→22） / 能量按费用扣（3→2）且手牌数减一（5→4） / 越界动作 `-1` 且
**逐字节不变** / 结束回合后 round 1→2、hp 80→68 / **15 步打到 victory** 且终局动作表为空。

证据串：`UI_WASM PASS exports=234 content=0x54af44dd hand=5 enemies=2 steps=15 result=victory rejected-unchanged=1`

### 三条被我自己写错的断言（都值得记）

- "打出的那张牌离开了手牌"：打出槽 0 后手牌是 `[0,1,2,3]` —— **槽位是位置、被压实**，不是身份
  （Review P2-A 的 `handSlot ≠ CardInstanceId`）。改成"手牌数减一"。
- "回合数前进"：`endTurn` 后实测 `turn 1→1` 而 `round 1→2`（敌人行动过）。改成"时间或局面动了"。
- "被指的敌人掉血"：内核为"每张可出的牌 × 每个活敌人"都发动作，`(防御, 敌人0)` 也合法但不碰敌人
  ⇒ 要挑**文本里有 `damage`** 的牌。

### 数字

闸门 27 → **28**；`ui-pure` 证据加 `decode=8`（合成向量：头部/英雄/状态轴/空槽/X 费/牌堆/动作表/
计数不符抛错）；units 1233、导出 234、四条对拍不动。

### 残留

- **主页面换数据源**（`CombatView`）：`Stage`/`TextOverlay` 仍吃 `MockScene`；
- **`PendingChoice`（`rd_env_choice_*`）没接**：战斗中出现选牌时动作表为空，闸门 28 会标 `stuck` 并停
  （**不假绿**）；
- **Beat（1–13 类演出）没接**：UI 仍靠观察向量 diff；
- **同名卡 / X 费扣能量 / 0 能量 / 敌人槽位稳定性**的定向夹具还没写（plan P2 明确要求的那四条）；
- `web/` 仍可独立运行（这一步没碰它，四道旧 web 闸门复跑全绿）。

### 残留

- **操作栏按整条带子预留**'''

io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(t.replace(anchor, addition))

edit(
    README,
    '''**聚合验收**：28 道闸门''',
    '''**聚合验收**：28 道闸门''',
    'readme noop',
)

t = io.open(README, encoding='utf-8').read()
old = '**聚合验收**：27 道闸门（含 `coverage-matrix`、`state-fields`、`ui-state`、`ui-abi`、`ui-next` 与 `ui-pointer`），一道红就整体红'
new = '**聚合验收**：28 道闸门（含 `coverage-matrix`、`state-fields`、`ui-state`、`ui-abi`、`ui-next`、`ui-pointer`、`ui-pure` 与 `ui-wasm`），一道红就整体红'
assert t.count(old) == 1
t = t.replace(old, new)
old2 = '''**`ui-next-p1.md`**'''
new2 = '''**`ui-p2-adapter.md`**（**P2 第一步：WASM 适配器**：`WasmHost`/`SnapshotReader`/`ActionDispatcher`/`GameStore` 的职责边界、148 格观察向量布局、"空槽 -1 vs 计数 0"两条坑、`_into` 参数顺序不统一等三个坑、闸门 28 的 10 条断言；单一构建产物由 `scripts/sync-wasm.mjs` 复制并记 sha256）、**`ui-next-p1.md`**'''
assert t.count(old2) == 1
io.open(README, 'w', encoding='utf-8', newline='\n').write(t.replace(old2, new2))
print('docs updated')
