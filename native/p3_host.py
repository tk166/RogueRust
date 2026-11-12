"""给 web-next/src/wasm/host.ts 追加运行层读取（P3 用）。"""

import io

P = 'web-next/src/wasm/host.ts'
t = io.open(P, encoding='utf-8').read()


def sub(old, new, label):
    global t
    assert t.count(old) == 1, '%s: 命中 %d 次' % (label, t.count(old))
    t = t.replace(old, new)


sub(
    '''  // ── 药水（夹具用：`?debug` 下造"会问句"的局面）──────────────────────────────''',
    '''  // ── 运行层：地图 / 观察 / 牌组 / 遗物 / 遭遇名 / 动作表（P3 的场景层）──────────
  //
  // 这一组**只做搬运**：把 i32 读出来，不解释语义。语义在 `run/observe.ts`（纯函数、可单测），
  // 场景判定在 `run/scene.ts`（纯函数、可单测）。理由与 P2 的 `snapshot.ts` 一样：
  // 解码是最容易搞错的地方，而它不该需要 wasm 才能测。

  /** 运行层观察向量（19 格，`env-abi.md` §11.3）。长度由模块自报，不写死。 */
  runObservation(): Int32Array {
    const len = Number((this.ex.rd_run_observe_len as () => number)());
    const out = new Int32Array(len);
    for (let index = 0; index < len; index += 1) {
      out[index] = (this.ex.rd_run_observe as (index: number) => number)(index);
    }
    return out;
  }

  /** 地图节点数（`-1` = 没有局）。 */
  mapLen(): number {
    return (this.ex.rd_run_map_len as () => number)();
  }

  mapRows(): number {
    return (this.ex.rd_run_map_rows as () => number)();
  }

  /**
   * `rd_run_map_node(index, field)`：0 row / 1 col / 2 kind / 3 out_degree /
   * 4..6 出边（**全局下标**）/ 7 reachable。
   *
   * ⚠️ 出边是**全局**下标（`env-abi.md` §11.2 专门解释过为什么不给行内下标）——
   * 这里原样返回，绝不在 UI 里自己加行偏移。
   */
  mapNode(index: number, field: number): number {
    return (this.ex.rd_run_map_node as (index: number, field: number) => number)(index, field);
  }

  /**
   * 走路动作表：`rd_run_action_count()` 是**可达节点个数**，第 `i` 条的 `arg0` 是目标节点
   * 的全局下标。
   *
   * ⚠️ 所以"进入节点 G"必须先在这里找到 `target === G` 的那一条 —— 直接把 G 当
   * `rd_run_step` 的入参是错的（G 是全局下标，`step` 收的是可达表里的**位置**）。
   */
  runActions(): { index: number; kind: number; target: number }[] {
    const count = Number((this.ex.rd_run_action_count as () => number)());
    const out: { index: number; kind: number; target: number }[] = [];
    for (let index = 0; index < count; index += 1) {
      out.push({
        index,
        kind: (this.ex.rd_run_action as (index: number) => number)(index),
        target: (this.ex.rd_run_action_arg as (index: number, which: number) => number)(index, 0),
      });
    }
    return out;
  }

  /** 牌组里的定义 id（`strike` / `bash+` …）。 */
  deckIds(): string[] {
    const count = (this.ex.rd_run_deck_count as () => number)();
    const out: string[] = [];
    for (let index = 0; index < count; index += 1) {
      out.push(
        this.readText(
          () => (this.ex.rd_run_deck_id_len as (index: number) => number)(index),
          (ptr) =>
            (this.ex.rd_run_deck_id_into as (index: number, ptr: number) => number)(index, ptr)
        )
      );
    }
    return out;
  }

  relicIds(): string[] {
    const count = (this.ex.rd_run_relic_count as () => number)();
    const out: string[] = [];
    for (let index = 0; index < count; index += 1) {
      out.push(
        this.readText(
          () => (this.ex.rd_run_relic_id_len as (index: number) => number)(index),
          (ptr) =>
            (this.ex.rd_run_relic_id_into as (index: number, ptr: number) => number)(index, ptr)
        )
      );
    }
    return out;
  }

  /** 当前遭遇的 id（`cultist` / `jaw_worm` …）；没有时是空串。 */
  encounterId(): string {
    const len = (this.ex.rd_run_encounter_id_len as () => number)();
    if (len <= 0) return "";
    return this.readText(
      () => len,
      (ptr) =>
        (this.ex.rd_run_encounter_id_into as (ptr: number) => number)(ptr)
    );
  }

  /** 节点 kind 的**内核名字**（`rd_run_kind_name_*`），用于诊断与"未知 kind"兜底。 */
  kindName(kind: number): string {
    const len = (this.ex.rd_run_kind_name_len as (kind: number) => number)(kind);
    if (len <= 0) return "";
    return this.readText(
      () => len,
      (ptr) => (this.ex.rd_run_kind_name_into as (kind: number, ptr: number) => number)(kind, ptr)
    );
  }

  // ── 药水（夹具用：`?debug` 下造"会问句"的局面）──────────────────────────────''',
    'host run layer',
)
io.open(P, 'w', encoding='utf-8', newline='\n').write(t)
print('host: run layer reads')
