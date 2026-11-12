/**
 * P1 示例：纯函数战斗队形。
 *
 * 与 R3F / React / WASM 无关。后续从 MockScene 切到 GameSnapshot 时无需改算法。
 * 坐标采用相机可见的世界半宽/半高，左侧永远留给玩家，右侧留给敌方。
 *
 * 约束：
 *   - portrait: 右侧单列，至多六名敌人；随密度缩放，防止相互遮挡。
 *   - landscape: 两行布局，上行 ceil(n/2)、下行 floor(n/2)，每行至多 3 人。
 *   - 槽位来自业务数据，不依据数组位置重编号；攻击目标仍使用原 slot。
 *   - 敌人数超出当前视觉设计能力时显式报错，不静默截断。
 */
export interface CombatViewport {
  readonly width: number; // CSS 像素（判定横竖屏）
  readonly height: number;
  readonly halfW: number; // 相机世界可见半宽
  readonly halfH: number; // 相机世界可见半高
}
export interface FormationPoint {
  readonly slot: number;
  readonly x: number;
  readonly y: number;
  readonly z: number;
  readonly scale: number;
  readonly row: 0 | 1; // 竖屏全部为第 0 行
}
export interface CombatFormation {
  readonly portrait: boolean;
  readonly hero: { readonly x: number; readonly y: number; readonly z: number };
  readonly enemies: readonly FormationPoint[];
}

export function computeCombatFormation(slots: readonly number[], view: CombatViewport): CombatFormation {
  if (!(view.width > 0 && view.height > 0 && view.halfW > 0 && view.halfH > 0)) {
    throw new RangeError("viewport must have positive dimensions");
  }
  if (slots.length > 6) {
    // 不用 slice(0, 6)：沉默漏显示一个可攻击敌人会造成 P0 级操作混乱。
    throw new RangeError(`formation supports at most 6 enemies; got ${slots.length}`);
  }
  if (new Set(slots).size !== slots.length) throw new RangeError("enemy slots must be unique");

  const portrait = view.height > view.width;
  const hero = {
    x: -view.halfW * (portrait ? 0.48 : 0.51),
    y: portrait ? view.halfH * 0.03 : -view.halfH * 0.04,
    z: 0.15,
  };
  const n = slots.length;
  if (n === 0) return { portrait, hero, enemies: [] };

  if (portrait) {
    // 竖屏：屏幕上部给敌人，底部给扇形手牌；用上下边界按 n 自适应间距。
    const top = view.halfH * 0.53;
    const bottom = -view.halfH * 0.31;
    // ⚠️ 上限 1.0 时两个敌人只隔约 114px（390 宽），而"名字+HP+意图"三行标签约 60px 高，
    // 会压到上面那个敌人身上。1.35 让 n=2 时也留得下标签；n 大时仍由区域高度约束。
    const gap = n < 2 ? 0 : Math.min(1.35, (top - bottom) / (n - 1));
    const center = (top + bottom) / 2;
    const scale = n < 2 ? 1 : Math.max(0.60, Math.min(1, gap / 0.98));
    return {
      portrait,
      hero,
      enemies: slots.map((slot, i) => ({
        slot,
        x: view.halfW * 0.49,
        y: center + ((n - 1) / 2 - i) * gap,
        z: -0.35,
        scale,
        row: 0,
      })),
    };
  }

  // 横屏：**每排至多 3 名**。n ≤ 3 只占一排，n ≥ 4 分两排（4 → 2+2，5 → 3+2，6 → 3+3）。
  //
  // ⚠️ 两条历史教训都在这里：
  // 1. 参考包写的是 `ceil(n/2)` / `floor(n/2)`，**n = 2 时"每排各 1 名"**，而每排只有一名时
  //    `rowX` 返回同一个 `mid` ⇒ 两个怪**上下叠在一条竖线上**，横屏看起来像竖屏。
  // 2. §360 为了修 (1) 改成 `n <= 4` 单排，结果 **n = 4 变成一排 4 名**，违反"每排 ≤ 3"这条
  //    更早、更强的约束（第十四轮 Review P1-C）。
  // 所以：单排的阈值是 **3**（一排最多 3 名），不是 4。
  const singleRow = n <= 3;
  const upperCount = singleRow ? n : Math.ceil(n / 2);
  const lowerCount = n - upperCount;
  const rightMin = view.halfW * 0.12;
  const rightMax = view.halfW * 0.78;
  const mid = (rightMin + rightMax) / 2;
  const rowX = (index: number, count: number): number => {
    if (count <= 1) return mid;
    // 保持阵型居中，在宽屏下也不要让三个怪物散得像三个孤岛。
    const dx = Math.min(1.10, (rightMax - rightMin) / (count - 1));
    return mid + (index - (count - 1) / 2) * dx;
  };
  return {
    portrait,
    hero,
    enemies: slots.map((slot, i) => {
      const row: 0 | 1 = i < upperCount ? 0 : 1;
      const withinRow = row === 0 ? i : i - upperCount;
      const count = row === 0 ? upperCount : lowerCount;
      return {
        slot,
        x: rowX(withinRow, count),
        // 只有一排时**竖直居中**（否则一排会贴在战场上半部，下半部空着）。
        y: lowerCount === 0 ? 0 : row === 0 ? view.halfH * 0.25 : -view.halfH * 0.16,
        z: -0.35,
        scale: 0.95,
        row,
      };
    }),
  };
}
