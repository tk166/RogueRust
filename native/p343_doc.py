"""§343 的 port-plan 章节 + wiki-gap 收尾。"""

import io

PLAN = 'docs/port-plan.md'
GAP = 'docs/sts-wiki-gap.md'


def sub(text, old, new, label, count=1):
    n = text.count(old)
    assert n == count, '%s: 命中 %d 次（期望 %d）' % (label, n, count)
    return text.replace(old, new)


SECTION = """
## §343 删卡服务：**每家店只能删一次**

第九轮 Review 的复核里查出来的一条（报告没提）。wiki.gg · The Merchant：
*"Card Removal Service — Can only be used **once per Shop**. Its price starts at 75 Gold and
increases by 25 each time it is bought at a shop."* fandom 同句。

这两句话是**两件事**，而 §159 只做对了一半：

* **价格**按 `removed_cards` **跨店累计** +25 —— 早就对了；
* **每家店一次**从来没实现 ⇒ 能在同一家店里连删三张（75 → 100 → 125），而 StS 只给一次。

### 字段与它的邻居

`removed_this_shop: bool` —— 布尔而不是计数：一家店只允许一次，"现在几次"是个不存在的问题。
它在 `enter_shop` 里清，于是"换一家店又能删"是自动的。

⚠️ **与 `removed_cards` 的分工必须写清**：那个是**服务涨价**（跨店累计），这个是**本次访问的
次数上限**。合成一个字段会让"删过之后价格涨了"与"这家店不能删了"变成同一个数 —— 而
判据里恰好有两条分别钉这两件事。

### 页面：又一个"启用的死按钮"

`ui_panels.js` 的商店面板里，"删一张牌"原来只看 `removePrice > gold`。规则加上之后，
它会在额度用完时仍然**启用**，点下去内核报 `RemovalUsed` —— 那正是本项目最恨的形态。

所以导出 `rd_run_removal_available()`（`1` 能 / `0` 这家店删过了 / `-1` 没有局），
按钮的可用性**只看它**。

**为什么不复用价格**（让 `rd_run_remove_price()` 返回 `-1`）：价格那一格要显示"75 金"，
把"不可用"塞进同一个数，页面就会把 `-1` 印成价格 —— §276 已经因为"售罄哨兵过折扣变成 0"
踩过一次同形的坑。

### 为什么这一条牵动存档与指纹

新字段 = 新字节，而 §308 的 `state-fields` 闸门正是为"加了字段忘了存/忘了算"设的：

| 位置 | 改动 |
|---|---|
| `state.rs` | 字段 + `enter_shop` 清位 + `remove_card` 检查并置位 + `removal_available()` 访问器 |
| `streams.rs` | `RunError::RemovalUsed`（**不复用** `WrongPhase`：相位是对的，错的是次数） |
| `state/archive.rs` | payload **版本 11 → 12**；写、读、还原三处；`sample_full()` 显式设它 |
| `hash.rs` | `removal_used=` 进指纹（它决定下一步的合法动作集） |
| `rd-wasm` | `rd_run_removal_available()` 导出 + `smoke.mjs` 的手抄清单 |
| `web/` | 快照多一格 + 商店面板的 `disabled` |

★ `sample_full()` 里那句"必须显式设"是重点：留默认值 `false` 的话，"漏还原一个字段就红"
这句话对它就是假的 —— §308 就是这么发现 18 个字段全在默认值的。

### 判据

| 判据 | 钉住什么 |
|---|---|
| `buying_and_removing_are_paid_for_and_never_silent`（改写后半段） | 同一家店第二次 ⇒ `RemovalUsed` 且**整局相等**；**换一家店** ⇒ 额度恢复而**价格继续累计**；空钱包 ⇒ `NotEnoughGold` 且**不消耗额度** |
| `the_removal_service_reports_whether_this_shop_still_allows_it`（rd-wasm） | 四态：`-1` 没有局 → `1` 商店 → `0` 用掉 → 拒绝不改额度 |
| `a_saved_run_round_trips_byte_identically`（既有，靠 `sample_full()` 扩展） | 新字段漏还原就红 |
| `state-fields` 闸门 | 新字段必须同时进存档与指纹（68 fields） |

负控 **4/4**（`native/p343_negative.py`）：不检查额度 / `enter_shop` 不清位 /
存档不还原 / 指纹里不写。第 ④ 条走**闸门**而不是 cargo test —— 那道闸门就是为这件事存在的。

⚠️ 两个坑：`rd_run_remove_card` 的**成功返回值是价格**（`Ok(price)`），不是 0（与 `buy_*` 不同），
第一版按 0 判断，把成功当成了拒绝；`hash.rs` 是 `state` 的**平级模块**，所以字段要 `pub(crate)`
（§308 的闸门要求指纹里出现**字面** `state.<字段>`）。

### 剩下的待核（写进 `docs/sts-wiki-gap.md`）

* 删卡服务上 Courier 与 Membership Card 是否"取更好的那一个"（fandom 说取、wiki.gg 说照常，两源互斥）；
* A16 是否加价删卡无据（wiki 只给 75，teemo.dev 标 *"exact / Variance: None"*），我们按加价实现。

### 数字

`rd-run 223`、`rd-wasm 185`（184 + 1）、`rd-core 819`、units **1227**（下限 1226 → 1227）；
`state-fields` 68 fields；导出 219 → **220**；四条对拍不动；`WEB_SMOKE PASS`；23/23 闸门。
"""

t = io.open(PLAN, encoding='utf-8').read()
assert '## §343' not in t
io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(t.rstrip('\n') + '\n' + SECTION)

# wiki-gap：把"删卡每店一次"从待核改成已实现，并留下剩下的两条
g = io.open(GAP, encoding='utf-8').read()
g = sub(g, '''⚠️ 待核三条：① 删卡服务上 Courier 与 Membership Card 是否"取更好的那一个"（fandom 说取、wiki.gg 说照常，两源互斥）；
② **删卡"每店一次"还没实现**（wiki.gg/fandom 都写 "Can only be used once per Shop"）—— 现在能同店连删；
③ A16 是否加价删卡无据（wiki 只给 75，teemo.dev 标 exact），我们按加价实现。''',
        '''**删卡"每店一次"已实现**（§343：`removed_this_shop`，换店恢复而价格继续累计）。
⚠️ 待核两条：① 删卡服务上 Courier 与 Membership Card 是否"取更好的那一个"（fandom 说取、wiki.gg 说照常，两源互斥）；
② A16 是否加价删卡无据（wiki 只给 75，teemo.dev 标 exact），我们按加价实现。''',
        'wiki-gap removal')
io.open(GAP, 'w', encoding='utf-8', newline='\n').write(g)
print('port-plan §343 + wiki-gap')
