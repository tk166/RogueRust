// 标题屏（`SC-00`）：种子 + 进阶 + 开始。
//
// ## 交互设计
//
// 1. **种子是数字输入框**，默认 `1`：可复现是这套工程的硬要求（闸门全用它），所以"看得到、
//    改得了"比"随机一个漂亮的"重要。留空 ⇒ 由内核给一个（`rd_run_start` 收 i32）。
// 2. **进阶用滑杆 0..20**：0 是标准，20 是满配；滑杆比下拉快，且两端有文字锚点。
// 3. **一个主按钮**："开始爬塔"。没有"继续"—— 没有存档，画一个假的继续按钮就是骗人。
// 4. ⚠️ **不要用 seed 哨兵判"有没有局"**：`i32::MIN` 是一个合法 seed（`docs/ui-state-model.md`
//    第 1 行专门写了）。所以这一屏的存在与否由 `rd_run_exists()` 决定，不是由这里的输入框决定。

import { useState } from "react";

export interface TitleSceneProps {
  readonly onStart: (seed: number, ascension: number) => void;
  /** 上一次用的种子（局终重开时回填，避免"每次都要重输"）。 */
  readonly lastSeed?: number;
  readonly lastAscension?: number;
  /** 局终后的重开文案不同。 */
  readonly restart?: boolean;
  /**
   * 有没有可继续的自动存档（`localStorage` 里内核写的那一份）。
   *
   * 有就多一个"继续上次"按钮，并显示第几幕/第几层/HP —— 玩家刷新/关掉浏览器之后
   * 能一眼看出"刚才那局还在"。
   */
  readonly resume?: {
    readonly act: number;
    readonly floor: number;
    readonly health: number;
    readonly healthMax: number;
  } | null;
  readonly onResume?: () => void;
}

const DEFAULT_SEED = 1;

export function TitleScene({
  onStart,
  lastSeed,
  lastAscension,
  restart = false,
  resume = null,
  onResume,
}: TitleSceneProps) {
  const [seedText, setSeedText] = useState(String(lastSeed ?? DEFAULT_SEED));
  const [ascension, setAscension] = useState(lastAscension ?? 0);

  const parsed = Number(seedText.trim());
  // ⚠️ 空串会让 `Number("")` 变成 0 —— 0 是一个合法种子，但"空输入框"不该等于"种子 0"。
  const seedValid = seedText.trim() !== "" && Number.isInteger(parsed) && Number.isFinite(parsed);

  return (
    <section className="scene scene-title" data-scene="SC-00">
      <h1>RogueRust</h1>
      <p className="scene-sub">一座塔 · 一副牌 · 一条往上爬的路</p>

      {resume && onResume && (
        <button type="button" className="primary title-resume" data-resume onClick={onResume}>
          继续上次（第 {resume.act} 幕 · 第 {resume.floor} 层 · 生命 {resume.health}/{resume.healthMax}）
        </button>
      )}

      <div className="title-form">
        <label className="field">
          <span>种子</span>
          <input
            type="text"
            inputMode="numeric"
            value={seedText}
            data-seed-input
            onChange={(event) => setSeedText(event.target.value)}
            aria-invalid={!seedValid}
          />
        </label>
        <label className="field">
          <span>
            进阶 <b data-ascension-value>{ascension}</b>
          </span>
          <input
            type="range"
            min={0}
            max={20}
            step={1}
            value={ascension}
            data-ascension-input
            onChange={(event) => setAscension(Number(event.target.value))}
          />
        </label>
        <button
          type="button"
          className="primary"
          data-start
          disabled={!seedValid}
          onClick={() => onStart(parsed, ascension)}
        >
          {restart ? "再来一局" : "开始爬塔"}
        </button>
        {!seedValid && <p className="field-error">种子要是一个整数（可以为负）</p>}
      </div>
    </section>
  );
}
