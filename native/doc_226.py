"""§226 docs."""
import io

ROOT = 'D:/Vibe/sts-tui/'

SECTION = '''
---

## §226 复制载体（`Dual Wield`）+ 让内容知道"哪一张是自己"（`Second Wind` / `Fiend Fire` 归正）

两件事，一件是**加载体**（§225.4 留下的第一件事），一件是**把一条声明的偏差修掉**。

### 226.1 「自己」与「整手牌」：只加一个**只读**事实，不动快照

§225 里 `Second Wind` 给 10 格挡（wiki 5）、`Fiend Fire` 打 21（wiki 14），原因不是"表达不了"，而是
**没人事先告诉内容哪一张是自己**：参考实现里打出的牌要到 `onTerminal` 才离开手牌，所以
`forEachCardInZone(Hand)` 的快照里看得见它。§225 试过让快照跳过它 —— 被 `archive_the_evidence` 挡回，
因为"打出的牌还在手牌"是**参考契约**的一部分（`CARD_DIFF` 逐字节对拍）。

这一节的修法把"跳过"从**内核**挪到**内容**：

* `forEachCardInZone` 每一趟绑卡时，若这一张 == `ExecContext::resolving_card`，就给
  `event_flags` 置 `CARD_IS_RESOLVING`（`1 << 5`）—— 与 §225 已经在填的 tag 位同一个位图；
* `expr::eval_bool` 的 `event.bool` 认得 `FieldKey: "card.isResolving"`；
* 内容的循环体写 `conditional(not(card.isResolving))`。

**没有正在结算的牌**（状态/遗物/敌人招式的节目）时这一位恒 0 —— "没有哪张牌是自己"。
判据：`the_hand_exhausting_cards_do_what_their_pages_say` 现在断言 5 格挡 / 14 伤害，而
`archive_the_evidence` 那条参考契约**一个字节都没动**（它不看这个位）。
`docs/sts-wiki-gap.md` §G.2 的那一行随之删除，并留下"为什么它不再是缺口"的记录。

### 226.2 复制载体：`ChoiceThen::Copy` + `PendingChoice::candidates` + `node.chooseCards`

`Dual Wield`（wiki：1 费 Uncommon Skill，"Choose an Attack or Power card. Add a copy (2 copies) of
that card into your hand."）需要的东西，内核一样都没有：

* `node.selectCards` 是**内核替玩家挑**并且**搬**牌（Stasis 那种），不问人；
* `PendingChoice` 的三条路都是**药水**：`Exhaust` / `DiscardThenDraw` / `ToHand`，全是"搬"；
* `node.createCardInstance` 只认**写死的**定义 id，"复制选中的那张"要 `ResultKey`（明确不支持）。

所以加三样，各管一件事：

| 新东西 | 一句话 | 为什么不能省 |
|---|---|---|
| `ChoiceThen::Copy` + `PendingChoice::copies` | 选中的牌**留在原处**，往手牌里造 `copies` 份同定义的新实例 | "搬"与"造"是两种语义：搬过去的要带每副本价格，造出来的必须是印刷价 |
| `PendingChoice::candidates` | 收窄后的**合法实例清单**（空 = 不过滤） | "Attack **或** Power"要读卡定义的 tag 表，而**状态层没有 `Content`**：清单由节点算好，内核只负责守 |
| `node.chooseCards` | `{OwnerSelector, FromZone, Min, Max, Copies, RequireAnyTag?}` ⇒ 提问 | 内容第一次能说"问玩家要哪几张牌" |

守法的三处（都在**动手之前**拒绝，§161.2(a) 的老规矩）：清单外的实例 ⇒ `NotInSource`；
`copies != 0` 与 `then != Copy` 不自洽（两个方向都拒）⇒ `CopiesNotApplicable`；
手牌/卡池容量不够 ⇒ `Capacity`。

运行层同一条账：`rd_env_choice_kind` 多一个数 `4`（复制），新导出 `rd_env_choice_copies`（页面要写
"各复制 N 份"），并且 `rd_env_choice_count` / `rd_env_choice_confirm` / `pile_card_id(3, i)` 三处
**一律改走 `choice_legal`** —— 原来是"数牌区 / 列牌区"，而收窄过的问句里合法选项比牌区少，那样会
让页面画出内核随后要拒绝的选项（"点了没反应"的死按钮）。

### 226.3 wiki 抓到一处内容错误（照 dump 改，不照记忆）

第一版把 `Dual Wield` 的落区写成 `ExhaustPile`（旧版 StS 它自我消耗）。抓到它的是**抓下来的 wikitext**：
`native/wiki_cards/dual_wield.txt` 的 Infobox 里**没有** Exhaust，正文只写 "add 1 copy (2 copies if
upgraded) of that card into your hand" ⇒ 落区 = `DiscardPile`，判据同一条改成断言"进弃牌堆、消耗堆为空"。
这就是 §218 那条纪律的用处：**页面在仓库里，记忆不在**。

### 226.4 一个测试自身的坑（记下来，别再踩）

`state::tests::a_copy_question_leaves_the_original_alone` 第一次跑出"副本 0 份"，原因是它用手抄 id 的
`hand_of()` 建手牌（`push_card("card_000001")`，绕过了 `next_card_instance_number` 发号器）——
于是 `create_card_instance` 把**同一个 id** 又发了一次，副本与原件同名、按 id 一比就全被过滤掉。
真实战斗里每一张牌都从发号器来，所以这不是内核缺陷；但"手抄 id 的测试"必须知道这一点，
判据里因此改成用 `create_card_instance` 造手牌，并把这句写进注释。

### 226.5 数字

* 单测 **919**（714 core + 110 run + 95 wasm）；四个对拍不变（`FIGHT_DIFF 182/182`、
  `CARD_DIFF 62/62`、`CARD_MULTI 124/124`、`ENEMY_DIFF 394/394`）。
* 内容：卡 **79 行**（+2 = `dual_wield` / `dual_wield+`），镜像 **85,988 B**（core 72,184）。
* 矩阵 **393 行**（+2）、具名测试 **919**、wiki 对照 **47** 张（`dual_wield` 走的是 `wiki:dump`，
  不是 `spec:` —— 页面已抓进 `native/wiki_cards/`）。
* `sts-wiki-gap.md` §G.2 少了一行（偏差**修掉了**，不是改成"声明"）。
'''


def main():
    path = ROOT + 'docs/port-plan.md'
    text = io.open(path, encoding='utf-8').read()
    assert '## §226' not in text, 'already there'
    io.open(path, 'w', encoding='utf-8', newline='\n').write(text.rstrip('\n') + '\n' + SECTION)
    print('doc_226: appended %d bytes' % len(SECTION))


main()
