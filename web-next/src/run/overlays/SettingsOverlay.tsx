// 设置/诊断面板：种子、进阶、场景、对账、牌组、遗物、日志。
//
// ## 为什么把诊断放在玩家能看见的地方
//
// 这一版里"对账失败"和"未知相位"是**必须**让玩家看到的事实（否则界面会看起来正常地错下去）。
// 顶栏已经有一条红条，但详情（哪一条不一致、内核给了什么相位）需要一个落脚点。
// 所以设置面板同时也是诊断面板 —— 不是开发菜单，是**这一版的可观测性**。
//
// ## 交互
//
// * Esc / 关闭按钮收起；
// * 不提供"改状态"的按钮（没有隐藏的作弊入口：那会让闸门绕过整个路由）。

import type { RunState } from "../RunStore";

export interface SettingsOverlayProps {
  readonly state: RunState;
  readonly onClose: () => void;
}

export function SettingsOverlay({ state, onClose }: SettingsOverlayProps) {
  const { run, scene, pending } = state;
  return (
    <div className="run-overlay" data-settings>
      <div className="run-overlay-card run-settings">
        <header className="deck-select-head">
          <h3>设置与诊断</h3>
          <p className="muted">Esc 关闭</p>
        </header>

        <dl className="settings-grid">
          <div>
            <dt>种子</dt>
            <dd data-settings-seed>{state.seed}</dd>
          </div>
          <div>
            <dt>进阶</dt>
            <dd data-settings-ascension>{state.ascension}</dd>
          </div>
          <div>
            <dt>场景</dt>
            <dd data-settings-scene>{scene.base}</dd>
          </div>
          <div>
            <dt>相位</dt>
            <dd data-settings-pending>{pending}</dd>
          </div>
          <div>
            <dt>层数</dt>
            <dd>{run?.floor ?? 0}</dd>
          </div>
          <div>
            <dt>生命</dt>
            <dd>
              {run?.health ?? 0} / {run?.healthMax ?? 0}
            </dd>
          </div>
        </dl>

        <section className="settings-section" data-settings-violations={state.violations.length}>
          <h4>对账（{state.violations.length} 条）</h4>
          {state.violations.length === 0 ? (
            <p className="muted">一致。</p>
          ) : (
            <ul>
              {state.violations.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          )}
        </section>

        <section className="settings-section" data-settings-relics={state.relics.length}>
          <h4>遗物（{state.relics.length}）</h4>
          <p className="muted">{state.relics.join("、") || "无"}</p>
        </section>

        <section className="settings-section" data-settings-potions={state.potions.length}>
          <h4>药水（{state.potions.length}）</h4>
          <p className="muted">{state.potions.join("、") || "无"}</p>
        </section>

        <section className="settings-section">
          <h4>最近日志</h4>
          <ul className="settings-log">
            {state.log.slice(-8).map((entry) => (
              <li key={entry.seq} className={`is-${entry.kind}`}>
                {entry.text}
              </li>
            ))}
          </ul>
        </section>

        <button type="button" data-settings-close onClick={onClose}>
          关闭
        </button>
      </div>
    </div>
  );
}
