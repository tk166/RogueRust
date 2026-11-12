// 投影出来的**屏幕布局**：DOM 覆盖层与闸门都读这里。
//
// 为什么要一个模块级的可变对象：卡牌位置每帧都在变（拖拽、选中抬起、扇形呼吸），
// 走 React state 就是 60Hz 重渲染。所以 3D 侧 `useFrame` 直接写，DOM 侧 rAF 直接读并改
// `style.transform`。**唯一的写者是 `Stage` 里的那个 `useFrame`**（§纪律 2：一个元素一个写者）。
//
// 闸门读它来知道"该往哪个像素点按下去" —— 这样闸门不需要猜布局，也不需要把布局算法抄第二份。

export interface CardScreen {
  slot: number;
  /** 卡片中心（CSS 像素，相对视口）。 */
  x: number;
  y: number;
  /** 卡片在屏幕上的宽高（CSS 像素）。 */
  w: number;
  h: number;
  /**
   * **牌面看起来有多宽**：上、下两条边投影长度的均值。
   *
   * 为什么不是 `w`：`w` 是四个角的外接矩形，牌斜着摆时比牌面宽（±15° 时约宽 30%）。
   * 文字要落在**牌面上**，所以用这个；`w` 只用来算占位与叠放。
   */
  faceW: number;
  /**
   * **露出来的宽度**：`min(w, 相邻牌中心的间距)`。
   *
   * 为什么不是 `w`：390px 宽的手机上，每张牌仍然有约 105px 的矩形，但相邻牌只隔约 33px
   * —— 也就是说 70px 被右边的牌压住了。决定"能不能读"的是这 33px，不是 105px。
   * 第一版拿 `w` 做判据，于是紧凑态**从不触发**，10 个中文标题叠在一起糊成一团。
   */
  visibleW: number;
  /**
   * **命中点**：按下去能选中这张牌的那个像素（不是牌心）。
   *
   * 叠放顺序单调（右压左）时，每张牌只露出左边一条；牌心可能被右边的牌盖住。
   * 这个点由布局算（它知道露出多少），**闸门不该自己猜**。
   */
  hitX: number;
  hitY: number;
  /** 是否被当前拖拽/选中状态抬起（抬起的牌画在最上面）。 */
  lifted: boolean;
}

export interface EnemyScreen {
  slot: number;
  x: number;
  y: number;
  /** 敌人身体的屏幕半径（CSS 像素），闸门用它挑一个"肯定命中"的点。 */
  r: number;
}

export interface ScreenLayout {
  cards: CardScreen[];
  enemies: EnemyScreen[];
  /**
   * 版面区域（CSS 像素）：HUD / 战场 / 手牌 / 操作栏。
   * 由 `computeCombatLayout` 算出，**闸门用它断言**，不读硬编码常数。
   */
  regions: import("./combatLayout").CombatRegions | null;
  width: number;
  height: number;
  /** 已渲染的帧数；闸门等它 > 0 才算"投影有效"。 */
  frames: number;
  /**
   * 画布在**页面**里的原点（CSS 像素）。
   *
   * `cards`/`enemies` 里的坐标已经是**视口**坐标（与 `event.clientX/clientY` 同一套），
   * 所以消费方通常不需要它；它存在是为了"从视口坐标反推画布局部坐标"这类诊断。
   */
  originX: number;
  originY: number;
}

export const layout: ScreenLayout = {
  cards: [],
  enemies: [],
  regions: null,
  width: 0,
  height: 0,
  frames: 0,
  originX: 0,
  originY: 0,
};
