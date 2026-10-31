"""Append §160 + a review-response section to docs/port-plan.md (UTF-8, no BOM, LF)."""
import io

PATH = "docs/port-plan.md"

SECTION = """
---

## 160. 回应外部评审：三个真缺陷 + 一个"不在切口之前"的守卫

`docs/vibe/advices-from-chatgpt-261031.md` 是一份外部评审（它自己声明"未在本机复跑测试"）。
这一节把它点名的**源码级**指控逐条对过码，然后修掉了三条**今天就是错的**。

### 160.1 逐条核对结果（六条全中）

| 评审条目 | 核对 | 结论 |
|---|---|---|
| **P0** 商店购买不是原子的 | `buy_card` / `buy_relic` 先 `adjust_gold` 再 `push_*?`，满容量时 `Capacity` 已扣钱 | **真的** |
| **P1** 运行层池仍静默截断 | `take(MAX_POOL)` / `.min(MAX_POOL)` 共 **7 处**（1784/1846/1849/1854/1923/2174/2415） | **真的**（今天不可达：20/13/30 vs 64）|
| **P1** Eternal Feather 整除顺序 | `amount * deck_len / 5` | **真的**（8 张给 4，应给 3）|
| **P1** Eternal Feather 触发点 | 塞在 `rest_heal()` 里，而它只在 `rest()` 调用；`smith()` 不治疗 | **真的**，而且 wiki 原文就写着 "Heal applies **on entering**" |
| **P1** `eternal_feather` 稀有度 | wiki 导航盒与 patch 注记：**Uncommon**（"from Boss -> Uncommon"）；内容是 `Rare` | **我们错** |
| **P1** `golden_idol` 该不该进掉落池 | wiki 导航盒把它列在 **Event**；内容是 `Rare`，于是 17% 的稀有档里混进一件事件遗物 | **我们错** |
| clippy 闸门没有 `-D warnings` | `clippy --all-targets … -MustMatch 'Finished'` | **真的**（§160.5 说明为什么还没开）|
| `static mut` 别名是**已经发生过**的事故 | `run.rs:67-69` 的注释写着访问违例 `0xC0000005` | **真的** |

后两条不是新发现，是**已经在 `port-plan` 里写过的教训**（§158.5 的死测试、§151 的 `fail()`），评审只是从代码里也读到了。

### 160.2 P0：购买只有一个提交点，而且失败的那一半在前

`push_card` / `push_relic` 自己先校验再写，失败时什么都不动 —— 所以**调换顺序就是完整修复**
（`adjust_gold` 不会失败）。没有引入事务框架，也没有复制一份容量判断。

判据 `a_refused_purchase_leaves_the_run_untouched`：牌组填到 `MAX_RUN_DECK` 后买卡必须 `Capacity`
**且金币一分不动、货架价不变**；遗物栏同理。负控：把顺序改回去 ⇒ 红在**金币**上（451 vs 499），
不是红在错误码上 —— 后者会让人以为"测试只是没覆盖"。

### 160.3 P1：Eternal Feather 的三件事，一次修完

1. **整除**：`amount * (deck_len / 5)`。分段函数的边界（5/8/9/10/14）逐个钉住 —— §157 只测了 10 张，
   而 10 张两种写法都是 6，所以全绿。**这不是测试太少，是分段函数只测了整档。**
2. **触发点**：进入篝火时付，所以 **Smith 也吃到**。`rest_heal()` 现在只剩"30% + Regal Pillow"，
   进入时那笔是 `rest_site_entry_heal()`，在 `begin_node` 的 `NodeKind::Rest` 分支里付。
   这是"遗物要绑生命周期、不要绑看起来相关的计算函数"的第一个实例。
3. **稀有度**：`Rare` → `Uncommon`（wiki）。

### 160.4 P1：`Rarity::Event` —— "不可掉落"终于能说出口

`golden_idol` 原来只能靠"写个假的稀有度"来表达 event-only，于是它进了 17% 的稀有档。
新增 `Rarity::Event`，并把规则收在**一处**：`relic_rarity_is_droppable` 只认
`RELIC_RARITY_WEIGHTS` 里的档，`pick_relic_avoiding` 在抽权重**之前**就把不可掉落的条目滤掉。

⚠️ 只加枚举值是不够的：只有事件遗物的池子会走到 `pick_rarity → None → unwrap_or(pool[0].rarity)`，
照样把事件遗物发出去。所以过滤必须在候选表构建时，而不是靠权重表"恰好抽不到"。
判据 `an_event_relic_is_never_drawn`：纯 Event 池 20 次全给 `RunId::EMPTY`，混合池 40 次只给 `anchor`。

### 160.5 没有照做的一条：`clippy -D warnings`

方向对，但**今天开不了**：树上有 6 条既有警告，其中三条值得先看清楚再决定怎么消：

* `host.rs:399/401` 的 **`unreachable pattern`**：`"StatusRemoved"` 与 `"StatusApplicationPrevented"`
  各被写进两个 `|` 分支 —— 后一个分支永远不匹配。这可能只是重复，也可能是**想映射到另一个事件**写错了。
* `intent.rs:824` 的 `unreachable pattern`：`unsupported` 兜底分支被前面 7 个分支全盖住，
  意味着"未知条件种类"其实走不到"响亮拒绝"那条路。
* 其余三条（`unused doc comment` / `unused variable` / `unused_mut`）是纯噪音。

先把这三条查清（尤其第二条：它关系到"未知条件是不是真的会报错"），再开 `-D warnings`。
顺序反了就会为了变绿灯而把警告消音，那比没开更糟。

### 160.6 采纳但本轮不做的（按评审自己的优先级）

* **L2 性质测试**：最值得做的一条，而且它正好能抓住 §160.2 那类 bug（"拒绝不改状态"就是不变量）。
  它的具体清单（拒绝不改状态 / 生命在区间内 / 卡牌不无故增减 / 同一奖励不能领两次 /
  卸下的遗物不再生效 / 每条内容可达 / 同种子同动作序列同结果）可以直接变成 7 条 property test。
* **`MAX_POOL` 静默截断（7 处）**：改成"超容 ⇒ `Err`"，今天不可达但形状和 §158 一样。
* **`begin_node` 里那笔治疗要不要"只付一次"**：现在由 `Pending::Rest` 的相位保证（一个节点只结算一次），
  没有单独的 `mark_rest_entered` 标志 —— 评审担心的重复付账在现有相位下走不到，但值得一条负控。
* `docs/status.md`：同意，但**只加一份**。评审建议三份（status / roadmap / architecture），
  三份就是三个会腐烂的新副本；现在的 `port-plan` 已经太长，再加两份短文档解决不了"哪个为准"。
  一份 `docs/status.md`（当前能力 + 最近验证 + 已知缺陷 + 指针到 plan 的节号）就够。

### 160.7 明确不同意的一条

评审第七节建议"暂时放下 `no_std` / 零堆分配 / 极小 WASM / ESP32-P4 适配"。
这是**产品决策**，不是工程发现，而且和这个项目的原始目标（"跑在 ESP32 这种嵌入式平台上" +
"多开当 RL 环境"）冲突。更重要的是：这些约束已经**付过账**（`forbid(unsafe_code)`、定容表、
纯整数），现在拆掉它们是纯支出、零收益。评审自己也留了台阶（"不必反向推翻能工作的固定数组"），
所以更准确的说法是它第二条的样子：**不要再为了省字节新增容量体操** —— 这一点完全同意，
`MAX_POOL = 64` 那 7 处静默截断就是容量体操留下的债。

### 160.8 数字

聚合验收 **18/18**；单测 758 → **761**（rd-core 632、rd-run 80 → **83**、rd-wasm 46）。
内容：13 遗物 = **C7 / U4 / R1 / Event 1**（`eternal_feather` 进 Uncommon，`golden_idol` 进 Event）。
⚠️ **Rare 只剩 1 件**，所以 17% 那一档每次都只能是它 —— 这是内容缺口（缺稀有遗物），不是 bug，
但它现在**看得见**了，这正是 §156 让稀有度落进内容表的目的。
"""

with io.open(PATH, "rb") as handle:
    raw = handle.read()
assert raw[:3] != b"\xef\xbb\xbf", "the plan is UTF-8 without BOM"
text = raw.decode("utf-8")
assert "## 160." not in text, "already appended"
if not text.endswith("\n"):
    text += "\n"
text += SECTION
with io.open(PATH, "wb") as handle:
    handle.write(text.encode("utf-8"))
print("port-plan.md now", len(text.split("\n")), "lines")
