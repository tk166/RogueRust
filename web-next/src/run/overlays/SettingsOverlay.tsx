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

import { useState } from "react";
import type { RunState } from "../RunStore";

export interface SettingsOverlayProps {
  readonly state: RunState;
  readonly onClose: () => void;
  /** 动效偏好：`"on"` / `"off"` / `"auto"`（跟随系统）。 */
  readonly motion: "on" | "off" | "auto";
  readonly onMotionChange: (value: "on" | "off" | "auto") => void;
  /** 导出当前这一局（内核写的档案文本）；`null` = 拒绝（战斗中/没有局）。 */
  readonly onExport: () => string | null;
  /** 从档案文本回档；返回内核的返回码与人话原因。 */
  readonly onImport: (text: string) => { code: number; message: string };
  /** 导出回放脚本（内核写）；`null` = 拒绝（战斗中/没有局）。 */
  readonly onExportReplay: () => string | null;
  /** 导入回放脚本并**逐步对拍**。 */
  readonly onImportReplay: (text: string) => { code: number; checked: number; diverged: number; message: string };
}

export function SettingsOverlay({
  state,
  onClose,
  motion,
  onMotionChange,
  onExport,
  onImport,
  onExportReplay,
  onImportReplay,
}: SettingsOverlayProps) {
  const [archive, setArchive] = useState("");
  const [importText, setImportText] = useState("");
  const [result, setResult] = useState<string | null>(null);
  const [replayOut, setReplayOut] = useState("");
  const [replayIn, setReplayIn] = useState("");
  const [replayResult, setReplayResult] = useState<string | null>(null);
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

        {/* 动效开关：plan P6 要求"支持减少动态效果选项"。写 localStorage，下一场战斗生效
            （导演在挂载时读一次，中途切换会让正在播的动画突然消失）。 */}
        <section className="settings-section" data-settings-motion={motion}>
          <h4>动效</h4>
          <div className="settings-motion">
            {(["auto", "on", "off"] as const).map((value) => (
              <button
                key={value}
                type="button"
                className={motion === value ? "motion-option is-active" : "motion-option"}
                data-motion-option={value}
                onClick={() => onMotionChange(value)}
              >
                {value === "auto" ? "跟随系统" : value === "on" ? "开" : "关（省电/不晕）"}
              </button>
            ))}
          </div>
          <p className="muted">下一场战斗生效。</p>
        </section>

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

        {/* 存档 / 回档（第十五轮 Review §6）：默认入口切到新 UI 之后，这一条从"可以没有"
            变成"必须有"——否则玩家刷新一下就丢局。 */}
        <section className="settings-section" data-settings-archive>
          <h4>存档</h4>
          <div className="settings-archive-actions">
            <button
              type="button"
              data-archive-export
              onClick={() => {
                const text = onExport();
                setArchive(text ?? "");
                setResult(text === null ? "导出被拒绝（战斗中不能存档）" : `已导出 ${text.length} 字节`);
              }}
            >
              导出这一局
            </button>
            <button
              type="button"
              data-archive-copy
              disabled={archive === ""}
              onClick={() => {
                void navigator.clipboard?.writeText(archive);
                setResult("已复制到剪贴板");
              }}
            >
              复制
            </button>
          </div>
          <textarea
            className="settings-archive-box"
            data-archive-out
            readOnly
            rows={4}
            value={archive}
            placeholder="点「导出这一局」之后，档案会出现在这里"
          />

          <textarea
            className="settings-archive-box"
            data-archive-in
            rows={4}
            value={importText}
            placeholder="把档案粘到这里，再点「回档」"
            onChange={(event) => setImportText(event.target.value)}
          />
          <div className="settings-archive-actions">
            <button
              type="button"
              data-archive-import
              disabled={importText.trim() === ""}
              onClick={() => {
                const outcome = onImport(importText.trim());
                setResult(`${outcome.message}（code ${outcome.code}）`);
              }}
            >
              回档
            </button>
            {result !== null && <span className="muted" data-archive-result>{result}</span>}
          </div>
        </section>

        {/*
          回放（`rd_run_script_*` / `rd_run_replay_*`）：与存档**不同** —— 存档描述"现在这一局"，
          脚本描述"这一局是怎么走到现在的"（每一步都带指纹）。导入时内核**逐步对拍**，
          所以"分叉在第几步"是可说的，不是"看起来不一样"。
        */}
        <section className="settings-section" data-settings-replay>
          <h4>回放</h4>
          <div className="settings-archive-actions">
            <button
              type="button"
              data-replay-export
              onClick={async () => {
                const text = onExportReplay();
                setReplayOut(text ?? "");
                if (text === null) {
                  setReplayResult("导出被拒绝（战斗中不能导出：一场战斗只有结果进脚本）");
                  return;
                }
                // "导出（至剪贴板）"：先尝试写剪贴板，失败也把文本留在下面的框里。
                let copied = false;
                try {
                  await navigator.clipboard?.writeText(text);
                  copied = true;
                } catch {
                  copied = false;
                }
                setReplayResult(`已导出 ${text.length} 字节${copied ? "，已复制到剪贴板" : "（剪贴板不可用，请手动复制下面的文本）"}`);
              }}
            >
              导出回放（至剪贴板）
            </button>
            <button
              type="button"
              data-replay-copy
              disabled={replayOut === ""}
              onClick={async () => {
                try {
                  await navigator.clipboard?.writeText(replayOut);
                  setReplayResult("已复制到剪贴板");
                } catch {
                  setReplayResult("剪贴板不可用，请手动复制");
                }
              }}
            >
              再复制一次
            </button>
          </div>
          <textarea
            className="settings-archive-box"
            data-replay-out
            readOnly
            rows={4}
            value={replayOut}
            placeholder="点「导出回放」之后，脚本会出现在这里（头部是 RDR1,S,seed,asc,内容指纹）"
          />

          <textarea
            className="settings-archive-box"
            data-replay-in
            rows={4}
            value={replayIn}
            placeholder="把回放脚本粘到这里，再点「导入回放」——内核会**逐步对拍**"
            onChange={(event) => setReplayIn(event.target.value)}
          />
          <div className="settings-archive-actions">
            <button
              type="button"
              data-replay-import
              disabled={replayIn.trim() === ""}
              onClick={() => {
                const outcome = onImportReplay(replayIn.trim());
                setReplayResult(outcome.message);
              }}
            >
              导入回放（逐步对拍）
            </button>
            {replayResult !== null && (
              <span className="muted" data-replay-result>
                {replayResult}
              </span>
            )}
          </div>
          <p className="muted">
            脚本自带 seed / 进阶 / 内容指纹，所以导入**不需要先开一局**；内容版本不同会被直接拒绝。
          </p>
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
