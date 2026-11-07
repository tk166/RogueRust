"""§284 文档：更正 §283 里那条假偏差 + 记录真根因 + 新判据。"""
import io

PLAN = 'D:/Vibe/sts-tui/docs/port-plan.md'
GAP = 'D:/Vibe/sts-tui/docs/sts-wiki-gap.md'
README = 'D:/Vibe/sts-tui/README.md'

DOC = """
---

## §284 更正 §283：那条"已知偏差"是**假的**，真根因是"目标恒空"被静默吞掉

§283 结尾我写了两条偏差，其中一条是：

> **`Confused` 每回合都挂一次**。原本想"首回合才挂"（计数器判第一次 `TurnStarted`），
> 但状态触发器的程序里 `combatantCounter(sel.source)` 读到的是 0（触发帧的 source 不是状态
> 拥有者），条件恒真 —— 那比"每回合都挂"更糟。

**这条是错的，而且诊断方式也是错的**（我推断了一个数，没有去验它）。这一节把它查清并修掉。

### 284.1 真正的因果链（三步，全是我的，不是内核的）

| # | 事实 | 我当时的判断 |
|---|---|---|
| 1 | `snecko_eye` 的 `applyStatus` 目标写成了 **`sel.eventTarget`**，而 `TurnStarted` **没有目标** ⇒ 解析出空集 ⇒ 什么都不做 | 没看出来；因为同一段的 `drawCards`（用 `sel.source`）成功了，症状只是"抽了 7 张但没 Confused" |
| 2 | 我改用 `sel.source` 后**仍然红** | 于是猜"计数器恒 0"，写成偏差 |
| 3 | 真因是 **2 根本没生效**：内容脚本用 `if not any(...)` 做幂等，第二次运行时整块被跳过，改动从未落进镜像 | 没有去看构建产物里的实际结构 |

`UsesStacks: false` 那条也是**假**的：`push_new_status` 根本不读三轴，
把 `UsesStacks` 改回 `false` 后判据依然绿。§283 里那两条"坑"的说明都按事实重写过。

### 284.2 真正的隐患，以及修法

参考语义**是对的**：没有目标的选择器解析出空集不是错误（`dealDamage(eventTarget)` 在目标
已死时也是空集）。所以**不能**在核心里把它变成报错 —— 那会误伤正常路径。

但"在一个**永远不会有**目标的事件里用 `eventTarget`"是**内容的静态错误**，可以在内容门里拦。
新增 `[6g] targetless triggers`：

```
无目标事件 = TurnStarted / TurnEnded / FoeDowned
遍历每条 状态/遗物 的触发器程序；
若出现 sel.eventTarget ⇒ 响亮失败（并指出是哪条状态、哪段程序）
```

今天 **44 段触发器程序、0 处违规**。负控把 `snecko_eye` 改回 `sel.eventTarget` ⇒ 立刻红。

### 284.3 用判据钉住"计数器真的被读到"

"读数是 0"虽然是假诊断，但**没有判据**这件事是真的 —— 所以补一条行为判据：

`Snecko Eye` 的战斗里，把 Confused 摘掉（模拟 `Orange Pellets`），再推进一回合 ——
**它不该回来**。若触发器的 `combatantCounter(sel.source)` 恒为 0，条件恒真、第二回合会再挂，
这条判据就会红（负控把条件改成 `== 999` 也红）。

于是 §283 那条**偏差被撤销**：`Confused` 现在**只在首回合挂一次**，与 wiki 一致。

### 284.4 留给"工具"的一条教训

"幂等脚本跳过整块"这类问题会让人**对着没生效的改动调试**，而症状与"改动是错的"完全一样。
这一节的做法：改完内容**先去构建产物里看那一块的结构**（`reader.py` 的 `_rows` / `--find`），
再跑判据。§283 的脚本已改成"直接重写整块"而不是"没有才加"。

### 284.5 账

判据：内容门 `[6g]`（44 段程序）+ `snecko_eye_draws_two_more_and_confuses_at_the_start` 的
第二半（摘掉后不回来）。负控 2 条全 RED（`sel.eventTarget` 回潮 / 条件永假）。
`rd-core` 797 / `rd-run` 152 / `rd-wasm` **130**；21/21 绿。
"""


def main():
    plan = io.open(PLAN, encoding='utf-8').read()
    io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(plan.rstrip('\n') + '\n' + DOC)

    g = io.open(GAP, encoding='utf-8').read()
    old = '''| Confused 的"何时挂" | 开局挂一次；`Orange Pellets` 清掉后不再回来 | **每回合都挂一次**（不叠加，所以只有"清掉后会回来"这一处偏差） | **偏差**：首回合判定写在触发器里读不到 source 计数器（恒 0），与其假装在判，不如显式偏差 |'''
    new = '''| Confused 的"何时挂" | 开局挂一次；`Orange Pellets` 清掉后不再回来 | **开局挂一次**（`snecko_eye_turns` 计数器判第一次 `TurnStarted`） | 一致 —— §283 记的"每回合都挂"是**错记**，真因是 `sel.eventTarget` 在无目标事件里恒空 + 脚本幂等守卫让修正没落进镜像（见 §284） |'''
    assert g.count(old) == 1
    g = g.replace(old, new)
    io.open(GAP, 'w', encoding='utf-8', newline='\n').write(g)

    r = io.open(README, encoding='utf-8').read()
    r = r.replace('（主计划 §1–§283）', '（主计划 §1–§284）')
    io.open(r and README, 'w', encoding='utf-8', newline='\n').write(r)
    print('§284 doc + gap correction + README')


main()
