"""Append §161.7 to docs/port-plan.md (UTF-8, no BOM, LF)."""
import io

PATH = "docs/port-plan.md"

SECTION = """
### 161.7 三张 Power 牌 + Power Potion（补内容，顺带两处"内容在说谎"）

§161.5 结束时的清单上，Power Potion 的缺口写着"本内容 0 张 `power` 牌"。这一节补内容：
**Inflame / Metallicize / Combust** —— 都是三口铁甲战士真实的能力牌，数字取
`docs/spec/sts-act1-inventory.md` 的第二列（5→7、2→3、3→4）。

`docs/spec/` 的清单**早就有这三行**，内容一直没跟上 —— 内容门那条 `cards.ids` 精确比对
（`INV_CARDS` 的 dict 是**逐牌事实契约**，不只比 id）就是为这种漂移准备的：加完牌它立刻红一次，
提醒我把六行事实写进去。

#### 加内容这件事本身几乎没写代码

三张牌的节目都是 `node.applyStatus`（`sel.source`，和 `buffer` 同一个形状），所以这一节**没有**
新增任何内核能力。唯一的代码改动是一行 **`+` 行过滤**（见下）。

#### 抓到的第一处谎：Combust 不掉血

`standard.combust` 的 `TurnEnded` 触发只做了"对全体敌人造成 N 伤害"，而牌面（以及清单里那个
`hp-loss-trigger` 标记）写着"**lose 1 HP** and deal 5 damage"。补上后是
`sequence([loseHp(1), dealDamage(allEnemies, stacks)])`。

"lose 1 HP"用的是 `sel.source` + `IgnoresBlock: true` —— 这不是新发明的形状：
`standard.constricted`（§147）就是这么写的，而 `IgnoresBlock` 正是"掉血"与"受伤"的区别。

#### 抓到的第二处谎（差点自己制造）：Metallicize **是宿主步骤**

`standard.metallicize` 的 `Triggers` 是 `null`。我据此判定"它什么都不做、`Heart of Iron` 从 §158
起就在发一个装饰性 buff"，于是给它加了一条 `TurnEnded` 触发 —— **这是错的**：

`host.rs:1192` 在回合结束的宿主步骤里**硬编码**了它（连同 `standard.plated_armor`），那是照参考实现
搬过来的（Metallicize 在参考里是一个 `TurnEndedHandler`，不是声明式触发，`port-plan.md` §112）。

加了触发就是**双重支付**，而挡住它的是两条既有测试：
`metallicize_grants_block_at_the_end_of_the_turn`（红在
`Exec(Expr(Ir(Missing("StatusId"))))` —— 我把字段名写成了 `StatusDefinitionId`，`combust` 那条写的是
`StatusId`）与 `plated_armor_and_metallicize_both_pay_block_at_turn_end`。

⇒ 已回滚，并且这条要记住：**"内容里没有触发"不等于"它什么都不做"** —— 也可能宿主步骤在管。
判断一个状态是不是死的，要 grep 内核，而不是只看 `Triggers`。

#### 抓到的第三处谎：候选池里混着 `+` 行

`choice_offered:attack` 会把 `twin_strike+` 当候选发出去。StS 的 Attack Potion 给的是**印刷牌**
（升级版不在卡池里，是升级造出来的）—— 给一张更强的牌是"承诺得更少、给得更多"，属于安静的那种错。
我们的升级约定是 id 加 `+`，所以过滤就一行；**是 power 牌让这件事第一次看得见**（三张基础牌
加三张 `+` 行，抽三张必然混进升级行）。

#### 内容门的两张表也跟着走

* `INV_CARDS` 多了六行（3 张牌 + 3 个 `+`），每行带**事实**（`("status", id, stacks, "source")`），
  门会重新读节目核对。
* `INV_POTIONS`/band 的口径：**26 瓶（C15/U7/R4）**。

#### 验证

- `rd-wasm` +1：Power Potion 端到端 —— 三个候选**恰好**是 `combust` / `inflame` / `metallicize`、
  都不带 `+`、都真的打了 `power` 标签；选 `inflame` 之后它是 0 费，打出后英雄拿到 **2 点力量**。
  （这是"同形状的药水只是内容改动"这句话的判据。）
- 词表穷尽测试扩到 `power_potion`；`every_potion_in_the_table_classifies_as_known` 仍然全绿。
- 聚合验收 **18/18**，单测 783 → **784**（rd-core 647、rd-run 86、rd-wasm 50 → 51）。
  镜像 full **38,384 B** / core **31,728 B**；卡 **36 张**（30 + 6 个 power 行）。

#### 还差的

| 要的东西 | 谁在等 |
|---|---|
| 无色牌池 | Colorless Potion |
| 战斗中升级手牌 | Blessing of the Forge |
| 整手牌改费 | Snecko Oil |
| 自动打出 / 打两次 | Distilled Chaos、Duplication Potion |
| 死亡拦截 / 逃跑 | Fairy in a Bottle、Smoke Bomb |
"""


def main():
    with io.open(PATH, "rb") as handle:
        raw = handle.read()
    assert raw[:3] != b"\xef\xbb\xbf", "the plan is UTF-8 without BOM"
    text = raw.decode("utf-8")
    assert "### 161.7" not in text, "already appended"
    if not text.endswith("\n"):
        text += "\n"
    text += SECTION
    with io.open(PATH, "wb") as handle:
        handle.write(text.encode("utf-8"))
    print("port-plan.md now", len(text.split("\n")), "lines")


if __name__ == "__main__":
    main()
