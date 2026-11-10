"""§349 文档同步：把四处陈旧文字改成真实接口（第十一轮 Review P1-2）。

代码改了、注释/表格没改，比没写更糟 —— 下一个人（或 Agent）会照注释理解实现。四处：

| 位置 | 旧 | 新 |
|---|---|---|
| `ui-state-model` §1 SC-00 | `rd_run_seed() == i32::MIN` | `rd_run_exists() == 0` |
| `ui-state-model` §3.2（未开局） | 同上 | 同上 |
| `ui-state-model` §5（三类权威事实） | 同上 | 同上 |
| `ui-state-model` §3.3 `bossName` | "无导出 / 写死 Slime Boss" | `rd_run_boss_id_*`（**开战前未知**） |

外加两处**新写**的说明：A20 双 Boss 的时间语义（§349）与 `resolveScene`（§349 P2-A）。
"""

import io

DOC = 'docs/ui-state-model.md'


def sub(path, old, new, label, count=1):
    t = io.open(path, encoding='utf-8').read()
    n = t.count(old)
    assert n == count, '%s: 命中 %d 次（期望 %d）' % (label, n, count)
    io.open(path, 'w', encoding='utf-8', newline='\n').write(t.replace(old, new))


# ── ① §1 SC-00 ─────────────────────────────────────────────────────────────
sub(DOC, '''| 1 | **SC-00** | 未开局 | `rd_run_seed() == i32::MIN`（`R.obs(0)` 也是 `i32::MIN`） | 节点面板 | `renderNode` | `rd_run_start(seed, asc)` → SC-01 |''',
    '''| 1 | **SC-00** | 未开局 | `rd_run_exists() == 0`（§348 —— **不要**用 `rd_run_seed() == i32::MIN`：那是一个合法 seed） | 节点面板 | `renderNode` | `rd_run_start(seed, asc)` → SC-01 |''',
    '§1 SC-00')

# ── ② §3.2 未开局 ─────────────────────────────────────────────────────────
sub(DOC, '''全部 run 侧导出返回 `-1` / `i32::MIN`。**3D 里这是一个真实的场景**（标题画面），
不需要任何新接口；判据是 `rd_run_seed() == i32::MIN`。''',
    '''全部 run 侧导出返回 `-1` / `i32::MIN`。**3D 里这是一个真实的场景**（标题画面），
判据是 **`rd_run_exists() == 0`**（§348）。⚠️ **不要**用 `rd_run_seed() == i32::MIN`：
`i32::MIN` 是一个**合法 seed**，那一局会被误判成未开局。''',
    '§3.2 SC-00')

# ── ③ §3.3 bossName ───────────────────────────────────────────────────────
sub(DOC, '''| `bossName` | **无导出** | 页面写死 `"Slime Boss"`（§6-G5） |''',
    '''| `bossId` | 敌人 id / **空串** | `R.txt(boss_id)` = `rd_run_boss_id_len` / `rd_run_boss_id_into` | §345 起有导出；**§348 起只在"已经确定"时给值**：站在 Boss 节点上还没开打 ⇒ 空串（不猜池子第一条） |
| `bossName` | 标签（`displayName(bossId)`） | 同上 + `RD_UI.displayName()` | §349（P2-B）：快照**两个都留** —— 只留名字的话，下游没法按身份绑定美术/音效 |

> **§349：Boss 身份的三种时间语义**（第十一轮 Review P1-1）。"上一只 Boss"与"即将挑战的 Boss"
> 不是同一个问题，A20 第三幕会把它们分开：
>
> | 时刻 | `rd_run_boss_id_*` |
> |---|---|
> | 正在打 | 就是这一场（`last_encounter`） |
> | **双 Boss 之间**（第一只已倒、第二只还没掷、还没通关） | **空串**（不知道） |
> | 最后一幕 Boss 已倒（通关屏） | 还是它 —— 刚打完的那只 |
>
> ⚠️ 与 StS1 的**已知偏差**：原版**进幕时**就定下本幕 Boss（地图顶上画着它），我们是**开战时**
> 才掷。所以"站在 Boss 节点上还没开打"时我们只能显示"本幕 Boss"。见 `docs/sts-wiki-gap.md`。''',
    '§3.3 boss fields')

# ── ④ §5 三类权威事实 ─────────────────────────────────────────────────────
sub(DOC, '''   * **有没有局**（`rd_run_seed() == i32::MIN`）；''',
    '''   * **有没有局**（`rd_run_exists() == 0`，§348）；''',
    '§5 existence')

# ── ⑤ §1 表头：加一句 resolveScene ────────────────────────────────────────
sub(DOC, '''> `web/ui_test.mjs` 有 **18 个夹具**，每个断言"命中预期的那一个"+"恰好命中一个"（覆盖层例外）。
> 下面每一行的判定式就是数组里那条 `test`。''',
    '''> `web/ui_test.mjs` 有 **18 个夹具**，每个断言"命中预期的那一个"+"恰好命中一个"（覆盖层例外）。
> 下面每一行的判定式就是数组里那条 `test`。
>
> **§349（P2-A）**：`classifyScene()` 返回**一个** id，但覆盖层是**叠在**底屏上的。3D 要用
> `resolveScene(s)` → `{ base, overlays[], unknownPending }`：`classifyScene` 只报 `SC-11a` 时，
> `resolveScene` 会同时给出 `base: "SC-04"`。两者共用同一份 `RAW`，判据不会漂。''',
    '§1 resolveScene note')
print('§349: ui-state-model synced (SC-00 ×3, bossName, resolveScene)')
