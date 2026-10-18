# contentc 审计：为"把内容换成 StS 第一幕"，编译器到底要动哪里

> **本文是什么**：一次**只读代码 + 量数据**的审计。回答四个具体问题：5 张行表写死在
> 哪（`文件:行号`）、opcode / 字段表的余量是多少（数字）、卡程序树在源文档里怎么表达、
> 哪些部分**根本不用**改编译器。同时记录本轮已经落地的两件事（byte-identity 闸门、多包结构）。
>
> **本文不是什么**：不是实现计划，不含新卡数值（数值唯一真相是
> `docs/spec/sts-act1-inventory.md`），不动 `kernel/`。本轮的约束是"不 author 新卡、
> 不改内核、不跑 cargo"，所以本文**没有**任何 cargo 证据。
>
> **行号可信度**：所有 `compile.py` 行号都是**本轮改完之后**的文件行号（本轮在
> `compile.py` 里加了两处：`--full-name/--core-name` 参数、`write_report` 的
> `Encounters` 守卫）。其余文件本轮未改。
>
> **本轮没有跑 `tools/acceptance.ps1` 全量**：它含 6 道 cargo 闸门，而 `kernel/` 有别的
> 代理在改。新增的那一道闸门我是**用 `acceptance.ps1` 自己的 `Invoke-Gate`（从 AST 里取出函数体）
> 按文件里那次调用的同样参数单独跑的**，结果见 §1.3。

---

## 0. 结论摘要（先看这 6 条）

1. **旧镜像真的可复现**：在当前编译器上重新编译 `bureaucrats.roguedeck.json`，
   `content.rdcf` / `content.core.rdcf` 与仓库里那两个文件**逐字节相同**。基线是真的，
   所以 §1 的闸门不是"把现状当真理"，而是"把现状钉成可检验的断言"。
2. **改编译器最可能的后果不是某条测试变红，而是所有对拍静默改比另一份内容**。
   已加闸门：钉死 2 个镜像 + 1 个源文档的 SHA-256，重编后必须逐字节复现，失败打印期望/实际 + 首个差异字节落在哪个 section。
3. **5 张行表的同一份事实被抄了 6 次、散在 4 个文件里**（§2.2），此外 `tools/rdcf_verify.py:31-37`
   **已经腐烂**（stride 写成 28/36/20，真值是 32/40/16），而且它的 `count×stride` 自洽检查
   因为读错了 manifest 层级而**永久静默**。加第 6 张表时**一定会漏一处**，漏的那处不会报错。
4. **opcode 余量充足**：256 个槽用了 139 个（opcode 0..138），**空闲 117 个**；
   超限在 `compile.py:285-286` 响亮失败。参考内容用 73 个 IR kind + 50 个对象形状
   就表达了 62 卡 / 394 敌人动作 / 109 遭遇 / 49 遗物 / 23 状态 + 整层 run 内容，
   StS 的 75 张卡引入的新节点种类是"个位数"，余量是它的 10 倍以上。
5. **字段表余量同理但不是瓶颈**：OPF 现在 749 条（core 353 条），偏移是 u32 ⇒ 条目数没有实际上限；
   真正的上限是**每个 opcode 的 `nfields` 是 u8（≤255）**，当前最宽的是那个 118 字段的
   敌人名录 `_obj(...)` 形状 ⇒ 还剩 **137** 个字段。
6. **卡的程序树现在就是"源文档直接写 ours 的节点"**：源文档里程序是
   `{"kind":"node.dealDamage","value":{...}}`，编译器对卡牌语义**零知识**（只认
   `is_ir()` / `wrap_key()` / 对象形状）。⇒ **author 75 张卡不需要动编译器的任何一行**；
   需要懂卡牌语义的是内核，不是编译器。

---

## 1. 安全网：byte-identity 闸门（本轮新增）

### 1.1 钉在哪、怎么跑

唯一真相：**`tools/contentc/expected_sha.txt`**（`键 = 值` 行式，注释里写了为什么和怎么重钉）。

```
source_path   = ref/RogueDeck-Core/src/RogueDeck.Sandbox.Run/SampleContent/bureaucrats.roguedeck.json
source_sha256 = 96d064c2cced72d1d21d8eb7e09bf081709dc2f966bc9f93118dea5608124073   (8,291,305 B)
full_sha256   = 648a1ff94929c31bd53879a4c77ff4972e75c2007afea3574eedcf1b07036bf7   (158,296 B)  content.rdcf
core_sha256   = d14525dac306e64251b6975c5aa0148eaf903f224aaf4b0ea11414189fc9feb6   ( 85,616 B)  content.core.rdcf
```

闸门：

```powershell
C:\Users\TK11\miniforge3\python.exe tools\contentc\verify_bytes.py            # 0=过 1=不一致 2=前置缺失
C:\Users\TK11\miniforge3\python.exe tools\contentc\verify_bytes.py --repin    # 故意的重钉（会显式打印 REPINNED）
```

它做三件**互相不能替代**的事：

| # | 检查 | 单独做会漏掉什么 |
|---|---|---|
| 1 | 源文档 SHA-256 与 `source_bytes` | 不说就分不清"编译器回归"和"源文档被换掉" |
| 2 | **用当前编译器重编到临时目录**，两个镜像都要与钉死值逐字节相同 | 只查 `out/` 会漏掉编译器回归（`out/` 还是旧的、还是对的） |
| 3 | 仓库里 `out/` 的两个镜像也必须等于钉死值 | 只查重编会漏掉"`out/` 陈旧但编译器没坏" |

`manifest.json` / `report.md` / `layout.txt` **不在钉的范围内**：它们内含计时和绝对路径，
本来就不逐字节可复现（本轮实测：`layout.txt` 可复现，另两个只有计时不同）。

### 1.2 为什么必须"先绿再改编译器"

`CARD_DIFF`(62/62)、`FIGHT_DIFF`(182/182)、`ENEMY_DIFF`、`corpus` 85、`coverage` 19/19、
`golden` 129 全部钉在 `tools/contentc/out/content.core.rdcf` 这一份镜像上
（`native/fight_diff.py:139`、`native/gen_card_specs.py:51-52`，其余经由
`native/card_specs.json` 间接钉住）。改 `compile.py` 若挪动了它的字节，这些闸门
**不会变红**——它们会从此比另一份内容并继续报绿。所以本轮的顺序是：
先在未改动的编译器上跑绿（§1.3 证据 A），再改编译器，再跑绿（证据 C）。

### 1.3 证据

**A. 未改动的编译器上跑绿**（`verify_bytes.py`，exit 0）

```
  source   : 96d064c2cced72d1 ... ok (8291305 B)
  content.rdcf (full)
    pinned : 648a1ff94929c31bd53879a4c77ff4972e75c2007afea3574eedcf1b07036bf7  158296 B
    fresh  : 648a1ff94929c31bd53879a4c77ff4972e75c2007afea3574eedcf1b07036bf7  158296 B  ok
    out/   : 648a1ff94929c31bd53879a4c77ff4972e75c2007afea3574eedcf1b07036bf7  ok
  content.core.rdcf (core)
    pinned : d14525dac306e64251b6975c5aa0148eaf903f224aaf4b0ea11414189fc9feb6  85616 B
    fresh  : d14525dac306e64251b6975c5aa0148eaf903f224aaf4b0ea11414189fc9feb6  85616 B  ok
    out/   : d14525dac306e64251b6975c5aa0148eaf903f224aaf4b0ea11414189fc9feb6  ok
CONTENTC_BYTES PASS (2/2 images, 1/1 source)
```

**B. 故意改坏一处 ⇒ 必须红，并指出差异在哪里 / 是哪一类**。
源文档是 `ref/` 下的只读镜像，不能动，所以做法是**拷一份**、把第一处
`"MaxNodeDepth": 64` 改成 `65`（一个数字），再用 `--src` 编译那份副本：

```
    size   : 158296 -> 158296 B (+0)
    header byte 20..23 (content_hash = FNV-1a of the source bytes) moved -> the SOURCE document changed, not (only) the compiler
    first payload difference: byte 114748 (0x1C03C)
      pinned TRM +21004 = 0x40
      fresh  TRM +21004 = 0x41
!! CONTENTC_BYTES FAIL (2 problem(s))
   content.rdcf (fresh compile)   648a1ff94929c31b…  c4d06e4b567187e9…
   content.core.rdcf (fresh compile) d14525dac306e642… fef688a876bf1352…
```

把这处改回（把副本恢复成原样）再跑，**回到 `CONTENTC_BYTES PASS`**。

这里有两个**必须处理的诊断陷阱**，闸门都专门绕开了：

1. header 第 20..23 字节是 `content_hash`（源文件的 FNV-1a），任何源文档改动都会先在那里
   "差一个字节"；把它当"第一个差异"报出来是**没用**的诊断 ⇒ 单独一行说明，扫描继续往 payload 走。
2. header 第 8..11 字节是 `total_size`，**任何尺寸变化**都会先在字节 8 显示 ⇒ 所以扫描
   从 `header + 目录`（`align4(32 + 20*12) = 272`）之后开始，尺寸变化单独用 `size :` 一行报。

上面最后两行 `TRM +21004 = 0x40 → 0x41` 就是被改掉的那个 64→65。

**C. 改完编译器之后再跑绿**：`--full-name/--core-name` 与 `write_report` 守卫加完之后，
两个 SHA 一字不差，`PASS`。

**C2. 闸门真正要抓的那一类：源文档没变、编译器变了**。
临时给 `compile.py` 的 `collect_strings()` 加一行 `found.add("zzz_byte_identity_probe")`
（模拟"改编译器顺手多注册了一个字符串"），源文档一字未动：

```
    size   : 158296 -> 158324 B (+28)          # 只改编译器也会改尺寸
    first payload difference: byte 77071 (0x12D0F)
      pinned padding after STR (that section ends at 77071) = 0x00
      fresh  STR +76799 = 0x7A                 # 字符串池末尾长出了一截
!! CONTENTC_BYTES FAIL
```

注意 `header ... SOURCE document changed` **这一行没有出现**——因为源文档没变。
这一组"三行里哪几行出现"就是分类器：`source ok + fresh MISMATCH + out/ ok` ⇒ 编译器回归；
`source MISMATCH` ⇒ 先查源文档；`fresh ok + out/ MISMATCH` ⇒ `out/` 陈旧。
还原 `compile.py` 后（SHA-256 与备份一致）立刻回到 `PASS`。

**D. 闸门作为 `acceptance.ps1` 第 10 道被红/绿计入**（用文件自己的 `Invoke-Gate` 跑）：

```
Exit     : 0        Ok : True     Evidence : 2/2 images         # 正常
Exit     : 1        Ok : False    Notes : 输出里找不到 /CONTENTC_BYTES PASS \(2/2 images, 1/1 source\)/
```

（红的那次是把 `expected_sha.txt` 里 `full_sha256` 改掉一位再跑，然后恢复。注意：**退出码**
和**证据串**是两道独立的判定，上面两行同时展示了它们。）

---

## 2. 实体段那 5 张表：写死在哪，加第 6 张表要动哪几处

### 2.1 全部位置（30 处，5 个文件）

"**自动**"= 该处已经在循环 `ENTITY_SECTIONS` / `F.ROW_SCHEMAS`，加了表不用改它。

| # | 位置 | 是什么 | 加第 6 张表要改吗 |
|---|---|---|---|
| 1 | `rdcfmt.py:160` | `NSEC = 20` | **只在用满空区号之后** |
| 2 | `rdcfmt.py:163-166` | 区号常量（`S_CARD..S_REL`=7..11、`S_ROOT`=12、`S_IDX`=13、`S_TAGS`=14） | 要（用空闲 15..19 之一） |
| 3 | `rdcfmt.py:167-171` | `SEC_NAMES` | 要 |
| 4 | `rdcfmt.py:172-173` | `SEC_ORDER`（**段写入顺序**，决定全部 offset） | 要（**追加到末尾**才能保住旧镜像字节，见 §3.5） |
| 5 | `rdcfmt.py:217-223` | `EK_*` 实体种类（1..9，已在 IDX 里当 `u8 ekind`） | 要（若希望在 IDX 里按 id 查到） |
| 6 | `rdcfmt.py:229-237` | `CARD_ROW`（15 cell） | — |
| 7 | `rdcfmt.py:238-248` | `STATUS_ROW`（20 cell） | — |
| 8 | `rdcfmt.py:249-253` | `EACT_ROW`（7 cell） | — |
| 9 | `rdcfmt.py:254-259` | `ENCT_ROW`（8 cell） | — |
| 10 | `rdcfmt.py:260-263` | `REL_ROW`（5 cell） | — |
| 11 | `rdcfmt.py:264-265` | `ROW_SCHEMAS` | 要（新表的 schema 注册进来） |
| 12 | `rdcfmt.py:272-273` | `row_stride()` = `align4(2*ncells)` | 自动 |
| 13 | `compile.py:53-54` | `ENTITY_SECTIONS`（5 个 `(表名, JSON 键)`） | 要 |
| 14 | `compile.py:55-56` | `SEC_OF`（表名→区号） | 要 |
| 15 | `compile.py:464` | `collect_strings()` 扫行表里的字符串 | 自动 |
| 16 | `compile.py:486-488` | `_row_groups()`（3 处的唯一来源） | 自动 |
| 17 | `compile.py:584-585` | 写行表 | 自动 |
| 18 | `compile.py:625-626` / `634-635` | payload + counts | 自动 |
| 19 | `compile.py:605-617` | `build_rows()`（stride 来自 `row_stride`） | 自动 |
| 20 | `compile.py:759-763` | 建行 + 把行表键从 ROOT 里排除（763 用 `dict(ENTITY_SECTIONS).values()`） | 自动 |
| 21 | `compile.py:770-789` | **IDX 的 10 段 `add(...)`**（Cards/Statuses/EnemyActions/Encounters/Relics/Map.Nodes/Events/Shops/Characters/Start.HeroName） | **要**（加一段） |
| 22 | `compile.py:827-838` | `attribution()` 分组 | 自动 |
| 23 | `compile.py:667-673` | `PRESENTATION_KEYS`（5 个 section 的表现层键） | 要（若新表有表现层字段） |
| 24 | `compile.py:676-723` | `strip_presentation()` 里 4 个 section 的写死特判（`EnemyActions:688`、`Encounters:696`、`Events:705`、`Shops:719`） | 要（同上） |
| 25 | `compile.py:977` / `986` | `write_report` 的实体段表 | 自动 |
| 26 | `compile.py:1322-1326` | `manifest.json` 的 `tables` 块（写死 5 条） | 要（否则 manifest 少一张表，`rdcf_verify` 会"查不到就跳过"） |
| 27 | `reader.py:223-224` | `_rows()` 的表名→区号 | 要 |
| 28 | `reader.py:265-268` / `287-291` / `310` | `document()`、`stats()`、`--table` choices | 要 |
| 29 | `validate.py:444-447` / `678-688` / `710-712` / `914-918` | 参考内容专用的校验器（表名映射、顶层键名单） | 可选（它只服务 roguedeck） |
| 30 | `tools/rdcf_verify.py:31-37` | 独立校验器的 `STRIDED` —— **已经陈旧且检查永久静默**（§7.1） | **必须先修**（不在 `tools/contentc/` 下） |

**最小动作集**（在 `tools/contentc/` 内、且不动 `reader/validate`）：#2 #3 #4 #11 #13 #14 #21
（+#26 让 manifest 说实话）＝**7 处 + 1 处可选**。其中唯一"不是抄一遍"的是 #21
（IDX 的 `add()` 循环按表写死，每张表一行）。

### 2.2 结论：真正的成本不在"加表"，在"改既有表的 schema"

同一个事实（"STATUS 有哪 20 个 cell"）现在有 6 份副本：`rdcfmt.STATUS_ROW`、
`compile.ENTITY_SECTIONS`、`compile.SEC_OF`、`compile:1322-1326` 的 manifest、
`reader._rows`、`validate.SNAME`。加第 6 张表要同时改 6 处，其中 2 处
（`rdcf_verify`、`validate`）**不在任何闸门覆盖范围内** ⇒ 漏一处不会报错。
这正是 §8 建议先做的事。

---

## 3. 容量账本（全是数字，measured）

数据来源：`tools/contentc/out/manifest.json`（本轮实测）与 `out/layout.txt`（逐 opcode 清单）。

### 3.1 opcode 空间

| 项 | full | core | 上限 | 余量 |
|---|---|---|---|---|
| OPD 条目数（= 最大 opcode + 1） | **139** | 130 | **256**（`u8`） | **117** |
| ├ 保留布局（op 0..7） | 8 | 8 | — | — |
| ├ 空洞（op 8..15，OPD 里是 0 描述符） | 8 | 8 | — | — |
| └ 动态（IR kind 73 + 对象形状 50） | 123 | 114 | — | — |
| 最大已用 opcode | 138 | 129 | **255** | 117 |
| OPD 段字节 | 1112 | 1040 | — | — |
| OPF 段字节 | 2996 | 1412 | — | — |

- 分配规则：`compile.py:265-287`，`op = 16` 起，先按排序后的 `kind` 字符串、再按排序后的
  对象形状（键元组的排序）依次发号 ⇒ **确定性**，与遍历顺序无关。
- 硬失败：**`compile.py:285-286`** `if op > 256: raise SystemExit("content needs %d opcodes;
  the opcode field is a u8")`。注意判据是"**下一个**待发号值 > 256"，正好等于"最后一个
  已用 opcode ≤ 255"，没有 off-by-one。
- **`u8` 上限硬失败在哪一行**：同一个数还有两次单字节写入，**没有守卫**：
  `compile.py:571-572`（保留分支，写 `len(kinds)`）与 `compile.py:578-579`（动态分支，写
  `lay.nfields`），都是 `struct.pack("<IHBB", off, name, nfields, opclass)`。
  opcode 数超限靠 285 拦；**`nfields > 255` 只能靠 `struct.error` 崩**（见 §3.2）。

**StS 的 75 张卡要引入新节点种类，够不够**：够，且余量是需要的 10 倍以上。
证据是**参考内容自己的密度**：73 个 IR kind + 50 个对象形状（合计 123 个动态 opcode）
就表达了 62 卡 + 394 敌人动作 + 109 遭遇 + 49 遗物 + 23 状态 = **637 个实体**，
外加地图/事件/商店/配方/工作台/元规则/碎片这一整层 run 内容。
即 **637 / 123 ≈ 5.2 个实体共用 1 个 opcode**。StS 第一幕
（75 卡 + 十几个敌人 + 约 40 遗物 + 20 事件）引入的**新**节点种类是"个位数"
（StS 独有机制：`applyPower` / `addCardToHand|Discard|DrawPile` / `gainEnergy` /
`exhaustCard` / 无攻击意图 …），按最悲观的 15 个算，117 → 102。
即使真的撞线，失败是**响亮的** `SystemExit`，不是静默错位。

### 3.2 OPF（字段表）

| 项 | full | core | 上限 | 余量 |
|---|---|---|---|---|
| OPF 条目数（= 所有 opcode 的字段数之和） | **749** | 353 | `u32` 偏移寻址 ⇒ 实际无条目上限 | — |
| OPF 段字节 | 2996 | 1412 | 4 GiB（`field_off` 是 u32） | — |
| **单个 opcode 的字段数上限** | — | — | **255**（`u8 nfields`） | — |
| 当前最宽 opcode 的字段数 | **118** | 118 | 255 | **137** |
| 槽位数最大的 opcode | 118 | 118 | — | — |
| 合计槽位（动态 123 个布局） | 800 | — | — | — |

- 当前最宽的那个是 `_obj(a_very_official_line,…,wrong_window_scribe)`——**118 个敌人 id
  当键的字典形状**（编译器把"同一组键的普通对象"整体给一个 opcode，所以字典越大
  nfields 越大）。加 StS 敌人会生成**另一个**键元组 ⇒ **新 opcode**，不会让这个 118 变胖。
- 字段数分布（123 个动态布局）：0 字段 9 个、1-3 字段 73 个、4-8 字段 29 个、9-16 字段 6 个、
  >16 字段 6 个。⇒ 绝大多数新 opcode 只花 1-3 个字段。
- **结论**：OPF 不是瓶颈。真正要盯的是"某个以 id 集合为键的字典形状"会不会涨到 255 字段
  （现 118，还有 137 的余量；一旦越界，崩的是 `struct.error`，没有友好信息 —— 见 §8 的修法）。

### 3.3 其余 `u16` / `u8` 账本（StS 撞线的先后顺序）

| 项 | 现值 (full / core) | 上限 | 守卫位置 | 余量 |
|---|---|---|---|---|
| 去重后 term 数 | 2,895 / 2,143 | 65,534 | `compile.py:314-315`（响亮） | 62,639 |
| AUX 单元（u16） | 3,810 / 2,078 | 65,533 | `compile.py:550-551`（响亮） | 61,723 |
| 字符串池条目 | 3,140 / 1,375 | 65,533 | `compile.py:525-526`（响亮） | 62,393 |
| **TRM 段字节** | **34,004** / 20,760 | **262,140** | ⚠ **无守卫**（`compile.py:543`/`549`，u16 字偏移） | 228,136 |
| IDX 行数（每类实体的 index 是 u16） | 691 | 65,535 **每类** | 无守卫 | 大 |
| 内容整数范围 | 实测 `[0, 1024]` | `[-32766, 32767]` | `compile.py:365-367`（响亮） | 大 |

⚠ **TRM 是最该注意的那一条**：`TRW` 存的是"字节偏移 / 4"，而 `compile.py:549` 直接
`struct.pack("<%dH", *trw)` —— 一旦 TRM 超过 262,140 B，报错是
`struct.error: ushort format requires 0 <= number <= 0xffff`，**不带任何上下文**。
当前 34 KB 用了 13%。参考内容 743,993 B 的程序体经 interning 后只剩 34 KB 的 term 表，
StS 第一幕的内容量比参考内容小得多，所以**这是"暂时安全"，不是"设计上安全"**。

### 3.4 行表 stride（改既有 schema 的隐含代价）

`row_stride = align4(2 * ncells)`（`rdcfmt.py:272-273`），`compile.py:608` 按它铺行。

| 表 | 现 cell | 现 stride | 加第 1 个 cell 后 | 代价 |
|---|---|---|---|---|
| CARD | 15 | 32 | 16 → 32 | **免费对齐**，但每行内容位移 |
| STATUS | 20 | 40 | 21 → 42 → **44** | stride +4 B/行，全表位移 |
| EACT | 7 | 16 | 8 → 16 | 免费对齐 |
| ENCT | 8 | 16 | 9 → 18 → **20** | stride +4 B/行 |
| REL | 5 | 12 | 6 → 12 | 免费对齐 |

⚠ 不管免不免费，**加一个 cell 一定会改变镜像字节**（每行的槽位顺序变了）⇒ 所有钉在
镜像上的对拍都要重新基线。这就是 §1 的闸门存在的理由：让你**不得不显式**再钉一次。

### 3.5 段号余量，以及"加表会不会动旧镜像"

`NSEC = 20`（`rdcfmt.py:160`）⇒ 段号 0..19，已用 0..14（15 个，含一个**声明了但从不写入**的
`S_TAGS = 14`，manifest 里 `bytes=0`）⇒ **空闲 15..19 共 5 个**。

这件事有直接后果，而且是好消息：

- **把新段号追加到 `SEC_ORDER` 末尾（15）⇒ 旧包字节不变**。理由：`Serializer.write`
  按 `SEC_ORDER` 顺序铺 payload，空数据走 `if not data:` 分支，只写一条
  `(sec, 0, 0, count)` 目录项、不占 payload。而目录本来就有 20 个槽（`NSEC*12 = 240 B`），
  现在只写了 15 条，第 16 条（段号 15）那 12 字节一直是零填充 —— 新写的
  `(15, 0, 0, 0)` 与"原本就是 0"**逐字节相同**。roguedeck 包没有这张表 ⇒ 数据空
  ⇒ 它的两个 SHA 一字不差。（若新表对某个包**非空**，payload 追加在文件末尾，
  前面所有 offset 仍不变，只有 `total_size` 和那一段变。）
- **把 `NSEC` 从 20 改成 21 ⇒ 全文件位移**。理由：`off = align4(HEADER_SIZE + NSEC*12)`，
  目录从 240 B 变 252 B，后面每一个段的 offset 都 +12。

⇒ **想加第 6 张表而不动旧镜像，就用空闲段号（15..19），不要动 NSEC。**

---

## 4. 源文档里的"卡的程序树"是怎么表达的

源文档里，一张卡长这样（`bureaucrats.roguedeck.json`，`Cards[0]`，逐字）：

```json
{ "Id": "paper_cut", "PackageId": "scenario",
  "Costs": [{"ResourceId": {"value": "standard.energy"}, "Amount": 1}],
  "Tags": [{"value":"attack"},{"value":"bureaucracy"},{"value":"action"}],
  "RetainInHandOnTurnEnd": false,
  "TurnEndHandDestinationZone": "DiscardPile",
  "PlayedCardDestinationZone": "DiscardPile",
  "NameKey": "Paper Cut", "DescriptionKey": null,

  "Program": { "Id": {"Value": "(unnamed)"}, "MaxNodeDepth": 64, "MaxProgramSteps": 1024,
    "Root": { "kind": "node.dealDamage",
      "value": { "TargetSelector": { "kind": "sel.eventTarget",
                                     "value": { "Cardinality": "ZeroOrOne",
                                                "RequiredContextCapabilities": "EventTarget" } },
                 "Amount": { "kind": "const", "value": { "Value": 6 } },
                 "ResultKey": null, "IgnoresBlock": false, "Element": null } } } }
```

关键事实：

1. **程序树就是 `{"kind": <字符串>, "value": <对象>}` 的多态节点树**，节点种类、
   字段名、嵌套方式**全部显式写在文档里**，源文档里没有任何"卡牌语义"的简写
   （没有"造成 6 点伤害"这种 DSL 糖）。
2. **编译器对卡牌语义零知识**。它只做三件事：`is_ir()` 认 `{"kind","value"}`
   （`compile.py:76-79`）、`wrap_key()` 认 `{"value":s}`/`{"Value":s}` 两种 id 包装
   （`compile.py:82-...`）、其余普通对象按"键元组的并集"给一个形状 opcode
   （`compile.py:251-263` 观测字段、`compile.py:265-287` 排序发号）。编码时
   `Encoder.ir()` 只按 opcode 的字段描述逐字段取值，**不认识 `node.dealDamage`
   这个名字**（`compile.py:396-404`）。
3. **所以"源文档能不能直接写成 ours 的 15/18 种节点 + 表达式"——能，而且现在就是这么写的。**
   编译器侧不需要任何改动：新卡只要用现成的 kind 字符串和字段拼装即可。
4. `node.*` 判别串**实测 18 个**，但要分成两类看：
   **15 个是内核的程序节点**（`kernel/rd-core/src/ir.rs:120-134` 的 `NodeKind` 枚举：
   sequence / conditional / forEachTarget / forEachCardInZone / dealDamage / gainBlock /
   heal / applyStatus / modifyStatusStacks / setCombatantCounter / drawCards /
   createCardInstance / moveCardToZone / gainResource / loseResource），
   另外 **3 个是 run 层的内容引用**（`node.encounter` / `node.event` / `node.shopRef`），
   `ir.rs:688-702` 明确断言它们**不是**程序节点。
   总数仍是 73 = **18 个 `node.*` + 55 个表达式/run 层**（`left`/`and`/`compare`/`const`/
   `combatantStatusStacks`/`fx.*`/`card.*`/`event.*` …）。
5. **"编译器不懂卡牌语义"的边界在哪**：编译器能装下任何节点种类，但**内核只执行
   `NodeKind` 枚举里的那 15 个**（`ir.rs:120-134`；未知 kind 在
   `NodeKind::from_wire_name` 返回 `None`，`ir.rs:688` 有测试钉住）。
   ⇒ 卡写不出来的原因会在**内核**那头失败，不在编译器这头。
   这条很重要：它意味着**不要为了 StS 去给编译器加"卡牌理解"**，那是错的一层；
   StS 需要的新机制（`applyPower` 之类）落地在内核 + 一个新的 kind 字符串上，
   编译器只需要**重新发一个 opcode**而已。

---

## 5. 哪些部分**不需要**改编译器

| 需求 | 为什么不用改 |
|---|---|
| author 75 张卡 | 程序树就是 IR 明文（§4）。编译器只发 opcode，新 kind 自动得到新 opcode |
| 新的**普通对象**形状（新意图/新费用/新奖励结构） | `Deriver` 按实测键集自动建形状（`compile.py:265-287`） |
| **事件 / 商店 / 地图 / 角色 / 消耗品 / 战斗资源 / 配方 / 工作台 / 元规则 / 碎片** | **今天就已经全走 ROOT + 通用 term**，不是行表：`compile_doc` 把除 5 张行表外的每个顶层键都塞进 `root_entries`（`compile.py:762-764`）。实测 full 变体 17 个 root、core 16 个。⇒ **StS 的事件/商店/地图不需要新表** |
| 新的 id 包装拼法 | 已经是字段级 flag（`FLAG_WRAP_LOWER/UPPER`），混用才退回 `F_TERM` |
| 表现层（名字/描述/美术） | 剥表现层的逻辑按 section 走（`compile.py:667-724`），已有 5 张表覆盖 |
| 内容规模变大 | 见 §3.3：term/aux/字符串都还有 6 万级余量 |

⇒ **"加第 6 张表"应该是最后手段**。只有当某类内容需要"定长行 + IDX 里 O(1) 按 id 查 +
内核按数组下标访问"时，才值得付 §2 的 30 处改动。**事件/药水大概率不需要**：它们现在
就能作为 ROOT 下的普通 JSON 子树存活，并且 `reader.py` 会原样读回来。

---

## 6. 多包结构（本轮落地）

```
tools/contentc/
  compile.py          # 唯一编译器；新增 --full-name / --core-name（默认值 = 历史行为）
  build.py            # 包驱动：--list / --package <名> / --all / --dry-run
  verify_bytes.py     # byte-identity 闸门
  expected_sha.txt    # 钉死的基线（只钉 roguedeck）
  packages/
    roguedeck/package.json      # src=ref/…/bureaucrats.roguedeck.json
                                # out_dir=tools/contentc/out      ← 历史位置，不能搬
                                # full=content.rdcf  core=content.core.rdcf
    sts/package.json            # src=packages/sts/sts.roguedeck.json
                                # out_dir=tools/contentc/packages/sts/out
                                # full=content.sts.rdcf  core=content.sts.core.rdcf
    sts/sts.roguedeck.json      # 两个手写状态，没有任何卡/敌人/遭遇/遗物/地图
    sts/out/content.sts.rdcf        (1264 B)
    sts/out/content.sts.core.rdcf   (1092 B)
    sts/out/build.json              # 源/镜像/编译器的 SHA-256（只有无 pin 的包才写）
```

设计取舍（都是为了不削弱 §1）：

- **`compile.py` 只多两个"改名"参数**，默认值与原行为完全一致 ⇒ 包的引入**不可能**改字节，
  而且这句话由 `expected_sha.txt` 证明，不是由我声明。
- **roguedeck 的输出目录保持在 `tools/contentc/out/`**：`native/fight_diff.py:139` 与
  `native/gen_card_specs.py:51-52` 把路径写死了，搬它会静默打断对拍。
- **`build.json` 只给无 pin 的包写**。有 pin 的包的身份已经在 `expected_sha.txt` 里记过一次；
  再写一份机器生成的副本、而普通 `compile.py` 运行不会刷新它 ⇒ 就是第二个会过期的事实源。
- **sts 包故意极小**：两个状态。它的作用是证明"第二个包能走完整条链"，而不是"StS 内容写好了"。
  它现在没有 pin，也**没有**进任何内核闸门；写进它 75 张卡的时候要同时决定是否给它加 pin 与对拍。

**链路验证**（本轮实跑）：

```
$ python build.py --all
  roguedeck  content.rdcf          158296 B  648a1ff94929c31bd53879a4c77ff4972e75c2007afea3574eedcf1b07036bf7
             content.core.rdcf      85616 B  d14525dac306e64251b6975c5aa0148eaf903f224aaf4b0ea11414189fc9feb6
  sts        content.sts.rdcf        1264 B  445b5fd6d4463c1ccdd65ad5f0e33f8e9ffbf29d0e7b82e3b1f22760eb224fa4
             content.sts.core.rdcf   1092 B  55640d62e473a86d8a1443a20fd67144a8bea54c64f3dbd077768e5674439077

$ python reader.py packages/sts/out/content.sts.rdcf --stats
  OPD 18 条 / OPF 25 条 / TRM 9 条 / STAT 80 B = 2 行 / IDX 2 条
  entities: cards=0 statuses=2 enemy_actions=0 encounters=0 relics=0

$ python reader.py packages/sts/out/content.sts.rdcf --find sts_vulnerable
  sts_vulnerable -> status[1]
```

再对 `Statuses` 逐路径做结构化回环（含键的**存在性**）：
`ROUNDTRIP EXACT: 2 status row(s), key presence included`。
⇒ 新包走通了 源文档 → 编译 → 镜像 → reader 复原 的整条链，且**旧包两个 SHA 一字未变**。

---

## 7. 三个会静默骗人的现存陷阱（都不在闸门覆盖内）

### 7.1 `tools/rdcf_verify.py` 的 `count×stride` 检查**永久静默**，而它的 stride 常量也是错的

- **静默的原因**：`rdcf_verify.py:132` 写的是 `tables = info.get("tables", {})`，但 `info`
  是 `manifest["variants"][name]`（里面只有 `file/bytes/flags/sections`），`tables` 块在
  manifest **顶层**。⇒ `tables` 恒为 `{}`，5 张表的自洽检查**一次都没跑成**。
  好在这段代码自己诚实：它会打印 `? CARD 段：manifest 里没有 tables.cards.count，**这项检查未执行**`
  并把它记进 notes（本轮实跑确认 5 条 `?` 全在）。**但脚本退出码是 0**。
- **常量是错的**：`rdcf_verify.py:31-37` 写 `CARD 28 / STAT 36 / EACT 16 / ENCT 20 / REL 12`，
  实测 `row_stride` 是 `32 / 40 / 16 / 16 / 12`。
- **两个错误互相掩护**：现在无害（因为恒不执行）；一旦有人只修 `:132`，它会因为
  ENCT `1744 B < 109 × 20 = 2180 B` 而**假红**。——这是"第二个事实源腐烂"的活样本。
- 该文件**不在本轮允许改动的范围**（只允许 `tools/contentc/**` + `acceptance.ps1`），
  所以只记录、不修。**建议优先修它**（或者让它直接 import `rdcfmt.row_stride`）。

### 7.2 `manifest.json` 的 `tables` 块是又一份手抄的副本

`compile.py:1322-1326` 逐表写死 5 条。加第 6 张表而忘了这里 ⇒ manifest 少一条 ⇒
`rdcf_verify` 的检查对它**静默跳过**（"查不到就跳过"）。这正是 §5 那条纪律的实例。

### 7.3 空文档会让编译器抛 `ValueError` 而不是说话

`compile.py:558` `n_ops = max(max(self.op_kinds), max(dyn)) + 1`：`self.op_kinds` 恒有
保留 op（0..7），但 `dyn` 在没有**任何** IR kind / 对象形状时是空的 ⇒ `max()` 对空序列
`ValueError`。sts 包塞了两个状态，所以有对象形状，踩不到。但如果将来想要一个**真·空包**
（比如"只放地图"的包），就会撞上这个。不在本轮范围内，记录备查。

---

## 8. 我应该先改哪一处：**把 5 张表的声明收敛成 `rdcfmt.py` 里的单一 `ROW_TABLES`**

不做这一步，加第 6 张表 = 同时改 30 处里的 7~10 处，散在 4 个文件；其中
`tools/rdcf_verify.py` 与 `validate.py` **不在任何闸门里**，漏了不会出声（§7.1 已经证明
这个失效模式真的会发生）。具体：把"表"升级成一条记录，其余全部循环它：

```python
# rdcfmt.py 里唯一一份事实
ROW_TABLES = [
    # (表名, JSON 顶层键, 段号, 实体种类, schema)
    ("CARD",   "Cards",       S_CARD, EK_CARD,   CARD_ROW),
    ("STATUS", "Statuses",    S_STAT, EK_STATUS, STATUS_ROW),
    ...
]
```

然后 `ENTITY_SECTIONS` / `SEC_OF` / `SEC_NAMES` / `SEC_ORDER` / `compile:770-789` 的 IDX 循环 /
manifest 的 `tables` 块 / `reader._rows` / `reader.document` / `reader.stats` /
`validate.SNAME` / `rdcf_verify.STRIDED` **全部从它派生**。收益是三条：

1. 加第 6 张表变成 **1 行**；
2. `row_stride` 只有一个来源，`rdcf_verify` 里那种手工抄 stride 的错误在结构上不可能发生；
3. "某张表忘了在 manifest 里登记"从"静默跳过"变成"编译期不可能"。

⚠ 这一步**会**改变镜像字节吗？只要 `SEC_ORDER` 的**顺序**和 schema 的**内容**不变，
就不会——而这正是 §1 闸门存在的意义：它会在你重构完的第一秒告诉你答案。
实操建议：**先跑绿 → 重构 → 再跑绿**；红了就说明你把某个顺序动了（那就改回来，
而不是 `--repin`）。

次要但同样该一起做的两件（都很小）：

- `compile.py:549` 的 TRW 加一条上限守卫（`trm` 超过 262,140 B 时
  `SystemExit("term table overflows the u16 word offset ...")`），和 `:314`/`:525`/`:550`
  那三处保持一致；
- 把 `nfields > 255` 的失败也变成一句人话（现在是 `struct.error`）。

---

## 9. 本轮改动的完整清单

| 文件 | 性质 |
|---|---|
| `tools/contentc/expected_sha.txt` | 新建：钉死的基线 + 为什么 + 怎么重钉 |
| `tools/contentc/verify_bytes.py` | 新建：byte-identity 闸门（`--repin` / `--src` / `--keep` / `--quiet`） |
| `tools/contentc/build.py` | 新建：多包驱动（`--list` / `--package` / `--all` / `--dry-run`） |
| `tools/contentc/packages/roguedeck/package.json` | 新建：把历史行为表达成一个包 |
| `tools/contentc/packages/sts/package.json` | 新建：新包（skeleton） |
| `tools/contentc/packages/sts/sts.roguedeck.json` | 新建：2 个手写状态，无卡 |
| `tools/contentc/packages/sts/out/*` | 构建产物（1264 B / 1092 B / build.json / manifest / layout / report） |
| `tools/contentc/compile.py` | 改：`--full-name`/`--core-name`（默认不变）；`write_report` 的 `Encounters` 守卫；`len(doc)` 取代写死的 22 |
| `tools/acceptance.ps1` | 改：**新增第 10 道闸门**（`contentc-bytes`）+ 给它加一条只影响显示的 evidence 正则 |
| `docs/spec/contentc-audit.md` | 新建：本文 |

**未改**：`content.rdcf` / `content.core.rdcf`（闸门证明逐字节未变）、`kernel/`、`native/`、`ref/`。
`out/manifest.json` / `out/report.md` / `out/layout.txt` 在验证 `build.py --all`（其中 roguedeck 一支）
时被重写过一次，随后**从备份还原**（它们不在 pin 范围内；重写版本与仓库版本只差计时数字）。
