"""§350：P0 交付（UI ABI 审计基线）+ 第 24 道闸门。"""

import io

PLAN = 'docs/port-plan.md'
README = 'README.md'


def sub(path, old, new, label):
    t = io.open(path, encoding='utf-8').read()
    assert t.count(old) == 1, '%s: 命中 %d' % (label, t.count(old))
    io.open(path, 'w', encoding='utf-8', newline='\n').write(t.replace(old, new))


SECTION = """
## §350 新 UI 的 P0：ABI 审计基线（+ 第 24 道闸门）

UI 计划 v1.1 的 P0 交付：**在写任何 UI 代码之前，把"新 UI 依赖的每个导出实际是什么行为"
用真实 wasm 钉下来**。产物是 `docs/ui-abi-audit.md` + `native/ui_fixtures/p0-scenes.json`，
由 `native/ui_abi_dump.mjs` 生成。

### 三个模式

| 命令 | 做什么 | 进闸门 |
|---|---|---|
| `--check` | 契约断言：52 个导出存在、19/148 长度、哨兵、`i32::MIN` 是合法 seed、18 场景 parity | ✅ 闸门 24 |
| `--report` | 用真实 wasm 跑 11 个场景，落**原始 dump**（值就是 wasm 说的，未经解释） | ❌（产物与内容有关） |
| `--check-fixtures` | 盘上的 dump 是否还对得上当前内容镜像 | ❌（手动） |

**为什么 `--check` 与内容无关**：它不读任何具体数值（价目、id），只断言形状与哨兵 ⇒
内容扩充不会让它变红。而 `--report` 的产物**与内容有关**（商店价目、遭遇 id），换内容后必须
重跑，否则审计文档引用的数字过期 —— 这两件事分开，闸门才不会变成内容工作的绊脚石。

### 真实到达的 11 个场景

`SC-00` 无局 / `SC-01` 祝福 / `SC-02` 地图 / `SC-03` 预战斗 / `SC-03b` 战斗中（含运行层事实）/
`SC-04` 奖励 / `SC-05` 商店 / `SC-07` 宝箱 / `SC-08` 事件 / `SC-11a` 遗物欠账 / `SC-12b` 战败。
每个都断言 `resolveScene` 落在**预期的那个** base 场景上。

`SC-12a`（幕通关）**显式标成合成**：要打穿一幕的 Boss，夹具代价太大；由 `--check` 的
18 条合成夹具覆盖，不假装主路径到达过。

### ★ 三个"夹具缺陷伪装成场景不可达"（这一节最值钱）

写这个 dump 时连踩三次，三次都表现为"这个场景走不到"，而**根因全在驱动脚本**：

1. `fight_begin` 之后**立刻** `fight_end` ⇒ 战斗还没结果 ⇒ 没有奖励屏、节点不结算 ⇒
   后续每一步 `rd_run_step` 被 `NodeNotSettled` 拒 ⇒ 商店/宝箱/事件"400 个种子都走不到"；
2. **站在战斗节点上 `begin_node` 什么都不做**（战斗靠 `fight_begin`/`fight_end` 结算）⇒
   "站在未结算节点就先 `begin_node`"这个分支**空转 26 跳**；
3. 落到商店那一格后**立刻被 `leave` 掉** ⇒ 搜索永远"没到达"。

⇒ 一般教训：**"场景不可达"这个结论，必须先排除"驱动脚本走错了"。** 这三条都不是内核缺陷。

顺带一条：`--report` 还抓到 `SC-05/SC-08` 被判成 `SC-12b` —— 因为行走途中输掉一场战斗，
局已经结束，而 **`runOver` 压过一切 `pending`**。分类器是对的，夹具错了（该跳过那个种子）。

### 对计划 v1.1 的两条事实更正（审计时确认）

| 计划的说法 | 实际 |
|---|---|
| "`enemy_name` 可能是展示文本…无可靠 ID 时用占位" | `rd_env_enemy_name_*` 返回**定义 id**（`acid_slime_m`）⇒ 可直接作资源键 |
| "`definitionId?: string` 仅在有可信来源时填充" | `rd_env_card_name_*` 返回**card definition id** ⇒ 可以直接填 |

⇒ AssetRegistry **零新增 ABI**。

### 诚实清单（审计文档 §4 的摘要）

**未验证**：`SC-12a` 真实快照、A20 双 Boss 的真实流程（只有单元测试）、`rd_env_choice_*`
（要触发药水/卡牌问句）、`beats_dropped > 0` 的降级、Beat kind 1–13 全量（实测只有 3 条）。
**确实缺失**：跨动作稳定的卡牌实例 id（首期按 `handSlot + revision` 处理）。

### 闸门 24

`native/ui_abi_dump.mjs --check`，`-MustMatch 'UI_ABI_CHECK PASS (exports \\d+, runObs 19,
combatObs 148, content 0x[0-9a-f]{8}, scenes 18)'`。

为什么它必须是一道闸门：审计文档引用的每条行为**只在一个地方被机器验证**。少了它，
删掉一个导出、改掉一个哨兵、把 `i32::MIN` 当成"没有局"，都不会有闸门红。

### 数字

闸门 23 → **24**；`rd-core 819 / rd-run 225 / rd-wasm 189`、units **1233**（本轮不动 Rust）；
导出 234（不变）；四条对拍不动。
"""

p = io.open(PLAN, encoding='utf-8').read()
assert '## §350' not in p
io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(p.rstrip('\n') + '\n' + SECTION)

# README：闸门数 23 → 24，并补一行 P0 产物
sub(README, '| `tools/acceptance.ps1` | **聚合验收**：23 道闸门（含 `coverage-matrix`、`state-fields` 与 `ui-state`），一道红就整体红 |',
    '| `tools/acceptance.ps1` | **聚合验收**：24 道闸门（含 `coverage-matrix`、`state-fields`、`ui-state` 与 `ui-abi`），一道红就整体红 |',
    'README gates')
sub(README, '**`ui-state-model.md`**（**场景 × 层 × 字段 × 接口**',
    '**`ui-abi-audit.md`**（**新 UI 的 P0 契约基线**：52 个导出的实测行为、11 个真实场景的原始 dump、未验证清单；闸门 24 由 `native/ui_abi_dump.mjs --check` 守）、**`ui-state-model.md`**（**场景 × 层 × 字段 × 接口**',
    'README audit doc')
print('port-plan §350 + README')
