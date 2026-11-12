"""port-plan §361：第十四轮 Review 的 5 项处置。"""

import io

PLAN = 'docs/port-plan.md'
DOC = 'docs/ui-p2-adapter.md'


def edit(path, old, new, label):
    t = io.open(path, encoding='utf-8').read()
    assert t.count(old) == 1, '%s: 命中 %d 次' % (label, t.count(old))
    io.open(path, 'w', encoding='utf-8', newline='\n').write(t.replace(old, new))


t = io.open(PLAN, encoding='utf-8').read()
anchor = '''### 残留

- **X 费扣能量**没有真夹具（见上）；'''
assert t.count(anchor) == 1

addition = '''---

## §361 第十四轮 Review 的五项处置

审阅在 `472b500..8383837` 上提了 3 个 P1 + 若干 P2。逐条核实后**全部成立**（唯一"冲突"是 n=4，
见 §361.5）。其中 P1-A 我复现到了用户可见的后果，这是本轮最值钱的一条。

### 1. P1-A：动作枚举的 `targetSlot` 不是卡牌的目标声明 ✅ 实证

**症状（真 wasm + 真浏览器）**：`defend` 的动作是 `targetSlots=[0,1]`（内核为"每张可出的牌 ×
每个活敌人"各发一条，因为它无法廉价判断定向性）⇒ 视图 `targeted=true` ⇒ **把「防御」拖到空白处
被回弹**：能量 3→3、格挡 0→0、手牌 5→5。真内核下**所有无目标牌都要求拖到敌人身上**。

**修法**：`native/build_zh_i18n.py` 同时生成 `web-next/src/view/cardMeta.ts`：
`id → { kind, targeting }`。

* `kind` 来自 `Cards[].Tags`（attack 96 / skill 135 / power 44 / status 6 / curse 14）；
* `targeting` 来自卡牌程序里有没有 **`sel.eventTarget`**（"作用于被选中的那个目标"），
  与 `sts/content/cards.json` 的显式 `target` 字段对拍 **10/10 一致**；
* `optionsFor` 对 `targeting === "none"` 的牌把内核过度枚举的多条动作**归并成一个代表动作**
  （`actionIndex` 取第一条真实动作，**不虚构** `targetSlot = -1` 的内核条目）。

`guessKind()` 整个删掉（P2-B 同一条修法）。

**闸门 29 新增三条**：手牌里同时存在 `targeted=false`/`true`；无目标牌拖空白处**生效**
（block 0→5、手牌 5→4）；定向牌拖空白处**回弹**（能量/手牌不变）。

### 2. P1-D：拒绝语义 ✅

`dispatch()` 的 `unchanged` 只覆盖 **148 格观察向量**，不覆盖随机数/内部实例/未导出字段 ——
注释里"一个字节都不改"是夸大，已改成"可观察向量逐字节不变"，并写明完整原子性只有 Rust 侧的
`hash_full` 能证明。

`App` 现在按返回码分支：

| 情形 | 处理 |
|---|---|
| `accepted` | 播 beat 文案 |
| `rejected && !unchanged` | **契约级错误**：`GameStore.isContractViolation()` ⇒ 冻结操作（`fatal` 状态）+ 显示诊断 |
| `broken` | 冻结 + "内核驱动坏了，不是玩家操作问题" |
| `-2`（已结束） | "战斗已经结束" |
| 其它拒绝 | "动作被拒绝（状态未改变）" |

### 3. P2-A：wasm sha **运行时**比对 ✅

`WasmHost.load(url, { manifestUrl })` 取同目录 `wasm.json`，把清单里的 sha256 与**实际字节**比对；
缺失或不等都拒绝装载并给出可操作的原因。`npm run dev` 改成 `node scripts/sync-wasm.mjs && vite`
（开发时不会静默载入旧副本）。

**闸门 28 负控**：把清单 sha 改成全 0（Blob URL 注入）⇒ 装载被拒绝，错误里含"不是同一份构建产物"。

### 4. P2-D / P2-E ✅

* `rd_env_enemy_overflow()`（敌人 > 6、向量装不下）现在被 `snapshot()` 消费：返回 1 就**拒绝解码**并
  报"无法完整显示"。⚠️ 解码器只比对"header 敌人数 == 槽位数"，两者都会是 6 ⇒ **发现不了溢出**，
  必须在进解码前问。
* `ChoiceModal`：`selectedCount > max` 时禁止确认、到上限后禁用未选项、显示"最多只能选 N 张"；
  文件头那句"kind 只有三个值"改成十种（实际早就十种）。

### 5. P1-B：手势版本校验 ✅

`GameStore.stateEpoch`：接受的动作、选牌确认、`refresh()` 各 +1。`App` 在按下时冻结 epoch，
松手时先比 epoch、再比四元组 `(index, kind, handSlot[, targetSlot])`，不匹配就**取消手势**。

⚠️ `targetSlot` **只对定向牌比**：无目标牌的动作被内核过度指定了敌人槽（防御是 0/1），而状态机的
业务目标是 `-1` —— 拿 `-1` 去比会把每一次正常出牌都判成"过期"（第一版就是这么红的）。

**闸门 29 新增**：按住一张牌 → 期间 `endTurn()` 换版（epoch 2→3）→ 松手在敌人身上 ⇒
**不出牌**（能量 3→3）。

### 6. P1-C：横屏 n=4 回到 2+2 ✅

`singleRow` 从 `n <= 4` 改成 **`n <= 3`**（一排最多 3 名）。n=4 → 2+2、5 → 3+2、6 → 3+3。
闸门 27 断言"n=4 恰好 2+2"、"每排 ≤ 3"、"n=2 同排且 x 分开"。

### 数字

闸门 **31** 不变；`ui-wasm-ui` 断言 14 → **20 条**（P1-A 三条 + P1-B 三条 + 既有）；`ui-pure` 仍
`rows=4`（含义改成"n=4 是 2+2"）；`ui-wasm` 加清单负控；units 1233、导出 234、四条对拍不动。

### 残留

- **X 费扣能量**没有真夹具（见上）；'''

io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(t.replace(anchor, addition))

edit(
    DOC,
    '''## 6. 还没做的''',
    '''## 5e. 第十四轮 Review 的处置（§361）

审阅提的 3 个 P1 全部成立，其中 **P1-A 复现到了用户可见后果**：真 wasm 下「防御」拖到空白处被回弹
（能量/格挡/手牌都不变），因为内核为"每张可出的牌 × 每个活敌人"各发一条动作，而 UI 拿
`some(targetSlot >= 0)` 反推"要不要目标"。

**根因一句话**：动作枚举的 `targetSlot` 不是卡牌的目标声明，是内核的**枚举策略**。

修法：`build_zh_i18n.py` 同时生成 `view/cardMeta.ts`（`id → {kind, targeting}`）——
`kind` 来自 `Tags`，`targeting` 来自程序里有没有 `sel.eventTarget`（与仓库旧内容的显式 `target`
字段对拍 10/10 一致）。无目标牌的多条动作**归并成一个代表动作**（不虚构 `targetSlot=-1`）。

其余四项：拒绝语义按返回码分支（`rejected && !unchanged` = 契约级错误，冻结界面）、
wasm sha **运行时**比对（`load()` 读 `wasm.json`；`dev` 先同步）、消费
`rd_env_enemy_overflow()`、`ChoiceModal` 查上限、手势 `epoch` 版本校验（松手时四元组不匹配就取消）、
横屏 `n=4` 回到 2+2。

## 6. 还没做的''',
    'doc 5e',
)
print('docs updated')
