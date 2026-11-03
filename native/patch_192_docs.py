"""§192/§193 doc updates: the specs that describe the cells and the two new semantics."""
import io


def patch(path, pairs):
    src = io.open(path, encoding="utf-8").read()
    for old, new in pairs:
        assert src.count(old) == 1, "%s: %d occurrences of %r" % (path, src.count(old), old[:70])
        src = src.replace(old, new)
    io.open(path, "w", encoding="utf-8", newline="").write(src)
    print("patched", path)


# ---------------------------------------------------------------- binary format
patch("docs/spec/content-binary-format.md", [(
"""## 7. 实现补充（2026-11-03）：`FORMAT_VERSION` 5

`EACT` 从 7 格涨到 9 格（§187：`ProgramAsc` + `AscensionMin`），行宽 16 → 20 B：

* `FORMAT_VERSION` 4 → 5，**旧镜像会被 `UnsupportedVersion` 直接拒绝**（不是尽力解析）；
* `tools/contentc/expected_sha.txt` 因此必须重新钉（`verify_bytes.py --repin`）：编译器变了，
  旧内容的产物字节必然移动。重钉之后 85 份语料与 4 条对拍仍是逐字节一致 —— 那是"格式变了、
  语义没变"的证据；
* 核心镜像（`roguedeck`）也涨了：85,616 → 87,192 B，全量 158,296 → 159,872 B。""",
"""## 7. 实现补充（2026-11-03）：`FORMAT_VERSION` 5 → 7

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
  读 `content-binary-format` 旧章节时别把两次数混起来。""")])

# ---------------------------------------------------------------- schema
patch("docs/spec/content-schema.md", [(
"""## 9. 实现补充（2026-11-03）：`EACT` 的 ascension 维度

§2 的 `EACT` 有 7 格（`Id/NameKey/DescriptionKey/PackageId/Intent/Program/extra`）。§187 加了**两格**：

| 格 | 类型 | 含义 |
|---|---|---|
| `ProgramAsc` | `F_TERM`（可空） | 升档后的节目，**与 `Program` 同形的信封**（`{Root, MaxProgramSteps, …}`），不是裸 `Root` |
| `AscensionMin` | `F_INT`（`0` = 无） | 从哪一级起改用 `ProgramAsc`。`0` **不**表示"从 0 级起" |

行宽 7 → 9 格，stride 16 → 20，`FORMAT_VERSION` 4 → 5。""",
"""## 9. 实现补充（2026-11-03）：`EACT` 的 ascension 维度（§192 起是**列表**）

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
（上面 Bellow 的 A17 变体写的是 Strength 5 + Block 9，不是只写 Block 9）。"""), (
"""## 10. 实现补充（2026-11-03）：事件的选项是**效果列表**""",
"""## 9b. 实现补充（2026-11-03）：敌人记录里的 `Rolls`（§193）

`ENCT[i].Enemies[j]` 多了一个键（**不是格** —— 敌人记录是 term 对象，加键不动任何 stride）：

| 键 | 类型 | 含义 |
|---|---|---|
| `Rolls` | 列表 `[{Key, Min, Max, AscensionMin?}, …]` | 开局掷骰：`Key` 计数器在 `Min..=Max` 里抽一个值，写进**这个敌人** |

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

## 10. 实现补充（2026-11-03）：事件的选项是**效果列表**""")])

# ---------------------------------------------------------------- semantics
patch("docs/spec/SEMANTICS-v1.md", [(
"""* `EACT.ProgramAsc` + `AscensionMin`：同一个动作的两份节目。""",
"""* `EACT.ProgramAsc`：同一个动作的**变体列表** `[{AscensionMin, Program}]`（§192 起；之前是
  "一个信封 + 一个阈值"，装不下两个档位）。取 `AscensionMin <= ascension` 里阈值最大的一个。"""), (
"""所以 Ascension 对核心的影响**只在入口**：一个动作要么走基础节目、要么走变体，
两者都是**已有的**执行器（`intent::execute_action` → `exec::execute`）。""",
"""所以 Ascension 对核心的影响**只在入口**：一个动作要么走基础节目、要么走变体，
两者都是**已有的**执行器（`intent::execute_action` → `exec::execute`）。

§193 另加一条：**开局掷骰**（`ENCT[i].Enemies[j].Rolls`）在建战斗时写进战斗员的计数器
（`battle::apply_spawn_rolls`，每抽一次 `random_step += 1`），动作里的 `combatantCounter`
读到它。规则本身不动 §2.1 —— 它只是给"伤害是多少"提供了一个**在第一次出招之前就固定**的值，
这正是 wiki 的 *chosen at the start of combat*。""")])

# ---------------------------------------------------------------- inventory
patch("docs/spec/sts-act1-inventory.md", [(
"""> `jaw_worm.bellow` 有两个档位（Strength @A2、Block @A17），而 `ProgramAsc` 每行只有一个 ⇒
> 变体带的是较早那个，Block 那一半写在内容的注释里。""",
"""> §192 起 `ProgramAsc` 是**变体列表**，所以 `jaw_worm.bellow` 的两个档位都在：A2 是
> Strength 4 + Block 6，A17 是 Strength 5 + Block 9（A17 那一条**重复**了 A2 的改动 ——
> 变体是整段节目，只有阈值最大的一条生效）。"""), (
"""§191 修掉了 8 条**基础值**与 wiki 不一致的招式并给它们补了升档""",
"""可变伤害（`louse_*.bite` 的 5-7 / 6-8、`darkling.nip` 的 7-11 / 9-13）在 §193 落地：
数字是 `ENCT` 敌人记录里的 `Rolls`（"chosen at the start of combat"），动作读
`combatantCounter`。`louse_green.bite` 仍是常量 6 —— 这份内容没有 `louse_green` 敌人记录，
把它改成计数器读取等于埋一个"0 伤害"的地雷（内容门用 `INV_UNWIRED` 钉住这件事）。

§191 修掉了 8 条**基础值**与 wiki 不一致的招式并给它们补了升档""")])

# ---------------------------------------------------------------- plan doc
patch("docs/spec/sts-act1-plan.md", [(
"""§187 把它加了：`EACT.ProgramAsc` + `AscensionMin`（两格）+ `intent.ascensionAtLeast`。""",
"""§187 把它加了：`EACT.ProgramAsc` + `AscensionMin`（两格）+ `intent.ascensionAtLeast`。
§192 又把那两格换成**一格变体列表**（一个动作两个档位），`intent.ascensionAtLeast` 保持不变。""")])
