"""Append §161.4 to docs/port-plan.md (UTF-8, no BOM, LF)."""
import io

PATH = "docs/port-plan.md"

SECTION = """
### 161.4 一张牌自己的价格：`standard.card_cost_delta`

评审第 2 步的另一半是"通用决策"之后的**动作语义**。这一节做"每副本价格"，因为它是三瓶药的共同缺口，
而参考实现**已经有答案**：`Cards/CardInstanceCostModifier.cs:13-34` 读的是卡实例上的一个 mark
counter，`StandardCombatIds.cs:93` 叫 `standard.card_cost_delta`。

#### 一件事值得先说：费用那半边**早就写好了**

`play.rs` 的 `CostStage::CardInstance`（priority 1100）从 §88 起就在读那一格、逐阶段 `.max(0)`
钳位。所以这一节**没有**动费用计算 —— 缺的是三件别的事：

| 缺的 | 谁补的 |
|---|---|
| 没人**写**这一格 | `resolve_choice` 的 `cost_delta` 参数（§161.3 的机制 + §161.4 的语义） |
| 没人**消费**它（`Cards/CardPlay.cs:176-183`）| `apply_plan_in_chain` 付款之后置 0 |
| 没人**显示**它 | `refresh_hand` 的代价列加上同一个增量 |

第四件是**新的 `then`**：`ChoiceThen::ToHand`（第三个消费者，Liquid Memories）。

#### 为什么它必须是"每张牌"的

状态是**按持有者**定价的（"你的技能牌便宜 1"），而"你刚拿回来的那张牌这次免费"是一个只属于**那一张
副本**的承诺 —— 它得跟着那张牌穿过手牌、弃牌堆、抽牌堆。参考的注释把这句话写得很清楚：*"a promise
made to one card, which has to travel with that card through the draw pile and the hand"*。

⚠️ **与 StS 的差别（写明了的偏差）**：StS 的 "costs 0 **this turn**" 在回合结束时过期，而参考的模型
是"**被出牌消费**" —— 一张没被打出的折扣牌会一直带着它。我们照参考实现：给回合结束加一次清除等于
发明一条参考没有的规则（§159.3 的教训是"不要实现一个关于不存在的**事件**的分数"）。这条偏差由
`the_per_copy_price_is_consumed_by_the_play` 的第二段钉住（打完再打一次是原价）。

#### 一个被 §161.4 **照出来的旧 bug**（这次最值钱的东西）

写完 `liquid_memories` 的端到端测试，它红了：屏幕上显示那张牌 0 费，内核却收了 1 点能量。

查下去发现不是价格的问题：`Step::HeroPlays` 是参考的形状 —— **按卡定义 id 找手里第一张**
（`ScenarioRunner.cs:109-111`，因为它的场景脚本是文本、没有实例号）。而页面是**按手牌位置**点的。
同定义的两份副本在参考那里不可区分，所以这条一直没露出来 —— **§161.4 的每副本价格是第一个让
"哪一张"变得有意义的东西**，于是它立刻变成一个死按钮：一张带折扣的 `strike` 排在普通 `strike`
后面时，玩家点了它，引擎打了前面那张。

修法是**加一个新的 step**，不动旧的：

* `Step::HeroPlays` 含义**冻着**（四条对拍流水线驱动它，改语义会移动基线）；
* `Step::HeroPlaysInstance { card: CardInstanceId, .. }` 是页面用的那一个，找不到那一份副本时报
  `CardNotInHand` —— **绝不**退回按定义找（那会把"这个位置空了"变成"打了别的一张牌"）。

顺带删掉了 `step_play` 里每步 `Box::leak` 一个定义串的写法（现在不需要字符串了）。

#### 内容：23 瓶（C12 / U7 / R4）

`liquid_memories`（Uncommon，shared）：*"Choose a card in your discard pile and return it to your
hand. It costs 0 this turn."* 稀有度同样用 `Potions` 表 + `Module:Potions/data` 两处独立来源核对。

#### 三处"同一个词表"的第三份

这一节又一次踩到了 §161.3 的教训，但这次**是被闸门抓住的**：加 `choice_discard_to_hand` 时，
`tests[cargo]` 里立刻红了三处（`known` 清单、内容门的 `POTION_CHOICE_KINDS`、
`the_potions_are_readable` 的白名单），而不是安静地少一处。§161.3 那条**穷尽**测试
（`every_potion_in_the_table_classifies_as_known`）现在也覆盖它，并且断言它落在 `2`（不要敌人目标）。

#### X 费牌：一个说不出口的折扣

X 费牌的代价走 `x_cost_payment`（**全部当前能量**），`Costs` 表对它没有意义 ⇒ 一个加在 `Costs` 上的
delta **看不见**。于是 Liquid Memories 选到 X 费牌时**拒绝**并保持问句不动，页面提示"换一张"：

```text
这张牌没有可取消的印刷费用（X 费牌按全部能量结算），换一张
```

静默地按原价把牌交过去，是"屏幕上写着免费、实际收全部能量"的另一种形状。

#### 验证

- 新测试 5 条：`rd-core` 3（每副本价格写进实例 / 给没有价格的 `then` 传价格被拒 /
  **按实例打牌打的是那一张**）、`rd-wasm` 1（Liquid Memories 端到端：问句、`min = 1` 的空答案被拒、
  屏幕上的 0、内核真的收 0、价格只兑现一次）、另有 §161.3 那条穷尽测试扩到三瓶。
- **两条负控**（`native/negctl_164.py`）：
  `price` 删掉"付款后置 0" → 红在"价格必须在**付款之后**消费掉"（left `-1` / right `0`）；
  `display` 删掉显示侧那一格 → **浏览器闸门**红在
  "no card in hand reads 0 after Liquid Memories (costs [2,1])" —— 屏幕说 1、内核收 0。
- 浏览器里第二条确定性场景（`browser_test` 第 (i) 段）：`givePotion("liquid_memories")` → 点"用" →
  标题是"从弃牌堆拿一张回手牌（它这次免费）· 1 张" → 不选就确认被内核拒（`-2`，问句还在）→
  选一张 → 确认 → 手牌里出现一张 0 费 → 打它，能量一动不动。
- 聚合验收 **18/18**；单测 774 → **779**（rd-core 640 → 643、rd-run 86、rd-wasm 48 → 50）。
  镜像 full **37,296 B** / core **30,776 B**。

#### 还差的

| 要的东西 | 谁在等 |
|---|---|
| **从卡池抽三张当候选**（`ChoiceSource::Offered` + 建卡实例 —— 内核不铸实例号，所以这活在 `rd-wasm`）| Attack / Skill / Power Potion |
| 无色牌池 | Colorless Potion |
| **整副手牌改费**（Snecko Oil 是"随机化手牌费用"，不是每副本价格）| Snecko Oil |
| 战斗中升级手牌 | Blessing of the Forge |
| `hash_full`（`choice` 要进去）| 训练状态去重 |
| 随机 soak 仍不认识选牌界面 | 已知缺口，覆盖率靠 `browser_test` 两段确定性场景 |
"""


def main():
    with io.open(PATH, "rb") as handle:
        raw = handle.read()
    assert raw[:3] != b"\xef\xbb\xbf", "the plan is UTF-8 without BOM"
    text = raw.decode("utf-8")
    assert "### 161.4" not in text, "already appended"
    if not text.endswith("\n"):
        text += "\n"
    text += SECTION
    with io.open(PATH, "wb") as handle:
        handle.write(text.encode("utf-8"))
    print("port-plan.md now", len(text.split("\n")), "lines")


if __name__ == "__main__":
    main()
