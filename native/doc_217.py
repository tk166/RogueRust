"""§217 docs."""
import io

ROOT = 'D:/Vibe/sts-tui/'

SECTION = '''
---

## §217 覆盖矩阵不再自我美化（审阅 P2-A 的三件事 + 五个对抗性夹具）

审阅 P2-A 说：矩阵是"证据索引"，但列名让人以为通过了语义验证。逐条核过，**三件事都成立**，
其中一件是我在 §215 重构时留下的真 bug。这一节把矩阵改成"只说它能证明的事"，并给它配了自检。

### 217.1 三处修正

| 审阅的话 | 复核结果 | 修法 |
|---|---|---|
| `if not reachable and aid in everywhere` 把字符串 id 与**字典键**比较 | ✅ **真 bug**：`everywhere` 在 §215 被改成按类别的 dict，这一行漏改 ⇒ "referenced elsewhere" 兜底**永远不成立** | 改成 `everywhere['EnemyActions']` |
| 扫描器不递归，也没有覆盖全部集成测试目录 | ✅ 少 8 条（`rd-run/src/state/archive.rs`）+ 1 条（`#[test]` 与 `fn` 之间隔着 doc 注释，`rd-wasm/src/run.rs:7041`） | 递归 `os.walk`；`head_of()` 允许注释；**注释里的 `#[test]` 用 `strip_rust` 的等长偏移排除** |
| 列名 `RuntimeTested` / `WikiVerified` 高估了证据 | ✅ | 拆成 `TestNamed` / `HarnessOnly` / `SourceTie` / `DeclaredDeviation`，表头写明"没有一列声称行为正确" |

**对账用 cargo 自己的清单**（不靠 grep 行数 —— 第一版就是这么错的）：

```text
cargo test -p <crate> -- --list     rd-core 704 + rd-run 108 + rd-wasm 94 = 906（含 2 条 #[ignore]）
§215/§216 的扫描器                    893   （缺 9 = 8 + 1）
§217 的扫描器                         906   == cargo 的清单
```

> 顺带纠正 §217 初稿里的一句话：我按"grep 到 906 行 `#[test]`、其中 4 处是注释"推过"真实 902"，
> 这是**错的** —— 同一行里可能出现两个属性，行数不是条数。以 `--list` 为准。

### 217.2 列名与口径（页面表头里也写了）

| 列 | 它**真的**说明什么 | 它**不**说明什么 |
|---|---|---|
| `Implemented` | 在内容里且可达（口径按类别，见 `build_entities`） | 玩法对不对 |
| `TestNamed` | 这个 id 以**字符串字面量**出现在某条测试的函数体里（注释不算） | **行为被断言**：`assert_eq!(id, "spiker")` 与"真打一场 spiker"在这一列里一模一样 |
| `HarnessOnly` | 没有具名引用，但整表遍历盖到了（`ENEMY_DIFF` / `CARD_DIFF` / 内核里 `potion_count()` 那类） | 按 wiki 的数在跑 |
| `SourceTie` | `wiki:<dump>`（= 有页面 **且** checker 钉了数字）或 `spec:<TABLE>`（= 只对上了人抄的清单） | 语义对齐：**动作的页面是从所属怪物继承的**，所以现在写成 `wiki:…(via <怪物>)`；`maw.nom_nom` 就是"有 wiki 标签、时间变量却错"的反例 |
| `DeclaredDeviation` | 有人**写下**了"它和 wiki 不一样" | 偏差只有这些 |

### 217.3 顺带发现：`§G` 的"已修"表被当成了"现存偏差"

§215 的解析器把 `docs/sts-wiki-gap.md` §G 的**两张**表都读了：`已修`（原值 → 现在）与
`仍然故意不修`（现存偏差）。于是 8 条早已修好的招式（`spiker.cut`、`chosen.poke`、`darkling.chomp`、
`gremlin_leader.slash`、`sentry.bolt`、`spire_growth.strategic`、`the_champ.execute`、
`the_champ.heavy_slash`）在矩阵里被列成"现存偏差"，读起来像 `ours 8 / wiki 7`。

现在只认"故意不修 / 放宽"那两张表（`armed` 开关），偏差数 **68 → 63**（−8 条历史，+1 条真偏差）。
新增的 `§G.2 语义放宽` 表收下了 §216 发现的那条：`standard.slow` 放大**任何直接伤害**，而 wiki
只放大"打出攻击牌造成的伤害"（要精确需要 `RestrictSourceCardTag` 进镜像格式）。
偏差表的存在性检查也从"只查动作与怪物"扩到**全部类别** —— 否则一条合法的状态偏差会被判成"表漂了"
（这条是加 `§G.2` 时当场撞出来的）。

### 217.4 `--selftest`：五个夹具，打扫描器自己

一个从不被测试的覆盖工具只是另一种意见。夹具建在临时目录里，不碰真实内容：

1. **嵌套目录**里的测试必须被找到（旧版丢的正是这 8 条）；
2. **`#[test]` 与 `fn` 之间夹 doc 注释**必须被找到；
3. **注释里提到的 `#[test]`** 必须**不**算测试（树里有 4 处这种提及；
   判据是"该位置在 `strip_rust` 之后是空格"——等长替换让偏移可以直接比对）；
4. **id 只出现在测试体的注释里** ⇒ 不算 `TestNamed`（新增 `strip_comments()`：剥注释但**保留字符串**，
   因为花括号配对要连字符串一起抹，抽字面量则必须要它们）；
5. **孤儿/声明谓词**：自己提到自己不算可达（§215 的恒真谓词就是这个），过时的
   `ORPHAN_OK` 声明必须红 —— 为此把那段检查抽成 `declaration_problems()`，让夹具能直接问它。

三条自检负控（都实测过）：关掉注释剥离 ⇒ 夹具 4 红；关掉递归 ⇒ 夹具 1/计数/嵌套字面量三条红；
把 `declaration_problems` 改成 `return []` ⇒ 夹具 5 的两条红。
顺带：写夹具时**它当场抓到我自己的一个错误**（我用 `chosen` 当"只在注释里"的例子，而它在另一条
夹具测试里是字面量），换成 `darkling` 才对。

### 217.5 数字

* **21/21 闸门绿**；单测 **904**（704 / 107 / 93）不变；四条对拍不变。
* 矩阵：`TestNamed` **230** / `HarnessOnly` **114** / 两层都没有 **16**（14 怪 + 2 状态）；
  `SourceTie:wiki` **177** / `spec` **94**；偏差声明 **63**；未声明孤儿 **0**；扫到具名测试 **906**。
* 与 §215 的差异全部来自修正：`TestNamed` +1（`CARD_DIFF` 那条被补上的卡）、`HarnessOnly` −1、
  偏差 68 → 63、测试数 893 → 906。
* 闸门 13 现在跑 `--check --selftest`（两条证据串都要出现）。
'''

port = io.open(ROOT + 'docs/port-plan.md', encoding='utf-8').read()
assert '## §217' not in port
io.open(ROOT + 'docs/port-plan.md', 'a', encoding='utf-8', newline='\n').write(SECTION)
print('port-plan §217 appended')

readme = io.open(ROOT + 'README.md', encoding='utf-8').read()
old = '（§1–§216，每一轮都留数字、记下被推翻的结论）'
new = '（§1–§217，每一轮都留数字、记下被推翻的结论）'
assert readme.count(old) == 1
readme = readme.replace(old, new)
old = '`coverage-matrix.md`（**生成物**：每个实体的 Implemented / RuntimeTested / WikiVerified / '\
      'Deviation / Evidence，闸门 13）'
new = '`coverage-matrix.md`（**生成物**：每个实体的 Implemented / TestNamed / HarnessOnly / '\
      'SourceTie / DeclaredDeviation / Evidence，闸门 13；带 `--selftest` 的五个对抗性夹具）'
assert readme.count(old) == 1, 'readme matrix line'
readme = readme.replace(old, new)
io.open(ROOT + 'README.md', 'w', encoding='utf-8', newline='').write(readme)
print('README updated')
