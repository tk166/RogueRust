"""§339 的 port-plan 章节：条件 DSL 的 OR 组 + 两处资格修正。"""

import io

PATH = 'docs/port-plan.md'

SECTION = """
## §339 条件 DSL 补上 OR（`RequiresAny`）+ 两处事件资格修正

八轮 Review 的 2.2 / 2.3 与复核 C2。三件事在同一个提交里，因为它们**必须同时成立**：
只加 DSL 不改内容 = 没修；只改内容没有 DSL = 表达不了；改了内容不改测试 = **修完反而红**。

### 1. `RequiresAny`：组内 OR、组间 AND

`run_expr` 的形态一直是"一串原子、全部成立才成立（AND）"，模块头自己写着
"缺 `or` 是**已知的表达力缺口**，真出现时再加"。真出现了：

* `The Moai Head`：*"either has Golden Idol, **or** their HP is at or below 50%"*。
  写两条 AND 原子会变成"两个都要满足"⇒ 满血 + 持有 Golden Idol 的玩家**永远遇不到**。

```json
"RequiresAny": [
  {"Kind": "health_percent", "Op": "at_most", "Amount": 50},
  {"Kind": "relic", "Op": "has", "Id": "golden_idol"}
]
```

语义：`AND(Requires) && (RequiresAny 为空 || OR(RequiresAny))`。

**为什么仍然是两个平铺列表，不是布尔树**：真实内容里的需求只有"AND 一组、OR 一组"这一种形状；
一棵树要一套解析器、一套求值器、一套"表里有但没实现"的判据，而两个循环就够了。树留到真的
需要嵌套时再说 —— 那时它值单独一节。

⚠️ **没有** `RequiresAnyAsc`。`RequiresAsc` 之所以存在，是因为 A15 真的改了价目
（`The Cleric` 的 Purify 50 → 75）；"以后可能需要"不是加接口的理由。

⚠️ **空的 `RequiresAny` = "这一组没要求"，不是"永不成立"**。这条区分很要紧：绝大多数选项没有
这个字段，判成 false 会让整个内容变成死按钮，而**没有任何闸门会红**（事件池只是变小）。

### 2. `The Moai Head`：AND → OR

`EventTables.Events3.the_moai_head` 原来只有 `health_percent at_most 50`。
改成 `RequiresAny`（两条原子）。**选项级**的 `[Offer: Golden Idol]` 原本就要求持有 Idol，
不用动。

### 3. `Tomb of Lord Red Mask`：反向资格 + 选项互斥

原来两处都错，而且**互相掩盖**：

1. **事件级** `Requires: relic has red_mask` ⇒ **没有**面具的玩家永远遇不到这个事件，
   而"献出全部金币换 Red Mask"正是 wiki 里**获得**这件遗物的途径之一 ⇒ 死内容。
   这个事件在 wiki 里**没有任何出现条件**（Act 3 池的普通一员）。
2. **选项级** `Offer all Gold` 只查 `gold at_least 1`，不查"没有面具" ⇒ 持有面具的玩家
   既能 `[Don the Red Mask]`（+222 金）又能再献一次金币拿**第二个** Red Mask。

wiki 的两屏是互斥的：有面具 ⇒ `[Don the Red Mask] / [Leave]`；没面具 ⇒
`[Locked] Requires: Red Mask / [Offer: X Gold] / [Leave]`。所以给 `Offer all Gold` 加
`relic lacks red_mask` —— `PRESENCE_OPS` 本来就认 `lacks`，不需要新词。

### ★ 旧测试把错的行为写成了规范（第二次）

`event_level_requirements_filter_the_pool_before_the_roll` 里：

```rust
assert!(!pool_has(&above_half, "the_moai_head"), "above 50% the Moai Head must not appear");
assert!(!pool_has(&base, "tomb_of_lord_red_mask"), "without the Red Mask the tomb is not in the pool at all");
```

第一条漏掉了 "or Golden Idol" 那一半，于是**满血 + 有 Idol 应该出现**被判成"必须不出现"；
第二条把"没有面具就遇不到"写成了规范。两条都不是"漏测"，是**把错的行为写成了期望值**
（与 §338 的折扣公式同一个形状，两次都是同一个病）。

所以重写整条判据：Moai **2×2 表四格全测**、Tomb 有/无面具都**在池里**、选项互斥四格全测。

### 4. 两处词表漂移（`FACT.md` §4.20 的同一个形状）

`native/sts_content_check.py` 里有一份**手抄的** `REQUIRES_KINDS`，注释写着"必须与
`rd-core::run_expr` 一致"，而 §331 加 `relic_count`（`N'loth`）时**只改了 Rust 那一份**。
它没红，是因为这份表只用来查**选项级** `Requires`，而 `relic_count` 只出现在**事件级**。

⇒ 两处一起修：词表补齐，并且事件级 `Requires` / `RequiresAny` 也走同一个
`check_requirement_atom`（顺带要求 OR 组**非空**——空列表是笔误，不是"永不成立"）。
以后同类漂移会红在内容门上，而不是变成"`?` 房不出事件"。

### 判据

| 判据 | 钉住什么 |
|---|---|
| `event_level_requirements_filter_the_pool_before_the_roll`（重写） | Moai 2×2 四格；Tomb 有/无面具都在池里；选项互斥四格；无条件事件不受影响 |
| 内容门 `[8]` 事件池 | 事件级 `Requires`/`RequiresAny` 的每个原子都过词表；OR 组非空；两组同时出现会被统计出来（`both groups: N`） |

负控 5/5（`native/p339_negative.py`）：OR 组短路 / 跳过 AND 组 / 事件级词表外 Kind /
空 OR 组 / 词表漏 `relic_count`，五条**各自**红，每条都断言具体失败文本。

⚠️ 两个负控自身的坑：**内容侧负控必须先重编镜像**（内容门在"源比镜像新"时 `exit 2`，
根本走不到那条检查 —— 第一版三条内容负控全是 `NOT CAUGHT`，原因与条件无关）；
**AND 组的 needle 要带 `!`**（`if !atom_holds(...)` —— 漏了感叹号就匹配不到，
负控"没装到切口上"）。

### 没有做的一件事（诚实记录）

内容里今天**没有**"同一格既有 AND 又有 OR"的条目，所以没有编一个假条目去测这个组合。
两组各自被真实内容钉住（Moai = 只有 OR，Tomb 的 offer = 只有 AND），求值顺序由负控 ①② 证明
不是摆设。真出现"既有 AND 又有 OR"的需求时，加一个真实条目再测。

### 数字

`rd-core 819`（判据重写，条数不变）、`rd-run 218`、`rd-wasm 182`、units **1219**；
内容镜像 `190052 B / 152380 B`；四条对拍不动；23/23 闸门。
"""

t = io.open(PATH, encoding='utf-8').read()
assert '## §339' not in t
io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t.rstrip('\n') + '\n' + SECTION)
print('port-plan §339 added')
