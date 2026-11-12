// 敌人外观的**资源解析**：内容 id → 一套程序化外观；不认识就**明确降级**。
//
// ## 为什么这一版没有 GLB
//
// plan P5 要"首批原创低多边形 GLB 角色 + AssetRegistry"。这一版**没有资产管线**（没有美术、
// 没有导出工具），所以：
//
// * **能做且已经做的**：把"某个敌人长什么样"变成一张**表**（颜色/体型/是否 Boss），
//   渲染层按表画程序化几何体；表里没有的 id 走 `placeholder` 并**计数**。
// * **明确不做的**：GLB 加载与动画命名（`AnimationClip` 与 beat 的对应）。写一个假的加载器
//   只会让"资产缺失"看起来像"资产有了"。
//
// ⇒ 未知 id 的降级是**可观察**的（`unknownEnemyAssets()`），闸门断言它为空；真出现了就是一条
// 可见的诊断，而不是"这个敌人看起来跟别的一样"。

export interface EnemyLook {
  /** 用哪套程序化外观。 */
  readonly shape: "slime" | "humanoid" | "beast" | "construct" | "placeholder";
  /** 主色（CSS 颜色；渲染层直接用）。 */
  readonly tint: string;
  /** 体型倍率（1 = 标准）。 */
  readonly scale: number;
  /** 是不是 Boss（画大一圈 + 特殊描边）。 */
  readonly boss: boolean;
}

const LOOKS: Record<string, Omit<EnemyLook, "boss">> = {
  // 按**内容 id**（`rd_env_enemy_name_*` 给的就是它）。没列到的走 placeholder。
  cultist: { shape: "humanoid", tint: "#b06bd8", scale: 1 },
  jaw_worm: { shape: "beast", tint: "#d8a24a", scale: 1.05 },
  louse: { shape: "beast", tint: "#9fbf6b", scale: 0.85 },
  "louse_normal": { shape: "beast", tint: "#9fbf6b", scale: 0.85 },
  "louse_defensive": { shape: "beast", tint: "#7fae52", scale: 0.9 },
  "louse_red": { shape: "beast", tint: "#d76b6b", scale: 0.9 },
  slime: { shape: "slime", tint: "#5fbf8f", scale: 0.9 },
  "acid_slime": { shape: "slime", tint: "#8fd85f", scale: 0.95 },
  "spike_slime": { shape: "slime", tint: "#5f8fbf", scale: 0.95 },
  "spike_slime_small": { shape: "slime", tint: "#7fb0d8", scale: 0.7 },
  "acid_slime_small": { shape: "slime", tint: "#a8e07a", scale: 0.7 },
  fungi_beast: { shape: "beast", tint: "#c98fd8", scale: 1 },
  "fat_gremlin": { shape: "humanoid", tint: "#8f8f8f", scale: 1.1 },
  "mad_gremlin": { shape: "humanoid", tint: "#d85f5f", scale: 0.9 },
  "sneaky_gremlin": { shape: "humanoid", tint: "#5f8fd8", scale: 0.9 },
  "shield_gremlin": { shape: "humanoid", tint: "#8fbf5f", scale: 1 },
  "gremlin_wizard": { shape: "humanoid", tint: "#a05fd8", scale: 0.95 },
  slime_boss: { shape: "slime", tint: "#3fa87f", scale: 1.6 },
  "the_guardian": { shape: "construct", tint: "#9aa7b8", scale: 1.5 },
  hexaghost: { shape: "construct", tint: "#6f7fe8", scale: 1.5 },
};

const unknown = new Set<string>();

/** 敌人 id → 外观。**未知 id 不抛**，降级成 placeholder 并记账。 */
export function enemyLook(id: string): EnemyLook {
  const base = LOOKS[id];
  const boss = /boss|guardian|hexaghost/.test(id);
  if (base) return { ...base, boss };
  unknown.add(id);
  return { shape: "placeholder", tint: "#7f8c99", scale: 1, boss };
}

/** 见过但表里没有的敌人 id（闸门断言为空；真出现就是"内容加了怪而外观表没跟上"）。 */
export function unknownEnemyAssets(): string[] {
  return Array.from(unknown).sort();
}

export function resetUnknownEnemyAssets(): void {
  unknown.clear();
}

/** 表里覆盖了多少个 id（诊断用）。 */
export function knownEnemyAssets(): number {
  return Object.keys(LOOKS).length;
}
