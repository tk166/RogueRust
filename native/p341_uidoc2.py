"""§341 收尾：§8 分类修正、G16 关闭、§7 加"场景夹具"要求、清掉 lib.rs 的 `122` 旧注释。"""

import io

DOC = 'docs/ui-state-model.md'
LIB = 'kernel/rd-wasm/src/lib.rs'


def sub(text, old, new, label, count=1):
    n = text.count(old)
    assert n == count, '%s: 命中 %d 次（期望 %d）' % (label, n, count)
    return text.replace(old, new)


t = io.open(DOC, encoding='utf-8').read()

# ── ① §8：三行非文本长度移出"文本 `_len/_into`"表 ──────────────────────────
t = sub(t, '''| `rd_run_observe_len` | — | ⚠️ 是 `rd_run_observe_len()`，**不是**文本 | §3.0 |
''', '', 'drop run observe_len row')
t = sub(t, '''| `rd_env_observe_len` | — | ⚠️ 是 `rd_env_observe_len()`，**不是**文本 | §0.3 |
''', '', 'drop env observe_len row')
t = sub(t, '''| `rd_env_pile_len` | — | ⚠️ 是 `rd_env_pile_len(zone)`，**不是**文本 | §2.1 |
''', '', 'drop pile_len row')

# §8.3 补全（三行都在这里，读者不会再以为它们是字符串 getter）
t = sub(t, '''| `rd_env_observe_len()` | 向量长度（148）。页面**必须**读它，不许写死 |''',
        '''| `rd_run_observe_len()` | 运行层向量长度（19）。`rd_run_observe(i)` 按它越界 |
| `rd_env_observe_len()` | 战斗向量长度（148）。页面**必须**读它，不许写死 |
| `rd_env_pile_len(zone)` | **计数**（不是文本）：`zone` 的牌数。`zone 3` = 问句的来源牌区 |''',
        'observe_len rows in 8.3')

# ── ② §6：G16 关闭（加一行，并标成"已关闭"）────────────────────────────────
t = sub(t, '''| **G15** | **`E.obs(140..147)` 恒 `-1`（保留）** | — | 3D **不要**读这 8 格 | 0（约定） |''',
        '''| **G15** | **`E.obs(140..147)` 恒 `-1`（保留）** | — | 3D **不要**读这 8 格 | 0（约定） |
| ~~**G16**~~ | ~~"有没有一场正在打的战斗"没有内核判据~~ | — | **已关闭（§341）**：`rd_run_in_fight()` → `1/0/-1` | 已完成 |

> **G16 为什么曾经是缺口**：`pending` 在"战斗前"与"战斗中"都是 `0`；`node_resolved()` 战斗中仍是
> false；`rd_env_done()` 在**没有会话**时返回 `1`（"结束了"），所以它不能反过来说"有没有战斗"。
> 于是"未开始"只能是页面自己记的 `mode` ⇒ 场景表不是状态的函数，而是**历史的函数**。
> `rd_run_in_fight()` 读的是 `fight_begin` 提交点写、`fight_end` 清的那一格 —— 与"战斗中不许
> 存档/回放"用的是同一个字段。''', 'G16 closed')

# ── ③ §7：加"场景夹具"要求（Review 3.3 的建议，最小版本）────────────────────
t = sub(t, '''反证（必须能红）：往本文里塞一个**不存在**的名字（`rd_run_` + 随便几个字母），检查器必须报错；
从白名单里删一条、同时删掉本文对它的提及，检查器必须报"未登记"。''',
        '''反证（必须能红）：往本文里塞一个**不存在**的名字（`rd_run_` + 随便几个字母），检查器必须报错；
从白名单里删一条、同时删掉本文对它的提及，检查器必须报"未登记"。

### 7b. 名字对了不等于场景对了（八轮 Review 3.3 的边界）

`ui_state_check.py` **只**证明"文档点名的导出都存在、每个导出都被登记"。它**不**证明：

* 参数/返回值/哨兵/长度单位对不对；
* 某个字段是否被写在**正确的表格行**里（只要名字在文中出现过就算登记 —— §8 的分类错位
  就是这么混过去的）；
* 场景谓词是否互斥、是否可达。

所以 §1 那张表还欠一份**可执行的**东西：19 个场景各一份 `snapshot` 夹具，断言
`classifyScene(snapshot)` **唯一命中**；多重命中或零命中都要**报错**，不是"取第一个"。
（`web/ui_panels.js` 的 `describe()` 已经是这张表的实现，`web/ui_test.mjs` 用字面量 snapshot
逐状态测 —— 但那是**页面**的版本，不是"这张表"的版本。3D 重写时应当先写 `classifyScene`，
再写渲染。）''', 'section 7b')

io.open(DOC, 'w', encoding='utf-8', newline='\n').write(t)

# ── ④ lib.rs 的旧注释：122 → 表达式（Review 3.5）────────────────────────────
u = io.open(LIB, encoding='utf-8').read()
u = sub(u, '''// The observation vector (`docs/spec/env-abi.md` §4) — 12 + 5 + 4×8 + 4×5 + 10×4 + 5 + 8 = 122''',
        '''// The observation vector (`docs/spec/env-abi.md` §4) — 12 + 5 + 6×8 + 6×5 + 10×4 + 5 + 8 = 148
//
// ⚠️ 这里原来写着 `4×8 + 4×5 … = 122`，而 `MAX_ENEMY_SLOTS` 从 4 涨到 6 之后表达式已经变成 148。
// 表达式一直是对的，只有注释在说谎 —— 而"这条向量有多长"正是调用方唯一要读的数。
// 唯一的权威是 `rd_env_observe_len()`；这条注释只是给人看的摘要，改常量时**必须**一起改。''',
        'lib.rs header comment')
u = sub(u, '''    /// The full 122-slot vector. Unoccupied slots are `-1`, not `0` (`env-abi.md` §4: 0 is a real
    /// value — "0 block", "0 stacks" — so it cannot mean "absent").''',
        '''    /// The full vector (`rd_env_observe_len()` slots — 148 today). Unoccupied slots are `-1`,
    /// not `0` (`env-abi.md` §4: 0 is a real value — "0 block", "0 stacks" — so it cannot mean
    /// "absent").''', 'lib.rs compute_observation comment')
io.open(LIB, 'w', encoding='utf-8', newline='\n').write(u)
print('ui-state-model: 8.3 / G16 / 7b ; lib.rs: 122 comments')
