// 地图屏（`SC-02`）：节点图、连线、可达高亮、Boss 哨兵、点一下就走。
//
// ## 交互设计（为什么这样）
//
// 1. **只画可达高亮，其余一律不可点**：地图上"能去哪"是内核给的（`map_node` 的 `reachable`），
//    UI 不自己算"应该能到"。不可点的节点**不是**禁用按钮（灰按钮看起来像 bug），而是普通图标，
//    点上去给一句"这一步到不了"，让玩家知道是规则限制而不是界面坏了。
// 2. **单击就走**（不做二次确认）：可点集合只有 2–3 个，且内核会再校验一次；多一次确认只是
//    让每一步变慢。误触的代价是"走了一格"，而格子本身是玩家选的。
// 3. **当前节点有"你在这里"**：地图上必须能一眼找到自己 —— 否则打完一场回来不知道站在哪。
// 4. **向上滚动**（第 1 行在底部）：与 StS 一致，也与"往上爬"的直觉一致。
// 5. **Boss 哨兵单独一行**：Boss 不是"又一个节点"，它标着这一幕的终点。
//
// 布局用归一化坐标（`MapModel.layout`）+ CSS 百分比，连线用 SVG。这样闸门可以只断言模型
// （谁连谁、谁可达），像素留给 CSS。

import { useMemo, useRef, useEffect } from "react";
import {
  NODE_KIND,
  nodeKindGlyph,
  nodeKindLabel,
  type MapModel,
  type MapNode,
} from "../observe.js";
import type { RunSnapshot } from "../observe.js";

export interface MapSceneProps {
  readonly run: RunSnapshot;
  readonly map: MapModel;
  readonly onEnter: (index: number) => void;
  readonly onBlocked: (index: number) => void;
  /**
   * Boss 哨兵这一步能不能进（`rd_run_action_arg` 里有 `BOSS_NODE`）。
   *
   * ⚠️ 它**不在** `map.nodes` 里 —— 第 16 层在地图之外。所以这个徽章不是"装饰"，
   * 它是第 15 层之后**唯一**的下一步。
   */
  readonly bossReachable: boolean;
  readonly bossIndex: number;
  /** 第几幕（§370）。换幕后 `floor` 是 0，所以标题必须带上幕数。 */
  readonly act: number;
  /** 遗物欠账/局终等覆盖层要求地图**不可操作**。 */
  readonly inert?: boolean;
}

const BOSS_ROW_KINDS = new Set<number>([NODE_KIND.boss, NODE_KIND.bossChest]);

export function MapScene({
  run,
  map,
  onEnter,
  onBlocked,
  bossReachable,
  bossIndex,
  act,
  inert = false,
}: MapSceneProps) {
  const current = run.node;
  const scrollRef = useRef<HTMLDivElement | null>(null);

  // 打到新的一层后自动滚到当前节点附近（不然玩家要自己找）。
  //
  // ⚠️ `current < 0`（还没出发）时**滚到底部**：第 1 行在底部（往上爬），开局的可选节点
  // 就在最下面。不滚的话玩家打开地图看到的是**地图顶端**（Boss 那一头），得自己往下翻
  // ——窄屏（390×844）上这就是"看不到任何可点的东西"（闸门 31 实测：触摸点在视口外）。
  useEffect(() => {
    const container = scrollRef.current;
    if (!container) return;
    if (current < 0) {
      container.scrollTop = container.scrollHeight;
      return;
    }
    const marker = container.querySelector<HTMLElement>(`[data-node="${current}"]`);
    marker?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [current]);

  // 只画"从某节点出发、且目标存在"的边；重复边（多条路径同一条边）去重。
  //
  // ⚠️ 哪条边高亮 = **从当前节点出发、且目标可达**的那条（"你现在能走的这一步"）。
  // 第一版写的是 `to.reachable`（目标可达就高亮），于是开局时第 1 行的节点全部可达、
  // 而它们**没有入边** ⇒ 一条高亮边都画不出来（闸门 34 第一次跑就是 0 条）。
  const edges = useMemo(() => {
    const seen = new Set<string>();
    const out: { from: MapNode; to: MapNode; live: boolean }[] = [];
    for (const node of map.nodes) {
      for (const target of node.edges) {
        const to = map.byIndex.get(target);
        if (!to) continue;
        const key = `${node.index}->${target}`;
        if (seen.has(key)) continue;
        seen.add(key);
        out.push({ from: node, to, live: node.index === current && to.reachable });
      }
    }
    return out;
  }, [map, current]);

  // 行分组：每行一个 `data-row`，从最后一行往前画（顶部是 Boss）。
  //
  // ⚠️ **DOM 顺序 == 视觉顺序**（大行号在前 = 屏幕上方）。第一版靠 CSS
  // `flex-direction: column-reverse` 把第 1 行翻到底部，而 SVG 连线用的是
  // `y = (1 - row/lastRow)` —— **两层互为镜像**，于是"节点在这一行、连线连到下一行"
  // （玩家实测：高亮的线往**下**走，可达节点却在上面）。现在改成：
  // 节点**绝对定位**在 `map.layout` 给的归一化坐标上，与连线**同一个公式**，
  // 所以"节点和线对不上"在结构上不可能再发生（闸门 54 逐条比对像素）。
  const rows = useMemo(() => {
    const byRow = new Map<number, MapNode[]>();
    for (const node of map.nodes) {
      const list = byRow.get(node.row) ?? [];
      list.push(node);
      byRow.set(node.row, list);
    }
    return Array.from(byRow.entries())
      .sort((a, b) => b[0] - a[0])
      .map(([row, nodes]) => ({ row, nodes: nodes.sort((a, b) => a.col - b.col) }));
  }, [map]);

  /**
   * 归一化坐标 → CSS 位置。**连线与节点共用这一个函数**（同一个事实只有一个来源）。
   *
   * `--map-pad` 是画布内边距：节点中心落在 `[pad, 100% - pad]` 区间里，SVG 也用同一个内边距
   * （`inset: var(--map-pad)`），所以 `x=0` 在两边是同一个像素。
   */
  const place = (value: number) =>
    `calc(var(--map-pad) + (100% - 2 * var(--map-pad)) * ${value.toFixed(6)})`;

  const boss = map.nodes.find((node) => BOSS_ROW_KINDS.has(node.kind)) ?? null;

  return (
    <section className="scene scene-map" data-scene="SC-02">
      <header className="scene-head">
        <h2>
          第 {act} 幕 · 第 {run.floor} 层 <span className="muted">/ {map.rows}</span>
        </h2>
        <p className="scene-sub">
          点击高亮节点前进 · 共 {map.nodes.filter((node) => node.reachable).length} 个可去之处
        </p>
      </header>

      {/* Boss 哨兵：可点时是**按钮**（第 15 层之后唯一的下一步），不可点时只是徽章。 */}
      {bossReachable && !inert ? (
        <button
          type="button"
          className="map-boss is-reachable"
          data-boss-sentinel={bossIndex}
          data-boss-reachable="1"
          onClick={() => onEnter(bossIndex)}
        >
          <span aria-hidden>{nodeKindGlyph(NODE_KIND.boss)}</span>
          <span>{nodeKindLabel(NODE_KIND.boss)}（可前往）</span>
        </button>
      ) : (
        <div className="map-boss" data-boss-sentinel={boss ? boss.index : -1}>
          <span aria-hidden>{nodeKindGlyph(NODE_KIND.boss)}</span>
          <span>{nodeKindLabel(NODE_KIND.boss)}</span>
        </div>
      )}

      <div className="map-scroll" ref={scrollRef}>
        <div className="map-canvas" style={{ ["--map-rows" as string]: String(map.rows) }}>
          {/* 连线在底层：`pointer-events: none` 保证不会挡住节点的点击。
              坐标与节点同源（`place()` + `--map-pad`），见上面的注释。 */}
          <svg className="map-edges" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden>
            {edges.map((edge) => {
              const from = map.layout.get(edge.from.index);
              const to = map.layout.get(edge.to.index);
              if (!from || !to) return null;
              return (
                <line
                  key={`${edge.from.index}-${edge.to.index}`}
                  data-edge={`${edge.from.index}-${edge.to.index}`}
                  data-live={edge.live ? "1" : "0"}
                  x1={from.x * 100}
                  y1={(1 - from.y) * 100}
                  x2={to.x * 100}
                  y2={(1 - to.y) * 100}
                  className={edge.live ? "map-edge is-live" : "map-edge"}
                  vectorEffect="non-scaling-stroke"
                />
              );
            })}
          </svg>

          <div className="map-field">
          {rows.map(({ row, nodes }) => (
            <div className="map-row" data-row={row} key={row}>
              {nodes.map((node) => {
                const isCurrent = node.index === current;
                const clickable = node.reachable && !inert;
                const spot = map.layout.get(node.index) ?? { x: 0.5, y: 0 };
                return (
                  <button
                    key={node.index}
                    type="button"
                    className={[
                      "map-node",
                      `kind-${node.kind}`,
                      node.reachable ? "is-reachable" : "",
                      isCurrent ? "is-current" : "",
                    ]
                      .filter(Boolean)
                      .join(" ")}
                    data-node={node.index}
                    data-kind={node.kind}
                    data-reachable={node.reachable ? "1" : "0"}
                    data-current={isCurrent ? "1" : "0"}
                    aria-label={`${nodeKindLabel(node.kind)}${node.reachable ? "（可前往）" : ""}${
                      isCurrent ? "（你在这里）" : ""
                    }`}
                    aria-disabled={!clickable}
                    // 与 `<line>` 用同一个公式：`x` 向右、`y` 归一化是"第 1 行在底部"，
                    // 所以屏幕纵向要取 `1 - y`。
                    style={{ left: place(spot.x), top: place(1 - spot.y) }}
                    onClick={() => (clickable ? onEnter(node.index) : onBlocked(node.index))}
                  >
                    <span className="map-node-glyph" aria-hidden>
                      {nodeKindGlyph(node.kind)}
                    </span>
                    <span className="map-node-label">{nodeKindLabel(node.kind)}</span>
                    {isCurrent && <span className="map-node-here">你在这里</span>}
                  </button>
                );
              })}
            </div>
          ))}
          </div>
        </div>
      </div>
    </section>
  );
}
