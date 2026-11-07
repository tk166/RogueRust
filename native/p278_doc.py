"""§278 文档：port-plan 新一节 + §277 分析文档"缺口一已做" + 缺口表 + README。"""
import io

PLAN = 'D:/Vibe/sts-tui/docs/port-plan.md'
ANALYSIS = 'D:/Vibe/sts-tui/docs/mechanism-gaps-analysis.md'
GAP = 'D:/Vibe/sts-tui/docs/sts-wiki-gap.md'
README = 'D:/Vibe/sts-tui/README.md'

DOC = """
---

## §278 `EVND` 事件**段表**（事件是一棵树）+ 两个百分比原子

§277 的分析文档（`docs/mechanism-gaps-analysis.md`）把"事件剧情分支被合并"列为**表达不了**的缺口：
`EV` 行是"两段文本 + 两串效果"，而真实 StS 的事件是**一棵树**（一段文本 → 若干选项 →
每个选项可能换来**另一段文本**，再给选项）。`golden_idol` 的 Outrun/Smash/Hide 三选一
就是被这套结构压掉的（旧内容把它写成"遗物 + 诅咒"，再给一个 A15 的"遗物 + 20 伤害"）。

这一节把缺口补上。

### 278.1 格式：`FORMAT_VERSION` 7 → 8，`EV` 缩成入口

```
EV   row = Id | NameKey | Entry        (8 B, 3 格)   -- 只是"从哪一段开始"
EVND row = Id | TextKey | Options      (8 B, 3 格)   -- 一段：正文 + 选项列表
EVND.Options[i] = { Label, Effects, EffectsAsc, Next }
```

* 选项是 **term 列表**，所以**选项数不再固定 2**（`golden_idol` 的第二段是三选一）。
  `MAX_EVENT_OPTIONS = 4` 是容量、不是规则，超了**报错**不截断（截断会让第 4 个按钮静默消失）。
* `Effects` / `EffectsAsc` 复用 §188 的形状（`[{Effect, Amount}]`），`Next` 空 = 终点。
* 段号 **17**（`S_EVND`），`nsec` 20 → 21。这是**唯一**一种"旧读取器不可能看起来正常"的改动：
  `EV` 行宽从 20 B 掉到 8 B，旧读者会把第一个节点 id 当成正文读出来 —— plausibly wrong，
  所以宁可升版本号让 `UnsupportedVersion(7)` 响亮。

### 278.2 ★ 迁移是机械的，判据是"语义快照逐字段相同"

`native/p278_migrate.py`：11 个旧事件 → 11 个入口 + 11 个段（每个段的两个选项 = 原来的两个）。
它先抓一份**语义快照**（id / 名字 / 正文 / 每个选项的标签+效果+A15），迁移后再抓一份，
**比对整份快照**。没有这一步的话，"迁移写错了"与"内容本来就这样"长得一模一样。
（脚本幂等：有 `Entry` 的行直接跳过。）

### 278.3 ★ 一处 shape 变了，四处读取器跟着红

| # | 位置 | 症状 |
|---|---|---|
| 1 | `content.rs::Content::event` | `description_key` / `label0` 这些 getter 不存在了（编译期就红，最好的一种） |
| 2 | `content.rs::option_list` | **运行时**：每段都是"有正文、0 个选项" |
| 3 | `content.rs::effect_list` | 同上：每个选项都是"0 条效果" |
| 4 | `rdcf_verify` / `manifest` / 内容门 / 覆盖矩阵 | 各少一张表/一个键 |

第 2、3 条是**同一个错的两种面孔**：`Effects` 在镜像里是 **`F_TERMLIST`**（kind 5：起点 + 条数），
不是 `F_TERM`。用 `field()` 读它会拿到"一个节点"，而错误的形状在这里**只会安静地变成空列表**。
修法：解包交给 `ir::NodeRef::term_list_field`（它本来就负责这件事），读取器只解释元素。

★ 另一处值得单独记：`option_list` 第一版**只填数组、没写条数**，而我在调用处写了句
"`option_list` 已经把条数写进 `count`"。它没有 —— 于是每段都是 0 个选项。
**注释声称的不变量，必须有代码或判据在后面撑着**，否则它就是一份假文档。

### 278.4 `golden_idol` 现在是**真树**（wiki 两屏 + 三选一）

```
golden_idol           "An idol of gold sits on a mossy altar."
  Take it   → relic:golden_idol        → golden_idol.boulder
  Leave it  → nothing                    (终点)
golden_idol.boulder   "…a giant boulder smashes through the ceiling…"
  Outrun    → curse:injury               (wiki 没有 A15 变体)
  Smash     → damage_pct:25   / A15 35%  (25% 最大 HP，A15 35%)
  Hide      → max_hp_pct:8    / A15 10%  (8% 上限，A15 10%)
```

数值取自 `slaythespire.wiki.gg/wiki/Golden_Idol_(Event)` 与 `slayspiredb.com` 的逐屏表
（**两个独立来源一致**：Take → 巨石屏；Outrun = Injury；Smash 25%(35%)；Hide 8%(10%)，
下限 1）。旧内容写的 `damage 20` 恰好等于 80 上限的 25%，所以它在旧 fixture 上"看起来对" ——
换一副牌就不对了，这正是"把百分比写成定值"的症状。

### 278.5 两个**百分比**原子（闭词表扩容）

| content says | means |
|---|---|
| `damage_pct:<n>` | 掉 `floor(max HP × n / 100)` 血（A15 走 `EffectsAsc`，是**另一条效果**而不是同一个数字换值） |
| `max_hp_pct:<n>` | 扣 `max(1, floor(max HP × n / 100))` **上限**，并把当前 HP 夹住 |

* 数字在**词里**（`Amount` 格必须是 0），内容门会拒 `Amount != 0`。理由：A15 的 35% 与 25% 是
  两条不同的效果句子，把数字放进 `Amount` 就得让"同一个效果词"在两处各有一个数字，而那两处
  一定会漂。
* 取整是 `floor`（整数算，内核不碰浮点）；`max_hp_pct` 的下限 1 与"上限不许变 0"是本内核的
  决定（0 上限会让下一次百分比恒为 0）。
* **ABI 的 `rd_run_event_amount_at` 改成读"效果真正会用的数字"**（解一次词）：
  否则百分比选项在页面上显示成"按上限 0% 受伤" —— 内容格是 0，而词里是 25。

### 278.6 运行层：`event_step` 是**状态**，不是推导

`RunState` 新增两个字段：

* `event_step: RunId` —— 这个事件**现在在哪一段**。它是局面的一部分（同一句
  `event=golden_idol` 可以是两个完全不同的屏幕），所以进 `run_hash`（`event_step=` 一行）。
* `event_next: RunId` —— 只在 `Pending::EventCard`（欠一次牌组编辑）时用：编辑完再去下一段。

`begin_event(id, entry)` 收**两个**参数：run 层**不读内容**（§133 的纪律），入口由调用方给。
`resolve_event_effects(effects, next, pool)`：`Some(next)` ⇒ 应用完效果**留在** `Pending::Event`、
房间**不结算**；`None` ⇒ 照旧收尾。

⚠️ **一个相位顺序的坑**：`rd_run_choose` 原来先取"有没有这个选项"再判相位。事件收尾后
`event_step` 是空的 ⇒ 取不到选项 ⇒ 返回 `-1`（"没有这个选项"），而契约是 `-2`（"相位没了"）。
两者对页面是不同意思（-1 是内容错，-2 是按钮该消失）。修法：**相位先判**。

### 278.7 判据 + 负控

| 判据 | 钉住 |
|---|---|
| `the_unknown_room_events_are_readable` | 每个事件的入口段读得出来、**每段 ≥2 个选项**、`Next` 必须存在、**没有孤儿段**（`reached.len() == event_step_count()`）、`golden_idol` 两段三选一 + 两个百分比 |
| `an_event_tree_advances_one_step_at_a_time` | 走第一段后 `event_step` 换成第二段、`Pending` 仍是 `Event`；走完最后一段才清空 + 相位关闭 |
| `losing_max_health_by_percent_never_goes_below_one` | `max_hp_pct` 扣的是上限、当前 HP 夹住、上限不许到 0 |
| `a_malformed_next_step_is_refused_before_anything_moves` | 坏 id 整个局面不动一个字节（⚠️ 只可能拒**形状**：存在性归内容门） |
| `a15_swaps_the_event_effect_list` | 走完两段：Smash 25%/35%、Hide 8%/10%、Outrun 无 A15 变体，最后一段才结算 |
| 内容门 `[6c]` | 11 房间 → 12 段、25 选项、44 效果（17 条在 A15 列表里）、孤儿段/坏 Next/坏百分比/坏入口各红一次 |

**负控**（`native/p278_negative.py`，改 JSON → 重编 → 跑门 → 还原）：孤儿段 / 坏 `Next` /
`damage_pct:0` / 入口指向不存在 —— 四条全 RED ✓（判据是**红在这一处**，不是"红了几条"）。

### 278.8 账

镜像 **149,528 B**（core 115,844 B）；`EVND` 12 行 × 8 B；`EV` 11 行 × 8 B（原 20 B）；
`rd-core` **791** / `rd-run` **149** / `rd-wasm` 124；`rdcf-verify` **8/8 tables, 16 count×stride**；
内容门 `STS_CONTENT PASS`；五道页面门 + SOAK 全过；21/21。

⚠️ 三处手抄常量这一节动了：`acceptance.ps1` 的 `7/7 tables`→`8/8`、`14`→`16`;
`content.rs` 的 `CORE_SECTIONS`/`FULL_SECTIONS` 从 manifest **重生成**（不再手抄）；
`verify_bytes.py --repin`（编译器改动是**故意**的，理由就是本节）。
"""


def main():
    plan = io.open(PLAN, encoding='utf-8').read()
    io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(plan.rstrip('\n') + '\n' + DOC)

    a = io.open(ANALYSIS, encoding='utf-8').read()
    a = a.replace('''### A 的具体改动清单''', '''### ✅ 状态：**方案 A 已落地**（`port-plan.md` §278）

`EVND` 段 + `EV.Entry` 已经做了，11 个旧事件机械迁移（语义快照逐字段比对），
`golden_idol` 补成真树（两段 + 三选一）。**方案 B（条件选项）仍未做** —— 见下面的清单。
下面保留当时的分析原文，作为"为什么这么加"的记录。

### A 的具体改动清单''')
    io.open(ANALYSIS, 'w', encoding='utf-8', newline='\n').write(a)

    g = io.open(GAP, encoding='utf-8').read()
    g = g.replace('''| 真实事件的**剧情分支**被合并（Golden Idol 三选一只有两个） | "事件的第 N 段"这个实体（`EV` 行是"两段文本 + 两串效果"） | `EVND` 节点表（每选项多一格 `Next`），`EV` 行退化成入口；再做条件选项 |''',
              '''| ~~真实事件的**剧情分支**被合并~~ | **§278 已做**：`EVND` 段表（`Options` 是 term 列表 ⇒ 选项数不固定）+ `EV.Entry`；`golden_idol` 已补成两段三选一（含 `damage_pct`/`max_hp_pct` 两个百分比原子）。**条件选项（`Requires`）仍未做。** |''')
    io.open(GAP, 'w', encoding='utf-8', newline='\n').write(g)

    r = io.open(README, encoding='utf-8').read()
    r = r.replace('（主计划 §1–§277）', '（主计划 §1–§278）')
    io.open(README, 'w', encoding='utf-8', newline='\n').write(r)
    print('§278 doc + analysis status + gap row + README')


main()
