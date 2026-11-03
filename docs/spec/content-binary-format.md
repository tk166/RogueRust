# RDCF —— `.roguedeck.json` 预编译二进制格式（v1）

> 编译器：`tools/contentc/compile.py`（写入） / `reader.py`（参考读取器） / `validate.py`（校验）
> 格式常量：`tools/contentc/rdcfmt.py`（唯一的事实来源，写入端与读取端共用）
> 实测报告：`tools/contentc/out/report.md`（体积）、`out/validate.md` 与 `out/validate-core.md`（正确性）
> 样本：`ref/RogueDeck-Core/.../bureaucrats.roguedeck.json`，8,291,305 B

---

## 1. 结论：预编译后多大

| | 字节 | 对原文 | 对紧凑 JSON |
|---|---|---|---|
| 原文（`WriteIndented=true` 的 JSON） | 8,291,305 | 1× | — |
| 紧凑 JSON（`separators=(",",":")`） | 1,774,029 | 4.7× | 1× |
| 紧凑 + 去掉冗余 `Children` 副本 | 921,704 | 9.0× | 1.92× |
| 紧凑 + `Children` + 表现层 | 775,712 | 10.7× | 2.29× |
| **`content.rdcf`（完整、无损）** | **158,296 B = 154.6 KiB** | **52.4×** | **11.2×** |
| **`content.core.rdcf`（去掉表现层）** | **85,616 B = 83.6 KiB** | **96.8×** | **20.7×** |

ESP32-P4 可用 SRAM 592 KiB：完整镜像占 **26%**，core 镜像占 **14%**。
**但两者都不该进 SRAM**——镜像是只读、不可变的，属于 flash（或 memory-mapped PSRAM）。
SRAM 里只放解释器的寄存器组和「当前节点游标」；按 `node.sequence` 只有 1 个节点 8~16 B 算，
整个 VM 状态是几百字节量级。**内容不是 SRAM 预算问题，是 flash 分区问题。**

再往下还能砍：从 `Map.EntryNodeIds` + 起始牌组做可达性 BFS，本内容 **43,506 B（27.5%）**
的实体是这张地图到不了的（109 个遭遇只有 23 个被放置，394 个敌人动作只有 89 个可达）。
详见 `out/validate.md` §G。是否该砍要看 act 2 的地图是否在别的文件里。

---

## 2. 表布局

小端。每个 section 4 字节对齐。文件 = 32 B 头 + 20×12 B 目录 + 各 section 顺序排布。

```
Header (32 B)
  u32 magic='RDCF'  u16 version  u16 flags(bit0=已剥表现层)
  u32 total_size    u32 dir_off=32  u16 nsec=20  u16 schema_version
  u32 content_hash  ; u32 reserved
SecDir  20 × { u32 offset, u32 size, u32 count }
```

| id | 名 | 内容 | 本内容实测 |
|---|---|---|---|
| 0 | `STR` | 字符串池 blob，NUL 结尾 UTF-8，**按字节排序** | 76,799 B / 3,140 串 |
| 1 | `STRO` | `u32[n+1]` 池内偏移 | 12,564 B |
| 2 | `OPD` | `u32 field_off, u16 name, u8 nfields, u8 opclass` | 1,112 B / 139 opcode |
| 3 | `OPF` | 每个字段：`u16 key_name, u8 kind, u8 flags` | 2,996 B / 749 字段 |
| 4 | `TRM` | term 记录，变长、4 字节对齐 | 34,004 B / 2,895 term |
| 5 | `TRW` | `u16[n]` term 记录的字偏移（`byte_off/4`） | 5,790 B |
| 6 | `AUX` | `u16[]` 列表体（子节点序列 / 字符串序列） | 7,620 B / 3,810 格 |
| 7 | `CARD` | 卡牌定长行，stride 32 B | 1,984 B / 62 |
| 8 | `STAT` | 状态定长行，stride 40 B | 920 B / 23 |
| 9 | `EACT` | 敌人动作定长行，stride 16 B | 6,304 B / 394 |
| 10 | `ENCT` | 遭遇定长行，stride 16 B | 1,744 B / 109 |
| 11 | `REL` | 遗物定长行，stride 12 B | 588 B / 49 |
| 12 | `ROOT` | 根指针 `u16 key_str, u16 term`（17 个顶层键） | 68 B |
| 13 | `IDX` | id 符号表 `u16 str, u8 ekind, u8 pad, u16 index, u16 rsvd` | 5,528 B / 691 |
| 14+ | | 保留 | 0 |

**三个 section 吃掉全部体积**：字符串池 `STR+STRO` = 89,363 B（56%）、term DAG
`TRM+TRW+AUX` = 47,414 B（30%）、五张实体表 = 11,540 B（7%）。对齐填充 3 B。

### 2.1 opcode：把 JSON 的键名变成整数

`{"kind": K, "value": {...}}` 这种多态信封在文件里出现 16,890 次。RDCF 给**每个**
`K` 分配一个 opcode；给**每个互异的普通对象键集合**也分配一个 opcode（普通对象没有
判别式，就用「排序后的键元组」当它的形状标识，本内容 50 个）。

opcode 0..15 保留固定语义：`_null` / `_str` / `_int` / `_bool` / `_arr` / `_json` /
`_wrap_lower` / `_wrap_upper`。≥16 按「先 IR kind（按名字排序）、再对象形状（按键元组排序）」
确定性地分配 → 73 + 50 = 123 个，本内容共 139 个 opcode。

`OPD` 给每个 opcode 一条 8 字节描述，其中 `field_off` 指向 `OPF` 里的一段
`nfields` 个 4 字节字段描述。

### 2.2 term 记录与内容寻址

```
u16 op ; u16 slot[nslots] ; 补齐到 4 的倍数       // nslots 由字段 kind 推出
```

**term 的身份是内容**：`(op, slots...)` 相同的子树 intern 成同一条记录，term id 是
u16 索引。于是 `Encounters` 里 31 条 trigger 程序（只有 10 个互异函数体、21 份逐字节
重复 = 743,993 B）自动塌成 10 个节点 —— 这就是 8.29 MB → 158 KB 的主因。
16,890 个 IR 实例最终只有 **2,895** 个互异 term。

### 2.3 字段 kind 与两个哨兵

每个 slot 都是 u16。**「键不存在」和「键存在但为 null」必须可区分**，否则往返会有
归一化歧义；这是格式能做成**精确无损**（而不是「语义等价」）的关键。

| kind | 槽 | ABSENT | NULL |
|---|---|---|---|
| `F_STR` | 1 | `0xFFFF` | `0xFFFE` |
| `F_INT` | 1 | `0x8000`(-32768) | `0x8001`(-32767) |
| `F_BOOL` | 1 | `0` | `3`（1=false, 2=true） |
| `F_TERM` | 1 | `0xFFFF` | `0xFFFE` |
| `F_TERMLIST` / `F_STRLIST` | 2（`AUX` 起址, 个数） | `(0xFFFF,0xFFFF)` | `(0xFFFE,0xFFFE)` |
| `F_JSON` | 1 | 同 `F_STR`（最后手段，本内容**一个字段都没用到**） |

`F_INT` 因此损失 -32768/-32767 两个值；编译器校验内容整数落在 `[-32766, 32767]`
（实测 [-300, 1024]）。

### 2.4 id 包装对象是免费的

引擎把 id 声明成 `readonly record struct X(string value)`，同一 id 在文档里有三种写法：
裸串、`{"value":s}`（小写，`CombatIds.cs`）、`{"Value":s}`（大写，run 层）。
**包装对象根本不落盘**：字段描述里的 flags 字节记下该字段用哪种拼法
（`FLAG_WRAP_LOWER`/`FLAG_WRAP_UPPER`）。只有拼法在一个字段里不统一时才退回 `F_TERM`，
由 `_wrap_lower`/`_wrap_upper` 两个 opcode 精确表示。

### 2.5 实体行

定长行，`stride = align4(2*ncells)`。每格用与 term 字段完全相同的槽编码（同样有
ABSENT/NULL 哨兵）。布尔用真正的 `F_BOOL` 格而不是打包位域 —— 打包位域分不出
「键不存在」和「键存在且为 false」。行尾的 `extra` 格是一个 `_obj` term，装下 schema
不认识的键，因此内容侧新增字段不会静默丢数据。

```c
struct CardRow   { u16 id, program, tags, costs, lifecycle, playCondition, queueOnPlay,
                       retainInHand, isAction, nameKey, descKey, packageId,
                       zoneTurnEnd, zonePlayed, extra; };        /* 62 × 30 B */
struct StatusRow { u16 id, nameKey, descKey, packageId, polarity, stacking,
                       tags, triggers, passive, combatRules,
                       deathPrevention, debuffBlock, incomingStatusDelay,
                       disclosure, prevention, amplification,
                       usesStacks, usesDuration, usesCharges, extra; }; /* 23 × 40 B */
struct EactRow   { u16 id, nameKey, descKey, packageId, intent, program, extra; }; /* 394 × 14 B */
struct EnctRow   { u16 id, enemies, heroResources, heroStartingStatuses,
                       triggeredEffects, heroDisplayName, cardsDrawnPerTurn, extra; }; /* 109 × 16 B */
struct RelRow    { u16 id, displayName, runPrograms, combatRules, extra; }; /* 49 × 12 B */
```

嵌套子记录（`Enemies[]`、`TriggeredEffects[]`、`Costs[]`、`Relic.RunPrograms[]`…）
不单独建表，一律存成一个 `_arr`/`_obj` term 的 u16 句柄 —— 复用同一套 interning，
代码量和体积都最小。

### 2.6 `ROOT` + `IDX`

`ROOT` 把「不是定长表的顶层键」（`Map`、`Events`、`Shops`、`Start`、`Characters`、
`MetaRules`、`Presentation`、`Balance`、`Deck`…）各指向一个 term。整个 `Map`、整个
`Events` 因此也是 DAG 的一部分，共享同一套 interning。

`IDX` 是 **id → 句柄** 的符号表（691 条，按字符串 id 排序，可二分）。9 类实体：
card / status / enemy_action / encounter / relic / map_node / event / shop / character。
运行时 `{"value":"paperwork"}` 这种引用变成 `IDX` 里的一次查找。

---

## 3. 为什么这么设计

1. **内容寻址而不是逐节点建记录。** 这是 158 KB 与 360–600 KB 的区别。
   16,890 个 IR 实例最终只有 2,895 条互异 term 记录（`TRM` 34,004 B，平均 11.7 B），
   其中 IR 子树的互异形状只有 875 个；逐实例建记录要大一个数量级。
2. **无损优先于更小。** 冗余的 `Children` 数组引擎会忽略（`CombatJson.cs:166-193`
   的裁剪逻辑；`EffectProgramNodes.cs:65,85-87` 说明它是只读计算属性），但 RDCF
   **照样存**——interning 之后它只值几个字节，换来的是 `validate.py` 能报「结构完全一致」
   而不是「我认为等价」。**精确**比**小 2%** 值钱。
3. **字段布局从数据推导，不写死在代码里。** 编译器观察每个 (opcode, 字段) 实际出现的
   存储类别，取并集；真有不可调和的字段就退回 `F_JSON`（本内容 0 个）。所以内容 schema
   演进不需要改编译器。
4. **行宽 = 2×格数，只有 u16 一种宽度。** MCU 端读一行是「按 schema 数组顺序取 2 字节」，
   不需要结构体布局、不需要对齐、不需要字节序转换练习。
5. **`STRO` 用 u32。** 池子 85 KB，超了 u16 射程；core 镜像的池子只有 31 KB，
   将来若要再省 5.5 KB，可以在 core 变体上换回 u16。
6. **字符串池按字节排序。** 一是 id 稳定（谁先遍历到不影响），二是 ASCII 段天然按码点
   有序，三是 flash 上可以前缀共享。

---

## 4. 校验（`out/validate.md` / `out/validate-core.md`，两个镜像全绿）

| 检查 | 内容 |
|---|---|
| A 良构 | 头/目录自洽；section 对齐且互不重叠；`SEC_TRW` 严格递增；**每个** term/string/aux/实体索引操作数都在范围内；字符串池排序不变量 |
| B 往返 | `reader.py` 重建的文档与 `json.loads(原文)` **逐路径结构相等**——字典键集、列表元素，**含键的存在性**（不存在的键回来还是不存在，`null` 回来还是 `null`）。不是比字节数 |
| C 引用完整性 | **929 个 id / 80 个命名空间 / 4,459 次引用**，**0 个悬空**。软引用（`standard.energy`、`gold` 这种资源）单列 |
| D id 合法性 | 929 个声明 id + 全部引用位都是纯 ASCII。文档本身非 ASCII（386/3140 串），全是表现文本——正是 id 与显示串必须分家的原因 |
| E 确定性 | 进程内跑两次 SHA-256 相同，且与磁盘镜像一致（`648a1ff9…`） |
| F 命名空间 | 0 个重复声明；29 张 `+` 升级卡全有基础卡；**组合 id 里嵌的 id 全部可解析**；choice id 只在一幕内唯一这件事被显式记档 |
| G 可达性 | 见 §1 的 43,506 B |

**校验过程中确认的两件事（都写进了 validate.md）：**

* `fx.offerReward` 的 `Reward` **不是引用**。`Rewards.cs:113-165` 里它只是个 `RewardId`
  标签，用于日志和 `RewardOfferedRunEvent`，offers 来自内联的 `Source`。
  所以 `event-…-shop`/`spoils:…`/`cards:…` 是**使用时铸出来的名字**，永远查不到声明表——
  它不是悬空引用，但**它把别的 id 当子串嵌进去了**（`cards:city_easy_02`），
  改名会让它变成孤儿而引擎毫无察觉。校验器把 62 个组合 id 的嵌入 id 逐个解析了一遍。
* `Encounters[].TriggeredEffects[].Event` 是 `TriggerEvent` 枚举名
  （`EncounterTriggerRebuild.cs:17` 用 `Enum.Parse`），不是 `Events` 脚本的引用。

---

## 5. 留给内核侧读取器的接口约定

镜像里**没有**任何运行时类型信息之外的东西；读取器只需要这四件事：

1. **定位表**：读 32 B 头，校验 magic/`total_size`；读 `dir_off` 处的 20×12 B 目录。
   所有表都是 `(offset, size, count)`。
2. **取字符串**：`STR[STRO[i-1] .. STRO[i]-1]`，NUL 结尾。`i==0` 是空串，
   `F_*` 的 `0xFFFF/0xFFFE` 是哨兵、不是 string id。
3. **走 term**：`p = TRM + 4*TRW[tid]`；`op = *(u16*)p`；查 `OPD[op]` 拿 `field_off`，
   在 `OPF` 里读 `nfields` 个 `(u16 key, u8 kind, u8 flags)`；槽紧跟在 op 后面。
   `op < 16` 是结构化保留字（`_null`/`_str`/`_int`/`_bool`/`_arr`/`_json`/两个 `_wrap_*`），
   `OPD[op].opclass == 0` 表示这是 IR 节点（结果形如 `{kind: OPD[op].name, value: {...}}`），
   `opclass == 1` 表示普通对象（结果就是那个字典）。
4. **解析 id**：`IDX` 按字符串 id 排序，可二分；命中后 `ekind` 决定去哪张表，
   `index` 是表内行号。行 stride 用 `row_stride(name)`。

配套约定：

* **解释器不需要对象图**。term 是 DAG，`field_off` 是编译期常量表，执行一个节点 =
  「读 opcode → 按 `OPF` 取操作数 → 跳执行器」，不需要构建任何树。
* **`MaxNodeDepth`/`MaxProgramSteps` 不在镜像里**（原始 JSON 里 553 个程序各写一遍，
  18,249 B），它们是引擎守卫常量，应由 VM 自己持有。
* **触发器事件名 → u8**：`TriggerEvent` 在本内容只用到 8 个值，编译期映射即可。
* **版本闸**：`RDCF.format_version` 独立于 `RunBlueprintSchema.CurrentVersion`
  （本内容 = 1）。头里的 `content_hash` 是原文的 FNV-1a-32，用来判镜像是否过期，
  不重新解析 JSON。
* 需要 `content.core.rdcf` 时看 `header.flags & 1`：置位表示表现层字段已被剥掉，
  读取器不能假设 `NameKey`/`Label`/`Presentation` 存在。

### 已知的可选优化（都还没做，因为收益小于风险）

* **`Presentation` 的按 id 映射变成超宽对象形状。** `Presentation.{Cards,Enemies,…}`
  是 `map<id, {Art,FlavorText,…}>`，键名就是 118/109/62/49/… 个实体 id，所以它们各成了
  一个 118 字段 / 109 字段的 opcode（`layout.txt` 里 opcode 125/133/128/129/126/127/130/131/132）。
  这些字段描述共 382 条 × 4 B = 1,528 B，加上记录本身 766 B，约 **2.3 KB（1.5%）**。
  改成 `_arr<{Id,…}>` 能省掉，但要放弃「形状由键集决定」这条统一规则，不值得。
  反正 core 镜像整个 `Presentation` 都不在。
* `TRW`（5,790 B）：term 记录已 4 字节对齐且长度都是 4 的倍数，理论上可以靠
  「opcode 隐含长度」从 0 顺序扫描推出来，省掉整张表——代价是随机访问变线性。
* `STRO` u32→u16（省 5.5 KB，仅 core 变体可行，因为它的池子只有 31 KB）。
* 可达性剪枝：43,506 B（27.5%），但需要先确认 act 2 的内容不在这里。
* `OPF` 里 749 个字段描述中，IR 字段的名字（`Amount`/`TargetSelector`…）对 VM 是死重，
  VM 只需要 kind 和 flags。可以让 `opclass==0` 的 opcode 不带 `key_name`，省约 1.2 KB。
  留着是因为它是「字段名 → 槽位」的唯一记录，调试和对拍全靠它。
* opcode 8..15 是预留块里的空洞（`OPD` 里是全零描述），只值 8×8 = 64 B。
## 6. 实现补充（2026-11-03）：term 表的**形状**也会被闸门读

§4 的校验原本只到"段字节数 == count × stride"。§183 的两个内容事故（`DurationTurns` 写成 term、
`sel.allEnemies` 的 `Cardinality` 写成对象）证明那层不够：**源 JSON 合法、编译成功、字节门全绿**，
而镜像里同一个字段在不同出现处形状不一致 ⇒ 编译器把整个字段降级成 `F_JSON` ⇒ 内核读到就报错。

现在第 11 道闸门（`tools/rdcf_verify.py` + `tools/rdcf_terms.py`）**独立解析** OPD/OPF/TRM/TRW/STR/STRO，
检查三条：

1. 除保留 opcode 5（`_json`）自己之外，任何 opcode 的任何字段都不许声明成 `F_JSON`；
2. 不允许存在 `_json` term（失败消息带那段 JSON 原文）；
3. `F_TERM` 槽指向的 term id 必须真实存在（段 id 位移那种"对的字节、错的 id"）。

负控在 `native/negctl_184.py`：**基线绿 → bug①红（且点名 opcode 与字段）→ bug②红 → 清理回绿**。
证据串因此多了一段：`... 1274 table rows, 6 term-shape checks over 5,038 terms`。

## 7. 实现补充（2026-11-03）：`FORMAT_VERSION` 5 → 7

三条 schema 变更，每次一行：

| 版本 | 变更 | `EACT` 格数 / 行宽 | 镜像（core / full） |
|---|---|---|---|
| 4 → 5 | `ProgramAsc` + `AscensionMin` 两格（§187） | 7 → 9 / 16 → 20 B | 85,616 → 87,192 / 158,296 → 159,872 |
| 5 → 6 | `EV` 的四格换成四个效果**列表**（§188），行宽不变、含义变了 | 9 / 20 | 不变 |
| 6 → 7 | `ProgramAsc` 变成**变体列表**，`AscensionMin` 格删掉（§192） | 9 → 8 / 20 → 16 B | 87,192 → 85,616 / 159,872 → 158,296 |

* 旧镜像一律被 `UnsupportedVersion` **直接拒绝**（不是尽力解析）；
* `tools/contentc/expected_sha.txt` 每次都得重新钉（`verify_bytes.py --repin`）：编译器变了，
  旧内容的产物字节必然移动。§192 那次重钉之后 `native/card_specs.json`（对拍闸门真正读的东西）
  **逐字节不变** —— 那是"格式变了、语义没变"的证据，而不是"重新钉一下让红变绿"；
* ⚠️ §192 那次是**行宽回退**：同一张表先涨后跌。所以"`EACT` 是 16 B"这句话只有在版本 7 下成立，
  读 `content-binary-format` 旧章节时别把两次数混起来。
