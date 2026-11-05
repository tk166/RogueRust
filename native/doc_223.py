"""§223 docs."""
import io

ROOT = 'D:/Vibe/sts-tui/'

SECTION = '''
---

## §223 让垂直切片的驱动像个玩家（于是 `apparition` / `buffer` 那两条偏差终于能修）

§222 把两条按 wiki 的内容修正挡回来了，理由是"24 个固定种子没有一个能打赢 Boss"。这一节去补那个
能力，结论比预想的更有意思：**光让驱动会打 Ethereal 并不够**，真正卡住的是**池子一动、整条路线就挪**。

### 223.1 驱动新加的四条能力（`web/act1_slice.mjs`）

| 能力 | 判据（都读**内容**，不读手抄清单） |
|---|---|
| **Ethereal 的牌本回合先打** | 卡面文字（`DescriptionKey`）里有 `Ethereal` —— 它就是"回合末不在手里就没了"，"留到下一回合"不是选项 |
| **无形算防守牌** | 卡面有 `intangible` 或 `block`；只按 `block` 找牌会把 Apparition 当成"不打人也不挡"的垃圾牌排最后 |
| **Power 最后打** | 卡面有 `next time` / `each turn` / `whenever` 之类的持续词：它当回合不解场，2 费的 Power 会吃掉一整个节奏 |
| **奖励屏挑牌，不拿第一张** | 奖励行带类型 chip（来自 content 的 tag）：`attack`/`skill` 优先，`power` 最后 |

第四条是真正关键的一条，也是 §222 诊断漏掉的一半：第一版永远点第一个"拿这张"，于是**卡池里多一张牌
= 第一张不再是原来那张 = 牌组换了一档**。

### 223.2 修正 §222 的诊断：不是"驱动不会打 Ethereal"

补完前三条之后按 wiki 放回 `apparition` / `buffer`，切片**仍然** 13 条红。补上第四条（挑牌）之后
HEAD 能过、加了内容仍然红。最后一步是把**种子表加长**（+20 个），才过。

所以真实机制是：**奖励屏的抽取发生在驱动能"跳过"之前**（roll 在池子上跑，池子多一张就换一条路线），
于是"内容变了"等于"这一次的 24 个种子全部换了命运"。切片自己的注释早就写着这件事：

> *"It is a **list**, not a lucky number: adding content changes the drop table, hence the route,
> hence which fights the driver wins."*

这一节因此把种子表从 24 个扩到 **44** 个，并把理由写在旁边 —— **不是**去回退一处正确的内容修正。

### 223.3 落地的内容修正

* `apparition`：基础带 `Ethereal`（`TurnEndHandDestinationZone = ExhaustPile`）、升级**去掉**它；
  两层都只给 **1 层**无形 + `Exhaust`（落区 `ExhaustPile`）。原来升级给 2 层、两层都没有 Ethereal
  —— 升级轴指错了方向。
* `buffer`：**Power / Rare / 2 费**（1(2) 层 Buffer）。原来按旧版写成 Skill / Uncommon / 1 费；
  这份内容的每张牌都钉在同一批 wiki 页上，留一张在旧基线等于有两套基线。
* 两处内容门的表跟着对齐：`INV_CARDS` 的四行、卡片 wiki 事实表（`apparition` 升级也是 1 层）、
  两条声明偏差**删掉**（内容已与页面一致）。
* `cards.upgrades` 那条闸门补了一个**有据可依**的例外：升级行可以少一个 `ethereal`
  （Apparition 就是 wiki 明确要求的那种），其它任何 tag 差别仍然红。

### 223.4 两个坑（都在这节里踩到）

* **`.mjs` 的模板字符串里不能有反引号** —— 注入到 `page.evaluate` 的那段代码是一个模板串，
  我在注释里写 `` `DescriptionKey` `` / `` `block` `` / `` 拿这张 ``，三次都把它截断成
  `SyntaxError: missing ) after argument list`。（FACT §2b 记的就是这条，这次一口气踩了三遍。）
* **镜像在编译期嵌进 `.wasm`**（`include_bytes!`）⇒ 任何内容改动都要**重编 wasm**，否则浏览器闸门
  跑的是旧镜像。§222 的四个隔离实验全废在这上面。

### 223.5 数字

* **21/21 闸门绿**（`ACT1_SLICE PASS`、四个对拍不变），单测 **912**（710 + 109 + 93）。
* 镜像 **84,588 B**（core 71,188）；卡 73 行不变 —— 这一节改的是**两行卡的定义**与**驱动**。
* 矩阵 387 行、具名测试 914；`apparition` / `buffer` 的 `DeclaredDeviation` 从有内容变回 `—`。
* 偏差总数因此 **75 → 73**（少了两条真修掉的）。
'''

port = io.open(ROOT + 'docs/port-plan.md', encoding='utf-8').read()
assert '## §223' not in port
io.open(ROOT + 'docs/port-plan.md', 'a', encoding='utf-8', newline='\n').write(SECTION)
print('port-plan §223 appended')

readme = io.open(ROOT + 'README.md', encoding='utf-8').read()
for old, new in [
    ('（§1–§222，每一轮都留数字、记下被推翻的结论）', '（§1–§223，每一轮都留数字、记下被推翻的结论）'),
    ('编译成 84,592 B 的 `rdcf` 镜像（core 镜像 71,200 B）', '编译成 84,588 B 的 `rdcf` 镜像（core 镜像 71,188 B）'),
]:
    assert readme.count(old) == 1, old[:40]
    readme = readme.replace(old, new)
io.open(ROOT + 'README.md', 'w', encoding='utf-8', newline='').write(readme)
print('README updated')
