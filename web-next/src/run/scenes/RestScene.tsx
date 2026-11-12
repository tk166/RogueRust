// 篝火（`SC-06`，`pending == 1`）：六类选项，可用性由**位掩码**决定。
//
// ## 交互设计
//
// 1. **画哪些按钮由内核的位掩码决定**（`§259`：`Rest 1 | Smith 2 | Recall 4 | Lift 8 | Toke 16 |
//    Dig 32`）。不画"看起来像有但点不动"的按钮 —— 那是最典型的死按钮。
// 2. **休息显示真实回复量**（`rd_run_rest_heal()` 已经算上遗物加成）。页面自己写
//    `hpMax * 30%` 会与遗物加成漂（§344 记过这个缺口）。
// 3. **锻造/抽烟斗要先选牌**：点下去进牌组选择器，选完才算完成。
// 4. **举重显示已经举过几次**（`Girya` 上限 3）。
// 5. **离开**：篝火可以什么都不做就走（内核有 `leave`）。

import type { CampfireOption } from "../models.js";

export interface RestSceneProps {
  readonly options: readonly CampfireOption[];
  readonly restHeal: number;
  readonly heroHp: number;
  readonly heroHpMax: number;
  readonly giryaLifts: number;
  readonly unknownBits: number;
  readonly onRest: () => void;
  readonly onSmith: () => void;
  readonly onToke: () => void;
  readonly onLift: () => void;
  readonly onDig: () => void;
  readonly onRecall: () => void;
  readonly onLeave: () => void;
  readonly busy?: boolean;
}

export function RestScene({
  options,
  restHeal,
  heroHp,
  heroHpMax,
  giryaLifts,
  unknownBits,
  onRest,
  onSmith,
  onToke,
  onLift,
  onDig,
  onRecall,
  onLeave,
  busy = false,
}: RestSceneProps) {
  const handler = (id: CampfireOption["id"]) => {
    switch (id) {
      case "rest":
        return onRest;
      case "smith":
        return onSmith;
      case "toke":
        return onToke;
      case "lift":
        return onLift;
      case "dig":
        return onDig;
      case "recall":
        return onRecall;
      default:
        return null;
    }
  };

  return (
    <section className="scene scene-rest" data-scene="SC-06">
      <header className="scene-head">
        <h2>篝火</h2>
        <p className="scene-sub">
          生命 {heroHp} / {heroHpMax} · 只能做一件事
        </p>
      </header>

      <div className="rest-options" data-rest-option-count={options.length}>
        {options.map((option) => {
          const onClick = handler(option.id);
          const hint =
            option.id === "rest"
              ? `回复 ${restHeal} 点生命`
              : option.id === "lift"
                ? `${option.hint}（已举 ${giryaLifts} 次，上限 3）`
                : option.hint;
          return (
            <button
              key={option.id}
              type="button"
              className="rest-option"
              data-rest-option={option.id}
              disabled={busy || !onClick}
              onClick={onClick ?? undefined}
            >
              <span className="rest-option-label">{option.label}</span>
              <span className="rest-option-hint muted">{hint}</span>
            </button>
          );
        })}
        {options.length === 0 && <p className="muted">这里没有可做的事（内核没给选项）。</p>}
      </div>

      {unknownBits !== 0 && (
        <p className="scene-note" data-rest-unknown-bits={unknownBits}>
          内核给了 UI 不认识的篝火选项（位 {unknownBits}）—— 这是"内核加了新选项而界面没跟上"。
        </p>
      )}

      <button type="button" data-rest-leave onClick={onLeave} disabled={busy}>
        什么都不做 · 离开
      </button>
    </section>
  );
}
