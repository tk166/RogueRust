"""Docs for §215: port-plan section, README numbers, and the gap doc's anti-rot section."""
import io

ROOT = 'D:/Vibe/sts-tui/'

# ── port-plan §215 ──────────────────────────────────────────────────────────────────────────────
SECTION = '''
---

## §215 工作包 D：覆盖矩阵（`docs/coverage-matrix.md`，闸门 13）

### 215.1 为什么现在做

前面几节（§206–§214）有一个共同形状：**"某只怪与 wiki 对不上"是这样被发现的 —— 我先想起来它可疑**，
然后去翻 `native/wiki_asc/` 与 `docs/spec/`。`chosen` 的 HP 错了很久（48 vs 95-99）、
`spiker.spike` 根本不是 wiki 的那一招、`spire_growth.strategic` 甚至不在遭遇的 `Actions` 名单里；
这期间 **20 道闸门全绿**。`docs/sts-wiki-gap.md` §4 早就写过句实话：*闸门看不见 wiki*。

闸门看不见 wiki，但闸门**能**看见另一件事：**某个实体没有任何来源、没有任何测试、也没有声明过偏差。**
这一节把这件事做成一张 360 行的表，并且**每一列都是派生的**。

### 215.2 五列的口径（这是这一节的全部内容）

| 列 | 派生方式 | 强弱 |
|---|---|---|
| `Implemented` | 在内容里且**可达**。怪：在某个遭遇名单里或被 `spawn` 点到；动作：被某只怪的动作表/AI 规则引用，或在 `INV_UNWIRED` 里声明；状态：被程序/触发器/药水原子引用（**按 token 边界**匹配，因为药水写的是 `combat_status:standard.duplication`）；牌组/遭遇/事件/遗物/药水可以按类别给出"池"的定义 | 弱（只说明"接上了"） |
| `RuntimeTested` | `test:<函数名>`：某条内核测试的**函数体**里出现这个 id；`harness:<名字>`：只有通用层遍历到它（`ENEMY_DIFF` 跑每一条 `EACT`、`CARD_DIFF` 跑每一张卡、`the_potions_are_readable` 跑每一瓶药水） | **两者强弱不同**：`harness` 只说明"跑过、程序文本与参考实现一致"，不说明"按 wiki 的数在跑" |
| `WikiVerified` | `wiki:<dump>`：`native/wiki_asc/*.txt`（或 `native/wiki_*.txt`）里有它的 `{{Enemy Infobox\\|Name=…}}`，**并且** checker 至少钉了它的一个数字（`INV_ASC_HP`/`INV_ASC_VARIANTS`/`INV_ROLLS`/`INV_SPAWN_COUNTERS`）；否则 `spec:<TABLE>` = 只对上了 checker 里那份**也是人抄的**清单 | 这一列是本页**最大的洞** |
| `Deviation` | 三个机器来源（`INV_UNWIRED`/`INV_NO_ASC`/`INV_NO_ASC_HP`）+ **直接解析** `docs/sts-wiki-gap.md` §G 的"故意不修"表与 §H 的 Boss 剩余差异表 | —— |
| `Evidence` | 该实体在 `sts_content_check.py` 里被引用到的 `§N` + 不变量表名 + 测试名 | —— |

**为什么每一列都要派生**：项目里已经有三次"第二个真相腐烂"的记录（`verify_bytes.py` 手抄的 stride
常量、`smoke.mjs` 手抄的导出清单、README 里那句"27 + 18"）。一张 360 行、六个类型的覆盖表如果靠手写，
下一次内容变更就会开始骗人，而**没有任何东西会红**。

### 215.3 生成器自己抓到四个 bug（都是"工具骗人"的形状）

1. **`strip_rust` 删字符 ⇒ 花括号坐标错位**。它把注释与字符串**删掉**再数 `{}`，于是函数体的结束位置
   是在缩短后的文本里算出来的，`the_potions_are_readable` 被切成 4675 字节（真实长度是它的一倍多），
   33 瓶药水**全部**报"没有任何证据"。改成等长替换（空格占位）后正常。
   ⇒ 教训：**扫描器坏掉时的输出是"看起来正常的一页"**，不是报错。
2. **`everywhere` 把实体自己的定义表也收进去了** ⇒ 每只怪都因为"定义了自己"而"可达"，orphan 永远报不出。
   负控（贴一只没人引用的 `ghost_slime`）当时报的是"没有证据列"而不是"不可达"。
   ⇒ 教训：**一个恒真的谓词不是谓词**；可达性必须按类别排除自身。
3. **方法名有单数也有复数**：`content.potion_count()`（一条）与 `rows(Table::Cards)` 并存，第一版只认复数。
   排序里那个"边 sort 边 index"的写法在 3 个元素时也崩了（`ValueError: not in list`）。
4. **`\\b` 被 JSON 层吃成了退格字符**（`r'\\b'` → `r'<BS>'`），三条 regex 变成永远匹配不上的空模式；
   而 `\\s`/`\\(` 因为不是合法转义反而活了下来 —— 这种**不对称**让"文件能 parse"完全掩盖了问题。
   ⇒ 与 FACT §2 同一条：源码里要写反斜杠，**别经过 `-c` / heredoc 的任何一层**；写成 `.py` 文件，
   或者干脆用 `(?:^|[^A-Za-z0-9_])` 代替 `\\b`、`chr(10)` 代替 `'\\n'`。

### 215.4 第一次跑出来的三条**内容**结论（不是工具的锅）

| 结论 | 依据 | 处理 |
|---|---|---|
| `acid_slime_s` / `spike_slime_m` / `louse_green` **没有任何遭遇引用它们** | `enc_small_slimes` 只放 `acid_slime_m`+`spike_slime_s`；`enc_louse` 只有红虱 | 写进 `ORPHAN_OK` **声明**（同 `INV_UNWIRED` 的做法），并且**声明本身也被检查**：哪天它们被接进遭遇、或 id 被删，闸门就红，逼着删声明 |
| `standard.rage` / `standard.flame_barrier` **内容里没有任何一行施放它们**（本内容没有 Rage / Flame Barrier 牌），只有内核测试按 id 直接施 | 矩阵的 `Implemented` 显示 `yes (test-only)` | 不改内容，但把"test-only"写在页面上 —— 它和"内容驱动的状态"不是同一件事 |
| **卡牌零份 wiki 出处**：51 张卡只有 `spec:INV_CARDS` | 仓库里没有任何卡牌页的 dump（只有怪物页） | 如实列为最大的洞。要补就得抓单卡页（§195.9 手抄过 `blind` 的稀有度与 Exhaust，全是那一类错） |

顺带修掉两处**矩阵正确、措辞误导**：`bronze_orb` 曾被分到 `bronze_automaton.txt`（那一页里也有一个
Bronze Orb 的 Infobox —— 比报错更糟的形状），`sentry.*` 曾被判"没有 wiki 出处"（主人是
`sentry_1/2/3`，动作 id 的前缀 `sentry` 不是记录名）。

### 215.5 闸门 13 钉住什么

`native/coverage_matrix.py --check`：**盘上的矩阵必须与重新生成的结果逐字节一致**（手改 = 陈旧 = 红）。
`Invoke-Gate` 还要 `MustMatch 'COVERAGE_MATRIX PASS (rows=\\d+, tests=\\d+, fresh)'`。
红的三类：①陈旧；②孤儿/坏声明/偏差表里的 id 不存在/wiki dump 没有主；③**扫描器坏了**
（具名测试少于 500 条，或探针 `spiker`/`chosen`/`standard.hex`/`bash` 扫不到测试）。
③ 是最要紧的一条：扫描器一坏，整页会变成全 `harness`、看起来照样"有证据"。

三条负控都实测过：手改一行 ⇒ 报出"第一处不同在第 84 行"；贴一只 `ghost_slime` ⇒
`monster ghost_slime 不可达`；把 §G 的 `giant_head.glare / count` 改成 `count_drifted` ⇒
`gap 文档里的 giant_head.count_drifted 在内容里不存在`。

### 215.6 数字

* **21/21 闸门绿**（新增第 13 道；后面八道只是编号后移）。单测仍 **900**；四条对拍不变。
* 矩阵 **360 行**：怪 47 / 动作 130 / 卡 51 / 状态 43 / 遭遇 34 / 事件 9 / 遗物 13 / 药水 33。
* `test:` **229** 行、`harness:` **115** 行、**16** 行连 harness 都没有（14 只怪 + 2 个状态）。
* `wiki:` **177** 行（47 怪 + 130 动作）、`spec:` **94** 行、声明过的偏差 **68** 行、未声明的孤儿 **0**。
* 扫描到具名测试 **893** 条、wiki dump **45** 份（6 份是早期副本，页面上列出来了）。

### 215.7 这一节之后，"下一件该干的活"变成可查的

页面的用法写在表头里：按 `WikiVerified = —` 或 `RuntimeTested = —` 排下去就是待办。
现在它指着三件事：**卡牌没有任何 wiki 出处**（51 张）、**14 只怪没有具名测试**、
**药水/事件/遗物的来源只有内容自查**。这三件都不好做，但至少不再是"想不起来"。
'''

port = io.open(ROOT + 'docs/port-plan.md', encoding='utf-8').read()
assert '## §215' not in port
io.open(ROOT + 'docs/port-plan.md', 'a', encoding='utf-8', newline='\n').write(SECTION)
print('port-plan §215 appended')

# ── README ──────────────────────────────────────────────────────────────────────────────────────
readme = io.open(ROOT + 'README.md', encoding='utf-8').read()
pairs = [
    ('（§1–§214，每一轮都留数字、记下被推翻的结论）', '（§1–§215，每一轮都留数字、记下被推翻的结论）'),
    ('**战斗内核 + 运行层 + 内容编译器 + 浏览器前端 + 二十道聚合闸门**',
     '**战斗内核 + 运行层 + 内容编译器 + 浏览器前端 + 二十一道聚合闸门**'),
    ('| `tools/acceptance.ps1` | **聚合验收**：20 道闸门，一道红就整体红 |',
     '| `tools/acceptance.ps1` | **聚合验收**：21 道闸门，一道红就整体红 |'),
    ('| *（可选）Node.js* | 18+ | 只有 20 道闸门里的浏览器测试需要 | <https://nodejs.org> |',
     '| *（可选）Node.js* | 18+ | 只有 21 道闸门里的浏览器测试需要 | <https://nodejs.org> |'),
    ('> 第 13 道闸门会比对它的 sha，陈旧就直接红。', '> 第 14 道闸门会比对它的 sha，陈旧就直接红。'),
    ('地图页（第 16 道闸门的对象，只走图、不结算）', '地图页（第 17 道闸门的对象，只走图、不结算）'),
    ('`sts-wiki-gap.md`（缺口清单，数字由 `native/gap_check.py` 重算） |',
     '`sts-wiki-gap.md`（缺口清单，数字由 `native/gap_check.py` 重算）、'
     '`coverage-matrix.md`（**生成物**：每个实体的 Implemented / RuntimeTested / WikiVerified / '
     'Deviation / Evidence，闸门 13） |'),
]
for old, new in pairs:
    assert readme.count(old) == 1, old[:40]
    readme = readme.replace(old, new)
io.open(ROOT + 'README.md', 'w', encoding='utf-8', newline='').write(readme)
print('README updated')

# ── gap doc §4 ──────────────────────────────────────────────────────────────────────────────────
gap = io.open(ROOT + 'docs/sts-wiki-gap.md', encoding='utf-8').read()
anchor = '* ⚠️ **闸门看不见 wiki**：'
assert gap.count(anchor) == 1
addition = ('* **逐实体的账在 `docs/coverage-matrix.md`（生成物，闸门 13）**：它把"每个实体被验证到哪一步"'
            '写成 360 行 —— `Implemented` / `RuntimeTested`（`test:` 还是只有 `harness:`）/ '
            '`WikiVerified`（`wiki:<dump>` 还是只有 `spec:<TABLE>`）/ `Deviation` / `Evidence`。'
            '本文档 §G、§H 的两张表**被它直接解析**（改了这里而不改内容，那条闸门会点名是哪个 id 漂了）。'
            '`WikiVerified = —` 的那几类就是"还没回到 wiki 页看过"的清单。\n')
gap = gap.replace(anchor, addition + anchor)
io.open(ROOT + 'docs/sts-wiki-gap.md', 'w', encoding='utf-8', newline='').write(gap)
print('gap doc §4 updated')
