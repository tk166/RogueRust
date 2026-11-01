"""Append §163 to docs/port-plan.md (UTF-8, no BOM, LF)."""
import io

PATH = "docs/port-plan.md"

SECTION = """
---

## 163. 回放：动作序列 + 每步哈希

REVIEW §六 第 4 步的另一半：**"版本化快照 … 外加动作序列和每步哈希。刷新后能继续；同一回放能复现
关键状态。"** §161.9 做了快照（一行文本），这一节做**动作序列**。

### 163.1 先补 `run_hash` —— 它在注释里活了很久

`rd-run/src/lib.rs` 从第一天就写 "step-wise `run_hash` determinism"，而它**只存在于注释里**。
没有指纹，"同一串动作之后局面相同"这句话就只能靠 `PartialEq` 一次性比整个结构体：能说"不一样"，
说不出**从第几步开始不一样** —— 而那正是唯一有用的信息。

`rd-run/src/hash.rs`：一局的**规范文本**（`key=value`、`\\n` 分隔）交给 `rd_core::hash::sha256`。
用 `rd_core::writer::TextWriter` 而不是自己拼字符串，理由与 `rd-core` 的战斗指纹同一条：**格式就是
契约**，两份手搓的实现迟早不一致。

覆盖：种子/等级/楼层/游标/血/金/幕/待决/已结算位图/牌组/遗物/药水/掉率/稀有度偏移/三条 `?` 房计数/
**七个随机流计数**/商店货架（含买走的空格）/奖励屏/事件/上一场遭遇/开局两次祝福/两个后续动作/整张地图
（**每一行的每一个槽位**，含被剪掉的）。
不覆盖：回放日志（宿主产物）、`error` 字符串（诊断）—— 与 `beats` 同类：记的是"发生过什么"。

判据 `the_same_state_hashes_the_same_and_a_change_moves_it`：**逐字段各改一处、哈希必须变**
（gold / health / deck / relics / potions / node），外加一条
`the_rng_counters_are_in_the_fingerprint` —— 少一个计数，之后的每个随机都错位，而**局面看起来一模一样**。

### 163.2 日志与回放：**懒上戳**，这样不必改 19 个导出

每个会改运行层的导出在**动手之前**调一次 `log(kind, a, b, text)`；`log` 顺手把**上一条**记录的哈希
补上（此刻的状态正是"上一次调用之后"）。于是：

* 不需要每个导出都从 `finish` 回来（`rd_run_step` 就不是）；
* 不需要 19 处"调用后再算一次哈希"的样板。

⚠️ 代价是**每一条会改状态的调用都必须被记录**，否则"上一条之后的哈希"会把它的效果算进去，而回放里
没人做这件事。第一版只记了"结算动作"，于是 `rd_run_fight_begin`（它写 `last_encounter`，进指纹）成了
漏网的那一个 —— 第 4 步就对不上。现在 `fight_begin` 与 `grant_potion` 也进脚本。

脚本是**一行**文本（`;` 分隔、`RDR1,seed,asc;` 开头），一行一步：
`kind,a,b,hash16,text`。哈希是 `run_hash` 的前 8 字节 —— 逐步比对只关心"变了没"，整条 64 字符的
十六进制只出现在错误信息里。

`rd_run_replay_from` 从头部记录的 `(seed, asc)` **重新开一局**，然后逐条调用**同一个导出函数**
（回放不重写规则：接受与拒绝都由导出自己决定），每条之后算哈希并比对，**返回第一个不一致的步号**：

```text
0         每一步都对上了
n > 0     第 n 步之后局面不同（n 从 1 开始）
-2        脚本读不懂 / 无法回放
```

### 163.3 一场战斗**不回放**，只回放它的**结果**

`CombatState` 没有反序列化，而且一场战斗是**玩家的出牌**，不是运行层的动作。所以脚本里记的是
`fight_end` 的**结果**：`a = 英雄剩余血量`，`b` 低两位是档位（精英/Boss）、高位是结果（1 胜 / 2 负 /
0 未决）。

为此把 `rd_run_fight_end` 的尾巴抽成 `apply_fight_outcome(session, hero_hp, result, elite, boss)` ——
**真打**与**回放**调的是同一个函数。第一版回放假定"记下来的战斗都是赢的"，第 4 步立刻红：录制那次
`result = 0`（没有奖励），回放却发了奖励。

⚠️ 这条偏差写明：**回放复现的是运行层，不是战斗**。要"Boss 战打到一半刷新还能继续"，缺的是
`CombatState` 的解析器，不是这一节。

### 163.4 判据：三条，其中两条是**伪造**

`a_recorded_run_replays_step_by_step_and_a_tampered_one_names_its_step`：

1. 真跑一小段（祝福 → 8 个节点，按类型结算：战斗 `begin`+`end`、篝火 `rest`、商店 `leave`、
   宝箱 `open`+`leave`、`?` 房 `choose`），导出脚本，回放 ⇒ `0`，`replay_checked == 步数`，
   并且回放前后的 `run_hash` **相同**；
2. **改掉第 3 步记录的哈希** ⇒ 返回 `3`，`replay_checked == 2`（前两步确实验过）；
3. **改掉第 2 步的参数** ⇒ 返回 `> 0`；
4. 垃圾头部 / 不认识的 kind ⇒ `-2` / 报第 1 步。

"回放通过了"是没用的断言 —— 只有**伪造的脚本被抓住、并且指出是哪一步**才算。

### 163.5 数字

- `rd-run` +3（哈希三条），`rd-wasm` +1（回放四条合一）。
- 导出 +5（`rd_run_script_len/into`、`rd_run_replay_from`、`rd_run_replay_checked/diverged`），
  `smoke.mjs` 对账 **147** 条。
- 聚合验收 **19/19**；单测 796 → **800**。

### 163.6 下一节

页面上的"回放"按钮（现在脚本只能从 ABI 取，`browser_test` 能用但玩家不能）；关键路径的真实指针点击
（CDP `Input.dispatchMouseEvent`）；内容版本指纹（现在只会在进战斗时以 `UnknownCard` 报错）。
"""


def main():
    with io.open(PATH, "rb") as handle:
        raw = handle.read()
    assert raw[:3] != b"\xef\xbb\xbf", "the plan is UTF-8 without BOM"
    text = raw.decode("utf-8")
    assert "## 163." not in text, "already appended"
    if not text.endswith("\n"):
        text += "\n"
    text += SECTION
    with io.open(PATH, "wb") as handle:
        handle.write(text.encode("utf-8"))
    print("port-plan.md now", len(text.split("\n")), "lines")


if __name__ == "__main__":
    main()
