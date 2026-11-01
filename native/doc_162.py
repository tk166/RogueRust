"""Append §162 to docs/port-plan.md (UTF-8, no BOM, LF).

Numbering from here on is **coarse**: one section per topic (the用户 asked for it -- finer numbers
made the patch scripts' bookkeeping silly).
"""
import io

PATH = "docs/port-plan.md"

SECTION = """
---

## 162. 整局的不变量：`check_invariants` 长全，存档在提交前问它

评审 §六 第 4 步的第一项：**"建立整局状态不变量验证 … 畸形或自相矛盾的存档在提交前被拒绝"**。

### 162.1 先发现它**已经存在**，所以这一节是"长全"而不是"新建"

`RunState::check_invariants` 早就在（规格 `run-layer.md` §6.2：地图合法性、楼层范围含 Boss 例外、
血量、三个容器的容量、游标与行的对应）。我一开始写了第二个 `validate()` 放在它旁边 —— 那正是本项目
反复抓的"同一个词表两处认识"，而这次抓住它的**是我自己**：两份校验器迟早会漂，而且漂了以后
"两边都拒绝"看起来是对的。

⇒ 已合并：新的判据进 `check_invariants`，`archive::restore` 问它，`validate` 这个名字不存在。

### 162.2 新长出来的判据，每一条都对应一个真 bug 或一种真攻击

| 判据 | 为什么它值得存在 |
|---|---|
| `len` 之前有内容、**之后是空的** | §161.10 的 `remove_card` 尾槽；现在存档里夹带这种状态会被**载入时**拒掉，而不是等到某次 `==` 才发现 |
| 遗物**不许重复** | 重复的一件会付两次钱 |
| 药水 ≤ 腰带格数 | Potion Belt 才是格数来源（§157），5 瓶却没有腰带是非法局面 |
| `pending` 与所在房间一致（`Pending::room`） | 一个"站在战斗节点上的篝火问句"是不存在的局面 |
| `event_follow` / `blessing_follow` 必须挂在对应问句上 | 否则那个后续动作永远没机会被完成 |
| `start_offers` 在表内 | 越界的祝福下标只会在开局时炸 |
| 商店：活报价必须有 id、价格不低于 -1 | 见下面那条"我写错了两次" |
| gold / removed_cards / act / ascension / potion_chance / rarity_offset 的取值范围 | 存档是外部输入 |

`Pending::room()` 是新的：**战斗奖励不限定房间**（普通/精英/Boss 三种战斗都会发奖励），所以它返回
`None` 而不是猜一个。`NodeKind::Boss` 在地图生成里从不赋值（Boss 是地图外的哨兵），所以"脚下是什么"
由 `node_at_cursor()` 回答 —— 那是 §161.8 的路由器踩过的同一件事。

### 162.3 与规格书的一处差异，写在这里而不是悄悄改规格

`run-layer.md` §6.2 第 1 条写 `0 < floor <= 17`，因为规格书按"15 行地图 + 16 Boss + 17 Boss 宝箱"
描述。实现里 **Boss 是第 16 层的哨兵、没有 17 层**（`map::BOSS_NODE`、`ROWS = 15`），所以校验器的
上界是 `ROWS + 1`。规格书是冻结的意图，代码是当前的事实 —— 两者不一致时**说出来**，不自己改一边。

### 162.4 一个太严的校验器比没有更糟（这条是 soak 教我的）

校验器的第一版把两条闸门打红了，而且**两次都是我的判据错，不是游戏错**：

1. **"`?` 房必须有问句"** —— 不，`NodeKind::Unknown => Pending::None`：`?` 房在 M1 是"有内容的空"
   （§6.3），它故意不带 pending。
2. **商店的"活报价"** —— 我写了两遍才写对：
   * 第一遍"每一行都必须活"：**买过的行** `price = -1` 而 `count` 不减（槽位下标要稳定，页面靠它下
     `buy_card(slot)`）⇒ 合法局面被拒；
   * 第二遍"有 id ⇔ 有价格"：`buy_card` **保留 id**、只把 price 设 −1 ⇒ 合法的"已买"被当成半死。
   * 真正的不变量只有两条：**活报价必须有 id**，**价格不会低于 −1**（−1 = 买走或没上架，两种死法
     在数据上一样，不该分开猜）。

所以这一节的验收不是"校验器能拒绝"，而是**两个方向都有**：

* `a_real_run_validates_at_every_step`：走一整幕，每个节点 `begin_node` + 结算 + `mark_resolved`，
  **每一步都问一次**，必须全过；
* `every_invariant_names_itself_when_violated`：13 条反例，**每条都指名它自己**（一条断言一个原因，
  否则"拒绝了"什么都证明不了）。

### 162.5 顺手修掉 `enter_node` 的半途提交

`check_invariants` 原来在游标**已经移动之后**才跑。于是"拒绝"会留下"页面说被拒、内核却已经站在那个
节点上"的局面 —— 页面随后卡在一个 settle 不了也走不掉的节点里。soak 里那 **334 个死控件**就是它的
症状，而报错原文（`Invariant("a shop card row …")`）正是我上面那两条错判据的产物。

现在先在一个 `Copy` 出来的副本上摆好 `(node, floor)` 再验证，全过才赋值 —— 与 §161.2(a) 同一条。

### 162.6 数字

- `rd-run` +2（整幕逐步验证 / 13 条反例），`archive` +1（**CRC 合法但状态非法**的存档被拒：
  先把一个不可能的局 `write` 出来，校验和当然是对的，于是拒绝只能来自不变量）。
- 负控：删掉"尾槽必须空"那一条 ⇒ `every_invariant_names_itself_when_violated` 红在
  `left: Ok(())` / `right: Err(Invariant("a deck slot past len is not empty"))`。
- 聚合验收 **19/19**；单测 793 → **796**。

### 162.7 下一节

回放（动作序列 + 每步哈希）；关键路径的真实指针点击（CDP `Input.dispatchMouseEvent`）；内容版本指纹。
"""


def main():
    with io.open(PATH, "rb") as handle:
        raw = handle.read()
    assert raw[:3] != b"\xef\xbb\xbf", "the plan is UTF-8 without BOM"
    text = raw.decode("utf-8")
    assert "## 162." not in text, "already appended"
    if not text.endswith("\n"):
        text += "\n"
    text += SECTION
    with io.open(PATH, "wb") as handle:
        handle.write(text.encode("utf-8"))
    print("port-plan.md now", len(text.split("\n")), "lines")


if __name__ == "__main__":
    main()
