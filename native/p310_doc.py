"""§310 记账：Orange Pellets 改回 wiki 语义（清 Debuff）。"""
import io

ROOT = 'D:/Vibe/sts-tui/'
PLAN = ROOT + 'docs/port-plan.md'
FACT = 'C:/Users/TK11/AppData/Roaming/CherryStudio/Data/Agents/6efe3bdb-2995-4862-8512-2593051661ef/memory/FACT.md'

DOC = r"""
---

## §310 `Orange Pellets`：一条"文档和代码一起错"的遗物

审阅报告 §5 说它的效果与 wiki 不符。核对确认：**wiki 是"清除所有 Debuff"，我们给的是
+3 力量 / +3 敏捷**（两个独立来源：`Orange Pellets` 页与 `Debuff` 页）。

### 310.1 为什么它一路绿到今天

三个地方同时错，而且互相印证：

1. **代码**（内容 `STAT` 行的程序）给 +3/+3；
2. **`docs/sts-wiki-gap.md` §F.19 的"wiki"列**写的是"+3 力量/敏捷" —— 那一列是从我们的行为
   抄的，于是"对账"永远通过（**这是比代码错更坏的一种**：文档是唯一的交叉核对）；
3. **`coverage-matrix`** 把 `orange_pellets_pays_once_all_three_card_kinds_were_played` 记成
   `Implemented + TestNamed` —— 测试名（"pays"）把错规则写死了，**测试替 bug 站岗**。

### 310.2 改法

* **新节点** `node.removeDebuffs{TargetSelector}`（`rd-core` 的 IR + exec）。为什么不是一个
  "applyStatus 负层数"：`RemoveStatus` 删的是**实例**，不是把层数减到 0（0 层实例留在表里是
  另一种状态）；而 `applyStatus` 还要过拦截器（Artifact 会吃掉一次）。移除没有拦截点，所以
  这个节点**不进请求队列**，直接删。
* **极性查定义**，不查实例字段：`status_polarity(definition_id, content)`（内容 `STAT.Polarity`
  优先、目录兜底 —— Artifact 的判定也用它）。
* 内容：三处成对 `applyStatus(strength 3)` + `applyStatus(dexterity 3)` 换成一个
  `removeDebuffs`；`DescriptionKey` 改成 wiki 的措辞。镜像 168,008 → **167,996 B**
  （core 镜像不变：描述是 presentation，`--no-core` 本来就不带它）。

### 310.3 两个踩坑（都是**通用形态**）

1. **实例上的极性会撒谎。** 第一版用 `StatusInstance.polarity` 判极性，判据当场红：
   清完之后力量/敏捷/荆棘也没了。因为那个字段是 `applyStatus` 那一刻**抄**进去的，
   测试助手给每一条都写 `Debuff`。⇒ 字段里有现成的值 ≠ 那是权威的值；要找**唯一入口**。
2. **判据只说"负面没了"是不够的。** 那种判据"清全部状态"也能通过 —— 所以判据里必须有
   "**正面一条都不许动**"那一侧。负控就是把规则改成"清 Buff"，红。

### 310.4 判据与负控

`orange_pellets_removes_every_debuff_and_keeps_the_buffs`（rd-core，真打三张牌）四侧：
只有两类 ⇒ 不清；三类齐 ⇒ Weak/Frail 清空；**正面（Strength/Dexterity/Thorns）原值**；
第四张牌不重复付。

**负控**（`native/p310_negative.py`）：把"只清 Debuff"改成"清 Buff" ⇒ **红**。

### 310.5 第二个"知道节点词表"的地方

`native/sts_content_check.py` 有一张 node-kind 分派表（把节点翻译成"事实"做内容盘点）。
加节点时它也必须动 —— 否则 `STS_CONTENT` 直接
`AssertionError: unexpected node kind 'node.removeDebuffs'`。
这次加的是 `("cleanse", target)` 这条事实，而不是把它展开成若干 `status` 事实：
展开之后"清掉 Weak 2"与"给 Weak -2 层"在盘点里就分不开了，而那是两件事。

### 310.6 账

镜像 **167,996 B**（core 132,044 B 不变）；`rd-core` 809（判据改名，条数不变）；
聚合闸门 **22/22**（`rust-units 1154 passed`、`sts-content 50 monsters`）。
"""


def main():
    plan = io.open(PLAN, encoding='utf-8').read()
    if '§310 `Orange Pellets`' not in plan:
        io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(plan.rstrip('\n') + '\n' + DOC)

    fact = io.open(FACT, encoding='utf-8').read()
    line = ('\n- `rd-core` 的节点词表在**两处**：`ir.rs`（`NodeKind` + `wire_name` + `from_wire_name` 的\n'
            '  `ALL` 表，三处都要同步）与 `native/sts_content_check.py` 的 node-kind 分派表（把节点翻成\n'
            '  "事实"做内容盘点）。§310 加 `node.removeDebuffs` 时漏了第二处，`STS_CONTENT` 直接断言\n'
            '  `unexpected node kind` —— 加节点要两处一起改。\n')
    marker = '## 6. `D:\\Vibe\\260927-fft`'
    if 'node.removeDebuffs' not in fact:
        fact = fact.replace(marker, line.strip() + '\n\n' + marker, 1)
        io.open(FACT, 'w', encoding='utf-8', newline='\n').write(fact)
    print('§310 recorded; FACT line added')


main()
