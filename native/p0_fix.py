"""修 `native/ui_abi_dump.mjs` 的场景驱动：**战斗要打到有结果**。

## 第一版的失败（值得记）

`--report` 第一版：`SC-04-reward` MISMATCH、`SC-05/07/08` UNREACHED。根因是**同一个**：

* `fight_begin` 之后立刻 `fight_end` —— 那时战斗**还没有结果**（`rd_env_result() == 0`），
  于是没有奖励屏（`pending` 仍是 0），节点也**没结算**；
* 而"节点没结算"会让下一步 `rd_run_step` 被拒（`NodeNotSettled`）⇒ `walkToKind` 直接放弃，
  于是商店/宝箱/事件全都"400 个种子里没走到"。

⇒ **一个夹具缺陷伪装成三个"场景不可达"。** 先让战斗有结果，再谈别的。

## 两种打法

* `playOutFight`：能出牌就出牌、否则结束回合 —— 一般能赢 ⇒ 奖励屏。
* `loseFight`：只结束回合、从不出牌 —— 一般会输 ⇒ 局终（`SC-12b`）。故意输，不伪造。
"""

import io

PATH = 'native/ui_abi_dump.mjs'


def sub(old, new, label=''):
    t = io.open(PATH, encoding='utf-8').read()
    assert t.count(old) == 1, '%s: 命中 %d' % (label or old[:40], t.count(old))
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t.replace(old, new))


# ── ① 两个打法（插在 `settleHere` 之前）──────────────────────────────────
sub('''/// 结算脚下这一格（把"待决"走完、或把战斗收掉），返回是否前进了一步。''',
    '''/// 把当前这场战斗打到**有结果**：能出牌就出牌，否则结束回合。返回 `rd_env_result()`。
///
/// ⚠️ 第一版在 `fight_begin` 之后**立刻** `fight_end`，那时战斗还没有结果 ⇒ 没有奖励屏、
/// 节点也没结算 ⇒ 后面每一步 `rd_run_step` 都被 `NodeNotSettled` 拒掉，于是"商店/宝箱/事件
/// 400 个种子都走不到" —— **一个夹具缺陷伪装成三个场景不可达**。
function playOutFight(maxSteps = 600) {
  for (let step = 0; step < maxSteps; step++) {
    if (ex.rd_env_done() !== 0) return ex.rd_env_result();
    const actions = combatActions();
    const play = actions.find((a) => a.kind === 0);
    const end = actions.find((a) => a.kind === 1);
    const pick = play || end;
    if (!pick) return -1;
    if (ex.rd_env_step(pick.index) !== 0) {
      // 被拒（例如目标过期）：退一步只结束回合；两个都不行就放弃。
      if (!end || ex.rd_env_step(end.index) !== 0) return -1;
    }
  }
  return -1;
}

/// 故意**输**：只结束回合、从不出牌。用来真实到达"战败"那一屏（`SC-12b`）。
function loseFight(maxSteps = 600) {
  for (let step = 0; step < maxSteps; step++) {
    if (ex.rd_env_done() !== 0) return ex.rd_env_result();
    const end = combatActions().find((a) => a.kind === 1);
    if (!end) return -1;
    if (ex.rd_env_step(end.index) !== 0) return -1;
  }
  return -1;
}

/// 结算脚下这一格（把"待决"走完、或把战斗收掉），返回是否前进了一步。''',
    'fight helpers')

# ── ② `settleHere` 的战斗分支 ────────────────────────────────────────────
sub('''    case 0: {
      // 战斗节点：开打、立刻收（这条判据不关心战果）。
      if (ex.rd_run_fight_begin() === 0) { ex.rd_run_fight_end(); return true; }
      return ex.rd_run_step(0) === 0;
    }''',
    '''    case 0: {
      // 战斗节点：**打到有结果**再收（见 `playOutFight`：立刻收会让节点不结算）。
      if (ex.rd_run_fight_begin() === 0) {
        playOutFight();
        ex.rd_run_fight_end();
        return true;
      }
      return ex.rd_run_step(0) === 0;
    }''', 'settleHere fight branch')

# ── ③ report：奖励屏要打到有结果 ─────────────────────────────────────────
sub('''      if (ex.rd_run_fight_end() >= 0) {
        scenes.push(captureRun("SC-04-reward", "reward screen after the fight"));
      }''',
    '''      const result = playOutFight();
      if (ex.rd_run_fight_end() >= 0) {
        scenes.push(captureRun("SC-04-reward", `fight result ${result} (1 = victory)`));
      }''', 'reward after a decided fight')

# ── ④ report：补 SC-12b（故意输）与 SC-12a（合成，显式标记）──────────────
sub('''  // ⑦ 商店 / ⑧ 宝箱 / ⑨ 事件：各找一个种子走到''',
    '''  // ⑥b 局终：**故意输一场**（只结束回合、从不出牌）—— 真实到达，不伪造。
  {
    let lost = false;
    for (let s = 1; s <= 400 && !lost; s++) {
      ex.rd_run_start(s, 0);
      finishBlessing();
      if (!walkToKind(1)) continue;
      if (ex.rd_run_fight_begin() !== 0) continue;
      const result = loseFight();
      if (ex.rd_run_fight_end() >= 0 && ex.rd_run_over() === 1) {
        scenes.push(captureRun("SC-12b-defeat", `seed ${s}, lost on purpose (result ${result})`));
        lost = true;
      }
    }
    if (!lost) {
      scenes.push({ label: "SC-12b-defeat", note: "UNREACHED within 400 seeds", raw: null });
    }
  }

  // ⑥c 幕通关（SC-12a）：要打穿一幕的 Boss，夹具代价太大 ⇒ **显式标记为合成**。
  scenes.push({
    label: "SC-12a-act-clear",
    note: "SYNTHETIC -- clearing an act needs the boss fight; the 18 synthetic fixtures in --check cover it",
    raw: null,
  });

  // ⑦ 商店 / ⑧ 宝箱 / ⑨ 事件：各找一个种子走到''', 'defeat + act-clear')

# ── ⑤ 期望表 ─────────────────────────────────────────────────────────────
sub('''    "SC-11a-pickup-debt": null, // only when the kernel really owes''',
    '''    "SC-11a-pickup-debt": null, // the overlay sits on whatever is underneath (SC-02 here)
    "SC-12b-defeat": "SC-12b",''', 'expectation table')
print('p0 driver fixed')
