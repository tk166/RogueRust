"""§316 记账：Act 3 的普通池 9 / 10（Shapes + Jaw Worm Horde）。"""
import io

ROOT = 'D:/Vibe/sts-tui/'
PLAN = ROOT + 'docs/port-plan.md'
ACCEPT = ROOT + 'tools/acceptance.ps1'

DOC = r"""
---

## §316 Act 3 的普通池：按 wiki 重排，补到 9 / 10

原来第三幕的 `Weak3` 是六条**近似**（`enc_byrds` / `enc_darklings` / `enc_maw` / `enc_orb_walker` /
`enc_spiker` / `enc_spire_growth`）。核对 wiki 的 `The_Beyond` 两张表（Easy 3 条 / Hard 7 条）之后：

| wiki | 池 | 结果 |
|---|---|---|
| 3 Darklings | Easy | ✅（**顺带修了只有 2 只的 bug**） |
| Orb Walker | Easy | ✅ |
| 3 Shapes | Easy | ✅（新怪 `Repulsor` / `Exploder`） |
| 4 Shapes | Hard | ✅ |
| The Maw | Hard | ✅ |
| Spheric Guardian + 2 Shapes | Hard | ✅ |
| 3 Darklings | Hard | ✅（克隆 `enc_darklings_hard`） |
| Spire Growth | Hard | ✅ |
| Jaw Worm Horde | Hard | ✅（3 只 `jaw_worm`，纯复用） |
| Transient | Hard | ❌ 要 `Fading` 与"伤害随回合涨"两条新机制 |

顺手**删掉两条错的内容**（都是"走不到的孤儿"或"挂错幕"）：
* `enc_byrds` 挂在第三幕 —— wiki 的第三幕回归名单里没有 Byrd（它是第二幕的），而第二幕已经有
  `enc_city_byrds`；
* `enc_spiker` —— wiki 的第三幕池子里**没有**单独一只 Spiker（它只在 Shapes 组里出现）。
  删掉之后 `content::tests::the_encounter_pools_are_readable`（"每条遭遇都能从某个池子走到"）
  才重新绿 —— 它当场抓到 `enc_spiker` 变成孤儿。

### 316.1 Shapes 是**组合槽**，不是三只固定怪

`3 Shapes` / `4 Shapes` / `Spheric + 2 Shapes` 用 §277 的 `Candidates`：每个槽的候选是
Repulsor / Exploder / Spiker 三条**完整敌人记录**。⚠️ 已知偏差：wiki 是"袋子里抽 3 不放回"，
我们是**逐槽独立按权重挑** ⇒ 会出现三只同一个。

顺带一个副作用值得记：因为这个"随机"，三条既有判据（Spiker 的两条、`starting_statuses...`）
不能再靠 `enc_spiker` 拿一只 Spiker 了 —— 现在用 `shapes_session_with(seed, "spiker", asc)`
**循环种子**直到组里真的出现它。第一版忘了把 `seed` 传进去，于是"无约束时两招都能出"那条
判据每次都拿到同一个种子、只看得见一招 —— 判据变红，抓的正是"我把随机性写死了"。

### 316.2 判据与负控

| 判据 | 钉的东西 |
|---|---|
| `the_exploder_hits_for_thirty_and_then_dies` | 30 点伤害 **+ 自己死**（只测伤害会漏掉"还站着"） |
| `the_repulsor_puts_two_dazed_into_the_draw_pile` | 2 张 `dazed` 进**抽牌堆**（只数张数会漏掉落区） |
| `every_encounter_in_the_image_builds_and_runs_without_a_thrown_step`（已有） | 五条新遭遇自动被扫到 |

**负控 2/2 红**（`native/p316_negative.py`）：Explode 去掉 `destroyCombatant` ⇒ 第一条红；
Daze 的落区改成 `DiscardPile` ⇒ 第二条红。

### 316.3 账

内容：**57 怪 / 60 遭遇 / 147 状态 / 158 敌人动作 / 116 变体（100 动作）**；
镜像 **176,864 B**（core 139,956 B）；Act 3 普通池 **9 / 10**（缺 `Transient`）。

`rd-core` 809 / `rd-run` 194 / `rd-wasm` **161**（+2）；聚合闸门 **22/22**（`rust-units 1164`）。
"""


def main():
    plan = io.open(PLAN, encoding='utf-8').read()
    if '§316 Act 3 的普通池' not in plan:
        io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(plan.rstrip('\n') + '\n' + DOC)
    accept = io.open(ACCEPT, encoding='utf-8').read()
    assert accept.count('  [int]$UnitsFloor = 1162') == 1
    io.open(ACCEPT, 'w', encoding='utf-8', newline='\n').write(
        accept.replace('  [int]$UnitsFloor = 1162', '  [int]$UnitsFloor = 1164'))
    print('§316 recorded; UnitsFloor 1164')


main()
