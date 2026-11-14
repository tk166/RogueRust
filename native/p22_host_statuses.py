"""§378：`host.ts` 加 `statuses(whom)` —— 战斗里**每一个**状态实例（id + 层数）。

## 为什么现在才加

观察向量里只冻结了 5 条状态轴（`strength/vulnerable/weak/dexterity/frail`），而内核早就有
`rd_env_status_count/_id_len/_id_into/_stacks`（§147 引入，注释里写得很清楚："一个看不见的减益
就是玩家没法绕开的减益"）。**数据一直在，界面没读** —— 玩家报的"我方和敌人的各种状态看不到"
就是这件事。

`whom`：`-1` = 英雄，`0..5` = 敌人墙位。
"""

import io

PATH = 'web-next/src/wasm/host.ts'
t = io.open(PATH, encoding='utf-8').read()

# ── 1. 导出名单（装载校验按这张表逐个查）──────────────────────────────────
OLD = '''  "rd_env_enemy_name_len",
  "rd_env_enemy_name_into",'''
NEW = '''  "rd_env_enemy_name_len",
  "rd_env_enemy_name_into",
  // §378：状态实例（id + 层数）。观察向量只冻结了 5 条轴，这是**完整**的那一份。
  "rd_env_status_count",
  "rd_env_status_id_len",
  "rd_env_status_id_into",
  "rd_env_status_stacks",'''
assert t.count(OLD) == 1
t = t.replace(OLD, NEW)

# ── 2. 读取函数（放在 `enemyName` 之后）────────────────────────────────────
OLD2 = '''  /** 敌人墙位槽的显示名。 */
  enemyName(slot: number): string {
    return this.readText(
      () => (this.ex.rd_env_enemy_name_len as (index: number) => number)(slot),
      (ptr) => (this.ex.rd_env_enemy_name_into as (index: number, ptr: number) => number)(slot, ptr)
    );
  }'''
NEW2 = '''  /** 敌人墙位槽的显示名。 */
  enemyName(slot: number): string {
    return this.readText(
      () => (this.ex.rd_env_enemy_name_len as (index: number) => number)(slot),
      (ptr) => (this.ex.rd_env_enemy_name_into as (index: number, ptr: number) => number)(slot, ptr)
    );
  }

  /**
   * 战斗者 `whom` 身上的**全部**状态实例（`env-abi.md` §147 那一组）。
   *
   * `whom`：`-1` = 英雄，`0..5` = 敌人墙位。`count < 0` ⇒ 没有这个战斗者（返回空数组，
   * 不是"0 个状态"—— 两者语义不同，但展示层对两者的处理都是"不画"）。
   *
   * ⚠️ 为什么不用观察向量里那 5 条轴：那是**冻结**的 ABI，加第 6 条会移动后面每一个偏移。
   * 而 `Constricted` 这种"每回合掉血"的减益不在那 5 条里 —— 玩家看不见就没法应对。
   */
  statuses(whom: number): { id: string; stacks: number }[] {
    const count = (this.ex.rd_env_status_count as (whom: number) => number)(whom);
    if (count <= 0) return [];
    const out: { id: string; stacks: number }[] = [];
    for (let index = 0; index < count; index += 1) {
      const id = this.readText(
        () => (this.ex.rd_env_status_id_len as (whom: number, index: number) => number)(whom, index),
        (ptr) =>
          (this.ex.rd_env_status_id_into as (whom: number, index: number, ptr: number) => number)(
            whom,
            index,
            ptr
          )
      );
      const stacks = (this.ex.rd_env_status_stacks as (whom: number, index: number) => number)(
        whom,
        index
      );
      out.push({ id, stacks });
    }
    return out;
  }'''
assert t.count(OLD2) == 1
t = t.replace(OLD2, NEW2)

io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('host.statuses(whom) 已加')
