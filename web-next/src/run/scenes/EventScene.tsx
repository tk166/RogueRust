// 事件（`SC-08`，`pending == 5`）：正文 + 按钮，可用性由内核给。
//
// ## 交互设计
//
// 1. **按钮条数由内容决定**（§278：`golden_idol` 第二段是三选一）—— 不写死 2。
// 2. **不可用的按钮画出来但禁用**，并说明原因（§279：`rd_run_event_option_available` 与
//    `rd_run_choose` 判的是同一个函数，所以"显示的能点却没反应"与"藏起来的其实能点"两种错
//    不可能只在一侧出现）。禁用**不是**隐藏：玩家要能看见"有个选项但我不满足条件"。
// 3. **效果用一句话说清**（`heal 7 · gold 20` 这种判别值翻人话）—— 不给玩家猜代价。
// 4. **"选牌"型选项**（`eventNeeds !== 0`）点下去会进牌组选择器（`SC-09`）。

import { eventName, eventOptionLabel, eventText } from "../../i18n/index.js";
import { effectSummary } from "../models.js";

export interface EventOptionView {
  readonly slot: number;
  readonly label: string;
  readonly available: boolean;
  readonly effects: readonly { kind: number; amount: number }[];
}

export interface EventSceneProps {
  readonly eventId: string;
  readonly text: string;
  readonly options: readonly EventOptionView[];
  /** `rd_run_event_needs`：0 无 / 1 删牌 / 2 升级 / 3 变形。 */
  readonly needs: number;
  readonly onChoose: (slot: number) => void;
  readonly busy?: boolean;
}

export function EventScene({ eventId, text, options, needs, onChoose, busy = false }: EventSceneProps) {
  return (
    <section className="scene scene-event" data-scene="SC-08" data-event-id={eventId}>
      <header className="scene-head">
        <h2>{eventName(eventId)}</h2>
        {needs !== 0 && (
          <p className="scene-sub" data-event-needs={needs}>
            {needs === 1 ? "选完还要从牌组删一张" : needs === 2 ? "选完还要升级一张" : "选完还要变形一张"}
          </p>
        )}
      </header>

      <p className="event-text" data-event-text>
        {eventText(eventId, text) || "（这个事件没有正文）"}
      </p>

      <div className="event-options" data-event-option-count={options.length}>
        {options.map((option) => (
          <button
            key={option.slot}
            type="button"
            className={option.available ? "event-option" : "event-option is-disabled"}
            data-event-option={option.slot}
            data-available={option.available ? "1" : "0"}
            disabled={busy || !option.available}
            title={option.available ? undefined : "这个选项现在不满足条件"}
            onClick={() => onChoose(option.slot)}
          >
            <span className="event-option-label">
              {option.label ? eventOptionLabel(option.label) : `选项 ${option.slot + 1}`}
            </span>
            {/* §382：`-1`（没有效果码）时 `effectSummary` 给空串 ⇒ **不画**这一行，
                而不是画"未知效果 -1"。选项自己的文字已经把话说清楚了。 */}
            {effectSummary(option.effects) !== "" && (
              <span className="event-option-effect muted">{effectSummary(option.effects)}</span>
            )}
            {!option.available && <span className="event-option-why">不满足条件</span>}
          </button>
        ))}
        {options.length === 0 && <p className="muted">这个事件没有选项。</p>}
      </div>
    </section>
  );
}
