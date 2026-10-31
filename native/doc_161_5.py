"""Append §161.5 to docs/port-plan.md (UTF-8, no BOM, LF)."""
import io

PATH = "docs/port-plan.md"

SECTION = """
### 161.5 三张候选：`ChoiceSource::Offered`（Attack / Skill Potion）

§161.3 的机制留了一个位置给"候选不是牌堆的一部分"。这一节把它填上。

#### 候选是**定义**，不是实例 —— 而且这不是省事，是正确

最省事的做法是先造三张牌塞进一个牌区（`SetAsidePile`），选完把两张扔掉。**没这么做**，理由是
**指纹**：那三张牌会进 `card_num=` 和三条卡行，而参考引擎里那个局面**根本没有它们** ——
一张还没进游戏的牌不该出现在哈希里。所以候选是三条 `CardDefinitionId`，被选中的那一张在
`resolve_choice` 里**才**被造出来，没被选的两张从来没存在过。

这条判据是 `an_offered_choice_creates_only_the_card_that_was_picked`：提问前后 `card_count()` 不变，
回答之后**只多一张**，发号器只动 1。

#### 顺带把"铸号"收成一件事

`Offered` 需要内核造卡，而铸号此前只在 `exec.rs`（`CreateCardInstance` 节点）里。§161.5 把
`numbered_text` + `create_card_instance` 搬进 `state.rs`（发号器本来就在那里），`exec.rs` 改成调用 ——
**两条铸号路径会给出两个"下一个是几"**，而每条路径单独看都是对的。

#### 答案有两种形状，因为它们回答两个不同的问题

```rust
pub enum ChoiceAnswer<'a> {
    Instances(&'a [CardInstanceId]),   // Hand / DiscardPile：这些实例里选哪些
    Offered(&'a [usize]),              // Offered：这三张里要哪个下标
}
```
形状与来源不匹配 ⇒ `WrongAnswer`。对应的读取器也分成两个：`choice_legal`（牌区，返回实例）与
`choice_offered`（候选，返回定义），**各自只回答一种形态**，而不是一个函数返回一个"看情况"的联合体。

`ChoiceSource::zone()` 因此变成 `Option<CardZone>` —— 这是**编译期接缝**：加 `Offered` 时它逼着
每个读者回答"候选从哪来"，而不是把候选当成一个空牌区。它当场抓出两处（`rd_env_choice_count` 与
`rd_env_choice_confirm` 的牌区读取）。

#### 抽三张是谁的事

**按标签过滤是内容的事**（哪些牌算 Attack 写在 `CARD.Tags` 里），**抽三张不重复是运行层的事**
（它持有 RNG，`RunState.rng` 私有正是为了让"谁推进了哪个流"只有一处）。所以
`rd-run` 新增 `draw_distinct(pool, count, out)`，用 `RunStream::Reward`（"从卡池取牌给你挑"和卡奖励
是同一件事的两半；`Potion` 那个流已经用来决定"掉不掉药水"，混用会让掉率与"抽到哪三张"互相干扰）。

池子比 3 短时返回实际张数，**要不要拒绝由调用方决定** —— 而调用方拒绝得**响亮**：
候选不足三张时这瓶药**不被消耗**并报出张数。

#### 内容：25 瓶（C14 / U7 / R4）

`attack_potion`、`skill_potion`（都是 Common）。**Power Potion 故意没加**：本内容
`power` 标签的牌是 **0 张**，凑不出三张候选。内容门加了一条判据把这件事变成闸门：
`choice_offered:<tag>` 要求至少 **3 张**带这个标签的牌，否则红 ——
"加了一瓶药但它给不出承诺的东西"正是本项目最怕的那种安静的死按钮。

#### 一个被自己的测试抓到的语义

端到端测试第一次红在 `confirm` 返回 `-2`：抽到的候选里有 `anger`（印刷 **0** 费）与 `whirlwind`
（X 费）。两件事分开处理：

* **0 费不是错误**：这瓶药承诺的"它这次免费"**已经成立**，`-0` 的折扣是正确答案；
* **X 费说不出口**：它走 `x_cost_payment`（全部能量），`Costs` 表对它没有意义 ⇒ 加在上面的 delta
  看不见。这种**拒绝并让问句留着**，页面提示"换一张"。

#### 页面的句子是两个字段的函数

`kind` 只有三个值，而"从弃牌堆拿一张"与"从三张候选里选一张"是同一个 `then = ToHand`。第一版
用 `kind` 写句子，于是 Attack Potion 弹出了"从弃牌堆拿一张回手牌"。所以新增
`rd_env_choice_source()`（`1` 牌堆 / `2` 候选），句子从 `(source, kind)` 两个数来。

#### 验证

- `rd-core` +3 测试（只造一张 / 两种答案形状不能互换 / 候选与来源必须一致）、`rd-wasm` +1（Attack
  Potion 端到端：三张**定义**、提问不造牌、每个候选都是 attack 且三张互异、回答后只多一张、
  屏幕上 0、内核真的收 0）。
- **负控**（`native/negctl_164.py pregrow`）：把"只造选中那一张"改成"三张全造" ⇒ 红在
  `ChoiceDone { picked: 3 } vs { picked: 1 }`。
- 浏览器第三条确定性场景（`browser_test` 第 (j) 段）：`givePotion("attack_potion")` → 用 →
  标题"从三张候选里选一张加进手牌（它这次免费）· 1 张" → 三张候选**都渲染出名字** → 选一张 →
  确认 → 手牌 +1、手牌里出现一张 0 费。
- 聚合验收 **18/18**；单测 779 → **787**（rd-core 643 → 647、rd-run 86、rd-wasm 50 → 51 → 再加
  内容门那条）。镜像 full **37,612 B** / core **31,088 B**。

#### 还差的

| 要的东西 | 谁在等 |
|---|---|
| **我们的内容没有 `power` 牌**（0 张） | Power Potion |
| 无色牌池 | Colorless Potion |
| 战斗中升级手牌 | Blessing of the Forge |
| **整手牌**改费（Snecko Oil 是"随机化手牌费用"，不是每副本价格）| Snecko Oil |
| 自动打出牌堆顶 / 打两次 | Distilled Chaos、Duplication Potion |
| 死亡拦截 / 逃跑 | Fairy in a Bottle、Smoke Bomb |
| `hash_full`（`choice` 要进去）| 训练状态去重 |
| 随机 soak 仍不认识选牌界面 | 已知缺口，覆盖率靠 `browser_test` 三段确定性场景 |
"""


def main():
    with io.open(PATH, "rb") as handle:
        raw = handle.read()
    assert raw[:3] != b"\xef\xbb\xbf", "the plan is UTF-8 without BOM"
    text = raw.decode("utf-8")
    assert "### 161.5" not in text, "already appended"
    if not text.endswith("\n"):
        text += "\n"
    text += SECTION
    with io.open(PATH, "wb") as handle:
        handle.write(text.encode("utf-8"))
    print("port-plan.md now", len(text.split("\n")), "lines")


if __name__ == "__main__":
    main()
