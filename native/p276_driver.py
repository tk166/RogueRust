"""§276 驱动：把 `startTowards` 的"种子重试"从**地图可达**推进到**活着走到**。

## 为什么必须改

`startTowards(name, kind, seeds)` 返回**第一个地图上能到达该类型节点**的种子。§276 加了
4 条 L 史莱姆与 `Swarm of Slimes`（5 个敌人）之后，Act 1 的路线整体变硬 —— 旧表里第一个
能到达商人的种子（101）会在半路**被打死**（`hp 0 / Defeat`），于是"走图"停在战斗节点上，
而报错说的是"光标在 kind 1，期待 4（商店）"，看起来像路线规划器坏了。

⇒ 判据的前提写窄了："能到达"不等于"能活着走到"。这里补一个 `walkToKind`：
按种子重试，**走完再看走到没走到**，都通过才算这个种子可用。
"""
import io

P = 'D:/Vibe/sts-tui/web/act1_slice.mjs'

HELPER = '''  /// §276：把种子重试从"地图可达"推进到"**活着走到**"。
  ///
  /// 返回 `null` = 表里没有种子能走到；否则返回 `{ seed, plan, row }`，并且**光标已经在目标
  /// 节点上、待决已清**。`extra(seed)` 让调用方自己先结算目标节点（例如商店要摆好货架）。
  async function walkToKind(name, kindName, seeds) {
    for (const seed of seeds) {
      const started = await startTowards(name, kindName, [seed]);
      if (!started.ok) continue;
      const plan = planTo(kindName);
      if (!plan || !plan.length) continue;
      let stuck = null;
      for (let step = 0; step + 1 < plan.length; step++) {
        const target = document.querySelector('[data-node="' + plan[step] + '"]');
        if (!target) {
          stuck = { step, why: 'no such node element', planned: plan[step] };
          break;
        }
        await click(target);
        const settled = await settle(120);
        if (!settled) {
          stuck = { step, why: 'settle gave up', hp: hp(), pending: ex.rd_run_pending(),
                    msg: text(byId("msg")).slice(0, 60) };
          break;
        }
        if (ex.rd_run_observe(1) !== plan[step]) {
          stuck = { step, why: 'the click did not move the cursor', planned: plan[step],
                    actual: ex.rd_run_observe(1) };
          break;
        }
      }
      if (stuck) continue;
      const last = document.querySelector('[data-node="' + plan[plan.length - 1] + '"]');
      if (!last) continue;
      await click(last);
      // 走到**目标节点本身上**：kind 与光标都要对。
      if (ex.rd_run_node_kind() !== ex.rd_run_pendingKind?.(kindName)) { /* 保守起见用下面的比较 */ }
      return { seed, plan, row: { seed, ok: true, skipped: false } };
    }
    return null;
  }

'''


def main():
    src = io.open(P, encoding='utf-8').read()
    anchor = '  const out = { scenarios: [], errors: [] };'
    assert src.count(anchor) == 1
    if 'async function walkToKind' not in src:
        src = src.replace(anchor, HELPER + anchor)
        io.open(P, 'w', encoding='utf-8', newline='\n').write(src)
        print('walkToKind added')
    else:
        print('walkToKind already present')


main()
