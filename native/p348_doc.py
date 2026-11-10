"""§348 文档：四条发现的处理 + P2-3 的证据边界（写清"没证明什么"）。"""

import io

PLAN = 'docs/port-plan.md'
DOC = 'docs/ui-state-model.md'
GAP = 'docs/sts-wiki-gap.md'


def sub(path, old, new, label):
    t = io.open(path, encoding='utf-8').read()
    assert t.count(old) == 1, '%s: 命中 %d' % (label, t.count(old))
    io.open(path, 'w', encoding='utf-8', newline='\n').write(t.replace(old, new))


# ── ① ui-state-model §7b：补"证据边界"（P2-3）────────────────────────────
sub(DOC, '''⇒ 一般教训：**"优先级 + 兜底"这种结构，兜底不能手写否定式，要由构造保证。**''',
    '''⇒ 一般教训：**"优先级 + 兜底"这种结构，兜底不能手写否定式，要由构造保证。**

### 7d. 这套夹具**没有**证明什么（§348，第十轮 Review P2-3）

包装层给每条基础场景自动加上"前面没人命中"，而 `scenesMatching()` 检查的正是这个**已经互斥化**
的结果 —— 所以"恰好命中一个"**大部分是构造的数学性质**，不是对 `RAW` 里业务条件的独立证明。

它证明了：

* 18 个夹具各自落在**预期的那个**场景（顺序对了）；
* 覆盖层真的与底屏共命中；
* 顺序被字面量钉住（改一行就红）；
* 表外的 `pending` 落到 `SC-??` 且说得出口（§348）。

它**没有**证明：

* 真实 WASM 状态一定会产生这些夹具里的组合（夹具是**手写的**快照，不是采集来的）；
* 某个字段被页面读对了（那是 `ui_test` 的 `cell-for-cell` 段与浏览器判据的事）；
* `RAW` 里每条业务条件本身是对的（那要靠面板测试 + 负控，以及"真实状态采集"——**还没做**）。

⇒ 下一步（真做 3D 时）：从宿主里**采集**少量真实快照（未开局 / 战斗前 / 战斗中 / 战斗后 /
宝箱叠遗物领取 / Boss 节点 / A20 第三幕），跑同一套 `classifyScene`。**不要**为临时 DOM 版
做像素级回归体系。''', 'section 7d')

# ── ② wiki-gap：Boss 进幕即定 vs 开战才掷（已知偏差）──────────────────────
sub(GAP, '''⚠️ 与 **StS 2** 的差异（未证实 StS 1 如此）''',
    '''⚠️ **已知偏差（§348）**：原版在**进幕时**就定下本幕 Boss（地图顶上画着它）；我们是**开战时**
才从本幕 Boss 池里掷（`RunStream::Combat`）。所以 `rd_run_boss_id_*` 在"站在 Boss 节点上、
还没开打"时返回**空串**（诚实地表示"还不知道"），页面显示"本幕 Boss"；打完之后才给真名。
把"进幕即定"搬过来会改 RNG 消耗顺序（`corpus` / 存档 / 回放都对它敏感），所以记在这里，
不在 UI 这一轮动。
⚠️ 与 **StS 2** 的差异（未证实 StS 1 如此）''', 'boss timing deviation')

# ── ③ port-plan §348 ─────────────────────────────────────────────────────
SECTION = """
## §348 第十轮 Review 的四条：Boss 身份、门禁豁免、seed 哨兵、未知 Pending

| 发现 | 我的核实 | 处理 |
|---|---|---|
| **P1-1** `rd_run_boss_id_*` 取本幕 Boss 池第一条，不是本局实际那只 | **成立，是我 §345 的实现错误** | 改成"只回答 `last_encounter` 落在本幕 Boss 池里的那一只"，否则空串 |
| **P1-2** `ui_state_check` 的 `KNOWN_ABSENT` 里还留着已经导出的 `rd_run_over` | **成立** | 删掉那条，并加一条"删掉真导出必须报 MISSING"的负控 |
| **P2-1** `noRun` 用 `i32::MIN` 当哨兵，而它是一个合法 seed | **成立** | 新增 `rd_run_exists()`；页面改用它 |
| **P2-2** `SC-02` 无条件兜底使 `SC-??` 不可达 | **成立** | 兜底要求 `pending === 0`；`SC-??` 给一份**显式**的未知状态面板 |
| **P2-3** "唯一命中"是构造性质，不是独立证明 | **成立** | 不改代码，在 `ui-state-model.md` §7d 写清"这套夹具没证明什么" |

### P1-1：为什么旧判据必然通过

旧实现取池子第一条，而旧判据只断言"三幕的 id 互不相同" + 写死 act 1 = `slime_boss` ——
**取第一条恰好满足这两条**。新判据直接测那个函数：

* 本幕池里**每一个** Boss 都 nameable（`slime_boss` / `the_guardian` / `hexaghost` …）；
* 池外的一律 `None`：普通遭遇、**别幕**的 Boss、空串；
* ABI 三态分清：`-1` 没有局 / `0` 有局但**还没打 Boss**（不猜）/ `>0` 长度。

⚠️ 写这条判据时立刻抓到自己的一个错：`map_or(-1, ..)` 把"还不知道"报成了"没有局"。

### 顺带记一条已知偏差

原版在**进幕时**就定下本幕 Boss（地图顶上画着它）；我们是**开战时**才掷。所以站在 Boss 节点上
还没开打时，页面只能显示"本幕 Boss"（查询返回空串），打完才有真名。把"进幕即定"搬过来会改
RNG 消耗顺序（`corpus` / 存档 / 回放都对它敏感）⇒ 记进 `docs/sts-wiki-gap.md`，不在 UI 这轮动。

### P1-2：豁免变成漏洞的形状

`KNOWN_ABSENT` 的语义是"文档**明说**它不存在"。`rd_run_over` 在 §344 导出之后，那一行就从
**待补项**变成了**豁免** —— 于是误删导出时检查器仍然通过，而"接口删除必须让文档检查失败"
正是这道闸门的主要目的。

新加的负控是**删掉一个真导出**（而不是塞一个假名字）：前者证明"删除会让闸门红"，后者只证明
"拼错会被抓"。

### P2-2：未知 Pending 必须显性化

兜底原来无条件 ⇒ `SC-??` 不可达 ⇒ 将来内核新增一个 `Pending`，页面会静默画成普通地图。
现在兜底要求 `pending === 0`，表外的值落到 `SC-??`，面板写"内核给的待决值 99 不在场景表里"。
夹具断言 `classifyScene === "SC-??"`、`scenesMatching` 为空、面板里**写得出那个值**。

### 判据与负控

| 判据 | 钉住什么 |
|---|---|
| `the_boss_id_names_the_actual_boss_not_the_pool_head`（rd-wasm） | 池里每个 Boss 都 nameable / 池外 `None` / ABI 三态 / `i32::MIN` 是合法 seed |
| `ui_test` 的 `unknown pending` 段 | `pending=99` ⇒ `SC-??` + 显式面板 |
| `ui_state_check`（闸门 23） | 文档点名的导出都存在；**删掉真导出**会红 |

负控 **4/4**（`native/p348_negative.py`）：Boss id 退回"取池子第一条" / **删掉 `rd_run_over`
导出** / `rd_run_exists` 退回 seed 哨兵 / 兜底退回无条件。

⚠️ 负控第一版有两条不合格，原因值得记：③ 把"**通过**的断言注入测试" —— 注入了也不红，
因为注入的东西是对的；**负控必须弄坏被测代码，不能弄坏"检查"**。

### 数字

`rd-wasm 189`、`rd-run 225`、`rd-core 819`、units **1233**（判据重写，条数不变）；
导出 233 → **234**；四条对拍不动；`WEB_SMOKE` / `UI_RENDER` / `BROWSER_TEST` PASS；23/23 闸门。
"""

p = io.open(PLAN, encoding='utf-8').read()
assert '## §348' not in p
io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(p.rstrip('\n') + '\n' + SECTION)
print('§7d + wiki-gap 偏差 + port-plan §348')
