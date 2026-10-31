"""Append §161.3 to docs/port-plan.md (UTF-8, no BOM, LF)."""
import io

PATH = "docs/port-plan.md"

SECTION = """
### 161.3 一张牌的选择：`PendingChoice`（REVIEW §六 第 2 步）

评审 §四.2 的原话是：**"不要推倒现有 `Pending`。战斗侧补一个边界明确的待决操作即可，例如选牌来源、
最少/最多张数、选完后的操作。同一机制应能服务卡牌、药水和事件，并让合法动作可枚举、可存档、可回放。"**
验收标准也给了：**"再加一张同类卡或一瓶同类药时，主要改内容定义，不复制一套状态机。"**

这一节就是把那句话落成代码，并且**当场带上两个消费者**（Elixir、Gambler's Brew），否则它就是一段
没人用的框架。

#### 它为什么是状态，而不是一个 UI 回调

参考引擎的 `CardChooser` 是宿主委托（`CombatStateSnapshot.cs` 连它一起排除），因为那边是单人同步
程序：问一句、当场答。本项目要**存档、回放、训练**，所以"正在等玩家选牌"必须能从状态里读出来。
⇒ `CombatState.choice: Option<PendingChoice>`，`resolve_choice` 是唯一把它消掉的人。

⚠️ **它不进 `hash_golden`**：那是参考规范文本的逐字节复刻，参考没有这个字段，写进去就是伪造参考的
输出。它属于 `snapshot.rs` 那张"状态里有、指纹里没有"的清单（与 `mark_source_combatant_id`、
`CardPlayTurnStats` 同类），**`hash_full` 落地时必须覆盖它**。这也是加它一个基线都没动的原因
（`golden-baseline 129 行`、`corpus-roundtrip 85` 一字未变）。

#### 四个函数，一个问句

| | |
|---|---|
| `PendingChoice { chooser, source, min, max, then }` | 谁在选、从哪个牌区、几张、选完做什么 |
| `begin_choice` | 提出问题。三道前置拒绝：已有待决、`min > max`、`min` 超过来源牌区的张数 |
| `choice_legal(out)` | 把合法选项按**牌堆顺序**列出来（缓冲区装不下 ⇒ `Container::ChoiceOptions`，不截断）|
| `resolve_choice(picks)` | **全部校验在动手之前**，然后一次搬完 |

`chooser` 是字段而不是"默认英雄"：内核不假定谁在玩（`Combatstate` 里没有"玩家"这个概念）。

`ChoiceThen` 目前两个变体：`Exhaust`（Elixir）、`DiscardThenDraw`（Gambler's Brew）。每加一种药水
就多一个变体 —— **这是有意的**，动作的语义必须能被列出来，否则"合法动作可枚举"是空话。反过来说，
内容只挑变体，不各写一套状态机。

#### 三条纪律

1. **拒绝不改任何东西。** §161.2(a) 在战斗层的同一句话。判据 `a_refused_choice_leaves_the_combat_
   byte_identical` 用**规范文本**比较（`CombatState` 没派生 `PartialEq`：18 个字段里 6 个定容容器，
   逐字段写一份"等价"没法确认自己没漏）＋单独比 `pending_choice()`（规范文本不含 `choice`）。
   覆盖：张数越界、来源不对、重复选同一张、没有待决问句。
2. **选牌不嵌套。** 两个待决问句叠在一起，界面无法表达先后，回放也无法表达 ⇒ `AlreadyPending`。
3. **`min == 0` 时取消永远可用。** 不是方便，是语义：两瓶药的原文都是"any number"。

#### 一个被删掉的重复

`turn.rs::draw_for_turn_start` 里那个"抽满 / 重洗一次 / 两堆都空就停"的循环搬进了
`CombatState::draw_cards_with_reshuffle`，因为 `DiscardThenDraw` 成了它的**第二个**消费者。抄第二份
的后果可预测：两边的重洗策略会分叉，而"少重洗一次"只表现为某一步的 `step=` 与牌序不同 —— 那是最难
从失败信息里读回来的错。

#### ABI：8 个新导出 + 一个复用的牌区号

`rd_env_choice_{pending,kind,min,max,count,pick,selected,clear,confirm}`。

**选项不另起一套字符串读取器**：`rd_env_pile_*` 的 zone id 加了一个 `3 = 待决问句的来源牌区`，
所以选择界面用的是看牌堆**同一套**渲染。没有待决问句时 `rd_env_pile_len(3)` 返回 `-1`（不是 0 ——
"没有问句"和"问句的答案是零个"是两件事）。

`Session::choice_picks` 是**界面暂存，不是游戏状态**：内核的动作是"把整份选择一次交过来"，
所以半截选择不是存档要描述的东西，`resolve_choice` 才可能保持原子性。

三条缝合规则：

* `compute_actions` 在有待决问句时返回**空表** —— 出牌和结束回合都不是合法答案，列出来就是一张
  全都会被拒的表，而随机驱动会在"战斗看起来还活着"的情况下永远撞 `-1`；
* `rd_env_step` 在有待决问句时返回 `-1` 并**留下原因**（`还有一次待决的选牌没回答`）。守卫放在
  动作表查找**之前**，否则越界下标和"问句没答"都会是同一个没有理由的 `-1`；
* `rd_env_choice_confirm` 按**牌堆顺序**交牌，不按勾选顺序 —— 两个人用不同顺序勾了同样两张牌，
  要的是同一件事，回放不该在意。

#### 内容：22 瓶（C12 / U6 / R4）

`elixir`（Uncommon，Ironclad 专属）与 `gamblers_brew`（Uncommon）。两瓶的稀有度都是 wiki 上
`Potions` 表 + `Module:Potions/data` 两处独立来源核对的。

⚠️ **这次最值得记的不是功能，是一个"看起来没问题"的谎**：加了 `choice_hand_exhaust` 之后，
`rd_env_use_potion` 认识它、内容门认识它、页面也能用，但 `rd_run_potion_effect`（决定"要不要弹敌人
选择器"的那一个）把它归成 **`0 = unknown`**。**没有一条闸门会红** —— 页面的 `=== 1` 判断只是走了
另一个分支。抓到它的是一条新加的**穷尽**测试：`every_potion_in_the_table_classifies_as_known`
走完整张 `POT` 表（腰带三格，所以 逐瓶 push → 查 → 清），断言每一瓶都不是 `0`。同时它也断言
那两瓶归类成 `2`（作用于手牌，不要敌人目标）—— "已知"不等于"分对类"。

#### 验证

- `rd-core` 7 条 + 1 条（来源牌区）新测试；`rd-wasm` 2 条（端到端问句 + 词表穷尽）。
- **三条负控**（`native/negctl_161_choice.py`）：
  `vocab` 把两个原子从 `known` 里删掉 → 红在
  "`elixir` (choice_hand_exhaust) classifies as UNKNOWN"；
  `atomic` 把重复检查挪到搬牌之后 → 红在"被拒绝的选牌改了战斗"（left 里 `card_000001` 已经在
  `exh=` 里）；
  `trunc` 把 `choice_legal` 的拒绝改成 `break` → 红在 `left: Ok(2)` / `right: Err(Full(ChoiceOptions))`。
- **浏览器里一条确定性场景**（`browser_test` 第 (h) 段）：用新加的
  `RD_DEBUG.givePotion("elixir")`（底层是 `rd_run_grant_potion`，**调试专用**，理由与
  `startWithSeed` 同：不能指望 40% 掉率 × 22 瓶里的 2 瓶）把 Elixir 放上腰带，然后
  **只按页面上的控件**走：点"用" → 弹窗打开 → 点一张牌 → 点确认 → 消耗堆 +1、动作表 0 → 9。
  它还钉住**弹窗关不掉**（`closeModal` 在有待决问句时直接返回），因为"问句没答 + 动作表为空"
  就是一张没有出路的页面。
- 聚合验收 **18/18**；单测 764 → **774**（rd-core 632 → 640、rd-run 86、rd-wasm 46 → 48）。
  内容镜像 full **37,124 B** / core **30,604 B**。

#### 还差的（下一节）

| 要的东西 | 谁在等 |
|---|---|
| **每张牌自己的价格**（参考 `CardInstanceCostModifier` 读 `mark_counters` 里预留的那一格，钳到 0，被出牌消费）| Liquid Memories、Snecko Oil、Attack/Skill/Power Potion |
| **从卡池抽三张当候选**（`ChoiceSource::Offered`）| Attack / Skill / Power Potion |
| **无色牌池** | Colorless Potion |
| **`hash_full`**（`choice` 必须进去）| 训练状态去重 |
| 随机 soak **不认识选牌界面**（`choices 0`），覆盖率靠上面那条浏览器场景 | —— 一条已知缺口，不是"已完成" |

`ChoiceSource::DiscardPile` 今天**没有内容**（Liquid Memories 还差上面第一条），所以它由
`a_choice_reads_its_source_pile_instead_of_assuming_the_hand` 直接钉住：机制读 `source`，不是假定
`Hand`。留一个没测的变体才是错的；留一个测过、有明确下一节的变体是可以接受的。
"""


def main():
    with io.open(PATH, "rb") as handle:
        raw = handle.read()
    assert raw[:3] != b"\xef\xbb\xbf", "the plan is UTF-8 without BOM"
    text = raw.decode("utf-8")
    assert "### 161.3" not in text, "already appended"
    if not text.endswith("\n"):
        text += "\n"
    text += SECTION
    with io.open(PATH, "wb") as handle:
        handle.write(text.encode("utf-8"))
    print("port-plan.md now", len(text.split("\n")), "lines")


if __name__ == "__main__":
    main()
