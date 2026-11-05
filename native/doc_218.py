"""§218 docs."""
import io

ROOT = 'D:/Vibe/sts-tui/'

SECTION = '''
---

## §218 卡牌的 wiki 对照：51 张卡从 `spec:` 变成 `wiki:`，并抓出 8 处真错

§217 结束时矩阵里最大的一格洞是：**卡牌 0 份 wiki 出处**（51 张只有 `spec:INV_CARDS`，而那份清单
本身也是人抄的）。这一节把它补上 —— 方法还是"两把独立的尺"，不是"再抄一遍"。

### 218.1 抓取与解析（`native/wiki_cards/` + `native/wiki_cards.py`）

`native/fetch_wiki_cards.py` 按卡名抓 **raw wikitext**（`?action=raw`），存成
`native/wiki_cards/<id>.txt`（28 份，进 git，可离线复查）。为什么是 wikitext 而不是渲染页：
**升级值写在另一个字段里**（`Deal (8;10) damage.`，`;` 前基础、后升级），渲染页把它压成上标 ——
正是手抄最容易错的那种形状（§195.9 的 `blind` 就是稀有度与 Exhaust 都抄错了）。

字段（类型 / 稀有度 / 费用 / 关键字）在检查时**从 dump 读**（`native/wiki_cards.py`），所以它们
不可能与页面漂开；**数字**在 `native/card_wiki_inventory.py` 里人工冻结 —— 因为
`Description` 是散文，在闸门里解析它等于再实现一遍规则。两边都指向同一份 dump。

两个坑：

* `Strike` / `Defend` 是**消歧页**（`#REDIRECT`），真正的页面是 `Strike_(Ironclad)`。
  第一版抓回来的是 31 字节的重定向页，检查器会说"没有 Card Infobox"（**响亮失败**，不是静默跳过）。
* `buffer` 的页面已经是 **v2.3 的重做版**（Power / Rare / 2 费），本内容按旧版（Skill / Uncommon /
  1 费）—— 这条不是抄错，是**版本基线**不同，写进偏差表而不是"修"。

### 218.2 抓到的 8 处真错（3 处修、5 处声明）

| 卡 | 内容原来 | wiki | 处理 |
|---|---|---|---|
| `blur` | 只给状态、**没有格挡** | "Gain 5 (8) Block." | **修**：程序加 `5` / `8` 格挡（真 bug，不是简化） |
| `blur` | Rarity **Rare** | Uncommon | **修**（稀有度决定奖励权重，是数值） |
| `sentinel` | Rarity **Common** | Uncommon | **修** |
| `apparition` | Rarity **Uncommon** | **Special**（事件专属） | **修** + 运行层新增 `Rarity::Special` 桶 |
| `slimed` | `unplayable + junk` | 1 费、可出、Exhaust | 声明（本内容的状态牌只有"抽到是负担"这一种用法） |
| `apparition` | 升级给 **2 层**无形、无 Ethereal/Exhaust | 升级去 Ethereal、两层都只给 1 层 | 声明（升级轴方向性错，强度在本内容的战斗里等价） |
| `sentinel` | 带 `ethereal`、没有"被消耗时给能量" | 无 Ethereal、被消耗时 +2 能量 | 声明（"被消耗"没有载体） |
| `void` | 只是"不可出的虚无牌" | 抽到时 -1 能量 | 声明（`OnDrawn` 对牌还没有载体） |
| `burn+` / `bandage_up+` / `dark_shackles+` | 没有升级行 | 有（4 伤 / 治疗 6 / 15 层） | 声明（缺内容行） |
| `bandage_up` / `dark_shackles` | 没有 `exhaust` tag | 有 Exhaust | 声明（"打出即消耗"没有载体，与 `slimed` 同一条） |
| `buffer` | Skill / Uncommon / 1 费 | Power / Rare / 2 费 | 声明（**版本基线**：页面是 v2.3 重做版） |

**`Rarity::Special` 是这一节唯一的运行层改动**，而且它是被**测试红**逼出来的：把 `apparition` 的
稀有度改成 `Special` 之后，`Rarity::from_name` 返回 `None` ⇒ `full_pool()` 拒掉整张牌表 ⇒
**每一个** `rd_run_choose_start` 都以 -2 失败，6 条 wasm 运行测试同时红，报的却是
"taking blessing 0"（离原因很远）。修法与 §160 给遗物加 `Event` 桶同形：桶存在是为了让"事件专属"
**可说**，并且所有按稀有度抽牌的地方都要排除它。新增判据
`a_special_card_is_known_and_never_put_in_a_reward`（两半：能解析 + 40 个种子一次都不给）。

### 218.3 判据

* `check_card_wiki`（内容门的第 2d 层，`ok("card wiki", "N cards x (type, rarity, cost, keywords, facts)")`）：
  五项分开判 —— ①类型在 tag 里；②稀有度；③费用（wiki 的 `-1` = X 费、`-2` = 不可出，
  用 `x_cost` / `unplayable` 两个 tag 表达同一件事）；④关键字（`{{KW|X}}` 才算，
  `{{KW|Exhaust|Exhausted}}` 是**条件**不是关键字）；⑤数字（基础行与升级行分开，按多重集比）。
  偏差表可以逐项覆盖，未覆盖的项**必须**等于 wiki。
* `blur_gives_five_or_eight_block_and_the_status`：5 / 8 格挡 + 状态还在。
* `a_special_card_is_known_and_never_put_in_a_reward`：见上。
* 负控两条：把 `Special` 从奖励过滤里去掉 ⇒ `seed 2: … ["anger", "bash", "apparition"]`；
  把 blur 的格挡节点删掉 ⇒ `blur: wiki's Block  left: 0  right: 5`。

### 218.4 数字

* **21/21 闸门绿**，单测 **906**（705 core + 108 run + 93 wasm，比 §217 多 2 条）；四条对拍不变
  （`CARD_DIFF 62/62`、`CARD_MULTI 124/124`、`ENEMY_DIFF 394/394`、`FIGHT_DIFF 182/182`）。
* 镜像 **80,648 B**（core 68,216）：+164 B —— blur 的两段格挡与三处稀有度字符串。
* 矩阵：卡牌 `SourceTie:wiki` **0 → 47**、`spec` **51 → 4**（只剩两张样例包自有牌的基础/升级行）、
  声明偏差 **12**。全表 `wiki:` **177 → 224**、`spec` **94 → 47**、偏差 **63 → 75**。
  扫到具名测试 **906 → 908**。
* 26 张牌的 `TestNamed` / `HarnessOnly` 也变了（blur 的两条新测试 + 卡牌常见名）。

### 218.5 还剩什么（矩阵现在指着的）

* **两张样例包自有牌**（`patient_guard` / `swift_strike`）没有 wiki 页 —— 已用 `NO_WIKI_PAGE` **列出**，
  不是静默跳过；内容是加了新牌而没人找页面时，那条检查会红。
* **8 条声明偏差**里有 4 条属同一类"没有载体"：`Exhaust`（打出即消耗）、`OnDrawn`（抽到时的触发）、
  "被消耗时"的触发、以及状态牌的"可出但 Exhaust"。这四条是**内容格式/内核能力**的缺口，
  不是抄写问题 —— 下一节若做，应该一次补一种载体，而不是逐张牌打补丁。
'''

port = io.open(ROOT + 'docs/port-plan.md', encoding='utf-8').read()
assert '## §218' not in port
io.open(ROOT + 'docs/port-plan.md', 'a', encoding='utf-8', newline='\n').write(SECTION)
print('port-plan §218 appended')

readme = io.open(ROOT + 'README.md', encoding='utf-8').read()
for old, new in [
    ('（§1–§217，每一轮都留数字、记下被推翻的结论）', '（§1–§218，每一轮都留数字、记下被推翻的结论）'),
    ('编译成 80,484 B 的 `rdcf` 镜像（core 镜像 68,048 B）', '编译成 80,648 B 的 `rdcf` 镜像（core 镜像 68,216 B）'),
]:
    assert readme.count(old) == 1, old[:40]
    readme = readme.replace(old, new)
io.open(ROOT + 'README.md', 'w', encoding='utf-8', newline='').write(readme)
print('README updated')
