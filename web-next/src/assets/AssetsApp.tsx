// 素材库预览页（`assets.html`）：**流水线的看得见那一端**。
//
// 三块：
//
// 1. **三维原型**（16 种）：每种原型画一个"标准身材"的实例 —— 检查几何排列本身；
// 2. **敌人**（清单里全部）：按原型的真实数据画，Boss 带光环、尺寸按清单；
// 3. **二维元素**：卡牌/遗物/药水/状态各自的两位字母徽章（清单里全部）。
//
// 为什么值得单独一页：素材是**生成**的，所以"某个敌人长得像一坨"只能在看的时候发现。
// 闸门 46 读这一页的 DOM/网格数做**覆盖断言**，人看图做**审美判断** —— 两件事分开。

import { Canvas } from "@react-three/fiber";
import { useMemo, useState } from "react";
import { Badge } from "./Badge";
import { FIGURES, type Archetype } from "./geometry";
import { ENEMY_ASSETS, BADGE_ASSETS, ASSET_COUNTS, ARCHETYPES } from "./manifest";
import { archetypeNames, assetCounts, badgeLook, enemyLook, lettersOf } from "./registry";
import { EnemyFigure } from "../stage/EnemyFigure";
import "./assets.css";

type Tab = "archetypes" | "enemies" | "badges";

const BADGE_KINDS = ["cards", "relics", "potions", "statuses"] as const;
const KIND_LABEL = { cards: "卡牌", relics: "遗物", potions: "药水", statuses: "状态" } as const;

/** 按总数算网格：返回每个 index 的世界坐标（居中）。 */
export function gridLayout(total: number, columns: number, spacingX = 2.05, spacingY = 2.0) {
  const rows = Math.max(1, Math.ceil(total / columns));
  return Array.from({ length: total }, (_, index) => {
    const column = index % columns;
    const row = Math.floor(index / columns);
    return [
      (column - (columns - 1) / 2) * spacingX,
      ((rows - 1) / 2 - row) * spacingY,
      0,
    ] as const;
  });
}

function Scene({ tab, columns, selected }: { tab: Tab; columns: number; selected: string }) {
  const ids = useMemo(() => {
    if (tab === "archetypes") return ARCHETYPES.slice();
    if (tab === "enemies") return [selected];   // 敌人页只画选中的那个（61 个塞一起看不清）
    return [];
  }, [tab, selected]);
  const positions = useMemo(() => gridLayout(ids.length, columns), [ids.length, columns]);
  const rows = Math.max(1, Math.ceil(ids.length / columns));
  // 相机距离按行数自适应：4 行时 z≈10，1 行时 z≈4.2（否则单个敌人会缩成一个点）。
  const distance = Math.max(4.2, rows * 1.95);
  return (
    <Canvas key={`${tab}-${selected}`} camera={{ position: [0, 0.4, distance], fov: 45 }} dpr={[1, 1.5]} shadows={false}>
      <ambientLight intensity={0.7} />
      <directionalLight position={[3, 6, 4]} intensity={1.1} />
      <directionalLight position={[-4, 3, -2]} intensity={0.35} color="#7fb0ff" />
      {ids.map((id, index) => {
        const look =
          tab === "archetypes"
            ? { ...enemyLook(id), archetype: id, figure: FIGURES[id], fallback: false }
            : enemyLook(id);
        return (
          <group key={id} position={positions[index]} scale={tab === "enemies" ? 1.6 : 1.25}>
            <EnemyFigure look={look} />
          </group>
        );
      })}
    </Canvas>
  );
}

function ArchetypeList() {
  return (
    <ul className="asset-list" data-archetype-count={ARCHETYPES.length}>
      {archetypeNames().map((name) => {
        const figure: Archetype = FIGURES[name];
        return (
          <li key={name} data-archetype={name} data-parts={figure.parts.length}>
            <code>{name}</code>
            <span className="muted">{figure.note}</span>
            <span className="muted">{figure.parts.length} 个基本体</span>
          </li>
        );
      })}
    </ul>
  );
}

function EnemyList({ selected, onSelect }: { selected: string; onSelect: (id: string) => void }) {
  return (
    <ul className="asset-list" data-enemy-count={ASSET_COUNTS.enemies}>
      {Object.entries(ENEMY_ASSETS).map(([id, asset]) => (
        <li
          key={id}
          data-enemy={id}
          data-archetype={asset.archetype}
          data-boss={asset.boss ? "1" : "0"}
          className={id === selected ? "is-selected" : undefined}
        >
          <button type="button" data-enemy-pick={id} onClick={() => onSelect(id)}>
            看
          </button>
          <code>{id}</code>
          <span className="muted">{asset.archetype}</span>
          <span className="muted">×{asset.scale}</span>
          {asset.boss && <span className="asset-tag">BOSS</span>}
        </li>
      ))}
    </ul>
  );
}

function BadgeGrid() {
  const [kind, setKind] = useState<(typeof BADGE_KINDS)[number]>("cards");
  const rows = Object.keys(BADGE_ASSETS[kind]);
  return (
    <div className="badge-panel">
      <div className="badge-tabs">
        {BADGE_KINDS.map((each) => (
          <button
            key={each}
            type="button"
            className={each === kind ? "badge-tab is-active" : "badge-tab"}
            data-badge-tab={each}
            data-badge-count={Object.keys(BADGE_ASSETS[each]).length}
            onClick={() => setKind(each)}
          >
            {KIND_LABEL[each]} {Object.keys(BADGE_ASSETS[each]).length}
          </button>
        ))}
      </div>
      <div className="badge-grid" data-badge-kind={kind} data-badge-rows={rows.length}>
        {rows.map((id) => {
          const look = badgeLook(kind, id);
          return (
            <div className="badge-cell" key={id} data-badge-id={id}>
              <Badge look={look} size="md" title={id} upgraded={id.endsWith("+")} />
              <code>{id}</code>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function AssetsApp() {
  const [tab, setTab] = useState<Tab>("archetypes");
  const [selected, setSelected] = useState<string>(() => Object.keys(ENEMY_ASSETS)[0]);
  const counts = assetCounts();
  const columns = tab === "archetypes" ? 4 : 6;
  return (
    <div className="assets-shell">
      <header className="assets-head">
        <h1>素材库</h1>
        <p className="muted">
          清单是**生成**的（`python native/build_assets.py`）：敌人 {counts.enemies} · 卡牌 {counts.cards} ·
          遗物 {counts.relics} · 药水 {counts.potions} · 状态 {counts.statuses}
        </p>
        <div className="assets-tabs">
          {(["archetypes", "enemies", "badges"] as Tab[]).map((each) => (
            <button
              key={each}
              type="button"
              className={each === tab ? "assets-tab is-active" : "assets-tab"}
              data-assets-tab={each}
              onClick={() => setTab(each)}
            >
              {each === "archetypes" ? `三维原型 ${ARCHETYPES.length}` : each === "enemies" ? `敌人 ${counts.enemies}` : "二维元素"}
            </button>
          ))}
        </div>
      </header>

      {tab !== "badges" && (
        <div className="assets-stage" data-assets-stage={tab}>
          <Scene tab={tab} columns={columns} selected={selected} />
        </div>
      )}

      <main className="assets-body">
        {tab === "archetypes" && <ArchetypeList />}
        {tab === "enemies" && <EnemyList selected={selected} onSelect={setSelected} />}
        {tab === "badges" && <BadgeGrid />}
        <p className="assets-foot muted">
          两位大写字母由 id 规则生成（`twin_strike` → TS、`strike` → ST、`standard.vulnerable` → SV）；
          换成图标/立绘时只替换 `Badge` 的内部实现，注册表接口不变。
        </p>
      </main>
    </div>
  );
}

/** 闸门 46 读它做覆盖断言（不读 DOM 内部结构）。 */
export function installAssetProbe(): void {
  (window as unknown as { __assets?: unknown }).__assets = {
    counts: assetCounts(),
    archetypes: archetypeNames().map((name) => ({ name, parts: FIGURES[name].parts.length })),
    enemies: Object.entries(ENEMY_ASSETS).map(([id, asset]) => ({ id, ...asset })),
    badges: Object.fromEntries(
      BADGE_KINDS.map((kind) => [kind, Object.keys(BADGE_ASSETS[kind])])
    ),
    letters: (id: string) => lettersOf(id),
    enemyLook: (id: string) => {
      const look = enemyLook(id);
      return { archetype: look.archetype, scale: look.scale, boss: look.boss, fallback: look.fallback, parts: look.figure.parts.length };
    },
  };
}
