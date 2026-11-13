"""自动存档：`localStorage` 里存内核写的档案 + 标题页"继续上次"。

## 设计（与 §368 的手动导出/导入共用同一条内核路径）

* **写**：`refresh()` 末尾（有新状态时）调 `archive_fill` → 文本 → `localStorage`。
  与上次存的文本相同就跳过（`archive_fill` 很便宜，但没必要每帧写盘）。
* **战斗中不写**：内核**拒绝**战斗中存档（`CombatState` 不进档案），所以 `inFight` 时直接跳过 ——
  结果是"战斗中刷新 = 回到开战前"，这是**诚实**的行为（而不是假装存住了）。
* **读**：标题页有 `继续上次`（显示第几幕/第几层/HP）。点它走 `importArchive`（内核校验
  全有或全无），坏档案会被拒绝并**清掉**，不留在那里反复失败。
* **清**：局终（`over == 1`）清掉 —— 死了的局不该还能"继续"。
"""

import io


def patch(path, pairs):
    t = io.open(path, encoding='utf-8').read()
    for label, old, new in pairs:
        assert t.count(old) == 1, '%s %s: 命中 %d 次' % (path, label, t.count(old))
        t = t.replace(old, new)
    io.open(path, 'w', encoding='utf-8', newline='\n').write(t)
    print('patched', path)


patch('web-next/src/run/RunStore.ts', [
    (
        'const',
        '''export interface LogEntry {''',
        '''/** 自动存档的键（`localStorage`）。 */
const AUTOSAVE_KEY = "rd.autosave";

/** 标题页"继续上次"要显示的东西（都是**存的时候**的快照，读不到就当没有）。 */
export interface ResumeInfo {
  readonly text: string;
  readonly act: number;
  readonly floor: number;
  readonly health: number;
  readonly healthMax: number;
  readonly at: number;
}

export interface LogEntry {''',
    ),
    (
        'fields',
        '''  /** 关动画（`?motion=off` / 系统偏好）：幕布直接不播。 */
  private readonly motionOff: boolean;''',
        '''  /** 关动画（`?motion=off` / 系统偏好）：幕布直接不播。 */
  private readonly motionOff: boolean;
  /** 上一次写进 `localStorage` 的档案文本（相同就不重写）。 */
  private lastAutosave: string | null = null;''',
    ),
    (
        'autosave call',
        '''    // 第一次出现违约就**钉住**（粘性）。之后即使 `violations` 变空也不解冻。
    if (this.state.violations.length > 0 && this.frozenReason === null) {
      this.frozenReason = this.state.violations[0];
    }''',
        '''    // 第一次出现违约就**钉住**（粘性）。之后即使 `violations` 变空也不解冻。
    if (this.state.violations.length > 0 && this.frozenReason === null) {
      this.frozenReason = this.state.violations[0];
    }
    // 自动存档：**每次状态变化之后**（局终就清掉）。
    this.autosave();''',
    ),
    (
        'autosave methods',
        '''  /** 关掉幕布（点一下 / 1.6 秒到）。 */''',
        '''  /**
   * 写自动存档。**战斗中不写**（内核拒绝：`CombatState` 不进档案）。
   *
   * 失败一律**安静**（隐私模式、配额满）—— 存档是便利，不是玩法；但局终要清，
   * 否则"死了的局还能继续"。
   */
  private autosave(): void {
    if (typeof window === "undefined") return;
    try {
      if (this.state.overWhy === 1 || this.state.overWhy === 2) {
        window.localStorage.removeItem(AUTOSAVE_KEY);
        this.lastAutosave = null;
        return;
      }
      const run = this.state.run;
      if (!run || this.host.run().inFight) return;
      const len = this.host.archiveFill();
      if (len <= 0) return;
      const text = this.host.readArchive(len);
      if (text === this.lastAutosave) return;
      this.lastAutosave = text;
      window.localStorage.setItem(
        AUTOSAVE_KEY,
        JSON.stringify({
          v: 1,
          at: Date.now(),
          text,
          act: this.state.act,
          floor: run.floor,
          health: run.health,
          healthMax: run.healthMax,
        })
      );
    } catch {
      // 隐私模式 / 配额满：存档只是便利，不打断游戏。
    }
  }

  /** 有没有可继续的存档（标题页读它）。坏数据当作没有，并**清掉**。 */
  resumeInfo(): ResumeInfo | null {
    if (typeof window === "undefined") return null;
    let raw: string | null = null;
    try {
      raw = window.localStorage.getItem(AUTOSAVE_KEY);
    } catch {
      return null;
    }
    if (raw === null) return null;
    try {
      const parsed = JSON.parse(raw) as Partial<ResumeInfo> & { v?: number };
      if (parsed.v !== 1 || typeof parsed.text !== "string" || parsed.text.length < 8) {
        throw new Error("bad shape");
      }
      return {
        text: parsed.text,
        act: Number(parsed.act ?? 0),
        floor: Number(parsed.floor ?? 0),
        health: Number(parsed.health ?? 0),
        healthMax: Number(parsed.healthMax ?? 0),
        at: Number(parsed.at ?? 0),
      };
    } catch {
      // 坏存档：清掉并留一条日志（否则每次打开都失败一次，玩家只会觉得"坏了"）。
      try {
        window.localStorage.removeItem(AUTOSAVE_KEY);
      } catch {
        /* 忽略 */
      }
      this.note("自动存档损坏，已丢弃", "warn");
      this.emit();
      return null;
    }
  }

  /** 关掉幕布（点一下 / 1.6 秒到）。 */''',
    ),
    (
        'import clears meta',
        '''    if (code === 0) {
      this.frozenReason = null;
      this.injectedViolation = null;''',
        '''    if (code === 0) {
      this.frozenReason = null;
      this.injectedViolation = null;
      // 回档之后允许自动存档立刻重写一次（文本可能相同，但 `lastAutosave` 是"上一次写盘的"）。
      this.lastAutosave = null;''',
    ),
])
print('done')
