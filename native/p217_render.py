"""§217 part 3: the page itself stops over-promising (header + summary + table)."""
import io

P = 'native/coverage_matrix.py'
text = io.open(P, encoding='utf-8').read()


def one(old, new, what):
    global text
    assert text.count(old) == 1, '%s: expected 1, found %d' % (what, text.count(old))
    text = text.replace(old, new)


one('''* **Implemented** —— 在内容里且**可达**（`orphan` = 内容长出一条没人引用的行，闸门红）。
* **RuntimeTested** —— `test:<函数名>`：某条内核测试的函数体里出现了这个 id；
  `harness:<名字>`：只有通用对拍层遍历到它（`ENEMY_DIFF` 跑每一条 `EACT`、`CARD_DIFF` 跑每一张卡）。
  ⚠️ `harness` 比 `test` 弱：它只说明"跑过、程序文本与参考实现一致"，不说明"按 wiki 的数在跑"。
* **WikiVerified** —— `wiki:<dump>`：`native/wiki_asc/` 或 `native/wiki_*.txt` 里有它的
  Infobox，**并且** checker 钉了它的数字；`spec:<TABLE>`：只对上了 checker 里那份**也是人抄的**清单；
  `—`：没有任何独立来源。**这一列是本页最大的洞，不粉饰**。
* **Deviation** —— 声明过的偏差（`INV_UNWIRED` / `INV_NO_ASC` / `INV_NO_ASC_HP` /
  `docs/sts-wiki-gap.md` §G、§H 两张表，直接解析）。
* **Evidence** —— `§N`（`sts_content_check.py` 引用到的 port-plan 小节）+ 不变量表 + 测试名。

**怎么用**：想找下一件该干的活，就按 `WikiVerified = —` 或 `RuntimeTested = —` 排序看。''',
    '''**⚠️ 这七列没有一列声称"行为正确"。** 它们回答的是三个更弱、但可以被机器检查的问题：
*这个实体有没有出处？有没有被任何测试引用？有没有人写下"它和 wiki 不一样"？*

* **Implemented** —— 在内容里且**可达**（`orphan` = 内容长出一条没人引用的行，闸门红）。
  可达性的口径按类别不同（怪=遭遇名单/`spawn`；动作=动作表/AI 规则；状态=程序/触发器/药水原子；
  卡=起始牌组或按稀有度的牌池），逐条写在 `coverage_matrix.py` 的 `build_entities` 里。
* **TestNamed** —— 这个 id 以**字符串字面量**出现在某条内核测试的函数体里（注释里的不算）。
  ⚠️ **它是"被引用"，不是"行为被断言"**：`assert_eq!(id, "spiker")` 与"真打一场 spiker 的战斗"
  在这一列里长得一模一样。§217 之前这一列叫 `RuntimeTested`，那个名字把"引用"读成了"验证"。
  测试名来自递归扫描（`cargo test -- --list` 是它的独立对账：906 条）。
* **HarnessOnly** —— 没有具名引用，但**整表遍历**盖到它了：`ENEMY_DIFF`（跑每一条 `EACT`）、
  `CARD_DIFF`（跑每一张卡）、或内核里"遍历整张表"的测试（`the_potions_are_readable` 之类）。
  这比 `TestNamed` 更弱：它只说明"跑过、程序文本与参考实现一致"。
* **SourceTie** —— `wiki:<dump>`：`native/wiki_asc/`（或 `native/wiki_*.txt`）里有它的 Infobox
  **并且** checker 钉了它的数字；动作那侧的括号 `(via <怪物>)` 是**必须写出来**的 ——
  页面来自所属怪物，不是这条动作自己核过（`maw.nom_nom` 有 wiki 标签、时间变量却错了，就是反例）。
  `spec:<TABLE>`：只对上了 `sts_content_check.py` 里那份**也是人抄的**清单。
  `—`：没有任何独立来源 —— **这一列是本页最大的洞，不粉饰**。
* **DeclaredDeviation** —— 声明过的偏差（`INV_UNWIRED` / `INV_NO_ASC` / `INV_NO_ASC_HP` /
  `docs/sts-wiki-gap.md` §G、§H 两张表，直接解析）。
* **Evidence** —— `§N`（`sts_content_check.py` 引用到的 port-plan 小节）+ 不变量表 + 测试名。

**怎么用**：想找下一件该干的活，按 `SourceTie = —` 或 `TestNamed = —` 排下去就是待办。
**不要**把 `TestNamed` 当成"已经验证过"——要验证语义，得去看那条测试**断言了什么**。''',
    'header bullets')

one('''    out.append('| 类别 | 行数 | `test:` | `harness:` | `—` | `wiki:` | `spec:` | 有偏差 | orphan |')
    out.append('|---|---|---|---|---|---|---|---|---|')
    total = {key: 0 for key in ('rows', 'test', 'harness', 'none', 'wiki', 'spec', 'dev', 'orphan')}
    for kind in KIND_ORDER:
        stats = summary[kind]
        out.append('| %s | %d | %d | %d | %d | %d | %d | %d | %d |' % (
            KIND_LABEL[kind], stats['rows'], stats['test'], stats['harness'], stats['none'],
            stats['wiki'], stats['spec'], stats['dev'], stats['orphan']))
        for key in total:
            total[key] += stats[key]
    out.append('| **合计** | %d | %d | %d | %d | %d | %d | %d | %d |' % (
        total['rows'], total['test'], total['harness'], total['none'], total['wiki'],
        total['spec'], total['dev'], total['orphan']))''',
    '''    out.append('| 类别 | 行数 | TestNamed | HarnessOnly | 两层都没有 | SourceTie:wiki | '
               'SourceTie:spec | 有偏差声明 | orphan |')
    out.append('|---|---|---|---|---|---|---|---|---|')
    total = {key: 0 for key in ('rows', 'named', 'harness', 'none', 'wiki', 'spec', 'dev',
                                'orphan')}
    for kind in KIND_ORDER:
        stats = summary[kind]
        out.append('| %s | %d | %d | %d | %d | %d | %d | %d | %d |' % (
            KIND_LABEL[kind], stats['rows'], stats['named'], stats['harness'], stats['none'],
            stats['wiki'], stats['spec'], stats['dev'], stats['orphan']))
        for key in total:
            total[key] += stats[key]
    out.append('| **合计** | %d | %d | %d | %d | %d | %d | %d | %d |' % (
        total['rows'], total['named'], total['harness'], total['none'], total['wiki'],
        total['spec'], total['dev'], total['orphan']))''',
    'summary table')

one('''        out.append('| Entity | Implemented | RuntimeTested | WikiVerified | Deviation | Evidence |')
        out.append('|---|---|---|---|---|---|')
        for row in rows:
            if row['kind'] != kind:
                continue
            cells = [row['id'], row['implemented'], row['runtime'], row['wiki'],
                     row['deviation'], row['evidence']]''',
    '''        out.append('| Entity | Implemented | TestNamed | HarnessOnly | SourceTie | '
                   'DeclaredDeviation | Evidence |')
        out.append('|---|---|---|---|---|---|---|')
        for row in rows:
            if row['kind'] != kind:
                continue
            cells = [row['id'], row['implemented'], row['named'], row['harness'], row['source'],
                     row['deviation'], row['evidence']]''',
    'entity table')

io.open(P, 'w', encoding='utf-8', newline='\n').write(text)
print('render patched')
