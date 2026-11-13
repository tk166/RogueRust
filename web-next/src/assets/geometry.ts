// 三维敌人的**几何目录**：16 种「立体几何排列组合」，每一种都是**纯数据**。
//
// ## 为什么是数据而不是组件
//
// 1. **可测**：闸门 45 在 Node 里就能断言"每种原型至少 2 个基本体、只引用已知形状、
//    角色只有 body/accent/eye" —— 不需要 WebGL。
// 2. **可替换**：将来换成 GLB 时，只需要把 `parts` 换成 `{ model, clips }`，清单与注册表不动
//    （`manifest.ts` 记的是**原型名**，不是网格）。
// 3. **确定性**：同一份数据在每次渲染里得到同样的构图，所以截图/闸门可复现。
//
// ## 三种角色
//
// `body`（主体，取调色板的 `body`）/ `accent`（次要，取 `accent`）/ `eye`（眼睛，取 `eye`）。
// 渲染层只按角色上色，不认具体原型 —— 加一个原型不需要改渲染代码。

export type Shape = "sphere" | "box" | "cone" | "cylinder" | "torus" | "octahedron" | "capsule";
export type PartRole = "body" | "accent" | "eye";

export interface FigurePart {
  readonly shape: Shape;
  /** 三轴尺寸（世界单位）。`sphere`/`octahedron` 只看 x；`torus` 用 x=半径, y=管径。 */
  readonly size: readonly [number, number, number];
  readonly position: readonly [number, number, number];
  readonly rotation?: readonly [number, number, number];
  readonly role: PartRole;
}

export interface Archetype {
  readonly name: string;
  /** 一句话说明这个原型"长什么样"（素材库页面直接显示）。 */
  readonly note: string;
  readonly parts: readonly FigurePart[];
}

/** 16 种原型。**名字必须与 `manifest.ts` 的 `ARCHETYPES` 一致**（闸门 45 核对）。 */
export const FIGURES: Record<string, Archetype> = {
  slime: {
    name: "slime",
    note: "一大球 + 一小球压在上面（软泥）",
    parts: [
      { shape: "sphere", size: [0.46, 0.46, 0.46], position: [0, -0.12, 0], role: "body" },
      { shape: "sphere", size: [0.24, 0.24, 0.24], position: [0.12, 0.26, 0.06], role: "accent" },
      { shape: "sphere", size: [0.06, 0.06, 0.06], position: [0.16, -0.02, 0.42], role: "eye" },
    ],
  },
  humanoid: {
    name: "humanoid",
    note: "盒状躯干 + 球头 + 两条盒状手臂（人形）",
    parts: [
      { shape: "box", size: [0.38, 0.5, 0.24], position: [0, -0.16, 0], role: "body" },
      { shape: "sphere", size: [0.2, 0.2, 0.2], position: [0, 0.26, 0], role: "body" },
      { shape: "box", size: [0.1, 0.34, 0.1], position: [-0.26, -0.1, 0], role: "accent" },
      { shape: "box", size: [0.1, 0.34, 0.1], position: [0.26, -0.1, 0], role: "accent" },
      { shape: "sphere", size: [0.05, 0.05, 0.05], position: [-0.07, 0.28, 0.18], role: "eye" },
      { shape: "sphere", size: [0.05, 0.05, 0.05], position: [0.07, 0.28, 0.18], role: "eye" },
    ],
  },
  beast: {
    name: "beast",
    note: "盒状身 + 锥形头 + 四条细腿（兽）",
    parts: [
      { shape: "box", size: [0.5, 0.3, 0.26], position: [0, -0.02, 0], role: "body" },
      { shape: "cone", size: [0.16, 0.24, 0.16], position: [0.3, 0.06, 0], rotation: [0, 0, -1.4], role: "body" },
      { shape: "box", size: [0.06, 0.26, 0.06], position: [-0.18, -0.28, 0.09], role: "accent" },
      { shape: "box", size: [0.06, 0.26, 0.06], position: [0.18, -0.28, 0.09], role: "accent" },
      { shape: "box", size: [0.06, 0.26, 0.06], position: [-0.18, -0.28, -0.09], role: "accent" },
      { shape: "box", size: [0.06, 0.26, 0.06], position: [0.18, -0.28, -0.09], role: "accent" },
      { shape: "sphere", size: [0.05, 0.05, 0.05], position: [0.38, 0.1, 0.08], role: "eye" },
    ],
  },
  construct: {
    name: "construct",
    note: "八面体核心 + 两圈环（构装体）",
    parts: [
      { shape: "octahedron", size: [0.34, 0.34, 0.34], position: [0, 0, 0], role: "body" },
      { shape: "torus", size: [0.42, 0.035, 0.42], position: [0, 0, 0], rotation: [1.57, 0, 0], role: "accent" },
      { shape: "torus", size: [0.3, 0.03, 0.3], position: [0, 0, 0], rotation: [0, 0, 1.57], role: "accent" },
      { shape: "sphere", size: [0.07, 0.07, 0.07], position: [0, 0.02, 0.32], role: "eye" },
    ],
  },
  gremlin: {
    name: "gremlin",
    note: "球身 + 两只锥耳 + 盒状脚（小鬼）",
    parts: [
      { shape: "sphere", size: [0.3, 0.3, 0.3], position: [0, 0.02, 0], role: "body" },
      { shape: "cone", size: [0.1, 0.24, 0.1], position: [-0.16, 0.3, 0], rotation: [0, 0, 0.4], role: "accent" },
      { shape: "cone", size: [0.1, 0.24, 0.1], position: [0.16, 0.3, 0], rotation: [0, 0, -0.4], role: "accent" },
      { shape: "box", size: [0.14, 0.08, 0.2], position: [-0.12, -0.28, 0.04], role: "accent" },
      { shape: "box", size: [0.14, 0.08, 0.2], position: [0.12, -0.28, 0.04], role: "accent" },
      { shape: "sphere", size: [0.05, 0.05, 0.05], position: [-0.08, 0.08, 0.26], role: "eye" },
      { shape: "sphere", size: [0.05, 0.05, 0.05], position: [0.08, 0.08, 0.26], role: "eye" },
    ],
  },
  slaver: {
    name: "slaver",
    note: "胶囊身 + 盒肩 + 锥形兜帽（奴隶主）",
    parts: [
      { shape: "capsule", size: [0.26, 0.5, 0.26], position: [0, -0.1, 0], role: "body" },
      { shape: "box", size: [0.52, 0.14, 0.2], position: [0, 0.14, 0], role: "accent" },
      { shape: "cone", size: [0.24, 0.3, 0.24], position: [0, 0.34, 0], role: "accent" },
      { shape: "sphere", size: [0.05, 0.05, 0.05], position: [-0.08, 0.3, 0.16], role: "eye" },
      { shape: "sphere", size: [0.05, 0.05, 0.05], position: [0.08, 0.3, 0.16], role: "eye" },
    ],
  },
  louse: {
    name: "louse",
    note: "胶囊身 + 两根触角 + 六条细腿（虱）",
    parts: [
      { shape: "capsule", size: [0.24, 0.34, 0.24], position: [0, 0, 0], role: "body" },
      { shape: "cone", size: [0.05, 0.22, 0.05], position: [-0.1, 0.26, 0], rotation: [0, 0, 0.3], role: "accent" },
      { shape: "cone", size: [0.05, 0.22, 0.05], position: [0.1, 0.26, 0], rotation: [0, 0, -0.3], role: "accent" },
      { shape: "box", size: [0.04, 0.16, 0.04], position: [-0.16, -0.2, 0.1], role: "accent" },
      { shape: "box", size: [0.04, 0.16, 0.04], position: [0.16, -0.2, 0.1], role: "accent" },
      { shape: "box", size: [0.04, 0.16, 0.04], position: [-0.16, -0.2, -0.1], role: "accent" },
      { shape: "box", size: [0.04, 0.16, 0.04], position: [0.16, -0.2, -0.1], role: "accent" },
      { shape: "sphere", size: [0.04, 0.04, 0.04], position: [-0.06, 0.06, 0.22], role: "eye" },
      { shape: "sphere", size: [0.04, 0.04, 0.04], position: [0.06, 0.06, 0.22], role: "eye" },
    ],
  },
  sentinel: {
    name: "sentinel",
    note: "柱身 + 盒状面罩 + 两颗球（哨兵）",
    parts: [
      { shape: "cylinder", size: [0.24, 0.56, 0.24], position: [0, -0.08, 0], role: "body" },
      { shape: "box", size: [0.4, 0.16, 0.2], position: [0, 0.26, 0], role: "accent" },
      { shape: "sphere", size: [0.06, 0.06, 0.06], position: [-0.09, 0.26, 0.14], role: "eye" },
      { shape: "sphere", size: [0.06, 0.06, 0.06], position: [0.09, 0.26, 0.14], role: "eye" },
      { shape: "torus", size: [0.3, 0.03, 0.3], position: [0, -0.34, 0], rotation: [1.57, 0, 0], role: "accent" },
    ],
  },
  spire_guard: {
    name: "spire_guard",
    note: "锥形塔身 + 环（尖塔守卫）",
    parts: [
      { shape: "cone", size: [0.34, 0.72, 0.34], position: [0, -0.06, 0], role: "body" },
      { shape: "torus", size: [0.26, 0.04, 0.26], position: [0, 0.14, 0], rotation: [1.57, 0, 0], role: "accent" },
      { shape: "sphere", size: [0.06, 0.06, 0.06], position: [0, 0.02, 0.2], role: "eye" },
    ],
  },
  floating_orb: {
    name: "floating_orb",
    note: "球 + 两道轨道环（浮空球）",
    parts: [
      { shape: "sphere", size: [0.34, 0.34, 0.34], position: [0, 0, 0], role: "body" },
      { shape: "torus", size: [0.5, 0.025, 0.5], position: [0, 0, 0], rotation: [1.2, 0.4, 0], role: "accent" },
      { shape: "torus", size: [0.44, 0.02, 0.44], position: [0, 0, 0], rotation: [-0.9, 0.8, 0], role: "accent" },
      { shape: "sphere", size: [0.08, 0.08, 0.08], position: [0, 0, 0.3], role: "eye" },
    ],
  },
  plant: {
    name: "plant",
    note: "柱状茎 + 三片锥叶 + 球状花苞（植物）",
    parts: [
      { shape: "cylinder", size: [0.08, 0.5, 0.08], position: [0, -0.16, 0], role: "accent" },
      { shape: "sphere", size: [0.24, 0.24, 0.24], position: [0, 0.22, 0], role: "body" },
      { shape: "cone", size: [0.14, 0.28, 0.14], position: [-0.2, 0.02, 0], rotation: [0, 0, 0.9], role: "accent" },
      { shape: "cone", size: [0.14, 0.28, 0.14], position: [0.2, 0.02, 0], rotation: [0, 0, -0.9], role: "accent" },
      { shape: "cone", size: [0.12, 0.24, 0.12], position: [0, -0.06, 0.18], rotation: [0.7, 0, 0], role: "accent" },
      { shape: "sphere", size: [0.05, 0.05, 0.05], position: [0, 0.24, 0.2], role: "eye" },
    ],
  },
  crystal: {
    name: "crystal",
    note: "三块八面体错角排列（晶体）",
    parts: [
      { shape: "octahedron", size: [0.3, 0.44, 0.3], position: [0, 0.02, 0], role: "body" },
      { shape: "octahedron", size: [0.16, 0.24, 0.16], position: [-0.26, -0.16, 0.06], rotation: [0, 0, 0.5], role: "accent" },
      { shape: "octahedron", size: [0.16, 0.24, 0.16], position: [0.26, -0.12, -0.04], rotation: [0, 0, -0.5], role: "accent" },
      { shape: "sphere", size: [0.05, 0.05, 0.05], position: [0, 0.06, 0.26], role: "eye" },
    ],
  },
  boss_blob: {
    name: "boss_blob",
    note: "巨大球 + 三颗小卫星球 + 环（Boss 软泥）",
    parts: [
      { shape: "sphere", size: [0.62, 0.56, 0.62], position: [0, -0.06, 0], role: "body" },
      { shape: "sphere", size: [0.22, 0.22, 0.22], position: [-0.42, 0.24, 0.1], role: "accent" },
      { shape: "sphere", size: [0.18, 0.18, 0.18], position: [0.44, 0.16, -0.06], role: "accent" },
      { shape: "sphere", size: [0.16, 0.16, 0.16], position: [0.06, 0.46, -0.1], role: "accent" },
      { shape: "torus", size: [0.5, 0.03, 0.5], position: [0, -0.2, 0], rotation: [1.57, 0, 0], role: "accent" },
      { shape: "sphere", size: [0.08, 0.08, 0.08], position: [-0.14, 0.06, 0.5], role: "eye" },
      { shape: "sphere", size: [0.08, 0.08, 0.08], position: [0.14, 0.06, 0.5], role: "eye" },
    ],
  },
  boss_machine: {
    name: "boss_machine",
    note: "盒状躯干 + 两根圆柱臂 + 环（Boss 机械）",
    parts: [
      { shape: "box", size: [0.56, 0.5, 0.34], position: [0, 0, 0], role: "body" },
      { shape: "cylinder", size: [0.12, 0.5, 0.12], position: [-0.4, -0.06, 0], role: "accent" },
      { shape: "cylinder", size: [0.12, 0.5, 0.12], position: [0.4, -0.06, 0], role: "accent" },
      { shape: "torus", size: [0.36, 0.04, 0.36], position: [0, 0.34, 0], rotation: [1.57, 0, 0], role: "accent" },
      { shape: "box", size: [0.24, 0.1, 0.06], position: [0, 0.06, 0.2], role: "eye" },
    ],
  },
  worm: {
    name: "worm",
    note: "三球串成一节 + 锥头（虫）",
    parts: [
      { shape: "sphere", size: [0.24, 0.24, 0.24], position: [0, -0.2, 0], role: "body" },
      { shape: "sphere", size: [0.2, 0.2, 0.2], position: [0.1, 0.02, 0], role: "body" },
      { shape: "sphere", size: [0.18, 0.18, 0.18], position: [0.16, 0.24, 0], role: "body" },
      { shape: "cone", size: [0.16, 0.22, 0.16], position: [0.2, 0.44, 0], role: "accent" },
      { shape: "sphere", size: [0.05, 0.05, 0.05], position: [0.16, 0.28, 0.16], role: "eye" },
    ],
  },
  ghost: {
    name: "ghost",
    note: "球头 + 锥形尾 + 两颗小球眼（幽灵）",
    parts: [
      { shape: "sphere", size: [0.3, 0.3, 0.3], position: [0, 0.14, 0], role: "body" },
      { shape: "cone", size: [0.26, 0.4, 0.26], position: [0, -0.24, 0], rotation: [3.14, 0, 0], role: "accent" },
      { shape: "sphere", size: [0.05, 0.05, 0.05], position: [-0.09, 0.18, 0.24], role: "eye" },
      { shape: "sphere", size: [0.05, 0.05, 0.05], position: [0.09, 0.18, 0.24], role: "eye" },
    ],
  },
};

export const SHAPES: readonly Shape[] = ["sphere", "box", "cone", "cylinder", "torus", "octahedron", "capsule"];
export const ROLES: readonly PartRole[] = ["body", "accent", "eye"];
