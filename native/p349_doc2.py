"""§349 的 port-plan 章节 + 第十一轮 Review 的本地复核意见。"""

import io

PLAN = 'docs/port-plan.md'
REVIEW = 'docs/vibe/Review_7d37d6f_11_UI_Readiness.md'


def sub(path, old, new, label, count=1):
    t = io.open(path, encoding='utf-8').read()
    n = t.count(old)
    assert n == count, '%s: 命中 %d 次（期望 %d）' % (label, n, count)
    io.open(path, 'w', encoding='utf-8', newline='\n').write(t.replace(old, new))


SECTION = """
## §349 A20 双 Boss 的身份窗口 + 文档同步 + 复合场景（第十一轮 Review）

第十一轮是"UI 就绪性"审查：结论是 **GO for 新 UI 架构，NOT YET for 冻结全部 ABI**。四条发现全部成立。

### P1-1：A20 第三幕的"上一只"与"下一只"

`boss_enemy_id` 只看"`last_encounter` 是否落在本幕 Boss 池里"。而 A20 第一只 Boss 倒下后：

```rust
if self.at_least(A_DOUBLE_BOSS) && self.bosses_fought == 0 {
    self.bosses_fought = 1;
    self.resolved = [0; 2];   // 节点重新开放
    return;                   // 不换幕、不清 last_encounter
}
```

⇒ **第二只还没掷**（要到下一次 `fight_begin`），而 `last_encounter` 仍是**第一只** ——
页面在"第二场开打前"报的是上一只。**"上一只 Boss 的身份"与"即将挑战的 Boss 的身份"被合并了。**

修法：把时间语义拆开，三条判据（**顺序有意义**）：

| 时刻 | 判据 | 回答 |
|---|---|---|
| 正在打 | `in_fight` | 就是 `last_encounter` |
| 双 Boss 之间（第一只已倒、第二只没掷、**还没通关**） | `!in_fight && !boss_beaten && bosses_fought == 1` | **未知**（空串） |
| 其余（含最后一幕 Boss 已倒的通关屏） | 落在本幕池里 | `last_encounter` |

⚠️ `boss_beaten` 必须排在"双 Boss 之间"**前面**：第二只倒下之后 `bosses_fought` 仍然是 1，
但那时我们**知道**它是谁（刚打完的那只）。写成 `bosses_fought == 1` 而不排除 `boss_beaten`，
通关屏会退化成"本幕 Boss 已击败" —— 负控 ② 钉的就是这一条。

### P1-2：代码改了、注释没改

四处陈旧文字（"比没写更糟"：下一个人会照注释理解实现）：

1. `run.rs` 的 `boss_enemy_id` 文档仍写"本幕的 Boss 池 → **第一条遭遇**"（与实现相反）；
2. `ui_panels.js` 的 SC-00 注释仍写 `noRun` 来自 seed 哨兵；
3. `ui-state-model.md` §1 / §3.2 / §5 三处仍写 `rd_run_seed() == i32::MIN`；
4. 同一份文档 §3.3 的 `bossName` 仍写"无导出 / 页面写死 Slime Boss"。

⇒ 全部改掉，并在 §3.3 补上**三种时间语义**与"进幕即定 vs 开战才掷"的已知偏差。

### P2-A：`classifyScene` 把两层合成一个 id

`SC-11a/11b` 是**模态覆盖层**，而 `classifyScene` 返回"第一个命中的 id" ⇒ "奖励屏 + 遗物选牌
欠账"只报 `SC-11a`，底下那一屏（`SC-04`）丢了。DOM 面板"用覆盖层暂时替换正文"是合理权衡，
但 3D 需要**复合**状态。

⇒ 新增 `resolveScene(s)` → `{ base, overlays[], unknownPending }`，**保留** `classifyScene`
（旧页面用它）。两者共用同一份 `RAW`，判据不会漂。

### P2-B：`bossName` 过早变成显示名

`runSnapshot()` 直接把 Boss 的 id 交给 `displayName()`，于是下游只能拿到格式化后的名字，
不能按 id 绑定美术/音效/本地化 —— 与 §0.5"内核给 id、显示层给名字"的边界不一致。
⇒ 快照**两个都留**：`bossId`（原样 id）+ `bossName`（标签）。`ui_test` 用静态检查钉住
"`bossId:` 必须真的从 `rd_run_boss_id_*` 读"。

### 判据与负控

| 判据 | 钉住什么 |
|---|---|
| `the_boss_id_names_the_actual_boss_not_the_pool_head`（扩写） | 池里每个 Boss 都 nameable / 池外 `None` / **A20 三种时间语义各一行** / `i32::MIN` 是合法 seed |
| `ui_test` 的 `resolveScene` 段 | "奖励 + 遗物选牌"两层同时存在（`base: SC-04`、`overlays: [SC-11a]`）；表外 pending 带出那个值 |
| `ui_test` 的 `bossId` 静态检查 | 快照必须留 id，不能只留名字 |

负控 **4/4**（`native/p349_negative.py`）：去掉 A20 窗口判据 / 判据里去掉 `boss_beaten` /
`resolveScene` 把覆盖层算进 base / 快照只留名字。

### ⚠️ 一个自己造的事故（记下来）

负控脚本末尾我写了"把页面原样写回"的一行：

```python
io.open(PAGE, 'w', ...).write(io.open(PAGE, ...).read())
```

`open('w')` **先截断**，所以它读到空、写回空 —— `web/index.html` 被清成 0 字节（2629 行）。
恢复靠 `git checkout -- web/index.html` + 重打 P2-B 补丁。**"为了保险"加的一行，恰好是唯一
破坏数据的一行**；负控脚本的收尾只该做 `finally` 里那一件事。

### 数字

`rd-wasm 189`、`rd-run 225`、`rd-core 819`、units **1233**；导出 234（不变）；
四条对拍不动；`WEB_SMOKE` / `UI_RENDER` / `MAP_RENDER` / `BROWSER_TEST` PASS；23/23 闸门。
"""

p = io.open(PLAN, encoding='utf-8').read()
assert '## §349' not in p
io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(p.rstrip('\n') + '\n' + SECTION)

RECHECK = """

---

# 附：本地复核意见（第十一轮，`7d37d6f` 上逐条核实）

> 记号：**✅ 成立** = 代码确认；**⚠️ 部分** = 现象真实但描述需修。

## A. 四条发现全部成立

| 报告项 | 复核 | 本地证据 | 处理 |
|---|---|---|---|
| **P1-1** A20 第二只 Boss 未选时仍报第一只 | **✅ 成立** | `mark_boss_beaten` 在 A20 第一只倒下后 `bosses_fought = 1` 并**不清** `last_encounter`；而 `boss_enemy_id` 只看"是否落在本幕池里" | 拆成三种时间语义，双 Boss 之间返回**未知**（§349） |
| **P1-2** 文档/注释未同步 | **✅ 成立（四处）** | `run.rs` 的 `boss_enemy_id` 文档仍写"第一条遭遇"；`ui_panels.js` SC-00 注释仍写 seed 哨兵；`ui-state-model` §1/§3.2/§5 三处；§3.3 `bossName` 仍写"无导出" | 全部改掉，并补上三种时间语义与"进幕即定"偏差 |
| **P2-A** `classifyScene` 把两层合成一个 id | **✅ 成立**（设计权衡，非缺陷） | 覆盖层按定义叠在底屏上 | 新增 `resolveScene()`，保留 `classifyScene` |
| **P2-B** 快照把 Boss id 过早变成名字 | **✅ 成立** | `runSnapshot()` 的 `bossName` 直接过 `displayName()` | 快照加 `bossId`，`bossName` 只作标签 |

## B. 我同意报告的两条"边界声明"

1. **门禁 23 不是 ABI 兼容验证** —— 它只做名字双向对账。报告没有把它误标成"完整验证"，
   这一点值得记：§7d 已经写了"这套夹具没证明什么"，同理"这道闸门没证明什么"也该写。
2. **"进幕即定 Boss"是独立的玩法保真度项目**，不该为了 UI 显示去改选 Boss 的 RNG 时机
   （会牵动 `corpus` / 存档 / 回放）。已记进 `docs/sts-wiki-gap.md` 的已知偏差。

## C. 关于"GO / NOT YET"的判断

同意。新 UI 的第一层不该是"直接在 3D 组件里散布 `rd_*` 调用"，而应是一层薄 Adapter：
`GameSnapshot / SceneResolution / LegalAction / GameBeat`。本轮的 `resolveScene` 与 `bossId`
就是这一层的第一块（都是**加**在现有结构上，没有动 DOM 版行为）。

## D. 顺带记一个自己造的事故

负控脚本末尾那行"把页面原样写回"（`open('w')` 先截断）把 `web/index.html` 清成了 0 字节。
恢复靠 `git checkout` + 重打补丁。**"为了保险"加的一行，恰好是唯一破坏数据的一行。**

> **一句话**：四条全部成立且已修；P1-1 是"上一只"与"下一只"被合并，P1-2 是"改了代码没改注释"。
> 同意报告的分期结论：可以开始新 UI 架构，但不要把 234 个导出立刻冻结成 UI v1。
"""

r = io.open(REVIEW, encoding='utf-8').read()
io.open(REVIEW, 'w', encoding='utf-8', newline='\n').write(r.rstrip('\n') + '\n' + RECHECK)
print('port-plan §349 + review recheck appended')
