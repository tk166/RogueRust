"""§224 docs."""
import io

ROOT = 'D:/Vibe/sts-tui/'

SECTION = '''
---

## §224 新载体：开战给**敌人**挂状态（`bag_of_marbles` 终于能用）

§222 试过 `bag_of_marbles`（wiki："At the start of each combat, apply 1 Vulnerable to **ALL
enemies**"），照着 `oddly_smooth_stone` 写成 `RelicEffect::StartCombatStatus` —— 而那一族状态是加在
**英雄**身上的（`apply_combat_bonus` 只认 `hero`）⇒ 英雄自己变易伤，Boss 战打不过。
**单元测试一条都没红**，是 `ACT1_SLICE` 抓到的（报的是"boss: the cursor is on kind undefined"，
离原因很远）。缺的不是状态，是**目标**。

### 224.1 载体

```text
RelicEffect::StartCombatStatusOnEnemies(&'static str, i32)
CombatBonus { … , enemy_statuses: [Option<CombatStatus>; MAX_COMBAT_STATUSES], enemy_status_count }
```

三处必须一起动，编译器会把两处漏掉的逼出来（`RelicEffect` 的三个 `match` 是穷尽的）：

| 位置 | 语义 |
|---|---|
| `push_relic` | 新变体**不是**"拿到就生效"（和 `StartCombatStatus` 同一档） |
| `end_of_combat` | 也**不是**回合末效果 |
| `combat_bonus` | 落到 `enemy_statuses`，合并规则与英雄那张表相同（两件遗物给同一条状态要相加） |

`rd-wasm` 的 `apply_combat_bonus` 负责真正落地：从战斗状态的 `turn_order` 里挑出 `team_id ==
"enemy"` 的单位逐个 `ApplyStatus`（**不另存一份敌人名单**）；场上没有敌人时记一条会话错误
（"开战状态没有目标"）而不是静默。

### 224.2 两个"看起来绿"的陷阱（都写进注释了）

* **`is_empty` 必须看第二张表**：漏了它，`apply_combat_bonus` 会在开头早退，遗物**静默不生效**。
  第一版判据是在"两件遗物同时戴"的场景里断言 `!is_empty()` —— 那时英雄表非空已经让它为假，
  于是这个 bug **看不出来**。现在有单独一条"只戴给敌人那件"的用例，负控（去掉
  `enemy_status_count`）红在那条上。
* **重复的 `match` 臂**：§221 那条 `bag_of_marbles => StartCombatStatus(...)` 还在时，新臂永远
  走不到（Rust 不报"不可达模式"，因为它是**先匹配到**而不是不可达）—— 判据的第一条断言
  （"敌人遗物不许给英雄加状态"）当场红在 `left: 2 right: 1`。

### 224.3 判据与负控

`the_two_combat_start_carriers_land_on_the_right_side`（rd-run）：
① 没遗物 ⇒ `is_empty`；② 只戴 `oddly_smooth_stone` ⇒ 英雄 1 条、敌人 0 条；
③ 再戴 `bag_of_marbles` ⇒ 英雄**仍** 1 条（不是 2）、敌人 1 条且是 `standard.vulnerable`；
④ 只戴 `bag_of_marbles` 时 `is_empty` 必须为假。

两条负控都实测：去掉 `is_empty` 里的 `enemy_status_count` ⇒ 红在"relic silently does nothing"；
把新臂改回英雄那张表 ⇒ 红在 `left: 2 right: 1`。

### 224.4 数字

* **21/21 闸门绿**（`ACT1_SLICE PASS`、四个对拍不变），单测 **913**（710 + 110 + 93，+1 条）。
* 遗物 **15**（`bag_of_marbles` 现在**真的能用**：§221 加它时只是内容行，§222 试挂过一次、
  被切片挡回，这一节把它接上）；镜像 **84,588 B** 不变（遗物行没变，只有运行层的实现变了）。
* 矩阵 387 行、具名测试 915。
'''

port = io.open(ROOT + 'docs/port-plan.md', encoding='utf-8').read()
assert '## §224' not in port
io.open(ROOT + 'docs/port-plan.md', 'a', encoding='utf-8', newline='\n').write(SECTION)
print('port-plan §224 appended')

readme = io.open(ROOT + 'README.md', encoding='utf-8').read()
old = '（§1–§223，每一轮都留数字、记下被推翻的结论）'
new = '（§1–§224，每一轮都留数字、记下被推翻的结论）'
assert readme.count(old) == 1
io.open(ROOT + 'README.md', 'w', encoding='utf-8', newline='').write(readme.replace(old, new))
print('README updated')
