"""Append §161.2 to docs/port-plan.md (UTF-8, no BOM, LF)."""
import io

PATH = "docs/port-plan.md"

SECTION = """
### 161.2 评审要的 L2 层：不变量，而不是更多"典型案例"

评审第四节第 1 条说得很直白：`tools/acceptance.ps1` 的 clippy 闸门只要求退出成功，所以
"测试还在、属性没了、总数仍过门槛"还能再出现。它建议四层，最缺 L2（性质测试）。
这一节先落两条**最便宜、也最贴近已发生 bug** 的不变量。

#### (a) 拒绝不改任何东西 —— 包括 RNG

`RunState` 派生 `Copy + PartialEq + Eq`，而且整局就是这一个结构体（`rng` 是它的字段）。
所以判据能写成最硬的一句：**调用前后整个 `RunState` 相等**。

这比"逐字段比较"强：漏比一个字段正是 §160 的 P0（金币变了、牌组没变、没人发现）。
逐字段的清单会过期，`==` 不会。

覆盖的拒绝种类：相位不对（无商店买卡/无篝火休息/无奖励领奖）、目标不对（不在图上的节点）、
容量满（§160 的 P0 在这一层被抓住）、重复领取、重复购买同一货位。

⚠️ 一处细节：判据用 `assert!` 而不是 `assert_eq!` —— 后者会把两个完整 `RunState`（地图就 40 行）
打两遍，而值得读的只有"哪一个动作"。**可读性也是断言的一部分**：一份读不下去的失败信息等于没有。

#### (b) 同一种子 + 同一动作序列 ⇒ 同一局

`rd-core` 有逐字节的哈希对拍、地图有 `same_seed_same_map`，但"整局走同一条路"此前只有浏览器
soak 在间接覆盖。判据直接比 `Vec<RunState>`，所以**一次多余的 RNG 抽取也会红**。

固定策略：每一步取**第一条能进的边**，然后按节点类型结算（Rest→rest / Treasure→open_chest /
Shop→leave / 其它→mark_resolved），走六层。`assert_ne!(trace(101), trace(102))` 是**反面控制**：
证明这个比较不是恒真。

⚠️ 写的时候踩了一个小坑：`enter_node` 收的是**全局节点号**，不是"本行第几个"，所以扫 `0..3`
一步都进不去（红在"the fixture must actually walk somewhere"——这条自检正是为这种错准备的）。
"""

with io.open(PATH, "rb") as handle:
    raw = handle.read()
assert raw[:3] != b"\xef\xbb\xbf", "the plan is UTF-8 without BOM"
text = raw.decode("utf-8")
assert "### 161.2" not in text, "already appended"
if not text.endswith("\n"):
    text += "\n"
text += SECTION
with io.open(PATH, "wb") as handle:
    handle.write(text.encode("utf-8"))
print("port-plan.md now", len(text.split("\n")), "lines")
