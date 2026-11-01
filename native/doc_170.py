"""Append §170 to docs/port-plan.md (UTF-8, no BOM, LF)."""
import io

PATH = "docs/port-plan.md"

SECTION = """
---

## 170. 外部评审第三轮：WASM 会话生命周期那一圈

第三份评审（`docs/vibe/Review_07c24a0_5c467b6.md`）的范围是 §161.10–§169。它的总判断是
"**底层规则的验证已经较强，但新的 WASM Session/ABI 生命周期仍可绕过或破坏这些契约**"，不给 P0/P1
写"已复现"，只做静态分析。我逐条对源码核实：**P0 与五条 P1 全部成立**。这一节修前四条（P0-1、
P1-1、P1-2、P1-3），P1-4/P1-5 留下一节。

### 170.1 P0-1：回放期间两个 `&mut` 同时活着

`rd_run_replay_from` 把 `run_slot().as_mut()` 绑在循环**外面**（为了写 `replaying`），然后在循环里
调 `rd_run_step` / `rd_run_begin_node` / …… —— 每一个都再取一次槽；而三条**拒绝分支**（记录格式坏、
种类不认识、参数不是整数）仍在用外面那个绑定。两个 `&mut` 指向同一个 `RunSession`，按别名模型是 UB。

更要紧的是它让一条**注释变成假的**：`lib.rs` 的槽注释一直写着"**没有导出会重入另一个导出**，
所以 `static mut` + 单访问器是 sound 的"——回放就是重入，而这句话正是"别名无害"的**理由**。

修法：外面那个绑定删掉。`replaying` 在一个立刻结束的作用域里设；三条拒绝分支改用**已有的**
`session_clear_replay(checked, idx)`（顺带删掉三处重复赋值）；比对哈希用自己的短借用。两条注释
（`lib.rs::slot()` 与 `run.rs::run_slot()`）改成新规则：

> **不许把槽的 `&`/`&mut` 拿过一次导出调用。** 借、用、放、再调用。

`rd_run_replay_from` 是唯一允许重入的地方，它现在就这么写；`src/run.rs` 里那行注释把这条规则钉在
循环开口处，下一个人照抄时看得见。

### 170.2 P1-1：`fight_begin` 不是事务

`in_fight = true` 写在**六条可失败步骤之前**（本幕遭遇池缺失、池为空、选遭遇、摇战斗种子、
`build_session_at`、`apply_combat_bonus`）。最后一条在 `install_session` **之后**才失败 —— 于是
函数返回 `-2`，槽里却留着一场**没有遗物加成的半初始化战斗**，而 `in_fight` 卡在 true。

卡住的 `in_fight` 不是审美问题：`rd_run_archive_fill` 会一直拒绝，而玩家**根本没有一场仗可以打完**
—— 与 §164.3 是同一类 bug（那一次是回放没清标记，被浏览器闸门抓到）。

修法：三个标记改到**提交点**写；可失败段整段收进一个块，失败就用 `RunState: Copy` 的整结构体快照
回到进函数那一刻（连"选遭遇已经消耗的随机数"一起还回去）；已经装上的战斗会话一并丢弃。

⚠️ 这里撞出一个**真隐患**，不只是借用检查器的脾气：`DeckEntry<'static>` 原来直接借
`RunId::as_str()`，那是指进 `RunState` 自己的存储 —— 也就是说 `FightPlan` 与 `RunState` 一直是
**别名**，而"回滚 = 覆写 `RunState`"会把战斗正在读的字节改掉。借用检查器拒绝编译，正好替我们拦住了
这个错误。改法：牌组项**拷贝出自己的字符串**再 leak（每次开战多几个小分配，代价与 `build_session`
本身同一量级，也就是 P2-3 那个 leak 的来源）。

### 170.3 P1-2：不拒绝重复开战

战斗进行中 `node_resolved()` 仍是 false（要到 `fight_end` 才结算），所以"这个节点已经结算过了"
**放行**重复调用：它会重新摇遭遇（烧掉一个 `Combat` 随机数）、再 leak 一份牌组、并且
`install_session` **覆盖**槽里正在打的那一场。实际效果是"站在战斗节点上反复按开打可以重摇遭遇"。

修法：入口 `if session.in_fight { fail(…) }`。页面因为"成功后立刻重渲染"挡住了双击，所以这不是
页面可利用的漏洞；但回放、RL 环境、测试都能踩 —— **ABI 契约不能指望调用者的 UI 习惯**。

### 170.4 P1-3：脚本接口没继承存档的守卫

§161.10 学过一次："战斗中不许存档"不能由页面的 `mode` 独占。存档在 ABI 层挡住了 `in_fight`；
脚本导出没有，回放更没有 —— 而回放会 `rd_run_start` **直接毁掉进行中的一局**。
两处都补上同一条守卫（回放的守卫在**解析之前**，所以一段头部合法的脚本也会先被拒）。

### 170.5 判据：全部绕开 UI 直接调 ABI

评审最锋利的一句是过程性的：这五条 P1 全落在闸门盲区 —— **没有一道闸门会绕开页面直接调 ABI，
也没有一道做故障注入**（像素门自检除外）。所以新增的三条测试都直接驱动导出：

| 测试 | 断言 |
|---|---|
| `a_second_fight_begin_is_refused_and_the_fight_in_progress_survives` | 第二次开战返回 `-2`；整局**相等**（含随机流计数）；战斗会话还在、英雄血量没被重设；日志**多一条**尝试记录（`log` 在动手之前调，这是 §163 懒上戳的前提），且它未上戳 |
| `a_refused_fight_begin_never_leaves_the_run_in_a_fight` | 两条**可达**的拒绝（没有节点、节点已结算）之后 `in_fight` 仍为 false、分层标记没漏、整局相等 |
| `the_script_abi_refuses_mid_fight_without_the_page` | 战斗中 `script_fill` 与 `replay_from` 都 `-2`、错误文本说明原因、局面与战斗都没动、`replay_checked/diverged` 不残留陈旧读数 |
| `fail_begin_restores_the_snapshot_and_clears_the_tier_flags` | 回滚**机制**本身：模拟走了一步随机数 + 三个标记，`fail_begin` 之后整局回到快照、标记清零、错误写入 |

**负控**（`native/negctl_170.py`，脚本自己改源码、跑一个测试、再还原）：

```text
[RED] P1-2 重入守卫        -> a_second_fight_begin_is_refused…          caught
[RED] P1-3 script_fill 守卫 -> the_script_abi_refuses_mid_fight…         caught
[RED] P1-3 replay 守卫      -> the_script_abi_refuses_mid_fight…         caught
[RED] P1-1 回滚函数体       -> fail_begin_restores_the_snapshot…         caught
```

### 170.6 ★ 明确说清楚"没被验证"的那一半

`fight_begin` 里"**建好战斗之后才失败**"的路径（本幕池缺失、池子选不出、遗物加成失败）由**内容
决定**，本仓库现有的内容走不到它们。所以：

* 它们由**构造**保证 —— 标记在提交点写、任何失败都回到快照，而不是靠"我记得写了"；
* 回滚函数本身有判据（上表最后一条）；
* 但**没有一条测试会让那三条路径真的失败**。这就是评审要求写明的"未验证项"，写在这里而不是
  留给下一个读者去猜。

### 170.7 数字

`rd-wasm` 55 → **59** 个测试，合计 806 → **810**；20/20 闸门全绿；`-UnitsFloor` 806 → 810。
`smoke.mjs` 仍 149 条导出（这一节没有新增/删除导出）。

### 170.8 下一节

评审剩下的两条 P1：

* **P1-4**：`run_hash` 的 8 KiB 上限失败被 `unwrap_or(0)` 变成一个**合法可比较的值**（两个都溢出的
  状态会"匹配"）。要做两件事：**证明边界**（最大合法局的文本长度 vs `MAX_TEXT`，今天没人量过），
  以及把失败传播成响亮拒绝而不是 0。
* **P1-5**：`rd_run_script_into(ptr)` 与 `fill/buf/capacity` 是同一件事的第二条路，且**只有测试在用**
  —— 删掉它，让脚本接口只剩一条路。

P2 里唯一值得当天做的是**把范围写进文档**：回放覆盖当前局是有意设计（`P2-1`），
且它只验状态轨迹、不验返回码（`P2-2`）。
"""


def main():
    with io.open(PATH, "rb") as handle:
        raw = handle.read()
    assert raw[:3] != b"\xef\xbb\xbf", "the plan is UTF-8 without BOM"
    text = raw.decode("utf-8")
    assert "## 170." not in text, "already appended"
    if not text.endswith("\n"):
        text += "\n"
    text += SECTION
    with io.open(PATH, "wb") as handle:
        handle.write(text.encode("utf-8"))
    print("port-plan.md now", len(text.split("\n")), "lines")


if __name__ == "__main__":
    main()
