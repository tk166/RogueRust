# `.roguedeck.json` 内容文档 schema 与二进制化勘察

> 勘察对象：`ref/RogueDeck-Core/src/RogueDeck.Sandbox.Run/SampleContent/bureaucrats.roguedeck.json`
> （8,291,305 B，CRLF，159,947 个换行，纯 ASCII）。
> 探针脚本（交付物，都在 `ref/`）：`content_probe.py`（主，全部统计）、`dup_check.py`（重复子树）、
> `raw_attr.py`（原始字节归属）、`rom_estimate.py`（ROM 体积模型）。
> 运行须 `PYTHONIOENCODING=utf-8`，且必须用 `ProcessStartInfo` 收 stdout（本机 `&` 调 exe 会吞输出）。

**四个头条结论（全部实测）**

| # | 结论 | 数字 |
|---|---|---|
| 1 | 这份 7.91 MB 里 **78.6% 是缩进空白**，紧凑 JSON 只有 1.77 MB | raw 8,291,305 B → compact 1,774,029 B |
| 2 | 紧凑形式里 **48.0% 是冗余的 `Children` 数组**（同一批嵌套节点的第二份拷贝） | 去掉后 1,774,029 → 921,704 B |
| 3 | `Encounters` 一节独占 **71.8% 的原始字节**；其中 31 条 trigger 程序只有 **10 个互异函数体**，21 份是逐字节重复 | Encounters 5,955,367 B；重复 743,993 B |
| 4 | 整份文档用到的效果节点只有 **73 种 opcode / 875 个互异子树**；按 opcode+u16 句柄编码，**内核 ROM ≈ 88 KB** | 见 §5 |

---

## 1. 实体清单与规模

### 1.1 顶层 22 个键的原始字节归属

`raw` 一列是在原文里逐字符量出的区间（`ref/content_probe.py` Phase 0），不是紧凑长度乘系数。

| 键 | 类型 | 条目 | **原始字节** | 占文件 | 紧凑字节 | 原文/紧凑 | 空格占比 |
|---|---|---|---|---|---|---|---|
| `Encounters` | array | 109 | **5,955,367** | **71.83%** | 1,027,137 | 5.80 | 82.8% |
| `Map` | object | 4 | 654,237 | 7.89% | 117,810 | 5.55 | 82.0% |
| `EnemyActions` | array | 394 | 627,387 | 7.57% | 280,980 | 2.23 | 55.2% |
| `Events` | object | 20 | 479,224 | 5.78% | 108,646 | 4.41 | 77.5% |
| `Statuses` | array | 23 | 178,591 | 2.15% | 57,346 | 3.11 | 67.9% |
| `Presentation` | object | 11 | 158,725 | 1.91% | 88,071 | 1.80 | 45.2% |
| `Cards` | array | 62 | 139,510 | 1.68% | 61,291 | 2.28 | 55.9% |
| `Relics` | array | 49 | 90,877 | 1.10% | 29,264 | 3.11 | 67.9% |
| `Shops` | object | 1 | 4,224 | 0.05% | 1,721 | 2.45 | 59.4% |
| 其余 13 键 | — | — | <3,500 | 0.04% | <1,600 | — | — |

`MapGeneration` 为 `null`；`CombatResources` / `Consumables` / `Shreds` / `Recipes` /
`Workbenches` 全为空（各 12–21 B）。**结论：7.91 MB 由 `Encounters` 一节决定，其余全部可忽略。**

### 1.2 每类实体的字节规模

`avg/median/max` 均为紧凑 JSON 字节（`enc()` = `json.dumps(separators=(",",":"), ensure_ascii=False)`）。

| 实体 | n | 合计 | avg | median | max | 撑大它的字段 |
|---|---|---|---|---|---|---|
| Card | 62 | 61,228 | 987 | 1,043 | 1,376 | `Program` 58.7% |
| Status | 23 | 57,322 | 2,492 | 836 | **18,266** | `Triggers` 84.8% |
| Relic | 49 | 29,214 | 596 | 652 | 1,059 | `RunPrograms` 86.7% |
| EnemyAction | 394 | 280,585 | 712 | 778 | 1,608 | `Program` 73.6% + `Intent` 9.8% |
| **Encounter** | 109 | **1,027,027** | 9,422 | 638 | **762,017** | `TriggeredEffects` 92.5% |
| Event | 20 | 108,198 | 5,409 | 5,083 | 13,291 | `situations[].Choices[].Effects` 91.5% |
| Character | 1 | 486 | — | — | 486 | — |
| MetaRule | 1 | 98 | — | — | 98 | — |
| Map | — | 117,810 | — | — | — | `Nodes` 113,445（31 节点） |
| Shop | 1 | 1,707 | — | — | — | 全部是 offers |
| Presentation | 11 小节 | 88,071 | — | — | 29,025(Enemies) | 引擎**完全不读** |

**极值极为畸形**：`Encounters` 中位数 638 B、最大 762,017 B——单个遭遇
`city_normal_ordinance_08` 占该节 74%、占紧凑文档 43%。
`Statuses` 中位数 836 B、最大 18,266 B（`still_missing_a_signature`）。

### 1.3 冗余：三个可实测的减重大头

| 冗余 | 紧凑 JSON 字节 | 占紧凑 | 原文折算 | 证据 |
|---|---|---|---|---|
| 全部对象键名 | **975,636** | 55.0% | ~4.6 MB | 571 个不同键名，98,763 次出现 |
| 其中 `kind` + `value` 信封 | 299,678 | 16.9% | — | `kind` 16,890 次 / `value` 22,681 次 |
| 冗余 `Children` 视图 | **852,325** | **48.0%** | **~3.98 MB** | `dup_check`：4,311 个节点带 `Children`，3,038 个与具名字段重复 |
| `Cardinality`+`RequiredContextCapabilities` | 117,612 | 6.6% | — | 选择器**类型**的派生属性 |
| `Presentation` 全节 | 88,071 | 4.97% | 158,725 | 引擎从不读（`Presentation.cs:4-7`） |

> `Children` 是**序列型节点以外的所有节点**上的一份额外拷贝。`CombatJson.cs:166-193`
> 已经实现了「只在构造函数真的接收 `children` 时才写」的裁剪，并记录了历史事故：
> 「一个 boss 规则因此膨胀到 311,624 个节点 / 15 MB，而树本身只有约 40 个节点」。
> 本文件显然产自裁剪生效之前。`ConditionalEffectNode.Children` 是**只读计算属性**
> （`Effects/Programs/EffectProgramNodes.cs:65,85-87`），反序列化时被忽略，
> 因此**删掉 `Children` 不改变任何行为**——文档自己也这么说（`CombatJson.cs:175-176`）。

### 1.4 字符串预算

| 指标 | 值 |
|---|---|
| 字符串叶子 | 38,066 个，共 **585,834 B**（紧凑的 **33.0%**） |
| 不同字符串 | 2,926 个 → 去重池 **77,484 B**（省 508,350 B，86.8%） |
| 长度分布 | ≤7 字符 8,356 / 8–15 字符 17,455 / 16–31 字符 11,221 / ≥32 字符 1,034 |
| 非 ASCII | 极少（`ensure_ascii` 差异仅 1,575 B），可视为纯 ASCII |
| 键名次数 Top | `value`×22,681、`kind`×16,890、`Cardinality`×4,218、`RequiredContextCapabilities`×1,952、`TargetSelector`×3,211、`Value`×6,469、`Children`×4,311 |
| 串值 Top | `sel.iterationTarget`×2,264、`node.setCombatantCounter`×1,637、`ZeroOrOne`×4,218、`sel.eventTarget`×1,637、`const`×3,695 |

**键名 + 串值 = 1,561,470 B = 紧凑文档的 88.0%。** 二进制化的全部收益都在这里。

---

## 2. 每类实体的 schema

字段名按 C# 属性名**原样**写（`System.Text.Json` 不做驼峰转换）。带
`WhenWritingNull`/`WhenWritingDefault` 的字段取默认值时不出现——这是「同一字段有时在
有时不在」的唯一原因。下表「本文件」列给出实测取值，它就是二进制布局的推导依据。

### 2.1 文档根 `RunBlueprint`（`RunBlueprint.cs:12-18` 位置参数 + `init` 属性）

| 键 | 类型 | 必填 | 含义 / 本文件 |
|---|---|---|---|
| `Deck` | `CardDefinitionId[]` | ✓ | 共享起始牌组（`:13`）；10 条 |
| `Events` | `map<id, EventScript>` | ✓ | `:14`；20 条 |
| `Encounters` / `Cards` / `EnemyActions` / `Map` | — | ✓ | `:15-18` |
| `SchemaVersion` | int | ✓ | 缺省视为 0；迁移梯 `RunBlueprintSchema.cs:17-24` |
| `Statuses` / `Relics` / `CombatResources` / `Consumables` | `[]` | 默认空 | `:28,32,48,52` |
| `Shops` | `map<id, ShopDefinition>` | 默认 `{}` | `:56` |
| `Start` | `RunStart` | 默认 | `:61`；`{HeroName:"Bureaucrat",MaxHealth:70,StartingHealth:70,Resources:{"gold":0},Deck[10],StartingRelics:[],StartingConsumables:[],StartingUnits:[],StartingParty:[]}` |
| `Characters` | `RunCharacter[]` | 默认 `[]` | 非空时**覆盖** `Start`（`:68`、`ResolveStart :167-175`） |
| `MetaRules` | `MetaRule[]` | 默认 `[]` | 本文件 1 条：`WhenResult:[Victory] → Effects:[meta.setFlag{Flag:"bnb.act1.cleared"}]` |
| `Presentation` / `Balance` | 对象 | 默认 | `:88` / `:94`。前者引擎不读，后者地图生成器**读** |
| `Programs` / `MapGeneration` / `Acts` / `Tutorial` / `StrategicMapGeneration` | 可空 | 默认省略 | `:44,100,121,129,110`；本文件只有 `MapGeneration: null` |
| `Shreds`/`Recipes`/`ShredRules`/`Workbenches` | 默认空 | `:79-83` | 碎片合成系统，本内容未用 |

**小冗余**：起始 10 张牌在 `Deck`、`Start.Deck`、`Characters[0].Start.Deck` **写了三遍**；
`Characters` 非空时顶层 `Deck` 已失效（`EffectiveDeckSize`，`RunDocumentValidator.cs:306-307`）。

### 2.2 其余实体（一个字段字典）

| 实体 | 字段 | 类型 | 必填 | 本文件实测 / 含义 |
|---|---|---|---|---|
| **Card**<br>`CardData.cs:11-45` | `Id` | string | ✓ | 62 条 = 33 基础 + 29 `+` 升级版 |
| | `PackageId` | string | 默认 `"scenario"` | 479 处全同 |
| | `NameKey` / `DescriptionKey` | string? | 可空 | `DescriptionKey` **479/479 全 null** |
| | `Costs` | `{ResourceId:{value},Amount}[]` | 默认 `[]` | |
| | `Tags` | `{value}[]` | 默认 `[]` | 占该节 11.9% |
| | `Program` | `EffectProgram<CardPlayContext>?` | 可空 | 占该节 **58.7%** |
| | `LifecyclePrograms` | `map<trigger, EffectProgram>` | 默认 `{}` | 全为 `{}` |
| | `RetainInHandOnTurnEnd` | bool | 默认 false | |
| | `TurnEndHandDestinationZone`/`PlayedCardDestinationZone` | enum 名 | 默认 `DiscardPile` | |
| | `QueueOnPlay`/`IsAction`/`PlayCondition` | — | 默认省略 | 本文件未出现 |
| **Status**<br>`StatusData.cs:12-152` | `Id`/`Polarity`/`UsesStacks`/`UsesDuration`/`UsesCharges`/`StackingBehavior` | — | | 23 条；`StackingBehavior` 本文件用 `MergeWithExistingInstance` |
| | `Tags` | `string[]` | 默认 `[]` | **裸字符串**，不是 `{value}` 包装 |
| | `PassiveModifiers` | `PassiveModifierData[]` | 默认 `[]` | `:225-260` |
| | `CombatRules` | `CombatRuleData[]?` | 可空 | 「法令」：戴上时改变战斗规则（`:267-282`） |
| | `Triggers` | `{Event, Program}[]` | 默认 `[]` | 占该节 **84.8%**；`Program` 是**上下文无关** `CombatJson`（`:146-155`） |
| | `DeathPrevention`/`DebuffBlock`/`IncomingStatusDelay`/`Disclosure`/`Prevention`/`Amplification` | 对象? | 可空 | **23/23 全 null** |
| **Relic** | `Id`/`DisplayName` | string | ✓ | 49 条；显示名内联 |
| | `RunPrograms` | `{event,condition,templates[]}[]` | 默认 `[]` | 占 **86.7%**；`templates[]` 全是 `tpl.literal`×41 |
| | `CombatRules` | `{trigger,priority,program}[]` | 默认 `[]` | 按 `trigger` 分派上下文（`RelicCombatRuleJsonConverter.cs:10-34`） |
| **EnemyAction**<br>`EnemyActionData.cs:8-15` | `Id`/`PackageId`/`NameKey`/`DescriptionKey` | string | Id ✓ | 394 条 |
| | `Intent` | `{Kind, Label}` | **✓** | `Kind ∈ {Special 168, Attack 110, Debuff 51, Defend 44, Buff 21}`；`Label` 占 Intent **69.8%（纯表现）** |
| | `Program` | `EffectProgram<EnemyActionContext>?` | 可空 | 占 **73.6%** |
| **Encounter** | `Id` | `{Value}` | ✓ | 109 条 |
| | `Enemies` | `{Id,DisplayName,MaxHealth,Actions[],StartingStatuses?,Position?,IntentRules?}[]` | ✓ | 149 条 / 123 互异（26 次逐字节重复）；`IntentRules` 只有 11 个遭遇有 |
| | `HeroResources` | `{Resource:{value},Current,Max}[]` | ✓ | 0.8%；**109 个完全相同** = `[{standard.energy,3,3}]` |
| | `HeroStartingStatuses` | `{Status:{value},Stacks,DurationTurns,Charges}[]` | ✓ | 1.1%；**109 个完全相同** = `[the_applicant,1,0,0]` |
| | `HeroDisplayName`/`CardsDrawnPerTurn` | `string?`/`int?` | 109/109 null | 0.5% |
| | `TriggeredEffects` | `{Event, Program}[]` | ✓ | **92.5%**（见 §3.6 的重复问题） |
| **Event**<br>`RunJson.cs:362-383` | `startSituationId` + `situations[{Id,TextKey,Choices[]}]` | — | ✓ | 20 脚本 / **50 situation** / **70 choice**；`Choices` 占 situation 93.9%，`Effects` 占 choice **91.5%** |
| | `Choice.Requirement` / `Choice.Costs` | — | **70/70 全 null** | 2,170 B 纯噪声；当前内容没用条件分支与花费 |
| **Map** | `Nodes[{id,type,payload:{kind,value},tags?}]` | — | ✓ | 31 节点：`combat`×23 / `event`×7 / `shop`×1；payload 一一对应 `node.encounter`/`node.event`/`node.shopRef` |
| | `Edges`/`EntryNodeIds`/`Layout` | — | | 41 / — / —；`Nodes` 113,445 B = `Map` 的 96% |
| **Shop** | `Offers[{Id,Currency:{Value},Price,Payload[fx.*],TextKey}]` | — | ✓ | 1 个（`city-shop`，1,707 B） |
| **Presentation** | 11 小节 × `{Art,FlavorText,Icon,Rarity,Frame,Color,Sound,Vfx,Tags[],Extra{}}` | `Presentation.cs:8-33` | | Enemies 118 / 29,025 B，Encounters 109 / 23,732，Cards 62 / 16,604，Relics 49 / 12,931，Events 15 / 3,273，Statuses 7 / 1,964，Characters 1，Game。`Frame`/`Color`/`Sound`/`Vfx` **362/362 全 null**。**引擎从不读** |
| **Balance** | `{Enemies,Encounters,Cards,Relics,Consumables,Characters}` map + `Defaults` | — | | 143 B，map 全空、`Defaults` 全 0 |

两个真实样本（截断）：

```json
// Cards[8] (481 B，最小)
{"Id":"red_tape","PackageId":"scenario","NameKey":"Red Tape","DescriptionKey":null,"Costs":[],
 "Tags":[{"value":"junk"},{"value":"unplayable"},{"value":"generated"},{"value":"bureaucracy"},{"value":"curse"}],
 "Program":{"Id":{"Value":"(unnamed)"},"Root":{"kind":"node.sequence","value":{"Children":[]}},
            "MaxNodeDepth":64,"MaxProgramSteps":1024},
 "LifecyclePrograms":{},"RetainInHandOnTurnEnd":false,
 "TurnEndHandDestinationZone":"DiscardPile","PlayedCardDestinationZone":"DiscardPile"}

// EnemyActions[43] (778 B，节选) —— 注意 Intent.Label 是纯表现，Program 才是行为
{"Id":"...","Intent":{"Kind":"Attack","Label":"Rubber Stamp Rush · 5 dmg"},
 "Program":{"Id":{"Value":"(unnamed)"},"Root":{"kind":"node.sequence","value":{"Children":[
   {"kind":"node.dealDamage","value":{"Amount":{"kind":"const","value":{"Value":5}},
     "Element":"","IgnoresBlock":false,"ResultKey":null,
     "TargetSelector":{"kind":"sel.eventTarget","value":{
        "Cardinality":"ZeroOrOne","RequiredContextCapabilities":"EventTarget"}}}}]}},
   "MaxNodeDepth":64,"MaxProgramSteps":1024}}
```

> `Map` 一节之所以有 654 KB：23 个 `node.encounter` 每个内联一整棵
> `reward.fixed → fx.offerReward → reward.pool → 每卡一个 fx.addCard` 的奖励树
> （111,369 B / 23 = 4,842 B each）。二进制化时奖励池必须**独立成表并用 u16 引用**，
> 否则 23 份池子各写一遍。

---

## 3. 「效果程序」的 JSON 表示

### 3.1 线格式：`{"kind": "...", "value": { ... }}`

判别式统一由 `CombatPolymorphicConverter<TBase>` 写/读（`CombatJson.cs:51-117`），
读端先扫 `kind` 再按 `value` 派发到「按上下文闭合的开放泛型」
（`CombatJsonRegistry.Resolve`，`CombatJson.cs:40-45`）。四种判别**键名**在文档里都用到了：

| 键 | 次数 | 用途 |
|---|---|---|
| `kind` | 16,890 | 全部战斗节点 / 表达式 / 选择器 / run 层节点 |
| `Op` | 744 | `compare` 的运算符（`ComparisonOperator` 枚举名） |
| `Kind` | 394 | `EnemyAction.Intent` 的 `IntentKind` |
| `type` | 31 | `Map.Node.type` |

### 3.2 已注册种类 vs 实际使用种类

| 注册表 | 注册数 | 出处 |
|---|---|---|
| `CombatJson.DefaultRegistry()` | **173** | `CombatJson.cs:217-421`（表达式 85 / 选择器 36 / 节点 52） |
| `RunJson.DefaultRegistry()` | **133** | `RunJson.cs:141-321` |
| **合计** | **306** | |
| **本文档实际出现的互异判别值** | **86**（其中 73 个是 `kind`） | 探针 Phase 3 |

即：**为了运行这份内容，VM 只需要实现 73 个节点 opcode + 少量表达式/选择器**；
剩下 200 多个种类是引擎能力，不是内容需求。这对 ROM 尺寸是决定性的。

### 3.3 节点种类清单与出现次数

按**原始 `kind` 计数**（含冗余 `Children` 带来的重复）与**去重后（剥掉冗余 `Children`）**两列：

| kind | 原始次数 | 去重后 | 归谁所有 |
|---|---|---|---|
| `const` | 3,695 | 1,090 | 各处 |
| `sel.iterationTarget` | 2,264 | 232 | Encounters |
| `node.setCombatantCounter` | 1,637 | 165 | Encounters |
| `sel.eventTarget` | 1,637 | 698 | Encounters/EnemyActions |
| `node.sequence` | 1,273 | 353 | 各处 |
| `node.applyStatus` | 936 | 343 | Encounters/EnemyActions |
| `compare` | 739 | 150 | Encounters |
| `fx.addCard` | 738 | 738 | Map/Events |
| `node.conditional` | 563 | 110 | Encounters/Statuses |
| `combatantCounter` | 550 | — | Encounters |
| `combatantStatusStacks` | 495 | 168 | Encounters |
| `fx.addRelicById` | 492 | 492 | Map/Events |
| `node.dealDamage` | 260 | 258 | EnemyActions |
| `node.gainBlock` | 181 | 169 | EnemyActions |
| `node.modifyStatusStacks` | 159 | 30 | Statuses |
| `sel.source` | 315 | 299 | 各处 |
| `fx.incrementCounter` / `fx.changeResource` / `fx.installNextCombatOpening` / `tpl.literal` | 70/63/41/41 | 同 | Events/Relics |
| `fx.offerReward` + `reward.pool` + `reward.fixed` | 39/39/23 | 同 | Map/Events |
| `node.forEachTarget` | 27 | 27 | Map |
| `node.encounter` / `node.event` / `node.shopRef` | 23/7/1 | 同 | Map |
| 其余 40 余种 | ≤20 | ≤20 |  |

完整清单由 `content_probe.py` Phase 3 逐条打印。

### 3.4 嵌套方式与深度

* 复合节点：`node.sequence`（`Children`，N 个）、`node.causalSequence`、
  `node.chooseOptions`（`Children` + `OptionLabels` + `Amount`）、
  `node.conditional`（`Condition` + `Then` + `Else`）、
  `node.forEachTarget`（`CollectionSelector` + `Body` + `MaxIterations`）、
  `node.forEachCardInZone`、`node.repeat`、`node.repeatUntil`、`node.randomTargets`。
  清单见 `CombatProgramModel.cs:544-555`（9 种复合）与 `:405-447`（41 种叶子）。
* 表达式作为**具名子字段**嵌套，不是 `Children`：
  `Amount`/`Stacks`/`Stacks`/`Count`/`Delta`/`Value`（数值），
  `TargetSelector`/`CollectionSelector`/`Selector`/`ToSelector`（选择器），
  `Condition`（布尔），`Card`（卡实例表达式），`Left`/`Right`/`Third`（算术）。
* **实测最大嵌套深度 = 37 层 JSON**（探针 Phase 0）；程序树本身最深 9 层
  （`node.conditional` → `Then` 链）。
* 递归结构：`sel.union`（`Members[]`）、`sel.withStatus`（`Inner`）是选择器里唯一递归的两处
  （`CombatProgramModel.cs:84-103`）。
* **`Children` 是额外的一份拷贝**（`CombatProgramModel.cs:144-256`）——见 §1.3。

### 3.5 表达式 / 选择器的实际种类

* 选择器（`sel.*`）：本文档用了 14 种，共 **4,368 个实例**，JSON 合计 **约 365 KB**，
  平均 **66–106 B 一个**。而每个选择器在二进制里只需要 **1 字节 opcode**（参数化的
  `sel.withStatus`/`sel.alliesWithStatus`/`sel.enemiesWithStatus` 再加 1 个 status u16）。
  `Cardinality`（`ZeroOrOne`/`Many`）与 `RequiredContextCapabilities`（`Source`/`EventTarget`…）
  **是 43 个具体选择器类的只读属性**（`CombatJson.cs:316-359` 注册表），
  在 JSON 里被逐实例写了两遍，共 117,612 B——**信息量为零，可全部删除**。
* 表达式（数值/布尔）：`const`(1,090 去重后) / `compare` / `and` / `or` / `not` /
  `combatantCounter` / `combatantStatusStacks` / `combatantCurrentResource` /
  `cardsPlayedThisTurn` / `cardsPlayedLastTurn` / `eventAmount` / `multiply` / `subtract` /
  `GreaterOrEqual`(249) / `Greater`(229) / `Equal`(183) / `Less`(80) / `LessThan`(3)。
  比较**节点本身**（`compare`）与**运算符**（`Op`）分两层：`compare` 的 `value` 里再放一个
  `{Left, Op, Right}`。`Op` 是枚举名，二进制 → 3 bit。
* 值类型表达式本身也走 `{kind,value}` 信封：`const` 的 JSON 平均 36 B，二进制 = opcode(1) + i16(2) = **3 B**。

### 3.6 逐字节重复（最关键的一条）

```text
encounter TriggeredEffects programs: 10 distinct bodies, 31 instances
duplicated bodies: 4 groups, 21 redundant copies, 743,993 B of identical JSON
    x5  134252 B each
    x4  39368 B each
    x10  7909 B each
    x6   3540 B each
all nodes: 875 distinct subtrees, 16890 instances; 441 duplicate groups
```

`city_normal_ordinance_08`（762,017 B）的 10 条 trigger 事件分布是
`{StatusApplied:2, StatusMerged:2, StatusStacksChanged:2, StatusRemoved:2, StatusExpired:2}`
——**同一条规则体被 5 个事件各写了两遍**。

**这条决定了二进制编码的形态**：程序体必须能被**内容寻址地共享**，
而不是每个事件内联一份。§5 的 875 个互异子树就是这个共享池的大小。

---

## 4. 引用的完整性

### 4.1 一切引用都是字符串

引擎里所有 id 类型都是 `readonly record struct X(string value)`
（`src/RogueDeck.Core/Combat/CombatIds.cs:3-78`，16 种）。
JSON 里同一个 id 有三种写法，取决于声明处的 C# 类型：

| 写法 | 出现次数 | 举例 | 出处 |
|---|---|---|---|
| `"value": "..."` | 3,128 次引用 | `{"value":"paperwork"}` | `StatusDefinitionId` 等（小写 `value`，`CombatIds.cs:3`） |
| `"Value": "..."` | 747 次引用 | `{"Value":"city_easy_02"}` | `EncounterRef.Id` 等（大写 `Value`） |
| 裸字符串 | 479 次声明 + `Tags` 里的 `"attack"` | `"Id":"red_tape"`, `"Tags":["junk"]` | `CardData.Id`（string）、`StatusData.Tags`（`string[]`） |

**声明总数 784 个 id**：

| 类别 | 数量 | 声明位置 |
|---|---|---|
| EnemyAction | 394 | `EnemyActions[].Id` |
| Encounter | 109 | `Encounters[].Id.Value` |
| Card | 62（33 基础 + 29 `+`） | `Cards[].Id` |
| Relic | 49 | `Relics[].Id` |
| MapNode | 31 | `Map.Nodes[].id` |
| Status | 23 | `Statuses[].Id` |
| Event | 20 | `Events` 的**键名** |
| Shop / Character | 1 / 1 | `Shops` 键名 / `Characters[].Id` |
| 合成 id（奖励池条目） | 62 (`card-<id>`) + `cards:<encounter>` | 由内容自己 mint，非声明 |

`< 65,536` ⇒ **全部 id 可以内化为 u16 句柄**，且不需要哈希。

### 4.2 外键关系全表

| 引用方（字段） | 指向 | 实测引用数 | 校验位置 |
|---|---|---|---|
| 程序节点 `ApplyStatusNode.StatusDefinitionId.value` | Status | 1,805 | `CombatDefinitionRegistryBuilder.cs:550-558` |
| 程序节点 `CreateCardInstanceNode.CardDefinitionId` / `fx.addCard.Card.value` | Card | 838 | `:560-563` |
| `fx.installNextCombatOpening.Rule.program` 里的 `StatusDefinitionId` | Status | 计入上行 | — |
| `EnemyActions[].Id.Value` 被 `Enemies[].Actions[].value` 引用 | EnemyAction | 485 | `RunDocumentValidator.cs:141-146`、`ScenarioBlueprint.cs:144-147` |
| `Enemies[].IntentRules[].Action` | EnemyAction | — | `ScenarioBlueprint.cs:149-152` |
| `Map.Nodes[].payload.Id.Value`（`node.encounter`） | Encounter | 23 | `RunDocumentValidator.cs:153-155`、`RunContentRegistry.cs:130-131` |
| `Map.Nodes[].payload.Id.Value`（`node.event`） | Event | 7 | `RunDocumentValidator.cs:156-158` |
| `Map.Nodes[].payload.Id.Value`（`node.shopRef`） | Shop | 1 | `:159-161` |
| `Start.Deck[].value` / `Characters[].Start.Deck[].value` | Card | 20 | `:95-97`、`:129-131` |
| `Start.StartingRelics[]` / `Characters[].Start.StartingRelics[]` | Relic | — | `:101`、`:132-134` |
| `Start.StartingConsumables[]` / `Characters[].Start.StartingConsumables[]` | Consumable | — | `:102`、`:135-137` |
| `Presentation.<Kind>[<id>]` 的**键** | 对应实体 | Enemies 118 / Encounters 109 / Cards 62 / Relics 49 / Events 15 / Statuses 7 | `:168-186`（`CheckPresentation`） |
| `Balance.{Enemies,Encounters,Cards,Relics,Consumables,Characters}` 的**键** | 对应实体 | 本文件全为空 map | `:188-196`（`CheckBalanceIds`） |
| `Cards[].Costs[].ResourceId.value` | CombatResource / 遭遇授予的资源 / `standard.energy` | — | `:261-274`（仅导出门禁） |
| `Cards[].Tags[].value`、`Statuses[].Tags[]` | 开放标签词表（**不是外键**） | 1,645（201 个互异） | 无校验 |
| `Recipes[].Ingredients[]` / `ResultCardId` | Shred / Card | 本文件空 | `:57-82` |
| `MetaRules[].Effects[].value.Flag` | 全局 flag 字符串（**不是外键**） | 1 | 无校验 |

`Tags` 是 1,645 次出现、201 个互异值的**开放词表**（`attack` / `spell` / `bureaucracy` /
`damage_over_time` / `upgraded` …）。**它必须是字符串池 + 位集，不能当外键**。
`CounterId`（550+70 次）、`TeamId`、`Element`、`PoolId`、`Flag` 同理。

### 4.3 「重命名一张卡会波及哪些地方」

实测三条样本：

| 被改名 id | 出现总次数 | 出现位置分布 |
|---|---|---|
| `paper_cut`（基础卡） | **13** | `value`×12（牌组/费用/程序），`Id`×1（声明） |
| `paperwork`（状态，本内容最热） | **280** | `value`×242（`StatusDefinitionId`），`Tags`×37，`Id`×1 |
| `city_easy_02`（遭遇） | 2 | `Value`×2（Map 节点 + 其它引用） |
| `self_inking_stamp`（遗物） | 11 | `Value`×10（`fx.addRelicById`），`Id`×1 |

**结论**：重命名是纯粹的全局字符串替换，**没有任何位置化引用可以依赖**：

1. 声明处（1 处，字段名取决于实体：`Id` / `Id.Value` / map 键）；
2. 所有 `{"value": "..."}`、`{"Value": "..."}` 引用；
3. **`Tags` 数组里的同名串**（`paperwork` 的 37 次就是这个）——最容易被漏掉，
   因为它在语义上既是「标签」又是「状态名」；
4. `Presentation.<Kind>` 与 `Balance.<Kind>` 的 **map 键**（不在值里，正则替换容易漏）；
5. 合成 id：`"card-<id>"`（62 个奖励池条目）、`"cards:<encounterId>"`、
   `"encounter_<encounterId>_trigger<index>"`（`EncounterTriggerRebuild.cs:18`）——
   **这些 id 是由别处的 id 拼出来的**，改名必须同步拼法；
6. `"<id>+"` 升级后缀约定：`RunDeckMappers.UpgradeSuffixWhenDefined`（`StandardRunPackage.cs:82-84`）。

因此编译期第一件必须做的事：**建立 id → u16 的符号表，把所有引用点改成句柄**，
让「改名」变成编译期错误而不是静默悬空。引擎目前只在少数几处校验（见 §6）。

---

## 5. 二进制编码提案

### 5.1 原则

1. **键名全灭**：`{"kind":K,"value":{...}}` → `u8 opcode` + 该 opcode 的**固定字段布局**。
   仅此一项消掉 975,636 B（紧凑的 55.0%）。
2. **字符串池 + u16 句柄**：2,926 个互异串分 core（1,638，**43,789 B**）与表现（1,248）两池；
   所有 `Id`/`ResourceId`/`StatusDefinitionId`/`TagId`/`CounterId`/`PackageId`/`Value` 变成 u16。
3. **枚举 → 1 字节**（40 个互异枚举值：`ZeroOrOne`/`GreaterOrEqual`/`DiscardPile`/`Direct`/
   `AddFlat`…）。其中 `Op` 只需 3 bit，`Cardinality` 只需 1 bit。
4. **派生字段全删**：`Cardinality`、`RequiredContextCapabilities`（选择器类型决定）、
   `MaxNodeDepth`/`MaxProgramSteps`（引擎常量）、**冗余 `Children`**。
5. **程序体内容寻址**：875 个互异子树建表，实例表存 u16 索引；每条 trigger/牌/动作只存一个
   `u16 programRoot`，多个事件共享同一 root 是**天然结果**，直接消灭 743,993 B 的逐字节重复。
6. **表现层剥离**：`Presentation`（88,071 B）+ `NameKey`/`DescriptionKey`/`TextKey`/
   `DisplayName`/`Intent.Label`/`FlavorText` 全部进**可选 sidecar**。

### 5.2 逐层布局（实测计数驱动）

| 层 | 记录数 | 布局 | 估算 |
|---|---|---|---|
| 字符串池 core | 1,638 串 | 长度前缀 blob + u16 偏移表 | **43,789 B** |
| 效果节点 opcode | 6,182 实例 | `u8 opcode` + 字段（枚举 1 B、int i16、id u16、子节点 u16） | 24,956 B |
| 表达式/选择器 opcode | 3,041 实例 | `u8 opcode` + 操作数 | 7,781 B |
| 排列/对齐/表头 | — | 预留 15% | 11,478 B |
| **CORE ROM** | | | **≈ 88 KB** |
| Presentation + 表现串 | 1,248 串 | JSON 88,071 B + 串 30,284 B | **≈ 118 KB（可剥离）** |
| **含表现合计** | | | **≈ 206 KB** |

（`ref/rom_estimate.py` 逐字段跑的模型；**参照点：原文 8,291,305 B、紧凑 JSON 1,774,029 B**。）

交叉验证用的**实测参照量**：互异效果节点子树 **875** 个（＝整个 ROM 的 opcode 表）；
节点实例 16,890 → **6,182**（剥冗余后）；表达式+选择器 3,041；
若 875 个互异形各存一次、子节点算 4 B 引用，得 90,183 B（与 core 同量级，互相吻合）。

**估算的不确定性**：计数全部来自探针实测；「字段长度」是模型假设（int=i16、id=u16、bool=1 B），
即使 1,090 个 `const` 全需要 i32 也只 +2 KB。
反向看：**不**剥冗余 `Children` → 节点层 ×2.7、core ≈ 130 KB；
**不**删 `Cardinality`/`RequiredContextCapabilities` → +118 KB；
不做程序体共享 → Encounters 一节恢复 743,993 B。
故 **88 KB 是「做对了」的下界量级，130–250 KB 是「做一半」的区间**。
未计 VM 解释器代码（对 ESP32-P4 是独立成本）。

### 5.3 可以砍掉的字段（按收益排序）

| 字段 | 实测字节 | 判定 |
|---|---|---|
| 全部键名 | 975,636 | **必须砍**（opcode 化） |
| 冗余 `Children` | 852,325 | **必须砍**（引擎本就忽略） |
| 逐字节重复的程序体 | 743,993 | **必须砍**（内容寻址共享） |
| `Cardinality` + `RequiredContextCapabilities` | 117,612 | **必须砍**（类型派生） |
| `Presentation` 全节 | 88,071 | **砍**（引擎不读，`Presentation.cs:4-7`）；放 sidecar |
| `ResultKey` | 26,826（1,578 次全 null） | 砍；二进制里只用 1 bit「有结果键」 |
| `DescriptionKey` | 10,538（479 次全 null） | 砍或 sidecar |
| `PackageId` | 5,748（479 次全 `"scenario"`） | 砍（默认值） |
| `Frame`/`Color`/`Sound`/`Vfx` | 18,100（362 次全 null） | 砍（在 Presentation 内，随之而去） |
| `Intent.Label` | 16,702（占 Intent 69.8%） | sidecar（纯表现） |
| `NameKey`/`TextKey`/`DisplayName` | ~14,000 | sidecar（表现） |
| `Element` | 3,900（260 次全 `""`） | 砍（默认值） |
| `Position`/`HeroDisplayName`/`CardsDrawnPerTurn` | 7,616（367 次全 null） | 砍（默认值） |
| `Tags`（201 互异） | 7,258（Cards）+ 1,645 次 | **保留**，但必须池化 |
| `MaxNodeDepth`/`MaxProgramSteps` | 18,249（553 程序 ×2） | 砍（引擎守卫常量） |
| `Deck`（顶层） | 266 | 砍（与 `Start.Deck` 重复） |

### 5.4 建议的 ROM 结构

```c
/* 头 */
struct RomHeader { u32 magic, version, schema; u16 str_pool_len, id_count;
                   u32 off_strings, off_nodes, off_exprs, off_programs, off_entities, off_map; };
u16  str_offsets[1638];  char str_blob[43789];   /* 字符串池，NUL 结尾，纯 ASCII */
u16  id_to_str[784];                             /* 符号表：声明 id -> 池句柄 */

/* 效果节点：opcode + 依 opcode 的定长字段；每类 opcode 一张编译期生成的布局表，
   VM 只查表不反射。子节点用「紧凑范围」表示（child_head / child_n 指向节点数组的一段），
   共享程序体因此天然不发生拷贝。 */
struct Node { u8 op; u8 flags; u16 a, b, c, child_head; u8 child_n; };
/* 表达式 / 选择器与 Node 同构，另一段数组。 */
u16  program_roots[875];                         /* 程序体池（内容寻址） */

/* 实体表：定长记录，O(1) 索引 */
struct CardRow     { u16 id, name, program, cost_res; i16 cost_amt;
                     u32 tags_bitset; u8 zones, flags; };            /* 62 × 18 B ≈ 1.1 KB */
struct StatusRow   { u16 id, name, tags, triggers; u8 polarity, stack_beh, flags; }; /* 23 × 12 B */
struct EnemyActRow { u16 id, name, program; u8 intent_kind; };        /* 394 × 7 B ≈ 2.8 KB */
struct EncounterRow{ u16 id, enemies, triggers, hero_res, hero_statuses;
                     u8 n_enemies, n_triggers; };                     /* 109 × 14 B ≈ 1.5 KB */
struct MapNodeRow  { u16 id, payload; u8 type, payload_kind; };       /* 31 × 6 B */
```

### 5.5 id 内化

* 声明 id 784 个 + 全部字符串 2,926 个 → 两者合并进一个 u16 池即可（< 65,536）。
* **但 `Tags` 必须独立**：201 个互异标签值应做成 `bitset<201>`（每张卡 26 B）或 u16 列表；
  考虑到单卡标签数 ≤ 5，**u16 列表更省**。
* `CounterId`、`TeamId`、`Element`、`PoolId`、`Flag` 都是开放字符串，走同一个池。
* 引擎侧的 16 种 id 结构体（`CombatIds.cs:3-78`）可以整体替换为 `typedef u16` 的强类型包装。
  当前每个 id 在 .NET 里是「16 B 结构体 + 堆上 string + 字典项」；
  在 MCU 上这层开销完全消失。

---

## 6. 内容编译器的工作量

### 6.1 引擎**已经**做了的校验（可前移到编译期）

| 校验 | 位置 | 说明 |
|---|---|---|
| 未知效果 JSON kind | `CombatJson.cs:40-45`（读时抛 `JsonException`） | 编译期：白名单 73 种 |
| 未知 run 层 kind | `RunJson.cs:36-39` | 同上 |
| 重复卡/状态/敌人动作/遗物 id | `CombatDefinitionRegistryBuilder.cs:116-117`、`:143-144`、`:170-171` | 编译期直接报 |
| **无执行器的节点类型** | `:504-506`（`MissingNodeExecutor`） | 编译期：opcode → 执行器查表 |
| 不安全副作用节点 | `:508-512` | 编译期：直接拒绝 |
| **原生操作缺请求处理器** | `:514-518`（`MissingRequestHandler`） | 编译期：opcode ↔ handler 双向表 |
| **选择器上下文能力不足** | `:522-533`（`ContextCapabilityMissing`） | **编译期最值钱的一条**：JSON 里 `RequiredContextCapabilities` 写着，编译期一验就删 |
| **目标域不匹配** | `:535-539`（`TargetDomainMismatch`） | 编译期 |
| **活体资格不匹配** | `:541-547`（`OperationEligibilityMismatch`） | 编译期 |
| `applyStatus`/`removeStatus` 引用未注册状态 | `:550-558` | 编译期 |
| `createCardInstance` 引用未注册卡 | `:560-563` | 编译期 |
| 临时规则子程序递归校验 | `:565-575` | 编译期 |
| 子程序路径 `EffectProgramNodePath` | `:577-582` | 编译期错误定位 |
| 全部诊断聚合后抛 | `:388-389`（`CombatDefinitionBuildException`） | 编译期一次性报全 |
| 英雄牌组 / 敌方动作 / 意图规则引用 | `ScenarioBlueprint.cs:134-156` | 编译期 |
| 地图节点 → 事件/遭遇/商店/工作台 | `RunContentRegistry.cs:114-145`、`RunDocumentValidator.cs:148-166` | 编译期 |
| 蓝图版本迁移 / 拒绝更新版本 | `RunBlueprintSchema.cs:33-60` | 编译期固化 |

### 6.2 编译器**必须新写**的校验（`RunDocumentValidator` 里已有原型的直接搬）

`src/RogueDeck.Sandbox.Run/Composition/RunDocumentValidator.cs` 是现成的参考实现，
418 行，覆盖了大部分跨表引用检查，但**它只在 Studio 里跑，不在加载路径上**。

| # | 校验 | 参考实现 | 备注 |
|---|---|---|---|
| 1 | 全局 id 唯一 + 非空 + 保留前缀（`shred:`） | `RunDocumentValidator.cs:31-40` | 实测本文件无重复 |
| 2 | 所有 `{"value":...}` / `{"Value":...}` 引用可解析 | `:95-166` | **本文件全部可解析**（784 个声明 id 覆盖 3,128+747+479 次引用） |
| 3 | 升级后缀约定：`x+` 必须有 `x` | `StandardRunPackage.cs:82-84` | 实测 33 基础 / 29 升级 |
| 4 | 遭遇内敌方动作已定义 | `:141-146` | |
| 5 | Presentation 键不悬空 | `:168-186` | 实测 118/109/62/49/15/7 个键全部命中 |
| 6 | Balance 键不悬空 | `:188-196` | 本文件为空 |
| 7 | 地图非空 / DAG 前向性 / 可达性 / 边端点合法 | `:222-231` + `RunMapValidator` | 31 节点 / 41 边 |
| 8 | `Cards[].Costs[].ResourceId` 有定义源 | `:261-274` | 导出级门禁 |
| 9 | 起始牌组非空（含角色覆盖） | `:239-256` | |
| 10 | **数值范围**：`Amount`/`Stacks`/`DurationTurns`/`Charges`/`MaxHealth` 与 i16 存储匹配 | 无现有实现 | 新写；实测 const 全部落在 ±小数百 |
| 11 | **深度与步数上限**：程序树深度 ≤ `MaxNodeDepth`(64)、节点数 ≤ `MaxProgramSteps`(1024) | 无现有实现 | 实测最深 9 层、单程序 1,725 节点 ⇒ `1024` 会被**合法内容**突破，需复核 |
| 12 | **枚举值白名单**（`Op`/`Polarity`/`Zone`… 40 个值） | 无现有实现 | 新写；这 40 个值决定 1 字节编码 |
| 13 | **标签词表**白名单 | 无现有实现 | 201 个互异标签；开放词表，至少做拼写校验 |
| 14 | u16 池容量：`distinct_strings ≤ 65535` | 无现有实现 | 实测 2,926，余量充足 |
| 15 | 冗余 `Children` 剥离后的**语义等价性**回归 | 无现有实现 | 需要一份「跑一遍对局，比 state hash」的 golden 测试（引擎已有 `CombatStateHasher.cs`） |
| 16 | 触发器事件名 → 上下文类型映射 | `EncounterTriggerRebuild.cs:14-72`（26 个分支） | 编译期把 `Event` 字符串变成 u8 索引 |

### 6.3 工作量小结

* **可以把 `RunDocumentValidator` 整个搬进编译器**（它是纯 data-in/data-out，
  没有引擎构建，`RunDocumentValidator.cs:10` 注释明说 "Pure data-in/data-out — no engine build"）
  ——约 400 行 C# 可直接复用。
* 新增的是：数值范围、深度/步数、枚举白名单、池容量、**冗余 `Children` 剥离的等价性回归**。
  合计约 300–500 行 + 一套 golden 对局测试。
* 编译期可以**一次性产出全部**：字符串池、opcode 表、程序体池、实体定长表、符号表、
  以及 §6.1 那张「opcode → 执行器」表（也是 VM 派发表）。
* **注意版本闸**：`RunBlueprintSchema.CurrentVersion` = 1（`RunBlueprintSchema.cs:17-24`）。
  二进制 ROM 应当独立版本化，并在编译期固化迁移梯的结果。

---

## 7. 宿主依赖与坑

### 7.1 `System.Text.Json` 的具体用法（每条都能在 MCU 上换掉）

| 事实 | 出处 | 对嵌入式/重写的含义 |
|---|---|---|
| **`WriteIndented = true` 是默认**，导致 78.6% 是空白 | `CombatJson.cs:158`；`RunJson.cs:93-96` | 引擎自己的注释承认这点：`RunJson.cs:90-92`「Bureaucrats & Broomsticks 从 13.6 MB 降到 4.1 MB，堆占用 134 MB → 54 MB」 |
| `RunBlueprintSchema.Upgrade` 会**重新 pretty-print** 整份文档 | `RunBlueprintSchema.cs:59`（`new JsonSerializerOptions { WriteIndented = true }`） | 每次版本迁移都把文件再放大 4.7 倍 |
| 每个多态节点包一层 `{"kind","value"}` | `CombatJson.cs:108-116`、`RunJson.cs:61-69` | 299,678 B 的信封 |
| `CombatPolymorphicConverter` 用**reader 副本**先探 `kind` | `CombatJson.cs:63-106` | 注释记录了旧实现的代价：「一个深程序要被重解析与深度相同的次数；加载一局约 1500 个状态触发器，大部分时间花在这里（≈1 秒）」 |
| `PolymorphicRunJsonConverter`（run 层）**仍用 `JsonDocument.ParseValue`** | `RunJson.cs:52-58` | run 层没有那个优化；每次多态节点都分配一个 `JsonDocument` |
| `CombatJson.CreateOptions` 无注册表时**共享冻结实例** | `CombatJson.cs:130-153` | 注释：「每次调用都新建 options 会让 STJ 重新反射它遇到的每个节点类型；那 1.6 秒是每场战斗启动 1.7 秒里的 1.6 秒」 |
| `WriteChildrenOnlyWhereTheyAreRead` 用 `TypeInfoResolver` 修改器按构造函数参数名裁剪 `Children` | `CombatJson.cs:177-193` | 历史事故：「一个 boss 规则达到 311,624 个节点 / 15 MB，而树本身约 40 个节点」；**本文件正是那个 bug 的产物** |
| 泛型按上下文闭合：`CardPlayContext` / `EnemyActionContext` / `CardLifecycleContext` 三套转换器同时注册 | `RunJson.cs:117-121` | 选项对象里挂了 3 组 × 4 个转换器 |
| 枚举用 `JsonStringEnumConverter` | `CombatJson.cs:159`、`RunJson.cs:97` | 枚举在线上是字符串名（`"GreaterOrEqual"`），不是序号 |
| `NodeJsonConverter` / `EventScriptJsonConverter` / `RelicCombatRuleJsonConverter` / `TriggeredRunEffectJsonConverter` / `ReadOnlySetJsonConverterFactory` 手写 | `RunJson.cs:110-114` | 每个都是额外的解析路径 |
| `EncounterTriggerRebuild` 用 `Enum.Parse<TriggerEvent>(name)` | `EncounterTriggerRebuild.cs:17` | 按**名字**解析；26 个 `TriggerEvent` 分支 → 编译期变 u8 |
| 触发器 id 是拼出来的：`encounter_{id}_trigger{index}` | `EncounterTriggerRebuild.cs:18` | 改名坑（见 §4.3） |
| `EncounterTriggerData.Program` 是**上下文无关**的 `JsonElement`，注册时才按事件闭合上下文 | `EncounterTriggerRebuild.cs:75-78` | 这意味着**同一个程序体的上下文由使用方决定**，二进制化时必须把「上下文」记为使用点属性，而不是共享体的一部分 |

### 7.2 文化相关

* **所有** `Parse`/`ToString` 都显式用 `CultureInfo.InvariantCulture`：
  `RunRecording.cs:121,129,139,208`、`TextPlay.cs:261,267,271,318,396`、
  `BotReport.cs:72,92`、`CliOptions.cs:76`、`PlayByHand.cs:35`、`Program.cs:149,304,325`。
* `System.Text.Json` 的数字解析/写出本身就是 invariant，**不读 `CurrentCulture`**。
* 文件是 **UTF-8 无 BOM、CRLF**，纯 ASCII（非 ASCII 仅约 1.5 KB 的转义）。⇒ 编码侧没有文化风险。
* 唯一的隐式依赖是**枚举名**：`JsonStringEnumConverter` 用 `Enum.ToString()`，
  而枚举名是编译期标识符，与 culture 无关。但换成二进制 opcode 时**必须冻结这份映射**，
  否则重排枚举成员就会静默改语义。

### 7.3 id 是字符串导致的内存开销

* 16 种 `readonly record struct X(string value)`（`CombatIds.cs:3-78`）：
  每个实例 **16 B**（8 B 引用 + 8 B 对齐/填充），指向一个堆上 `string`
  （最小 24 B 头 + 长度 ×2 字符）。**同一个 id 的每次出现都是一次独立的字符串引用**。
* 注册表用 `ImmutableDictionary<TKey, TValue>`，键是这些结构体
  （`CombatDefinitionRegistryBuilder.cs:16-30`）：每个条目 = 结构体键 + 桶开销，
  且 `ImmutableDictionary.AddRange` 在合并 base 时会分配新节点。
* 内容里的 3,128 + 747 + 479 次引用，在 .NET 里等于同样数量的结构体 + 指向共享
  `string` 实例的引用（反序列化时 STJ 默认**不**做字符串驻留，
  所以同一 id 的 242 次出现很可能各是一份独立 `string`）。
* `Encounters` 那种「每条 trigger 内联一整棵程序树」的写法，
  在 .NET 里就是 762 KB 的 JSON → 数量级更大的 `IEffectNode<T>` 对象图；
  引擎注释给出了实测：**加载一局 134 MB 堆 → 去掉缩进后 54 MB**（`RunJson.cs:91-92`）。
* **对 MCU 的含义**：所有 id 内化成 u16 之后，这一整层（结构体 + 堆字符串 + 字典）
  在 ESP32-P4 上直接消失。一个 6,182 节点的程序图在 ROM 里是 ~30 KB，
  运行期只需要一个「当前节点游标」而不是对象图。
  可选 SRAM 592 KB 里放不下任何一份 .NET 风格的内容图，但放得下整个 ROM 三次。

### 7.4 其它踩坑

* **`CombatProgramModel`（1514 行）是编辑器模型，不是线格式**。它用 `Kind: "dealDamage"`
  这种无前缀名字，而线格式是 `node.dealDamage`；`CombatProgramModel.cs:405-447` 的 41 个叶子
  与 `:544-555` 的 9 个复合 **不等于** `CombatJson` 注册的 52 个节点（数量、命名、粒度都不同）。
  做二进制 opcode 表时**必须用 `CombatJson.cs:364-421` 的注册表**，不是编辑器模型。
  `CombatProgramModel.ClassifyNode` 明确说明「超出建模子集的节点返回 null，保留 JSON 逃生舱」
  （`:1220-1439`）。
* `StatusData.cs:8-11` 的注释：状态的**触发器与拦截器是 `Func` 逃生舱，没有数据形式**，
  `StatusData` 只承载「数据面」。所以 `Triggers` 是单独一层（`StatusTriggerData`），
  且由 sandbox composer 而不是 `ToBlueprint()` 重建（`StatusData.cs:34-36`）。
* `ScenarioBlueprint.Compile()` 要求**至少一个英雄、至少一个敌人**，否则抛
  （`ScenarioBlueprint.cs:65-68`）；牌组引用未知卡也抛（`:137-140`）。
* `StudioVocabulary`（523 行）是**纯显示词表，不参与序列化**
  （`StudioVocabulary.cs:8-10`：「nothing here is serialized」）。二进制化时可直接忽略，
  但它是「41 个叶子 + 9 个复合 kind、25 个选择器」的权威人性化清单，
  可用来生成 ROM 里的调试名字表（可选）。
* `Map` 里 23 个 `node.encounter` 每个内联一整棵奖励树（`reward.fixed` → `fx.offerReward`
  → `reward.pool` → 每卡一个 `fx.addCard`）。这是 `Map` 有 654 KB 的原因；
  二进制化时奖励池应当**独立成表并由 u16 引用**，否则 23 份池子会被各写一遍。
* `CombatDefinitionRegistryBuilder(CombatDefinitionRegistry baseRegistry)`（`:63-68`）的
  设计说明「注册只增不减，因此跳过 base 的校验是安全的」。二进制 ROM 应当复用这个不变量：
  **库只需编译一次并整体校验**。

---

## 附：测量方法与复现

本机 shell 会吞掉 `&` 起的 exe 的 stdout，且放进管道会直接失败，**必须**用
`ProcessStartInfo` + `RedirectStandardOutput` 收输出，并设 `PYTHONIOENCODING=utf-8`：

```powershell
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = 'C:\Users\TK11\miniforge3\python.exe'
$psi.Arguments = '"D:\Vibe\sts-tui\ref\content_probe.py" --samples 2'
$psi.RedirectStandardOutput = $true; $psi.RedirectStandardError = $true
$psi.UseShellExecute = $false; $psi.WorkingDirectory = 'D:\Vibe\sts-tui\ref'
$psi.EnvironmentVariables['PYTHONIOENCODING'] = 'utf-8'
$p = [Diagnostics.Process]::Start($psi)
$so = $p.StandardOutput.ReadToEnd(); $se = $p.StandardError.ReadToEnd(); $p.WaitForExit()
```

`content_probe.py` 分 7 个 Phase：0 原始字节归属 / 1 实体统计 / 3 节点普查 / 3b 程序树（不重复计）
/ 3c 节点归属小节 / 4b 引用图 / 5 冗余 `Children`；辅助脚本 `dup_check.py`（整树哈希去重）、
`raw_attr.py`（逐字符区间）、`rom_estimate.py`（体积模型）。

**已知测量局限**：`raw_attr.py` 与 Phase 0 的顶层区间算法略有差异（前者精确到字符 span，
后者把键名一起算入），相差 <1.6%（Encounters 5,861,586 vs 5,955,367 B），本文以
`content_probe.py` 为准。§3 里「节点自身字节」累计会超过文档大小，因为嵌套子树的字节
被逐个父节点重复计入——需要不重复口径时看 §3.3 的计数与 `rom_estimate.py` 的输出。
## 8. 实现补充（2026-11-03）：三个新节点/字段与两个方言陷阱

### 8.1 新增的节点与字段

| 名字 | 形状 | 说明 |
|---|---|---|
| `node.destroyCombatant` | `{TargetSelector}` | 把一个战斗员移出战斗（§178）。与 `node.createCombatant` 一样**立即生效**，不走效果队列 —— "立即"正是"只发生一次"唯一能表达的形式 |
| `STAT.DeathPrevention` | `{SurvivingHealth:int, Percent:int?, Repeating:bool?}` | PreDown 拦截（§180）。`Percent` 是**本移植的扩展**：参考的记录只有平值，表达不了 wiki 的 "30% of Max HP" |
| `sel.sourceIncludingDowned` | `{}` 或 `{Cardinality}` | 参考的 `SourceIncludingDownedCombatantTargetSelector`。`sel.source` 对**倒下的**战斗员解析为空集 ⇒ 挂在 `Downed` 上的分裂必须用这一个 |

### 8.2 ★★ 两个只在**内核**炸、内容门看不见的方言坑

1. **`node.applyStatus` 的 `DurationTurns` / `Charges` 是裸整数，不是 term。**
   写成 `{"kind":"const","value":{"Value":0}}` 时，只要**别的卡写的是裸整数**，编译器就会把该
   opcode 的这个字段**声明成 `F_JSON`**（"原始 JSON 逃生口"），而内核的 `NodeRef::field()`
   对 `F_JSON` **无条件**报错。症状极具误导性：**加一张卡，另一个不相关的测试红了**
   （`Ir(WrongKind("F_JSON"))`）。
2. **`sel.allEnemies` 的 `value` 是 `{}` 或 `{"Cardinality":"Any"}`。** 写 `"Many"` 是同一个症状。

⇒ 形状判据现在由第 11 道闸门（`tools/rdcf_terms.py`）在**镜像层面**检查（§184）：
除保留 opcode 5 自己，任何 opcode 的任何字段都不许声明成 `F_JSON`。

## 9. 实现补充（2026-11-03）：`EACT` 的 ascension 维度（§192 起是**列表**）

§2 的 `EACT` 有 7 格（`Id/NameKey/DescriptionKey/PackageId/Intent/Program/extra`）。§187 加了
`ProgramAsc` + `AscensionMin` 两格；§192 把那一对换成**一格列表**：

| 格 | 类型 | 含义 |
|---|---|---|
| `ProgramAsc` | `F_TERM`（可空） | **变体列表** `[{AscensionMin, Program}, …]`。每个 `Program` 是与 `Program` 格**同形的信封**（`{Root, MaxProgramSteps, …}`），不是裸 `Root` |

行宽 7 → 9（§187）→ **8 格 / stride 16（§192）**，`FORMAT_VERSION` 4 → 5 → 7。

**为什么不是"再加一对格"**：`jaw_worm.bellow` 的 Strength 在 A2 升、Block 在 A17 升
（`native/wiki_asc/jaw_worm.txt:30`：`Gains (3;Asc|2|4;Asc|17|5) Strength. Gains (6;Asc|17|9) Block.`）。
一对格只能装一个档位；两对格只能装两个；而列表的长度由内容决定。选择规则只有一条：
**`AscensionMin <= ascension` 里阈值最大的那个**（顺序不参与判定），
`AscensionMin` 为 `0` 的元素**永不生效**（`0` 是"没填"，不是"从 0 级起"）。
"阈值升序且不重复"由 `native/sts_content_check.py` 的独立第二份钉住。

⚠️ 语义上的一个变化：一个 A17 变体是**整段节目**，所以它必须**重复** A2 的改动再加自己的
（上面 Bellow 的 A17 变体写的是 Strength 5 + Block 9，不是只写 Block 9）。

**阈值写在内容里，不由内核推**：内核不知道一条遭遇来自哪个池（精英也可能出现在事件里），
所以"普通 2 / 精英 3 / Boss 4"这条规则由内容作者按怪的种类填，招式表则是 17/18/19。

另有一个新条件 `intent.ascensionAtLeast`（`{Value: n}`）：StS 的 A17/18/19 在源码里是每只怪
`getMove` 里的一段 `if`，数据化引擎不能照抄；把那个 `if` 交给内容的 `IntentRule` 就行。

## 9a. 实现补充（2026-11-03）：`node.selectCards`（§195.4）

从 §195.4 起，**挑哪张卡**第一次能被内容说出来。它是本内核自己的节点（参考的四个 `sel.*` 卡选择器
在 `sel.rs` 里被明确判为不支持）：

| 字段 | 含义 |
|---|---|
| `OwnerSelector` | 谁的牌堆（敌人的"你"= `sel.allEnemies`；死亡归还时是 `sel.eventTarget` = 凶手） |
| `FromZone` / `FallbackZone?` | 从哪个牌区拿；第一个空了才看 `FallbackZone`（Stasis：抽牌堆，空则弃牌堆） |
| `Order` | `HighestRarity` / `First` / `Random`（只有 `Random` 消耗一次 `random_step`） |
| `Count` | 1..=8（普通整数格，不是表达式） |
| `ToZone` / `Placement?` | 搬去哪里（默认堆底） |

稀有度排名只有一处定义：`Rare 4 > Uncommon 3 > Common 2 > Basic 1 > Status 0 = Curse 0`
（按**价值**排，不是枚举序号 —— 照 StS 的枚举序号降序会变成"先偷诅咒"）。

它搬卡走的是 `EffectRequest::MoveCardToZone`（与 `node.moveCardToZone` 同一个请求），所以触发器
照样看得见、"一次请求一次效果"的账照样成立。

## 9b. 实现补充（2026-11-03）：敌人记录里的 `Rolls`（§193）

`ENCT[i].Enemies[j]` 多了一个键（**不是格** —— 敌人记录是 term 对象，加键不动任何 stride）：

| 键 | 类型 | 含义 |
|---|---|---|
| `Rolls` | 列表 `[{Key, Min, Max, AscensionMin?}, …]` | 开局掷骰：`Key` 计数器在 `Min..=Max` 里抽一个值，写进**这个敌人** |
| `Counters` | 列表 `[{Key, Value, AscensionMin?}, …]` | 开局**固定**计数器（§195.1）：随机值表达不了"开局就是 30"，而节目没法初始化计数器 |

这与 `ProgramAsc` 的阈值规则**故意方向相反**：那里的 `AscensionMin = 0` 是"没填"（永不生效），
这里的缺席是"**这就是基础值**"。所以"忘了给 A2 那行填阈值"（两行都是 0）会被
`Content::spawn_rolls` 当成**同键同阈值**而报错，而不是悄悄两行都生效。

动作侧读它用的是参考**自己**的表达式 `combatantCounter(Selector, CounterId)` —— 没有新节点种类：

```jsonc
"Rolls": [{"Key": "roll.bite", "Min": 5, "Max": 7},
          {"Key": "roll.bite", "Min": 6, "Max": 8, "AscensionMin": 2}]
"Program": {"Root": {"kind": "node.dealDamage",
                     "value": {"Amount": {"kind": "combatantCounter",
                                          "value": {"Selector": {"kind": "sel.source", …},
                                                    "CounterId": "roll.bite"}}}}}
```

一条**没有** `Rolls` 的记录与一条写着 `Rolls: []` 的记录是两个 opcode（opcode 按出现过的键集派生），
所以 `EnemySpec::rolls()` 把"键缺席"读成**空列表**而不是错误 —— 否则 roguedeck 那份内容
（一条都没有）整份读不出来。

## 10. 实现补充（2026-11-03）：事件的选项是**效果列表**

`EV` 原来每行有 `Effect0/Amount0` 与 `Effect1/Amount1` 四格：**一个选项一条效果**，而词表是闭集。
§188 把四格换成四格 **term**：

| 格 | 类型 | 含义 |
|---|---|---|
| `Effects0` / `Effects1` | `F_TERM` | `[{Effect: "<词>[:<载荷>]", Amount: n}]` |
| `Effects0Asc` / `Effects1Asc` | `F_TERM`（可空） | **A15** 的变体（wiki: *Unfavorable Events*） |

行宽仍是 10 格 / 20 B，但**格的含义变了** ⇒ `FORMAT_VERSION` 5 → 6（一个还按旧版读的读者会把
term id 当字符串 id）。

三条约束，都由内容门钉住：
* 每条效果都在闭词表里（载荷形如 `curse:<id>` / `relic:<id>`）；
* 一个选项里**最多一条**改牌效果（`remove_card` / `upgrade_card` / `transform_card`）—— 待答的
  选牌只有一个位置，两个就是内容错误（运行层报 `RunError::TwoDeckChanges`）；
* `Effects*Asc` 若存在，**必须与基础不同**（"变糟了"却什么都没变是 typo，没有症状）。

## 11. 实现补充（2026-11-03）：A10 的诅咒

`ascenders_bane` 是内容里第一张**"删不掉"**的牌。它靠两处配合：

* 内容：`Rarity: "Curse"`、`Tags: [curse, unplayable, ethereal]`、`TurnEndHandDestinationZone:
  "ExhaustPile"`（`ethereal` 那个标签的判据要求这一格，内容门会查）；
* 内核：`remove_card` 按 **id** 拒绝它（`RunError::CannotRemove`）—— StS 自己也是把这条写在这张卡
  的代码里，而不是一个通用标签，所以这里照抄这个形状，并把常量与理由写在 `state.rs`。
