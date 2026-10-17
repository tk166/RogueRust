# 卡片选择器 / 卡片区域 —— 事实勘察报告

**性质**：只读勘察。本报告只给镜像实测事实，不给移植方案；没有改 `kernel/`、没有改 `ref/`、没有跑 cargo。
**日期**：2026-10-17（工作区文件时间）
**镜像**：`tools/contentc/out/content.core.rdcf`
**参考实现**：`ref/RogueDeck-Core/`（只读），锚点 `fd43e68ab91f40b475b745725abb17134b951c51`

## 0. 一句话结论

**「扩卡片选择器」救不了那 4 张卡 —— 那 4 张卡根本没用卡片选择器。**
镜像里 4 种卡片选择器判别串（`sel.deckCards` / `sel.matching` / `sel.random` / `sel.choose`）一共 7 条 term，
**全部挂在 run 层效果上**（`fx.removeCards` / `fx.upgradeCards` / `fx.duplicateCards` / `fx.transformCards`），
只从 `ROOT Events` 和 `ROOT Shops` 可达，**在 62 个卡程序树里出现 0 次**。
真正卡住 `archive_the_evidence(+)/shredder_drawer(+)` 的是两个战斗节点
`node.forEachCardInZone`（2 条 term）与 `node.moveCardToZone`（1 条 term），外加一个卡实例表达式 `cardInstance.iterated`。

---

## 1. 复现方法（先看这一段，否则数字对不上）

### 1.1 镜像身份

```
python tools/contentc/reader.py out/content.core.rdcf
```
```
image            : out\content.core.rdcf (85616 B)
format version   : 1   flags=1   schema_version=1
content hash     : 0xD1075DE5
  OPD    off=36828   bytes=1040    count=130     <- 130 个 opcode
  TRM    off=39280   bytes=20760   count=2143    <- 2143 条 term
  AUX    off=64328   bytes=4156    count=2078
  CARD   off=68484   bytes=1984    count=62      <- 62 张卡
  STAT   off=70468   bytes=920     count=23
  EACT   off=71388   bytes=6304    count=394
  ENCT   off=77692   bytes=1744    count=109
  REL    off=79436   bytes=588     count=49
roots            : Balance, Characters, CombatResources, Consumables, Deck, Events, Map,
                   MapGeneration, MetaRules, Recipes, SchemaVersion, Shops, ShredRules,
                   Shreds, Start, Workbenches
```
`flags=1` 表示 presentation 字符串已剥离（这解释了 `NameKey` / `DescriptionKey` 全是 `ABSENT`）。

### 1.2 勘察脚本

新建了 `native/_recon_card.py`（**一次性勘察脚本，不进构建、不被任何 crate 引用**）。
它只做一件事：通过 `tools/contentc/reader.py` 的 `Rom` 读镜像，再用原始 slot 重建父子关系，然后打印事实。
子命令：`terms` / `fields` / `selectors` / `census` / `tree <card-id>` / `cards` / `who <term...>` / `zones`。

它**不信任 `reader.py` 的 JSON dump** 来算父子关系 —— 因为 dump 出来的是解码后的 Python 对象，
而 ABSENT（键不存在）与 NULL（键存在、值为 null）在 dump 里长得不一样，必须回到 u16 slot 才能分辨。

### 1.3 本机 shell 的坑（会影响你复现）

本机 shell 被剥空，且 `& exe args` 会吞掉 stdout（放进管道直接报
`Cannot run a document in the middle of a pipeline`）。所以下面所有命令**实际是这样起的**：

```powershell
$psi = New-Object Diagnostics.ProcessStartInfo
$psi.FileName='C:\Users\TK11\miniforge3\python.exe'
$psi.Arguments='native\_recon_card.py census'
$psi.WorkingDirectory='D:\Vibe\sts-tui'
$psi.RedirectStandardOutput=$true; $psi.RedirectStandardError=$true; $psi.UseShellExecute=$false
$psi.StandardOutputEncoding=[Text.Encoding]::UTF8; $psi.StandardErrorEncoding=[Text.Encoding]::UTF8
$psi.EnvironmentVariables['PYTHONIOENCODING']='utf-8'
$p=[Diagnostics.Process]::Start($psi)
$o=$p.StandardOutput.ReadToEndAsync(); $e=$p.StandardError.ReadToEndAsync()
$null=$p.WaitForExit(180000)
$o.Result; $e.Result
```

也就是说，**逻辑命令行**是（工作目录 `D:\Vibe\sts-tui`）：

| 问题 | 命令 |
|---|---|
| Q1 term 数与归属 | `native\_recon_card.py terms` |
| Q2 字段表 + 原始 slot | `native\_recon_card.py fields` |
| Q3 选择器 census | `native\_recon_card.py selectors` |
| Q4 区域字符串 | `native\_recon_card.py zones` |
| Q5 4 张卡的树 | `native\_recon_card.py tree archive_the_evidence archive_the_evidence+ shredder_drawer shredder_drawer+` |
| Q7 卡程序树 kind census | `native\_recon_card.py census` |
| 逐卡判定 | `native\_recon_card.py cards` |
| 某 term 被谁用 | `native\_recon_card.py who 154 165 153 1696 …` |

---

## 2. Q1 —— `forEachCardInZone` / `moveCardToZone` 有几条、属于谁

`native\_recon_card.py terms`（完整输出）：

```
term total            : 2143
node.forEachCardInZone   op=59  terms=2  ids=[154, 165]
node.moveCardToZone      op=66  terms=1  ids=[153]

node.forEachCardInZone   term 154  reachable from 2 card program(s): archive_the_evidence, archive_the_evidence+
node.forEachCardInZone   term 165  reachable from 2 card program(s): shredder_drawer, shredder_drawer+
node.moveCardToZone      term 153  reachable from 4 card program(s): archive_the_evidence, archive_the_evidence+, shredder_drawer, shredder_drawer+

term 154  (node.forEachCardInZone) direct parents: t156(node.sequence), t162(node.sequence)
term 165  (node.forEachCardInZone) direct parents: t167(node.sequence), t172(node.sequence)
term 153  (node.moveCardToZone) direct parents: t154(node.forEachCardInZone), t165(node.forEachCardInZone)
```

**结论：**

| kind | op | 镜像里的 term 数 | term id | 用在哪些卡 |
|---|---|---|---|---|
| `node.forEachCardInZone` | 59 | **2** | 154, 165 | 154 → `archive_the_evidence` / `archive_the_evidence+`；165 → `shredder_drawer` / `shredder_drawer+` |
| `node.moveCardToZone` | 66 | **1** | 153 | 同上 4 张（它唯一的父节点就是上面两条 `forEachCardInZone`） |

补充事实（`native\_recon_card.py who 154 165 153`）：

```
term 154 node.forEachCardInZone
  CARD    [ 36] archive_the_evidence           field Program
  CARD    [ 37] archive_the_evidence+          field Program
term 165 node.forEachCardInZone
  CARD    [ 38] shredder_drawer                field Program
  CARD    [ 39] shredder_drawer+               field Program
term 153 node.moveCardToZone
  CARD    [ 36] archive_the_evidence           field Program
  CARD    [ 37] archive_the_evidence+          field Program
  CARD    [ 38] shredder_drawer                field Program
  CARD    [ 39] shredder_drawer+               field Program
```

- 这两个 kind **在整个镜像里只被 4 张卡的 `Program` 用到**：不涉及任何 `STATUS` / `EACT` / `ENCT` / `REL` 行，
  也不涉及任何 `ROOT`（`Events` / `Shops` / `Deck` / …）。
- `moveCardToZone` **只作为 `forEachCardInZone.Body` 出现**，从来没有独立使用。
- `archive_the_evidence` 与它的升级版共用同一条 `forEachCardInZone` term（154），
  `shredder_drawer` 两版共用 165 —— 两条 term 的差别只有一个字段（见 Q2 的 `TakeFirst`）。

---

## 3. Q2 —— 真实字段表与每条 term 的实际取值

### 3.1 `node.forEachCardInZone`（op 59，opclass=0，nfields=7，nslots=7）

`native\_recon_card.py fields` 输出：

```
op 59  node.forEachCardInZone  opclass=0 nfields=7 nslots=7
  [0] Body                 TERM      flags=0 (bare)
  [1] DefinitionFilter     TERM      flags=0 (bare)
  [2] MaxIterations        INT       flags=0 (bare)
  [3] OwnerSelector        TERM      flags=0 (bare)
  [4] TagFilter            STR       flags=1 ({value:})
  [5] TakeFirst            INT       flags=0 (bare)
  [6] Zone                 STR       flags=0 (bare)
```

| # | 字段名 | 字段 kind | wrap flags |
|---|---|---|---|
| 0 | `Body` | `F_TERM` | 0 |
| 1 | `DefinitionFilter` | `F_TERM` | 0 |
| 2 | `MaxIterations` | `F_INT` | 0 |
| 3 | `OwnerSelector` | `F_TERM` | 0 |
| 4 | `TagFilter` | `F_STR` | `FLAG_WRAP_LOWER`（线上是 `{"value": "<tag>"}`） |
| 5 | `TakeFirst` | `F_INT` | 0 |
| 6 | `Zone` | `F_STR` | 0（裸字符串） |

**每条 term 的原始 u16 slot 与取值：**

```
--- term 154  raw slots [153, 65534, 64, 18, 776, 1, 79]
    Body                 TERM     raw=[153]      t153 node.moveCardToZone
    DefinitionFilter     TERM     raw=[65534]    (NULL 0xFFFE)
    MaxIterations        INT      raw=[64]       64
    OwnerSelector        TERM     raw=[18]       t18 sel.source
    TagFilter            STR      raw=[776]      junk
    TakeFirst            INT      raw=[1]        1
    Zone                 STR      raw=[79]       Hand
--- term 165  raw slots [153, 65534, 64, 18, 776, 32769, 79]
    Body                 TERM     raw=[153]      t153 node.moveCardToZone
    DefinitionFilter     TERM     raw=[65534]    (NULL 0xFFFE)
    MaxIterations        INT      raw=[64]       64
    OwnerSelector        TERM     raw=[18]       t18 sel.source
    TagFilter            STR      raw=[776]      junk
    TakeFirst            INT      raw=[32769]    NULL          <- 32769 = 0x8001 = NULL_INT
    Zone                 STR      raw=[79]       Hand
```

`reader.py` 对这两条 term 的 JSON（注意 `DefinitionFilter` 是 `None`、`TakeFirst` 有一条是 `None`）：

```python
{'kind': 'node.forEachCardInZone', 'value': {
  'Body': {'kind': 'node.moveCardToZone', 'value': {
      'CardExpression': {'kind': 'cardInstance.iterated', 'value': {}},
      'OwnerSelector': {'kind': 'sel.source', 'value': {'Cardinality': 'ZeroOrOne',
                                                        'RequiredContextCapabilities': 'Source'}},
      'Placement': 'Bottom', 'ResultKey': None, 'ToZone': 'ExhaustPile'}},
  'DefinitionFilter': None, 'MaxIterations': 64,
  'OwnerSelector': {'kind': 'sel.source', 'value': {...}},
  'TagFilter': {'value': 'junk'}, 'TakeFirst': 1, 'Zone': 'Hand'}}     # term 165 是 'TakeFirst': None
```

**关于 "缺的键在二进制里是 0xFFFF / dump 里可能不出现或为 null" —— 实测是哪一种：**

- 这两个节点**一条 term 都没有出现 ABSENT**（`0xFFFF` / `F_INT` 的 `0x8000` / 列表的 `0xFFFF`）。
- 出现的全是 **NULL**：
  - `DefinitionFilter` = `0xFFFE` → dump 里键**存在**，值为 `None`（JSON `null`）。
  - `TakeFirst`（term 165）= `0x8001`（`NULL_INT`）→ 键**存在**，值为 `None`。
  - `ResultKey`（term 153）= `0xFFFE` → 键**存在**，值为 `None`。
- 所以：**`absent` ⇒ 键在 dump 里根本不出现；`null` ⇒ 键出现、值为 `null`**。这两条 term 用的是后者。
- 另外，C# 侧 `ForEachCardInZoneNode` 还有第 8 个属性 `MarkFilter`，它带
  `[JsonIgnore(WhenWritingNull)]`，镜像里所有实例都是 null ⇒ **编译器从没见过这个键 ⇒ opcode 字段表里干脆没有它**。
  这就是「字段表 = 各实例键集的并集」的直接证据：**恒为 null 且被 JsonIgnore 的键，不是 ABSENT，而是不存在**。
  文件位置：`ref/RogueDeck-Core/src/RogueDeck.Core/Combat/Effects/Programs/EffectProgramNodes.cs:295-300`
  （`TagFilter` 在 `:295`，`MarkFilter` 的 `[JsonIgnore(WhenWritingNull)]` 在 `:298-299`，
  `public TagId? MarkFilter { get; }` 在 `:300`）。

### 3.2 `node.moveCardToZone`（op 66，opclass=0，nfields=5，nslots=5）

```
op 66  node.moveCardToZone  opclass=0 nfields=5 nslots=5
  [0] CardExpression       TERM     flags=0 (bare)
  [1] OwnerSelector        TERM     flags=0 (bare)
  [2] Placement            STR      flags=0 (bare)
  [3] ResultKey            TERM     flags=0 (bare)
  [4] ToZone               STR      flags=0 (bare)
```

| # | 字段名 | 字段 kind | wrap flags |
|---|---|---|---|
| 0 | `CardExpression` | `F_TERM` | 0 |
| 1 | `OwnerSelector` | `F_TERM` | 0 |
| 2 | `Placement` | `F_STR` | 0（裸字符串） |
| 3 | `ResultKey` | `F_TERM` | 0 |
| 4 | `ToZone` | `F_STR` | 0（裸字符串） |

**唯一的 term 153，原始 slot `[152, 18, 13, 65534, 72]`：**

| 字段 | raw slot | 值 |
|---|---|---|
| `CardExpression` | `152` | `t152 cardInstance.iterated`（0 字段，`{"kind":"cardInstance.iterated","value":{}}`） |
| `OwnerSelector` | `18` | `t18 sel.source` → `{Cardinality:"ZeroOrOne", RequiredContextCapabilities:"Source"}` |
| `Placement` | `13` | `"Bottom"` |
| `ResultKey` | `65534` (`NULL16`) | `null`（dump 里键存在、值 None） |
| `ToZone` | `72` | `"ExhaustPile"` |

C# 侧字段名与二进制完全一一对应，`MarkFilter` 那种「不存在」的情况在这里没有发生（5/5 全中）：
`ref/RogueDeck-Core/src/RogueDeck.Core/Combat/Effects/Programs/EffectProgramNativeNodes.cs:1284-1295`
（`OwnerSelector` `:1287`、`CardExpression` `:1289`、`ToZone` `:1290`、`Placement` `:1291`）。

### 3.3 关于 `TagFilter = {"value": "junk"}`

`"junk"` 不是随便的字符串，它是**卡定义上的 tag**。同一张卡自己的 `Tags` 字段（`_arr` + `FLAG_WRAP_LOWER` 元素）实测是：

```
Tags  t159  kinds=['_arr', 'op6']
  t6     op6  {'value': 'bureaucracy'}
  t21    op6  {'value': 'block'}
  t35    op6  {'value': 'form'}
  t53    op6  {'value': 'junk'}
  t158   op6  {'value': 'exhaust_payoff'}
```

即：`TagFilter` 的语义 = **"卡定义（不是卡实例）的 Tags 里含这个 tag"**，
参考实现写在 `EffectProgramNodeExecutors.cs:452-458`（`:457` 是
`&& definition.Tags.Contains(tag)`，`:454` 的注释原文是
"the tags live on its definition; an instance whose definition isn't registered has none"）。

---

## 4. Q3 —— 卡片选择器判别串

### 4.1 镜像里实际出现的（大小写逐字）

`native\_recon_card.py selectors` 输出（全部 `sel.*` / `card.*` / `cardInstance.*` opcode）：

```
card.upgradeLevel      op=18  terms=1   fields=(none)
cardInstance.iterated  op=19  terms=1   fields=(none)
sel.allAllies          op=73  terms=1   fields=(none)
sel.allCombatants      op=74  terms=1   fields=AliveOnly:BOOL MayIncludeDownedTargets:BOOL
sel.allEnemies         op=75  terms=1   fields=(none)
sel.alliesWithStatus   op=76  terms=3   fields=StatusDefinitionId:STR
sel.choose             op=77  terms=4   fields=Count:INT Inner:TERM Purpose:STR
sel.deckCards          op=78  terms=1   fields=(none)
sel.enemiesWithStatus  op=79  terms=2   fields=StatusDefinitionId:STR
sel.eventTarget        op=80  terms=1   fields=Cardinality:STR RequiredContextCapabilities:STR
sel.iterationTarget    op=81  terms=1   fields=Cardinality:STR
sel.lowestHealthEnemy  op=82  terms=1   fields=Cardinality:STR
sel.matching           op=83  terms=1   fields=Inner:TERM Predicate:TERM
sel.random             op=84  terms=1   fields=Count:INT Inner:TERM
sel.source             op=85  terms=1   fields=Cardinality:STR RequiredContextCapabilities:STR
sel.withStatus         op=86  terms=5   fields=Inner:TERM StatusDefinitionId:STR
```

**卡片选择器（card selectors）一共只有 4 种，共 7 条 term：**

| 判别串（逐字） | op | term 数 | term id | 字段（kind） | 实际取值 |
|---|---|---|---|---|---|
| `sel.deckCards` | 78 | **1** | 1696 | （无字段，nfields=0） | `{"kind":"sel.deckCards","value":{}}` |
| `sel.matching` | 83 | **1** | 1738 | `Inner`:TERM, `Predicate`:TERM | `Inner`=t1696 `sel.deckCards`；`Predicate`=t1737 `compare{Left=card.upgradeLevel{}, Op="LessThan", Right=const{Value:1}}` |
| `sel.random` | 84 | **1** | 1697 | `Count`:INT, `Inner`:TERM | `Count`=1（raw 1）；`Inner`=t1696 |
| `sel.choose` | 77 | **4** | 1739, 1746, 1771, 2137 | `Count`:INT, `Inner`:TERM, `Purpose`:STR | 见下表 |

`sel.choose` 四条逐条：

| term | `Count`（raw） | `Inner` | `Purpose`（raw → 值） |
|---|---|---|---|
| 1739 | 1（raw `1`） | t1738 `sel.matching` | `1332` → `"upgrade a card"` |
| 1746 | 1（raw `1`） | t1696 `sel.deckCards` | `1106` → `"remove a card from your deck"` |
| 1771 | 2（raw `2`） | t1738 `sel.matching` | `1332` → `"upgrade a card"` |
| 2137 | 1（raw `1`） | t1696 `sel.deckCards` | `1105` → `"remove a card"` |

四个 `sel.choose` 的完整 JSON：

```python
{'kind': 'sel.choose', 'value': {'Count': 1, 'Inner': {'kind': 'sel.matching', 'value': {
    'Inner': {'kind': 'sel.deckCards', 'value': {}},
    'Predicate': {'kind': 'compare', 'value': {'Left': {'kind': 'card.upgradeLevel', 'value': {}},
                                               'Op': 'LessThan',
                                               'Right': {'kind': 'const', 'value': {'Value': 1}}}}}},
  'Purpose': 'upgrade a card'}}                                          # t1739
{'kind': 'sel.choose', 'value': {'Count': 1, 'Inner': {'kind': 'sel.deckCards', 'value': {}},
  'Purpose': 'remove a card from your deck'}}                            # t1746
{'kind': 'sel.choose', 'value': {'Count': 2, ...same as 1739..., 'Purpose': 'upgrade a card'}}   # t1771
{'kind': 'sel.choose', 'value': {'Count': 1, 'Inner': {'kind': 'sel.deckCards', 'value': {}},
  'Purpose': 'remove a card'}}                                          # t2137
```

**注意：`sel.choose.Purpose` 是唯一的字符串字段，且是裸字符串（无 wrap）。**

### 4.2 一次都没出现的（= 0 次）

C# 的卡片选择器注册表只有 7 个名字（`ref/RogueDeck-Core/src/RogueDeck.Run/Serialization/RunJson.cs:209-218`）：

```
r.Register("sel.deckCards", typeof(DeckCardsSelector))
 .Register("sel.instance", typeof(InstanceSelector))
 .Register("sel.lastAddedCard", typeof(LastAddedCardSelector))
 .Register("sel.matching", typeof(MatchingCardSelector))
 .Register("sel.take", typeof(TakeSelector<RunCardInstance>))
 .Register("sel.random", typeof(RandomSelector<RunCardInstance>))
 .Register("sel.choose", typeof(ChooseSelector<RunCardInstance>));
```

镜像实测：

```
sel.deckCards        terms=1 [1696]
sel.instance         terms=0
sel.lastAddedCard    terms=0
sel.matching         terms=1 [1738]
sel.take             terms=0
sel.random           terms=1 [1697]
sel.choose           terms=4 [1739, 1746, 1771, 2137]
```

⇒ `sel.instance`、`sel.lastAddedCard`、`sel.take` **各 0 次**（连 opcode 都没分配，因为 opcode 表是按文档里出现过的 kind 建的）。

另外 10 条**战斗员**选择器判别串在镜像里有出现（`sel.source` / `sel.eventTarget` / `sel.allAllies` /
`sel.allEnemies` / `sel.iterationTarget` / `sel.lowestHealthEnemy` / `sel.allCombatants` / `sel.withStatus` /
`sel.alliesWithStatus` / `sel.enemiesWithStatus`），而 `CombatJson.cs:318-358` 一共注册了 **36 条**，
剩下 **26 条**在镜像里 **0 次**，逐条如下（这条结论是我把 `CombatJson.cs:318-358` 的 `Register("sel.…")`
名字抓出来、再和 opcode 表名字集合求差得到的）：

```
sel.sourceIncludingDowned   sel.allDamagedAllies      sel.highestHealthEnemy
sel.lowestHealthAlly        sel.highestHealthAlly     sel.union
sel.first                   sel.except                sel.withoutStatus
sel.damaged                 sel.downed                sel.lowestHealth
sel.highestHealth           sel.lowestStatusStacks    sel.highestStatusStacks
sel.lowestHealthPercentage  sel.highestHealthPercentage  sel.adjacent
sel.sameColumn              sel.sameRow               sel.allInColumn
sel.allInRow                sel.frontmostEnemy        sel.backmostEnemy
sel.nearestEnemy            sel.opposingInColumn
```

### 4.3 卡片选择器**不在任何卡程序里**（关键）

```
-- who references the four (direct parents, whole image)
  sel.deckCards   t1696 parents=t1697(sel.random),t1738(sel.matching),t1746(sel.choose),t2137(sel.choose)
                        | in card programs: -
  sel.matching    t1738 parents=t1739(sel.choose),t1771(sel.choose)          | in card programs: -
  sel.random      t1697 parents=t1698(fx.duplicateCards),t1831(fx.transformCards) | in card programs: -
  sel.choose      t1739 parents=t1740(fx.upgradeCards)                        | in card programs: -
  sel.choose      t1746 parents=t1747(fx.removeCards)                         | in card programs: -
  sel.choose      t1771 parents=t1772(fx.upgradeCards)                        | in card programs: -
  sel.choose      t2137 parents=t2138(fx.removeCards)                         | in card programs: -
```

`native\_recon_card.py who 1696 1697 1738 1739 1746 1771 2137`：

```
term 1696 sel.deckCards   ROOT Events   ROOT Shops
term 1697 sel.random      ROOT Events
term 1738 sel.matching    ROOT Events
term 1739 sel.choose      ROOT Events
term 1746 sel.choose      ROOT Events
term 1771 sel.choose      ROOT Events
term 2137 sel.choose      ROOT Shops
```

**没有任何 CARD / STATUS / EACT / ENCT / REL 行可达这 4 种 kind，只从 `ROOT Events` 与 `ROOT Shops` 可达。**
它们消费方全是 **run 层**效果（`RunJson.cs:277-283` 注册的 `fx.removeCards` / `fx.duplicateCards` / `fx.upgradeCards` / `fx.transformCards`）。

**交叉验证**：`native\_recon_card.py cards` 对 62 张卡逐张列出 `outside-15` 的 kind，
`sel.deckCards` / `sel.matching` / `sel.random` / `sel.choose` **一次都没出现**（见 §9 的完整期望输出）。

---

## 5. Q4 —— 卡片区域（zone）怎么表达

**是字符串枚举名的原文，不是整数。** 三个相关字段全是 `F_STR`、`wrap flags = 0`（裸字符串）。

C# 侧的合法值（`ref/RogueDeck-Core/src/RogueDeck.Core/Combat/Cards/CardZones.cs:3-22` 与 `:27-31`）：

```csharp
public enum CardZone { DrawPile, Hand, DiscardPile, ExhaustPile, BanishedPile, QueuePile, SetAsidePile }
public enum ZonePlacement { Bottom, Top }
```

镜像里**实际出现过**的（`native\_recon_card.py zones`，只保留合法的枚举名；`From`/`To` 的命中是地图节点 id，不是牌区）：

```
  Placement  = 'Bottom'       terms=[153]          <- node.moveCardToZone
  ToZone     = 'DiscardPile'  terms=[128, 135]     <- node.createCardInstance
  ToZone     = 'ExhaustPile'  terms=[153]          <- node.moveCardToZone
  ToZone     = 'Hand'         terms=[144, 184, 1380, 1387, 1402, 1410, 1423]  <- node.createCardInstance
  Zone       = 'Hand'         terms=[154, 165]     <- node.forEachCardInZone

-- the CARD row zone strings
  PlayedCardDestinationZone   = 'DiscardPile'    cards=48
  PlayedCardDestinationZone   = 'ExhaustPile'    cards=14
  TurnEndHandDestinationZone  = 'DiscardPile'    cards=62
```

| 枚举 | 合法值 | 镜像里出现过 |
|---|---|---|
| `CardZone` | `DrawPile` / `Hand` / `DiscardPile` / `ExhaustPile` / `BanishedPile` / `QueuePile` / `SetAsidePile` | `Hand`、`DiscardPile`、`ExhaustPile`（3 个）；`DrawPile` / `BanishedPile` / `QueuePile` / `SetAsidePile` **0 次** |
| `ZonePlacement` | `Bottom` / `Top` | 只有 `Bottom`；`Top` **0 次** |

具体到这两个节点：
- `node.forEachCardInZone.Zone` 在这个镜像里**只取 `"Hand"`**（两条 term 都是）。
- `node.moveCardToZone.ToZone` 只取 `"ExhaustPile"`，`Placement` 只取 `"Bottom"`。

`Placement` 的语义（参考实现，`ref/.../Combat/Effects/CardZoneEffects.cs:155-215`）：
同区 + `Bottom` = **完全不做任何事**（`WasMoved: false`，判据在 `:187`），同区 + `Top` 才重排；
跨区时 `MoveCardToZone(id, zone, placement)`（`CardZones.cs:212-223`），`Top` 是 `Insert(0, …)`。
owner 不匹配则抛异常（`CardZoneEffects.cs:175-179`）。

---

## 6. Q5 —— 这 4 张卡的完整程序树

`native\_recon_card.py tree archive_the_evidence archive_the_evidence+`（完整输出）：

```
CARD[36] archive_the_evidence
  Costs                        TERM     raw=[10]     t10 _arr
  DescriptionKey               STR      raw=[65535]  ABSENT
  Id                           STR      raw=[275]    archive_the_evidence
  IsAction                     BOOL     raw=[0]      ABSENT
  LifecyclePrograms            TERM     raw=[11]     t11 _obj
  NameKey                      STR      raw=[65535]  ABSENT
  PackageId                    STR      raw=[1157]   scenario
  PlayCondition                TERM     raw=[65535]  (ABSENT)
  PlayedCardDestinationZone    STR      raw=[52]     DiscardPile
  Program                      TERM     raw=[157]    t157 _obj
  QueueOnPlay                  TERM     raw=[65535]  (ABSENT)
  RetainInHandOnTurnEnd        BOOL     raw=[1]      false
  Tags                         TERM     raw=[159]    t159 _arr
  TurnEndHandDestinationZone   STR      raw=[52]     DiscardPile
  extra                        TERM     raw=[65534]  (NULL)

Program envelope t157  Root=t156
root t156 node.sequence
    .Children[0] -> t154 node.forEachCardInZone
        .MaxIterations = 64
        .TagFilter = junk
        .TakeFirst = 1
        .Zone = Hand
        .Body -> t153 node.moveCardToZone
            .Placement = Bottom
            .ToZone = ExhaustPile
            .CardExpression -> t152 cardInstance.iterated
            .OwnerSelector -> t18 sel.source
                .Cardinality = ZeroOrOne
                .RequiredContextCapabilities = Source
            .ResultKey = NULL
        .DefinitionFilter = NULL
        .OwnerSelector -> t18 sel.source
            .Cardinality = ZeroOrOne
            .RequiredContextCapabilities = Source
    .Children[1] -> t155 node.gainBlock
        .Children = ABSENT  [ABSENT]
        .Amount -> t12 const
            .Value = 8
        .ResultKey = NULL
        .TargetSelector -> t18 sel.source
            .Cardinality = ZeroOrOne
            .RequiredContextCapabilities = Source

CARD[37] archive_the_evidence+      (Program 信封 t163, Root=t162)
root t162 node.sequence
    .Children[0] -> t154 node.forEachCardInZone      <- 和上面**同一条 term**
        ... 完全相同 ...
    .Children[1] -> t161 node.gainBlock
        .Amount -> t160 const  .Value = 12
        .TargetSelector -> t18 sel.source
```

`shredder_drawer` / `shredder_drawer+` 同形，只是换成 t165 / t167 / t172：

```
CARD[38] shredder_drawer           (Program t168, Root=t167)
root t167 node.sequence
    .Children[0] -> t165 node.forEachCardInZone
        .MaxIterations = 64
        .TagFilter = junk
        .TakeFirst = NULL  [NULL]        <- 和 154 的唯一差别
        .Zone = Hand
        .Body -> t153 node.moveCardToZone
            .Placement = Bottom
            .ToZone = ExhaustPile
            .CardExpression -> t152 cardInstance.iterated
            .OwnerSelector -> t18 sel.source
            .ResultKey = NULL
        .DefinitionFilter = NULL
        .OwnerSelector -> t18 sel.source
    .Children[1] -> t166 node.dealDamage
        .Children = ABSENT
        .IgnoresBlock = false
        .Amount -> t37 const  .Value = 9
        .Element = NULL
        .ResultKey = NULL
        .TargetSelector -> t2 sel.eventTarget
            .Cardinality = ZeroOrOne
            .RequiredContextCapabilities = EventTarget

CARD[39] shredder_drawer+          (Program t173, Root=t172)
root t172 node.sequence
    .Children[0] -> t165 node.forEachCardInZone      <- 同一条 term
    .Children[1] -> t171 node.dealDamage
        .Amount -> t170 const  .Value = 14
        .IgnoresBlock = false   .Element = NULL   .ResultKey = NULL
        .TargetSelector -> t2 sel.eventTarget
```

**语义读法**（不改代码，只是把字段翻译成句子）：
「把手牌里带 `junk` tag 的卡移到 `ExhaustPile` 底部；`archive` 系列取前 1 张，`shredder` 系列不限张数；
然后 `gainBlock 8/12` 或 `dealDamage 9/14`」。

**除卡片选择器外还缺什么 —— 逐张清点（`native\_recon_card.py cards`）：**

```
archive_the_evidence    kinds=7  unhandled-node=['node.forEachCardInZone', 'node.moveCardToZone']
                                 outside-15=['cardInstance.iterated', 'const', 'sel.source']
archive_the_evidence+   kinds=7  同上
shredder_drawer         kinds=8  unhandled-node=['node.forEachCardInZone', 'node.moveCardToZone']
                                 outside-15=['cardInstance.iterated', 'const', 'sel.eventTarget', 'sel.source']
shredder_drawer+        kinds=8  同上
```

即：**4 张卡额外需要的只有 3 样东西**，其中 2 样是节点、1 样是卡实例表达式：
1. `node.forEachCardInZone`（Body / Zone / TagFilter / TakeFirst / MaxIterations / DefinitionFilter / OwnerSelector）
2. `node.moveCardToZone`（CardExpression / OwnerSelector / ToZone / Placement / ResultKey）
3. `cardInstance.iterated`（0 字段，`{"kind":"cardInstance.iterated","value":{}}`，镜像里只有 t152 这一条，
   而 `who 152` 显示它**只在 CARD[36..39] 的 Program 里出现**）

`const` / `sel.source` / `sel.eventTarget` 已经在用（其它 58 张卡都靠它们跑），不是新缺口。

**另外确认**：这 4 张卡除了 `Program` 之外的 program 字段是空的 ——
`PlayCondition` = ABSENT、`QueueOnPlay` = ABSENT、`LifecyclePrograms` = t11（共享的空 `_obj`）、
`Costs` = t10（共享 `_arr`）。所以「卡程序」这棵树就是 `Program.Root` 这一棵，没有别的地方藏东西。

---

## 7. Q6 —— 参考实现侧：这 4 种选择器在哪、读什么状态

### 7.1 解析（判别串 → 类型）

| 判别串 | 注册位置 |
|---|---|
| `sel.deckCards` | `ref/RogueDeck-Core/src/RogueDeck.Run/Serialization/RunJson.cs:211` |
| `sel.instance` | `…RunJson.cs:212` |
| `sel.lastAddedCard` | `…RunJson.cs:213` |
| `sel.matching` | `…RunJson.cs:214` |
| `sel.take` | `…RunJson.cs:215` |
| `sel.random` | `…RunJson.cs:216` |
| `sel.choose` | `…RunJson.cs:217` |

所在方法 `RegisterSelectors(RunJsonRegistry r)`，`RunJson.cs:209`；注释原文：
> `// Card selectors. Only the card closing is registered (no effect consumes a relic selector yet).`

⚠️ **这是 run 层的注册表，不是战斗层。** 战斗层的 `sel.*` 注册在
`ref/.../RogueDeck.Core/Combat/Serialization/CombatJson.cs:318-358`，**里面没有 `sel.deckCards` / `sel.matching` /
`sel.random` / `sel.choose`**，只有 `sel.source` / `sel.allAllies` / `sel.allEnemies` / … 那批战斗员选择器。

### 7.2 求值（实现）

| 判别串 | 类型 | 定义位置 | `Select` 位置 |
|---|---|---|---|
| `sel.deckCards` | `DeckCardsSelector` | `ref/.../RogueDeck.Run/Selectors/RunSelectors.cs:40-44` | `:42` |
| `sel.matching` | `MatchingCardSelector` | `…RunSelectors.cs:131-145` | `:142-144` |
| `sel.take` | `TakeSelector<T>` | `…RunSelectors.cs:149-161` | `:159-160` |
| `sel.random` | `RandomSelector<T>` | `…RunSelectors.cs:165-183` | `:175-182` |
| `sel.choose` | `ChooseSelector<T>` | `…RunSelectors.cs:188-215` | `:207-215` |

### 7.3 它们分别需要读什么状态 —— **`CombatState` 一个字段都不读**

| 选择器 | 实际依赖 |
|---|---|
| `sel.deckCards` | `context.Run.Deck`（`RunSelectors.cs:42`）；`RunState.Deck` 定义在 `ref/.../RogueDeck.Run/RunState.cs:164`（`=> ActiveMember.Deck`），`PartyMember.Deck` 在 `ref/.../RogueDeck.Run/PartyMember.cs:27` |
| `sel.matching` | `Inner.Select(context)` + 谓词 `Predicate.Evaluate(context.WithCard(card))`（`:142-144`）。`WithCard` 在 `ref/.../RogueDeck.Run/Effects/Programs/RunExpressions.cs:58`（把当前卡塞进 `RunEvalContext.Card`）。谓词里的 `card.upgradeLevel` 注册在 `RunJson.cs:180`，实现 `CardUpgradeLevelExpression` 在 `RunExpressions.cs:403` |
| `sel.random` | `RunPool.Uniform(candidates).DrawMany(context.Run, take)`（`:175-182`）→ 读 **run 的 RNG**：`RunState.NextRandom`（`ref/.../RogueDeck.Run/RunState.cs:854`），实现在 `ref/.../RogueDeck.Run/Effects/Programs/RunPool.cs:60-92`（每次抽取推进一步 RNG） |
| `sel.choose` | `context.Chooser`（`IRunEntityChooser`，接口 `RunSelectors.cs:14-38`）+ `context.Intent`（`RunChoiceIntent`）+ 跳过时写 `Run.NoteDeclinedChoice()`（`:207-215`）。**没有 chooser 时直接抛 `InvalidOperationException`**（`:210-212`） |

`RunEvalContext` 的字段集（`ref/.../RunExpressions.cs:32-42`）：`Run` / `Event` / `Card` / `Chooser` / `Intent`。
**里面没有 `CombatState`。**

⇒ **结论：这 4 种卡片选择器 100% 是 run 层语义，读的是 `RunState`（牌库 `Deck`、run RNG、player chooser），
与战斗态 `CombatState` 无关。** 参考实现里战斗内的"玩家选牌"是另一套东西：
`ICombatCardChooser`（`ref/.../RogueDeck.Core/Combat/Cards/CardZones.cs:37-40`）+ 卡实例表达式
`cardInstance.chosenInZone`（`CombatJson.cs:308`），**而那个在镜像里 0 次**。

### 7.4 顺带：镜像确实用到了、但"字段被忽略"的相邻风险（事实，不是建议）

战斗员选择器 `sel.source` / `sel.eventTarget` / `sel.lowestHealthEnemy` / `sel.iterationTarget` 在镜像里
**带 `Cardinality` + `RequiredContextCapabilities` 两个字符串字段**，实测取值：

```
t2     sel.eventTarget        Cardinality='ZeroOrOne' RequiredContextCapabilities='EventTarget'
t952   sel.iterationTarget    Cardinality='ZeroOrOne'
t310   sel.lowestHealthEnemy  Cardinality='ZeroOrOne'
t18    sel.source             Cardinality='ZeroOrOne' RequiredContextCapabilities='Source'
```

- `Cardinality` 在**全部实例里只有一个值**：`'ZeroOrOne'`。
- `RequiredContextCapabilities` 只见过 `'Source'` 与 `'EventTarget'`。
- 内核 `sel.rs::leaf_for` 对这些 kind 是「查表返回叶子，不读字段」，所以这两个字段今天是被丢掉的。
  若将来出现别的 `Cardinality` 值（如 `ExactlyOne` / `Any`），这会变成一个静默改语义的点。

---

## 8. Q7 —— 卡程序树上，15 种 `node.*` 之外的 kind

`native\_recon_card.py census`（完整输出，**并集**口径：所有 62 个 `Program.Root` 树可达的 term id 去重后的并集）

```
card programs with a Root: 62 / 62

kind                       in-15-node terms     edges    used-by-#cards
node.sequence              YES        40        0        43
node.dealDamage            YES        16        14       18
const                      -          15        48       59
node.applyStatus           YES        14        27       32
node.gainBlock             YES        10        9        14
multiply                   -          4         4        6
node.createCardInstance    YES        4         12       12
node.drawCards             YES        3         11       12
node.forEachCardInZone     YES        2         4        4
cardInstance.iterated      -          1         1        4
combatantStatusStacks      -          1         4        6
node.gainResource          YES        1         2        2
node.moveCardToZone        YES        1         2        4
sel.allEnemies             -          1         6        4
sel.eventTarget            -          1         25       40
sel.source                 -          1         21       33

kinds outside the 15 node.* kinds: 7 distinct ->
    ['cardInstance.iterated', 'combatantStatusStacks', 'const', 'multiply',
     'sel.allEnemies', 'sel.eventTarget', 'sel.source']
of the 15 node.* kinds, NOT present in any card program: 6 ->
    ['node.conditional', 'node.forEachTarget', 'node.heal', 'node.loseResource',
     'node.modifyStatusStacks', 'node.setCombatantCounter']
```

口径说明：`terms` = 并集里该 kind 的**去重 term 条数**；`edges` = 并集内部**父→子槽位出现次数**
（同一个 term 被多个父引用会重复计）；`used-by-#cards` = 用到该 kind 的卡数量（62 张里）。
`node.sequence` 的 `edges = 0` 是因为它**只当根**用（43 张卡的根就是 sequence）。

**回答 Q7 的三条事实：**

1. **15 种 `node.*` 里只有 9 种在卡程序树上出现过**：`sequence` / `dealDamage` / `applyStatus` / `gainBlock` /
   `createCardInstance` / `drawCards` / `forEachCardInZone` / `gainResource` / `moveCardToZone`。
   另外 6 种**在 62 个卡程序里 0 次**。它们实际在哪（下表是**下界**：我只扫了每张表的 program/trigger 类字段
   `Program` / `Triggers` / `PassiveModifiers` / `CombatRules` / `RunPrograms` / `TriggeredEffects` / `Intent`，
   没扫 `DeathPrevention` / `Disclosure` / `Prevention` / `Amplification` / `IncomingStatusDelay` / `DebuffBlock`）：

   | kind | 镜像 term 数 | 至少被这些表用到（行数） |
   |---|---|---|
   | `node.conditional` | 32 | `ENCT` 10、`STATUS` 7 |
   | `node.setCombatantCounter` | 30 | `ENCT` 8、`STATUS` 8、`EACT` 5 |
   | `node.modifyStatusStacks` | 15 | `STATUS` 7、`ENCT` 2 |
   | `node.forEachTarget` | 6 | `ENCT` 6 |
   | `node.heal` | 3 | `REL` 3 |
   | `node.loseResource` | 1 | `STATUS` 1 |

   即：这 6 种**确实被内容用到**（不是死变体），只是不在卡程序树上。
2. **15 种之外的 kind 只有 7 种**：`const`(15 条) / `multiply`(4) / `sel.eventTarget`(1) /
   `sel.source`(1) / `sel.allEnemies`(1) / `combatantStatusStacks`(1) / `cardInstance.iterated`(1)。
   前 6 种不是"源码里看着支持"，而是**有执行证据**：它们出现在 `approved_for_disposal` / `compounded_penalty` /
   `invalidated` 等卡上，而那些卡正是 `exec.rs:2992` 那条钉子测试断言 `ran == 58` 里的成员 ⇒ 至少在这些用例上能求值。
   第 7 种 `cardInstance.iterated` 则只落在那 4 张被拒的卡上。
3. **真正没实现、且出现在卡程序树上的 kind，只有 2 个节点 + 1 个表达式**：
   `node.forEachCardInZone`(2 条) / `node.moveCardToZone`(1 条) / `cardInstance.iterated`(1 条)。
   **它们三个加起来正好只落在 4 张卡上**（CARD[36..39]）。

**鲁棒性检查**：把根从 `Program.Root` 换成「卡行上所有 program 字段」（`Program` + `LifecyclePrograms` +
`PlayCondition` + `QueueOnPlay`），kind 集合**完全不变**（17 种，多出来的只有 `_obj` 信封本身）；
再把 `Tags` / `Costs` / `extra` 也算进去，只多出 `_arr` 和 `op6`（字符串包装 opcode）。
⇒ 没有别的 kind 藏在卡的其它字段里。

**逐卡核对**（`native\_recon_card.py cards` 完整输出，58 张 `unhandled-node=-`，只有 4 张带缺）：

```
duplicate_copy                 root=t51    kinds=1   unhandled-node=-   outside-15=[]
red_tape                       root=t51    kinds=1   unhandled-node=-   outside-15=[]
unsigned_form                  root=t51    kinds=1   unhandled-node=-   outside-15=[]
…
archive_the_evidence           root=t156   kinds=7   unhandled-node=['node.forEachCardInZone', 'node.moveCardToZone']
                                                   outside-15=['cardInstance.iterated', 'const', 'sel.source']
archive_the_evidence+          root=t162   kinds=7   unhandled-node=['node.forEachCardInZone', 'node.moveCardToZone']
                                                   outside-15=['cardInstance.iterated', 'const', 'sel.source']
shredder_drawer                root=t167   kinds=8   unhandled-node=['node.forEachCardInZone', 'node.moveCardToZone']
                                                   outside-15=['cardInstance.iterated', 'const', 'sel.eventTarget', 'sel.source']
shredder_drawer+               root=t172   kinds=8   unhandled-node=['node.forEachCardInZone', 'node.moveCardToZone']
                                                   outside-15=['cardInstance.iterated', 'const', 'sel.eventTarget', 'sel.source']
```

这与内核里已有的钉子测试一致（`kernel/rd-core/src/exec.rs:2992`
`every_card_program_in_the_image_either_runs_or_is_refused_by_kind`，断言
`ran == 58`、`refused == [36, 37, 38, 39]`、错误全是 `ExecError::UnsupportedNode`、且这 4 张的第一个子节点
确实是 `NodeKind::ForEachCardInZone`、其 `Body` 是 `NodeKind::MoveCardToZone`）。
本报告是用镜像**独立**重算出来的同一结论。

---

## 9. 与「扩卡片选择器」相关的规模判断（只给事实依据）

### 9.1 收益侧

- 扩四种 run 层卡片选择器，能让 **0 张**卡从 58 变多 —— 因为 62 个卡程序树里这 4 种 kind 出现 **0 次**（§4.3）。
- 扩它们的真实受益方是 `fx.removeCards` / `fx.upgradeCards` / `fx.duplicateCards` / `fx.transformCards`，
  而在我扫过的字段范围内这 4 个效果只从 `ROOT Events` 与 `ROOT Shops` 可达（§4.3）—— 那是 run 层，不是战斗内核。

### 9.2 成本侧的镜像事实

- `sel.deckCards` 的字段表是**空的**（nfields=0），`sel.matching` 只有 `Inner`+`Predicate`，
  `sel.random` 只有 `Count`+`Inner`，`sel.choose` 只有 `Count`+`Inner`+`Purpose`。二进制形状极简。
- 但语义全在 run 层：`RunState.Deck` / run RNG（`NextRandom`，每次抽取推进一步）/ `IRunEntityChooser`
  （缺 chooser 直接抛异常）/ `IRunExpression<bool>` 谓词 + `RunEvalContext.WithCard` 的当前卡绑定。
  这些内核一个都没有：`CombatState` 里没有 run 牌库、没有 run RNG 步进、没有 chooser。

### 9.3 反过来说，把那 4 张卡跑起来需要什么（镜像+内核现状对照）

| 需要的东西 | 镜像事实 | 内核现状（只读源码，未运行） |
|---|---|---|
| `CardZone` 枚举与 7 个线上名 | 只用到 `Hand`/`DiscardPile`/`ExhaustPile` | **已有**：`state.rs:482` 的 `CardZone`；`exec.rs:1138` `zone_from_wire_name` 已覆盖全部 7 个名字 |
| 移牌到区（含 Placement） | `Placement` 只有 `Bottom` | **已有**：`state.rs:1864` `CombatState::move_card`；`exec.rs:1138` 的 `zone_from_wire_name` 已被 `createCardInstance` 节点用来解 `to_zone` |
| 卡实例 id 迭代绑定 | `cardInstance.iterated` 1 条，只在这 4 张卡里 | **没有**：`exec.rs` 有 `iteration_target: Option<CombatantId>`（战斗员迭代），没有"卡实例迭代"；`expr.rs:207` 把 `cardInstance.iterated` 放在 `INT_KINDS` 分类表里、并注明"表里有但没实现"（`expr.rs` 注释 + `exec.rs` 模块头 `:19-20` 明说） |
| 按 tag 过滤卡定义 | `TagFilter = {"value":"junk"}`，`junk` 确实是卡 tag | **部分**：`content.rs` 有 `card.tags()`（返回 term 句柄），但 `exec.rs` 目前只按 `DefinitionFilter` 读过 `CardDefinitionId`，没读 card tag 集合 |
| `TakeFirst` / `MaxIterations` | `1` / `64`；`NULL` 表示不限 | 无 |

判断（明确标为**我的判断**，非事实）：**「扩卡片选择器」是错的方向，而且是大活**（要引入 run 层牌库 + run RNG +
chooser，收益 0 张卡）；**真正把这 4 张卡跑通是小活**（2 个节点 + 1 个 0 字段的卡实例表达式，牌区枚举与 `move_card`
原语内核已有，镜像里只需要支持 `Hand` 一个源区、`ExhaustPile` 一个目标区、`Bottom` 一种落位、`junk` 一个 tag 过滤值）。

---

## 10. 我没能查清 / 边界（诚实清单）

1. **没有运行任何 Rust 代码**（任务禁止跑 cargo）。所以「内核已有什么/缺什么」全部来自读源码与源码注释
   （`exec.rs` 模块头 `:19-20`、`:1136-1146`、`:1864` 等）与既有测试断言，**不是执行验证**。
   特别是「`content.rs` 能不能方便地按 tag 查卡定义」我只看到 `card.tags()` 返回 term 句柄，没验证解 `_arr` 的辅助函数是否已存在。
2. **`cardInstance.iterated` 在 `expr.rs:207` 的 `INT_KINDS` 里**，而该表的注释说「表里有但没实现的走 `UnsupportedKind`」。
   我没有确认实现体里到底有没有它的分支 —— 这一条请以 `exec.rs` 的证据（4 张卡因 `UnsupportedNode` 被拒）为准，
   它只证明**节点**被拒，**没有**单独证明表达式被拒。
3. `fx.removeCards` / `fx.upgradeCards` / `fx.duplicateCards` / `fx.transformCards` 我只追到 `ROOT Events` /
   `ROOT Shops`，**没有**逐条列出是哪个 event id / shop id（Root 树里 `Events` 是 op 123/125 那一族 `_obj`，
   逐个展开成本较高且与本问题无关）。
4. `sel.choose.AllowSkip` 在 C# 上有 `[JsonIgnore(WhenWritingDefault)]`，镜像里 4 条 term 都没有这个键
   ⇒ 只能推断这 4 处都是默认值 `false`；**镜像无法区分**「作者显式写 false」与「作者没写」。
5. `node.forEachCardInZone` 的 `DefinitionFilter` 在这个镜像里**每条都是 NULL**，
   所以「非 null 时它到底是什么 term 形状」（是 `{"value":"<card definition id>"}` 还是别的）**没有实例可看**。
6. 我没有去数 `sel.*` 战斗员选择器在 394 条敌动作里的完整分布（只数了出现/未出现的 kind 种类），
   因为问题只问卡片选择器。
7. `reader.py` 我只读没改。`native/_recon_card.py` 是一次性脚本，里面硬编码了
   「15 种已知 node kind」的集合与「4 种卡片选择器判别串」，**这两个列表是抄任务描述 + 镜像实测交叉验证的**，
   脚本本身不做语义判断（`cards` 子命令里的 `unhandled-node` 只比对 2 个 kind）。
