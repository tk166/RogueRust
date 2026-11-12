"""i18n/index.ts：加事件表（名字/正文/选项标签）+ 事件屏改用它们。"""

import io


def patch(path, pairs):
    t = io.open(path, encoding='utf-8').read()
    for label, old, new in pairs:
        assert t.count(old) == 1, '%s %s: 命中 %d 次' % (path, label, t.count(old))
        t = t.replace(old, new)
    io.open(path, 'w', encoding='utf-8', newline='\n').write(t)
    print('patched', path)


patch(
    'web-next/src/i18n/index.ts',
    [
        (
            'table union',
            'export type I18nTable = "cards" | "relics" | "potions" | "monsters" | "statuses";',
            'export type I18nTable = "cards" | "relics" | "potions" | "monsters" | "statuses" | "events";',
        ),
        (
            'tables map',
            '''  statuses: zh.statuses as Record<string, Entry>,
};''',
            '''  statuses: zh.statuses as Record<string, Entry>,
  events: zh.events as Record<string, Entry>,
};''',
        ),
        (
            'fallbacks map',
            '''  statuses: new Set(),
};''',
            '''  statuses: new Set(),
  events: new Set(),
};

/**
 * 事件**选项标签**的英文 → 中文。
 *
 * ⚠️ 与上面的 `Entry` 表不同：选项标签不是 id，是内容里的英文短句（`Take it` / `[Reach Inside]`），
 * 所以它是**一张纯映射表**（来源见 `native/zh_events.py` 的文件头：能对上官方中文的用官方，
 * 对不上的手译并标注）。查不到就回退英文，并单独计数。
 */
const EVENT_LABELS = zh.eventLabels as Record<string, string>;
const eventLabelFallbacks = new Set<string>();''',
        ),
        (
            'helpers',
            '''/** 清空回退记录（闸门每次断言前重置，避免上一次的计数污染）。 */''',
            '''/**
 * 事件显示名。没有条目时回退到 id 的末段（`golden_idol` → `golden idol`），并记一次回退。
 */
export function eventName(id: string): string {
  const found = entry("events", id);
  if (found && found.name) return found.name;
  return id.replace(/_/g, " ");
}

/**
 * 事件正文：有官方中文就用它，否则用**内容给的英文**（`fallback`）。
 *
 * ⚠️ 子节点（`golden_idol.boulder` 这类）没有官方中文来源 —— 它们只有内容里的英文
 * `TextKey`。所以这里显式收一个 fallback 并**计数**：静默显示英文会让"没翻译"看起来像
 * "本来就这样"。
 */
export function eventText(id: string, fallback: string): string {
  const found = entry("events", id);
  if (found && found.text) return found.text;
  if (fallback) eventLabelFallbacks.add(`text:${id}`);
  return fallback;
}

/** 事件选项标签：英文 → 中文（查不到回退英文并计数）。 */
export function eventOptionLabel(label: string): string {
  const found = EVENT_LABELS[label];
  if (found) return found;
  eventLabelFallbacks.add(label);
  return label;
}

/** 事件 i18n 的回退计数（闸门用预算断言）。 */
export function eventI18nFallbacks(): { texts: number; labels: number; labelsSample: string[] } {
  const labels = Array.from(eventLabelFallbacks).filter((key) => !key.startsWith("text:"));
  const texts = Array.from(eventLabelFallbacks).filter((key) => key.startsWith("text:"));
  return { texts: texts.length, labels: labels.length, labelsSample: labels.slice(0, 20) };
}

/** 清空回退记录（闸门每次断言前重置，避免上一次的计数污染）。 */''',
        ),
        (
            'reset also clears labels',
            '''export function resetCoverage(): void {
  for (const table of Object.keys(fallbacks) as I18nTable[]) fallbacks[table].clear();
}''',
            '''export function resetCoverage(): void {
  for (const table of Object.keys(fallbacks) as I18nTable[]) fallbacks[table].clear();
  eventLabelFallbacks.clear();
}''',
        ),
    ],
)

patch(
    'web-next/src/run/scenes/EventScene.tsx',
    [
        (
            'import i18n',
            '''import { effectSummary } from "../models.js";''',
            '''import { eventName, eventOptionLabel, eventText } from "../../i18n/index.js";
import { effectSummary } from "../models.js";''',
        ),
        (
            'drop local title',
            '''/** 事件 id → 中文标题。内容侧没有事件表，就用 id（**不假装翻译过**）。 */
function eventTitle(id: string): string {
  const dot = id.lastIndexOf(".");
  const tail = dot >= 0 ? id.slice(dot + 1) : id;
  return tail.replace(/_/g, " ");
}

''',
            '''''',
        ),
        (
            'use i18n title',
            '''        <h2>{eventTitle(eventId)}</h2>''',
            '''        <h2>{eventName(eventId)}</h2>''',
        ),
        (
            'use i18n text',
            '''      <p className="event-text" data-event-text>
        {text || "（这个事件没有正文）"}
      </p>''',
            '''      <p className="event-text" data-event-text>
        {eventText(eventId, text) || "（这个事件没有正文）"}
      </p>''',
        ),
        (
            'use i18n labels',
            '''            <span className="event-option-label">{option.label || `选项 ${option.slot + 1}`}</span>''',
            '''            <span className="event-option-label">
              {option.label ? eventOptionLabel(option.label) : `选项 ${option.slot + 1}`}
            </span>''',
        ),
    ],
)
print('done')
