"""§344 的文档：ui-state-model 的 G1/G2/G9/G11 关闭 + port-plan §344。"""

import io

DOC = 'docs/ui-state-model.md'
PLAN = 'docs/port-plan.md'


def sub(text, old, new, label, count=1):
    n = text.count(old)
    assert n == count, '%s: 命中 %d 次（期望 %d）' % (label, n, count)
    return text.replace(old, new)


# ── ① §6 缺口表：四条标成已关闭 ────────────────────────────────────────────
t = io.open(DOC, encoding='utf-8').read()

t = sub(t, '''| **G1** | **"这一局结束了"没有内核判据** | 页面在 `fight_end` 看到失败时自己置 `runOver`（`index.html:1329`） | `rd_run_over()` → `0/1` + `rd_run_over_why()` → `0` 战败 / `1` 幕尽 | 小：`RunState` 已有相关事实（health==0 / boss_beaten） |''',
        '''| ~~**G1**~~ | ~~"这一局结束了"没有内核判据~~ | — | **已关闭（§344）**：`rd_run_over()` → `1/0/-1`，`rd_run_over_why()` → `0` 进行中 / `1` 战败 / `2` 通关 / `3` 地图走完了 | 已完成 |''',
        'G1 closed')

t = sub(t, '''| **G2** | **幕尽头没有动作** | 页面按钮只本地置 `runOver` | `rd_run_end_act()`，或在动作表里发一个 kind | 中：要定"幕尽头"是什么状态 |''',
        '''| ~~**G2**~~ | ~~幕尽头没有动作~~ | — | **已关闭（§344）**：`rd_run_end_act()`（`0` 接受 / `-2` 拒绝）。三条前提：没有待决问句 / 脚下节点已结算 / `reachable()` 为空 | 已完成。⚠️ 当前内容里**几乎不可达**（最后一排的唯一前进方向是 Boss 哨兵）—— 见 §6 末尾 |''',
        'G2 closed')

t = sub(t, '''| **G9** | **`restHeal` 的 30% 住在渲染层** | `Math.floor(hpMax*30/100)` | `rd_run_rest_heal()` | 很小，**且是规则外泄**，优先级最高 |''',
        '''| ~~**G9**~~ | ~~`restHeal` 的 30% 住在渲染层~~ | — | **已关闭（§344）**：`rd_run_rest_heal()` | 已完成。⚠️ 它不只是分层问题：`rest_heal()` 还含 `regal_pillow`（+15）与 `eternal_feather`（每 5 张 +3），页面自己算**显示的数字是错的** |''',
        'G9 closed')

t = sub(t, '''| **G11** | **beat kind 13 无 ABI 常量** | 页面 `switch` 落空 ⇒ 静默不播 | 加 `BEAT_DESTROYED = 13` + 页面分支 | 很小，但**漏了就是静默** |''',
        '''| ~~**G11**~~ | ~~beat kind 13 无 ABI 常量~~ | — | **已关闭（§344）**：`BEAT_DESTROYED = 13`，并且有一条**穷尽**判据（`1..=13` 每个都有常量、`14` 不在闭集里） | 已完成。⚠️ 页面**根本不消费 beat**（动画走 `diffObservations`）—— 所以"页面 switch 落空"是本文档当初的推断，真实缺口是"消费者无法命名它" |''',
        'G11 closed')

# ── ② §6 末尾的说明：G2 的可达性 + 一条新观察 ──────────────────────────────
t = sub(t, '''> **G9 / G1 / G11 是"会静默出错"的三条**，其余是"做不好看/做不了"。静默那三条优先。''',
        '''> **G9 / G1 / G11 是"会静默出错"的三条**，其余是"做不好看/做不了"。静默那三条优先。
>
> ### 四条关闭之后的两条观察（§344）
>
> 1. **G9 不只是"分层不好看"**：页面原来自己算 `Math.floor(hpMax*30/100)`，而
>    `RunState::rest_heal()` 还含 `regal_pillow`（+15）与 `eternal_feather`（每 5 张牌 +3）——
>    持那两件遗物时**显示的数字是错的**（显示 +24、实际 +39）。"规则外泄"最终总会变成
>    "两个数"，只是时间问题。
> 2. **SC-02b（幕尽头）在当前内容里几乎不可达**：`reachable()` 在最后一排把 **Boss 哨兵**
>    当成唯一前进方向（`inv:§7.2`：Boss 是 floor 16、在地图之外），所以"真的没事可做"只在
>    **Boss 已倒**时成立 —— 而那时要么换幕、要么就是最后一幕（`Victory` 优先）。
>    `rd_run_end_act()` 仍然值得存在（它是 SC-02b 的内核落点，守卫是"真的没事可做"），
>    但**场景表里那一行应当标成"当前内容不可达"**，而不是假装它在跑。''',
        'section 6 note')

# ── ③ 场景表：SC-12b / SC-02b 的判定式改成内核事实 ────────────────────────
t = sub(t, '''| 5 | **SC-12b** | 局终 | `rd_run_over() == 1`（§6-G1，**尚未导出**） | 节点面板 | `renderNode` | 重开 / 换 seed |''',
        '''| 5 | **SC-12b** | 局终 | `rd_run_over() == 1`（§344 已导出；`rd_run_over_why()` 说为什么） | 节点面板 | `renderNode` | 重开 / 换 seed |''',
        'SC-12b')

t = sub(t, '''| 17 | **SC-02b** | 幕尽头 | `rd_run_in_fight() == 0` 且 `pending == 0` 且 `rd_run_action_count() == 0` 且 `kind >= 0` | 节点面板 | `renderNode` | 页面侧 `end_act`（**无内核动作**，§6-G2） |''',
        '''| 17 | **SC-02b** | 幕尽头 | `rd_run_in_fight() == 0` 且 `pending == 0` 且 `rd_run_action_count() == 0` 且 `kind >= 0`。⚠️ **当前内容不可达**（§6 末尾） | 节点面板 | `renderNode` | `rd_run_end_act()`（§344 起是内核动作） |''',
        'SC-02b')

# ── ④ §2.1 顶栏与 §3.8 篝火：两个字段改成内核导出 ─────────────────────────
t = sub(t, '''| `contentPin` | 8 位十六进制 | 构建时定死 | `rd_content_fingerprint()` | T0 | 与 `packages/sts/out/build.json` 的镜像 sha 同源 |''',
        '''| `contentPin` | 8 位十六进制 | 构建时定死 | `rd_content_fingerprint()` | T0 | 与 `packages/sts/out/build.json` 的镜像 sha 同源 |
| `runOver` | `0/1` | 血量归零 / 幕尽 / 通关 | `rd_run_over()` | T2 | §344：**不要自己记**（曾经是页面的一对模块级变量） |
| `runEndWhy` | `0` 进行中 / `1` 战败 / `2` 通关 / `3` 地图走完了 | 同上 | `rd_run_over_why()` | T2 | 数值是 `RunEnd` 的判别值，**不要重排** |''',
        'top bar run over')

t = sub(t, '''| `restHeal` | `1..` | **无导出**：页面算 `hpMax * 30 / 100` | §6-G9：**规则住在渲染层**，这是最该修的一条 |''',
        '''| `restHeal` | `1..` | `rd_run_rest_heal()` | §344：**已关闭 G9**。它含 `regal_pillow`（+15）与 `eternal_feather`（每 5 张 +3），页面自己算会显示错数 |''',
        'restHeal')
io.open(DOC, 'w', encoding='utf-8', newline='\n').write(t)
print('ui-state-model: G1/G2/G9/G11 closed + scene rows')
