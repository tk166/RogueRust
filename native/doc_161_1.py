"""Append §161.1 to docs/port-plan.md (UTF-8, no BOM, LF)."""
import io

PATH = "docs/port-plan.md"

SECTION = """
---

## 161. 按评审 §六 的顺序做：正确性补强 → 通用决策 → 垂直切片

评审的第六节给了五步。§160 已经吃掉第 1 步的前三件（商店原子性、Eternal Feather、Golden Idol），
这一节从剩下的两件开始，**每修一项就写一节**，不再攒着。

### 161.1 七个 `MAX_POOL` 截断点 → 响亮失败

评审 P1 的原话是"药水、遗物、奖励卡池仍是**静默截断**"。数了一下是 **7 处**，分布在 5 个函数：

| 函数 | 原来 | 现在 |
|---|---|---|
| `stock_shop` | `card_pool.len().min(MAX_POOL)` | `pool_fits(len)?` 后 `len()` |
| `pick_potion` | 三处 `take(MAX_POOL)` / `min(MAX_POOL)` | 同上 |
| `pick_relic_avoiding` | `take(MAX_POOL)` | 同上 |
| `grant_random_cards` | `pool.len().min(MAX_POOL)` | 同上 |
| `roll_reward` | `card_pool.len().min(MAX_POOL)` | 同上 |

新增 `RunError::PoolTooLarge { pool, max }` 与一个 `pool_fits`。**容量还是容量**（不换 `Vec`：
那对无 `std` 的内核是错答案），变的是"超了要红"。

判据 `a_pool_longer_than_the_capacity_is_loud_instead_of_cut`，两半都测：
**恰好 64 仍然能用**（容量不该被误伤）、**65 立刻红并说出长度与上限**。四个入口各测一遍
（`roll_reward` / `pick_relic` / `pick_potion` / `begin_node` 的商店补货）。

负控（`native/negctl_161_pool.py`）：把 `roll_reward` 的守卫删掉**并把循环改回 `.min(MAX_POOL)`**
（只删守卫会越界 panic —— 那是另一条错误路径，会让负控"红得没意义"）。红在
"one card over the cap must be a red, not a silently smaller pool"，正是要的那句。
"""

with io.open(PATH, "rb") as handle:
    raw = handle.read()
assert raw[:3] != b"\xef\xbb\xbf", "the plan is UTF-8 without BOM"
text = raw.decode("utf-8")
assert "### 161.1" not in text, "already appended"
if not text.endswith("\n"):
    text += "\n"
text += SECTION
with io.open(PATH, "wb") as handle:
    handle.write(text.encode("utf-8"))
print("port-plan.md now", len(text.split("\n")), "lines")
