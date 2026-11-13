"""第十五轮 Review 的处置文档：port-plan §368 + README + ui-parity 缺口更新 + 审阅文档结论。"""

import io


def edit(path, old, new, label):
    t = io.open(path, encoding='utf-8').read()
    assert t.count(old) == 1, '%s: 命中 %d 次' % (label, t.count(old))
    io.open(path, 'w', encoding='utf-8', newline='\n').write(t.replace(old, new))


# ── port-plan §368 ─────────────────────────────────────────────────────────
PLAN = 'docs/port-plan.md'
t = io.open(PLAN, encoding='utf-8').read()
assert '## §368' not in t
section = '''

---

## §368 第十五轮 Review 的处置：冻结边界、重复模态、部署边界、SC-02b、存档

审阅原文在 `docs/vibe/Review_35bf81ac_3cc98cb_15_P3_P7.md`（末尾附了我的逐条核实）。
这一节记的是**修了什么、判据是什么**，以及**明确没修**的。

### 368.1 冻结边界（审阅 §2，P1）

**问题**：`blocked` 只作为几个组件的 `busy`/`inert`；`BlessingScene`/`RewardScene`/`EndScene`/
`CombatScreen` 都没收到；`settleDefault()` 不检查；`CombatScreen` 直接调 `GameStore.dispatch`
**完全绕过**。⇒ 横幅写着"界面已冻结"，玩家照样能出牌、能拿奖励、能用默认动作跳过欠账。

**修法**（判据只有一份）：

| 层 | 做法 |
|---|---|
| `RunStore` | 粘性 `frozenReason` + `canMutate()`；**31 个**动作方法全部在函数体第一行过它 |
| `GameStore` | `setDispatchGuard()` —— 冻结时**连 `rd_env_step` 都不调**，返回 `reason: "frozen"` |
| `CombatScreen` | `frozen` prop：不接手势、显示横幅、把 `isFrozen` 当 fatal 处理 |
| `RunApp` | `blocked = violations>0 || frozen`，传给**所有**场景与覆盖层 |

**粘性**是关键设计：`violations` 每帧重算，清空就自动解冻会让玩家在半可信状态里继续操作。
只有"重开一局"（或回档成功）能解。

闸门 43 `ui-freeze`：注入一条违约 ⇒ **24 个入口**（含战斗出牌/结束回合/`fight_end`、奖励四项、
祝福、地图、`settleDefault`、商店、篝火、宝箱、事件、欠账四项、药水两项、幕间、离开、选牌两项）
逐个尝试，全部"被拒绝 + 局面逐字段不变"；撤掉注入后**仍然**冻结；重开才解冻。
证据串：`UI_FREEZE PASS entries=24 refused=24 sticky=1`

### 368.2 重复的遗物模态（审阅 §3，P2）

`RunApp` 里 P4 之前的通用覆盖层（`data-run-overlay`，文案还写着"牌组选择器在 P4"，带一个
`settleDefault()` 按钮）已删除。遗物欠账**只有** `PickupOverlay` 一条路。

### 368.3 `SC-02b` 的身份与继续能力（审阅 §4，P2）

**问题**：`EndScene` 自己把 `data-scene` 算成 `over ? SC-12b : SC-12a` ⇒ `SC-02b` 报成 `SC-12a`，
"继续"按钮也只在 `SC-12a` 时给。当前内容下 `SC-02b` 不可达，所以闸门 34/36 的
`domScene() == scene.base` **从未执行到它**。

**修法**：身份与能力抽成纯函数 `scene.ts::endSceneFor(scene)` → `{ sceneId, kind, canContinue }`。
`SC-02b` 报自己的 id 且 `canContinue: true`（内核动作同样是 `end_act`）。
闸门 33 用**纯函数**钉住三屏（不依赖"某条路径真的走得到"）。

### 368.4 部署边界（审阅 §5，P2）

**问题**（我构造性复现过）：`file.startsWith(DIST)` 不是目录边界 ——
`/../dist-backup/private.txt` 归一化后仍然以 `dist` 开头。

**修法**：`path.relative` 判归属（拒绝 `..` 开头、绝对路径、任何一段 `..`）+ 拒绝 NUL/反斜杠/
坏百分号转义。另外 `cacheControlFor` 改成**只对带 8 位哈希的 assets** 用 `immutable`
（注释里"文件名含 hash"的假设以前没被代码验证）。

闸门 42 的负控从 1 条扩到 6 条（含同前缀兄弟目录、`%2e%2e`、legacy 兄弟、`%zz`），
并断言不带哈希的 assets 不是 immutable。
⚠️ 旧闸门只测了 `/../package.json` —— 它恰好落在 `dist` 之外，所以"越界被拒绝"一直绿着。

### 368.5 存档 / 回档（审阅 §6，发布判断 → 已实现）

默认入口已经切到 `run`，所以"刷新就丢局"从"可以没有"变成"必须有"。

内核早有可信档案（`MAGIC-base64-校验和`，含内容指纹），界面只做搬运：
设置面板里"导出这一局" → 文本域 → 复制 / 粘贴 → "回档"。

* **全有或全无**：坏档案被内核拒绝时，当前这一局**一个字节都不动**（内核先装本地再赋值）；
* **战斗中不能存档**（`CombatState` 不进档案），拒绝**说出原因**；
* 刷新之后没有"局槽"⇒ `importArchive` 先建一个占位局再整体覆盖（档案会完整替换它）；
* 回档**成功**会解除粘性冻结（新状态是内核校验过的档案，不是"违约之后看起来正常了"）。

闸门 44 `ui-archive`：导出 → 刷新 → 导入逐字段相同；乱码/篡改/截断三种坏档案全被拒且局面不变；
战斗中导出被拒且说原因。证据串：`UI_ARCHIVE PASS bytes=822 refused=3 roundtrip=1`

### 368.6 明确没修（审阅 §7）

* **P5b GLB 资产管线**：没有美术与导出工具，只有程序化外观表 + 降级；
* **打赢 Boss → 第二幕的 E2E**：自动出牌策略打不过第 16 层；
* **真机**：移动端结论仍来自 CDP 仿真；
* **回放**：内核导出在，界面未做（优先级低于存档）。

### 368.7 数字

闸门 43 → **44**；`ui-freeze` 24 个入口；`ui-archive` 3 种坏档案；
units 1233、导出 234、四条对拍不动。
'''
io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(t.rstrip('\n') + section)

# ── README：闸门数与缺口 ────────────────────────────────────────────────────
edit('README.md', '**聚合验收**：42 道闸门', '**聚合验收**：44 道闸门', 'readme count')
edit(
    'README.md',
    '''* **存档 / 回档 / 回放**：内核导出齐全，新入口**没有界面**（旧入口有）。见 `docs/ui-parity.md` §2。''',
    '''* **回放**：内核导出齐全，新入口**没有界面**（旧入口有）。**存档/回档已经补上**（设置面板里
  导出/导入；闸门 44），见 `docs/ui-parity.md` §2。''',
    'readme gap',
)

# ── ui-parity：把"没有存档"改成"已有导出/导入，缺回放" ──────────────────────
edit(
    'docs/ui-parity.md',
    '''| **存档 / 回档 / 回放** | `#archiveBox` + `rd_run_archive_*` / `rd_run_restore_from` / `rd_run_replay_*` | 新入口不能导出/恢复一局，也不能看回放 | **已知缺口**。内核导出都在，缺的是界面；`web/` 保留就是这个用途 |''',
    '''| **存档 / 回档** | `#archiveBox` + `rd_run_archive_*` / `rd_run_restore_from` | — | **已补齐**（第十五轮 Review §6）：设置面板里"导出这一局"→ 文本 → 粘贴 →"回档"；闸门 44 守"导出→刷新→导入逐字段相同 + 坏档案被拒且局面不动" |
| **回放** | `rd_run_replay_*` | 新入口不能看回放 | **已知缺口**（优先级低于存档）。内核导出都在 |''',
    'parity archive',
)

# ── 审阅文档：处置结果 ─────────────────────────────────────────────────────
REVIEW = 'docs/vibe/Review_35bf81ac_3cc98cb_15_P3_P7.md'
t = io.open(REVIEW, encoding='utf-8').read()
assert '### 五、处置结果' not in t
result = '''

### 五、处置结果（本轮已落地）

| 序 | 任务 | 结果 | 守它的闸门 |
|---|---|---|---|
| 1 | 统一冻结边界（粘性） | **已修**：`RunStore` 31 个动作全过 `canMutate()`；`GameStore.setDispatchGuard()` 冻结时连 `rd_env_step` 都不调；`CombatScreen` 加 `frozen` prop；`RunApp` 把 `blocked` 传给所有场景 | 43 `ui-freeze`（24 个入口，全部"被拒 + 局面逐字段不变"；撤掉注入仍冻结；重开才解冻） |
| 2 | 删旧 `data-run-overlay` fallback | **已修**：遗物欠账只剩 `PickupOverlay` | 43（`settleDefault` 在冻结下被拒）+ 36（拾取流程） |
| 3 | `serve.mjs` 目录边界 + assets 缓存 | **已修**：`path.relative` 判归属；只对带 8 位哈希的 assets 用 immutable | 42（负控从 1 条扩到 6 条：同前缀兄弟目录 / `%2e%2e` / legacy 兄弟 / `%zz` / 无哈希 assets） |
| 4 | `SC-02b` 身份与继续能力 | **已修**：抽成纯函数 `endSceneFor()`；`SC-02b` 报自己的 id 且能继续 | 33（纯函数，不依赖"这条路径可达"） |
| 5 | 存档 / 导出 | **已实现**（按"正式入口"定位）：设置面板导出/导入，全有或全无，战斗中拒绝并说原因，回档成功解除冻结 | 44 `ui-archive`（导出→刷新→导入逐字段相同；乱码/篡改/截断全拒且局面不动） |

**未修（审阅 §7 的分级建议，已采纳到文档措辞）**：P5b GLB 资产管线、打赢 Boss → 第二幕的
真实 E2E、真机测试、回放界面。`docs/ui-parity.md` §2 与 `README` §10.4 已按"PARTIAL"措辞写清。

**同时修掉一个验收工具自身的坑**：证据数组的收尾 `)) {` 被两次插到数组中段（后面还有条目 ⇒
语法错误），而**陈旧输出让验收看起来还在跑**（`acc.txt` 的 mtime 没变，读到的是上一次的结果，
连"全绿"都是旧的）。已写成幂等脚本 `native/evidence_tail.py` 归位，并把这条教训记在
`port-plan.md` §4 那一类"工具骗人"的形态里。
'''
io.open(REVIEW, 'w', encoding='utf-8', newline='\n').write(t.rstrip('\n') + result)
print('docs written')
