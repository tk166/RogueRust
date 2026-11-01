"""Append §171 to docs/port-plan.md (UTF-8, no BOM, LF)."""
import io

PATH = "docs/port-plan.md"

SECTION = """
---

## 171. 外部评审第三轮（续）：哈希容量的边界与"第二条路"

§170 修了会话生命周期的四条。这一节收尾剩下两条 P1 —— 一条是"错误被合法值掩盖"，一条是
"同一件事有两条路，其中一条没有容量契约"。

### 171.1 P1-4：8 KiB 的边界，先量再谈

`run_hash` 在规范文本超出 `MAX_TEXT`（8192 B）时返回 `None`，而三个调用点都把它写成
`unwrap_or(0)`。`0` 是一个**合法可比较的值**，所以两个都溢出的状态会互相"匹配" —— 这正是评审说的
"错误不能用某个合法数据值掩盖"。

评审同时指出："能否在正常内容达到该上限尚未独立验证。"**这句话才是重点**：仓库里只有
`the_text_is_canonical_and_not_truncated`，用的是 `run()` 那副 10 张牌 —— 它证明不了后盘。

**先量。** 新增 `the_largest_legal_run_fits_the_hash_buffer`：牌位全部塞满、每个 id 都取
`ID_CAP`（40）长、遗物 24 件、药水 5 瓶、金币 `i32::MAX`、Ascension 20 —— 那是**类型**允许的最大
文本，内容以后怎么改都超不过它。**实测 4186 B / 8192 B = 51%。**

于是**判据改了**：我第一版写的是"两倍余量"，一跑就红（4186 × 2 = 8372 > 8192）。真实余量是 1.96 倍，
所以我不能留一个自己都不成立的判据 —— 改成"至少 1.5 倍余量"，并把**实测值与它的含义**写进注释：

> 文本的约 90% 是 id 文本（60 张牌 + 24 遗物 + 5 药水）。**把 `MAX_RUN_DECK` 或遗物容量翻倍，
> 就会溢出。**

**再把失败传播出去。** `RunSession` 多一格 `hash_failed`，唯一的取哈希入口
`RunSession::state_hash()` 在 `None` 时置它；`script_fill` 见到它就**拒绝导出**（"导不出脚本：
这一局的状态文本超出了哈希缓冲"），回放的比对也把"算不出"与"不一致"分成两种结果
（前者 `-2` 并说明，后者才是分叉）。

⚠️ 诚实交代**没测到的那一半**：`hash_failed` 与回放的 `state_hash() == None` 分支对**合法状态不可达**
（就是上面量出来的 51%）。而且回放会 `rd_run_start` 建**新**会话，`hash_failed` 一开始就是 false ——
所以回放侧的这条分支连"置标记"都进不去。测试测的是**接线**（置标记后导出拒绝、局面不变），不是
"哪天真的会响"。它存在的意义是：容量哪天被改大，它响，而不是两个溢出的状态互相点头。

### 171.2 P1-5：删掉第二条路

`rd_run_script_into(ptr)` 往调用方指针里写 `script_len()` 个字节，**没有容量参数** —— `unsafe` 契约
是"你自己留够地方"。对 Rust 调用者成立；对这个 ABI 存在的理由（wasm/JS）就是一把对着脚的枪。

但真正的判据不是"加个参数"，而是：**它和 `fill`/`buf`/`capacity` 做同一件事，而且唯一的用户是内核
自己的测试**。页面走的是 `fill`。所以正确的动作是**删掉** `into` 与 `len`，让测试改走页面那条路
（`fill` → 问容量 → 按长度读模块自己的缓冲区）。脚本接口现在只有一条路。

顺带证实了 `smoke.mjs` 那个"手抄两次"的设计是对的：删导出之后，`REQUIRED` 里那两个名字必须同步删，
否则闸门会报"缺导出"。

### 171.3 判据与负控

| 测试 | 断言 |
|---|---|
| `the_largest_legal_run_fits_the_hash_buffer`（`rd-run`） | 最大类型态文本 < 8192 B；≥1.5 倍余量；且 > 4 KiB（否则它量的不是最大态）；`println!` 打出实测值与百分比 |
| `an_unavailable_hash_is_refused_not_treated_as_zero`（`rd-wasm`） | 置 `hash_failed` 后 `script_fill` 返回 `-2`、错误文本提到"哈希缓冲"、局面不变 |

负控（`native/negctl_170.py`，五条全 RED）：

```text
[RED] P1-2 重入守卫        -> a_second_fight_begin_is_refused…            caught
[RED] P1-3 script_fill 守卫 -> the_script_abi_refuses_mid_fight…           caught
[RED] P1-3 replay 守卫      -> the_script_abi_refuses_mid_fight…           caught
[RED] P1-4 hash_failed 守卫 -> an_unavailable_hash_is_refused…             caught
[RED] P1-1 回滚函数体       -> fail_begin_restores_the_snapshot…           caught
```

### 171.4 数字

`rd-run` 99 → **100**，`rd-wasm` 59 → **60**，合计 810 → **812**；20/20 闸门全绿；
`-UnitsFloor` 810 → 812。导出 **-2**（`rd_run_script_len` / `rd_run_script_into` 删除），
`smoke.mjs` 的 `REQUIRED` 同步减二，页面侧 `ex.*` 对账仍 **149** 条（那两个名字页面本来就没调）。

### 171.5 这一轮评审的收尾状态

| 项 | 状态 |
|---|---|
| P0-1 回放期间的别名 | 已修（§170.1），注释里的 soundness 理由也改了 |
| P1-1 `fight_begin` 不是事务 | 已修（§170.2），含一个被借用检查器拦下的真隐患 |
| P1-2 重复开战 | 已修（§170.3） |
| P1-3 脚本接口没有 `in_fight` 守卫 | 已修（§170.4） |
| P1-4 哈希容量失败降级成 0 | 已修（§171.1），边界**量过** |
| P1-5 `script_into` 没有容量参数 | 已修（§171.2），删掉第二条路 |
| P2-1 回放破坏当前局 | 有意设计，**已写进文档**（§163.3 / §171.6） |
| P2-2 回放不校验返回码 | 范围选择，**已写进文档**（§171.6） |
| P2-3 每场战斗的 `Box::leak` | 有意保留；§170.2 让牌组项**自己拥有**字符串，泄漏量略增但换掉了"`FightPlan` 与 `RunState` 别名"这个隐患 |

### 171.6 把两条 P2 的范围写清楚

* **回放会覆盖当前局**（`P2-1`）。`rd_run_replay_from` 用 `rd_run_start` 从头部重开，这是**有意**的：
  回放的本职是"复现这一局"，不是"在旁边验算"。页面在拒绝/分叉时都会重画，玩家看得见自己站在哪。
  要"不改当前局的验算"得另开一个 wasm 实例 —— 记在 §168.7 那类候选里，不在这一轮做。
* **回放只验状态轨迹，不验返回码**（`P2-2`）。脚本记的是动作，判据是每一步之后的 `run_hash`；
  一个"当时成功、现在被拒且状态没变"的动作会被哈希判成一致。这是**范围选择**：要验 API 语义就得把
  返回码写进脚本（格式 `RDR2`），那是另一件事。今天的取舍是"状态对了就算对"，因为状态才是玩家能看见的。

### 171.7 下一节

`docs/spec/` 的 19 份规格书还没做过 §169 那种体检（`run-layer.md` / `ui-plan.md` 会随实现漂）。
按用户的意思，这类脚手架文档留到项目收尾时统一处理，避免反复修改 —— 记在这里，不排进下一轮。
"""


def main():
    with io.open(PATH, "rb") as handle:
        raw = handle.read()
    assert raw[:3] != b"\xef\xbb\xbf", "the plan is UTF-8 without BOM"
    text = raw.decode("utf-8")
    assert "## 171." not in text, "already appended"
    if not text.endswith("\n"):
        text += "\n"
    text += SECTION
    with io.open(PATH, "wb") as handle:
        handle.write(text.encode("utf-8"))
    print("port-plan.md now", len(text.split("\n")), "lines")


if __name__ == "__main__":
    main()
