"""§331 文档：事件级条件 + N'loth。"""

import io

PLAN = 'docs/port-plan.md'
GAPS = 'docs/event-gaps.md'
README = 'README.md'


def sub(t, old, new, label, count=1):
    n = t.count(old)
    assert n == count, '%s: %d (want %d)' % (label, n, count)
    return t.replace(old, new)


# ── port-plan ────────────────────────────────────────────────────────────────
t = io.open(PLAN, encoding='utf-8').read()
assert '## §331' not in t
t = t.rstrip('\n') + '\n' + """
## §331 事件级条件 + `N'loth`：事件侧最后两条机制缺口

`docs/event-gaps.md` §3 从 §318 起就写着这两条，现在都关掉了。

### 1. 事件级条件（"这条事件**出不出现**"）

`EventTables` 的条目原来只有 `MinFloor` / `MaxFloor` / `MinGold` 三个数。而 wiki 上有些事件的
**出现**本身有条件：

* `The Moai Head` —— 只在 **HP ≤ 50%** 时出现；
* `Tomb of Lord Red Mask` —— 只在**持有 `red_mask`** 时出现；
* `N'loth` —— 只在**至少 2 件遗物**时出现。

这三条原来要么"永远在池子里 + 选项被锁"，要么根本没做。前者**不是等价物**：一个用不上的事件
仍然会占掉一次 `?` 房，而那正是"事件级"与"选项级"的区别（也是分布上的区别）。

做法：

1. `EventTables` 的条目多一格 **`Requires`**，与**选项**的 `Requires` 是**同一个字段名、同一串
   原子**（`run_expr` 的 `KINDS`），所以求值只有一份实现；
2. 新增数值 kind **`relic_count`**（`N'loth` 的"≥2 件"）；
3. `content.rs` 加 `event_pool_at_with_facts`（`event_pool_at` 委托它、传 `None` = 不筛，
   存量调用与测试一个字都没改）；
4. `rd-wasm` 在 `?` 房改用带 facts 的那一个 —— **先筛后掷**的纪律不变（池子里有几个不改变
   筛掉几个之后的随机流位置）。

⚠️ 踩了两个坑，都记在这里：

* `option_is_available(content, term, facts)` 期望的是**选项节点自己的 term id**（它自己从那个
  节点上读 `Requires`），不是"`Requires` 那一格的列表 id"。传列表 id 会让整池变成 `None`，
  而 `None` 在调用方读作"内容里没有这个池"—— 报错看起来完全像内容缺池；
* 判据一开始用了 `tools/contentc/out/content.rdcf`，那是 **roguedeck** 包的镜像（没有
  `UnknownRooms`，也就没有事件）。sts 的镜像是 `packages/sts/out/content.sts.rdcf`。

### 2. `N'loth`：两件**随机候选**遗物

wiki 原文（`slaythespire.wiki.gg/wiki/N'loth`）：

> It will only appear if the player has **at least 2 Relics**.
> "Relic A" and "Relic B" will be **randomly chosen from the player's currently held Relics**.
> `[Offer: Relic A]` **Lose this relic.** Obtain a special relic. … Rewards `N'loth's Gift`.

所以它**不是**"玩家任选一件"，而是"系统掷两件、玩家二选一"。这比"任选"便宜得多：候选在
**开事件那一刻**定下来，两个选项是**固定的**，页面一行都不用改。

三块：

1. `EVND` 节点多一格 **`RelicOffer: N`**（这一段要掷几件候选）；
2. `rd-run` 存下这一掷（`event_relic_offer_ids` / `event_relic_offer_len`，进存档也进指纹），
   并让效果载荷 **`relic_lose:@N`** 在**应用时**解析成"第 N 件候选"（内容里写不出具体 id）；
3. `rd-wasm` 在 `begin_event` 之后用 `RunStream::Event` 掷（**拒绝采样**：只从"还没被选中"的
   那些里掷，于是"两件不同"由掷法保证，而不是掷完再去重 —— 后者会让分布偏向列表靠前的遗物），
   并把标签里的 `{0}` / `{1}` 换成那件遗物的**显示名**。

标签替换放在 **ABI** 里而不是页面：页面本来就是"读一段字节当按钮文字"，所以零改动；
"页面自己拼文案"是 §274 记过的那类重复。

### 3. 三个"批量改名"事故（都是同一类）

这一轮改 `event_offer_len` → `event_relic_offer_len` 时，一次 `replace` 把 §320 **卡牌**候选的
字段也改了，于是 `event_offer_len()` 返回遗物件数、`Pending::EventOffer` 永远不设 —— 三条既有
判据当场红（`two candidates come back: left 0`）。教训与 `FACT.md` §3 一致：
**改名要按"字段定义 + 每一处使用"逐个确认，不能对整份文件做全局替换**。

另外两处：`resolve_event_effects` 里照抄 §320 的"进这一段先清候选"，把**遗物**候选也清了
（于是 `relic_lose:@0` 永远解析不到，报 `UnsupportedEventEffect`）；常量 `MAX_EVENT_RELIC_OFFER`
一度被定义在两个 crate 里（现在只在 `rd-core::content`，`rd-run` 是 `pub use`）。

### 判据

* `event_level_requirements_filter_the_pool_before_the_roll`（rd-core）：Moai 在 50% / 51%
  两侧、Tomb 在有/无红面具两侧，外加"没有 `Requires` 的事件不受影响"与"不带 facts 不筛"；
* `nloth_offers_two_of_the_held_relics_and_takes_the_one_you_pick`（rd-wasm）：两件候选**不同**
  且都在手上、标签里 `{0}` 被换成**显示名**、点下去真的失去那一件并拿到 `N'loth's Gift`；
* `nloth_stays_out_of_the_pool_below_two_relics`（rd-wasm）：1 件时不在池子里、2 件时在。

负控 2/2：删掉 Tomb 的 `Requires` ⇒ `not in the pool at all`；把"清遗物候选"加回去 ⇒
`UnsupportedEventEffect`。

数字：`rd-core 813 / rd-run 214 / rd-wasm 181`、units **1208**（下限 1205 → 1208）、
事件 **36 条**（三幕池 13+15+11 = 39 条）；四条对拍不动。
"""
io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(t)
print('port-plan §331 ok')

# ── event-gaps：两条机制缺口划掉 ──────────────────────────────────────────────
g = io.open(GAPS, encoding='utf-8').read()
g = sub(g, "### 3.1 事件级条件：**部分有**，其余没有",
        "### 3.1 事件级条件：**已做**（§331）", 'gaps 3.1 head')
g = sub(g, """**还没有**的是另外几类：

* 遗物（`tomb_of_lord_red_mask` 要红面具）、
* HP 百分比（`the_moai_head` 要 ≤50%）、
* 牌组内容（没有 wiki 事件需要这条，但 `wing_statue` 是**选项级**的同类条件，已能做）、
* 计时（`secret_portal` 要"这一局已经 800 秒"）。""",
        """**§331 补上了 `Requires`**：`EventTables` 的条目现在可以带**一串原子**（与选项的 `Requires`
同一个词表），在**掷之前**筛池。已用在三个事件上：

| 事件 | 条件 | 原子 |
|---|---|---|
| `the_moai_head` | HP ≤ 50% | `health_percent at_most 50` |
| `tomb_of_lord_red_mask` | 持有红面具 | `relic has red_mask` |
| `nloth` | 至少 2 件遗物 | `relic_count at_least 2`（新 kind） |

**仍然没有**的：

* 计时（`secret_portal` 要"这一局已经 800 秒"）—— 运行层没有墙钟，而"回合数"不是同一个量；
* 牌组内容的事件级条件（目前没有 wiki 事件需要；`wing_statue` 是**选项级**的同类条件）。""",
        'gaps 3.1 body')
g = sub(g, "### 3.2 \"从手上任选一件遗物失去\"（`N'loth`）",
        "### 3.2 \"从手上任选一件遗物失去\"（`N'loth`）：**已做**（§331）", 'gaps 3.2 head')
g = sub(g, """需要一个**新的待决问句**：现在的 `PendingChoice` 有三类来源（手牌/弃牌堆/消耗堆/抽牌堆/三张候选），
**全是牌**。遗物问句与它同构（来源 + 候选 + `then`），成本主要在 ABI 与页面，不在内核。""",
        """⚠️ 原文把 wiki 记成了"任选一件"，其实 **`N'loth` 掷两件随机候选、玩家二选一**
（`Relic A` / `Relic B` 从当前持有的遗物里挑）。所以不需要新的"任选"问句：

* `EVND` 多一格 `RelicOffer: 2`，候选在**开事件那一刻**掷定（`RunStream::Event`，拒绝采样保证
  两件不同）；
* 效果载荷 `relic_lose:@0` / `@1` 在**应用时**解析成候选；
* 选项标签的 `{0}` / `{1}` 由 **ABI** 换成遗物显示名 —— 页面零改动。

顺带：`nloths_gift`（稀有牌概率 ×3）早在 §292 就实现了。""",
        'gaps 3.2 body')
io.open(GAPS, 'w', encoding='utf-8', newline='\n').write(g)
print('event-gaps updated')
