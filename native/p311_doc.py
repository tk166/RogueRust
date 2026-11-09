"""§311 记账：Act 2 的普通遭遇池 3 → 10（wiki 13 条）+ 一个跨实例的真 bug。"""
import io

ROOT = 'D:/Vibe/sts-tui/'
PLAN = ROOT + 'docs/port-plan.md'
ACCEPT = ROOT + 'tools/acceptance.ps1'

DOC = r"""
---

## §311 Act 2 的普通遭遇池：3 → 10 条（wiki 的 13 条里）

审阅报告 §7 只含糊提了一句"刷新池与概率偏差"；核对之后这是**当前最大的敌人侧缺口**：
`Weak2` 池原来只有 3 条（`shelled_parasite` / `chosen` / `snecko`），而 wiki 的 `The_City` 是
Easy 5 + Hard 8 = **13 条组合**。

### 311.1 做了什么

| 新增 | 靠什么 |
|---|---|
| `3 Byrds` | 现有 `byrd`（**顺手修了 `enc_byrds` 只有 1 只的 bug**） |
| `Chosen and Byrds` | 现有（wiki: 1 Chosen + **1** Byrd） |
| `Cultist and Chosen` | 现有 |
| `3 Cultists` | 现有 |
| `Shelled Parasite and Fungi` | 现有 |
| `Spheric Guardian` | **新怪物**：HP 20、Activate(25 Block)、Debuff Attack(10 + 5 Frail)、Slam(10×2)、Harden(10 + 15 Block)；开场 **Block 40 + Artifact 3 + Barricade** |

池子现在是 10 条、**带 wiki 的权重**（`Weight` ×5 取整：10/10/10/10/10/15/20/15/15，另加
Spheric 的 10）。缺的 3 条各缺什么写在 `docs/sts-wiki-gap.md` §D.3.1：`snake_plant` 要
`standard.malleable`、`centurion`+`mystic` 要"按定义挑一只友军"的选择器、`2 Thieves` 要 `mugger`。

### 311.2 三个"内容之外的发现"

1. **`apply_starting_statuses` 用 plain id 挂状态** —— 三只 byrd 的三份 `StartingStatuses`
   全叠到 `byrd` 身上（实测 9 层），`byrd#2` / `byrd#3` 一层都没有。同一个 bug 早就存在于
   `enc_three_sentries`（三只哨卫各 Artifact 1 ⇒ 一只 3 层、两只 0 层），只是没人读过第二只。
   修法：把"实例 id 怎么算"抽成 `unique_instance_id()`，构建方与挂状态方共用（一处规则）。
   判据 `three_byrds_each_start_with_their_own_flying` **逐只**读 —— 只读一只区分不了
   "每只 3 层"与"一只 9 层"。负控：改回 plain id ⇒ 红。
2. **一条遭遇不能进两个池**（`content::tests::the_encounter_pools_are_readable`）。
   两幕都有 "3 Byrds"，所以 Act 2 用自己的一条 `enc_city_byrds`（敌人记录复制自 `enc_byrds`）。
3. **同一只怪物不能跨档位**：`Sentry and Spheric Guardian` 没做 —— 判据按池子档位钉一条
   `MaxHealthAsc`（精英 A8 / 普通 A7），Sentry 同时在 Act 1 精英池与 Act 2 普通池，两条要求
   不可能同时成立。这一条要等"按 (monster, tier) 钉 HP"被建模。

### 311.3 判据

| 判据 | 作用 |
|---|---|
| `every_pool_encounter_builds_and_can_pick_its_first_intents`（已有） | 每个池里的**每一条**遭遇都要能建起来并选出第一招 —— 10 条新池子成员自动被它扫到 |
| `three_byrds_each_start_with_their_own_flying` | 实例 id 的修复（逐只断言） |
| `the_spheric_guardian_starts_with_block_artifact_and_barricade` | Block 40（新基建 `StartingBlock`）+ Artifact 3 + Barricade + 第 1 回合 Activate |
| `sts_content_check.py` | 独立清单：怪物数 / 遭遇数 / 动作表 / 升阶决策 / 升阶数字 / 池子成员 / 敌人组成 |

**负控**：起始状态改回 plain id ⇒ `three_byrds_...` 红（`native/p311_negative.py`）。

### 311.4 账

内容：**51 怪 / 53 遭遇 / 142 敌人动作 / 101 个升阶变体（88 个动作）**；
镜像 **169,820 B**（core 133,660 B）；`rd-core` 809 / `rd-run` 194 / `rd-wasm` **153**（+2）；
聚合闸门 **22/22**（`rust-units 1156 passed`、`sts-content 51 monsters`）。
"""


def main():
    plan = io.open(PLAN, encoding='utf-8').read()
    if '§311 Act 2 的普通遭遇池' not in plan:
        io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(plan.rstrip('\n') + '\n' + DOC)
    accept = io.open(ACCEPT, encoding='utf-8').read()
    assert accept.count('  [int]$UnitsFloor = 1154') == 1
    io.open(ACCEPT, 'w', encoding='utf-8', newline='\n').write(
        accept.replace('  [int]$UnitsFloor = 1154', '  [int]$UnitsFloor = 1156'))
    print('§311 recorded; UnitsFloor 1156')


main()
