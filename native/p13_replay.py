"""设置里的「回放」：导出脚本（复制到剪贴板）+ 导入并逐步对拍。

## 内核语义（读 `run.rs` 得到的三条，都不是猜的）

1. 脚本头自带起点：`RDR1,S,<seed>,<asc>,<内容指纹>`（或 `RDR1,A,<档案>`）⇒ **导入不需要先有局**，
   `rd_run_replay_from` 自己 `rd_run_start`。
2. 每一步记 `种类,arg0,arg1,指纹` ⇒ 回放**逐步比对指纹**，`replay_checked()` 是验过的步数、
   `replay_diverged()` 是分叉的那一步（`0` = 没有分叉）。
3. **战斗中导不出**（一场战斗只有结果进脚本，回放必然分叉）—— 内核拒绝并给原因。

所以这一屏是"可复现"的证据面：导出 → 换个页面导入 → 逐步对拍 → 步数与分叉位置都说得清。
"""

import io


def patch(path, pairs):
    t = io.open(path, encoding='utf-8').read()
    for label, old, new in pairs:
        assert t.count(old) == 1, '%s %s: 命中 %d 次' % (path, label, t.count(old))
        t = t.replace(old, new)
    io.open(path, 'w', encoding='utf-8', newline='\n').write(t)
    print('patched', path)


# ── 1. host：脚本导出 / 回放 ───────────────────────────────────────────────
patch('web-next/src/wasm/host.ts', [
    (
        'script + replay',
        '''  /** 最近一次拒绝的原因（`rd_run_last_error_*`）。 */''',
        '''  // ── 回放脚本（`rd_run_script_*` / `rd_run_replay_*`）──────────────────────
  /**
   * 让内核把回放脚本写进它自己的缓冲，返回长度；`<0` = 拒绝（原因见 `lastError`）。
   *
   * ⚠️ **战斗中导不出**：一场战斗只有"结果"进脚本，回放它必然分叉 —— 内核直接拒绝。
   */
  scriptFill(): number {
    return (this.ex.rd_run_script_fill as () => number)();
  }

  /** 读回脚本文本（`scriptFill` 之后调用）。 */
  readScript(len: number): string {
    const ptr = Number((this.ex.rd_run_script_buf as () => number)());
    const bytes = new Uint8Array(this.ex.memory.buffer, ptr, len).slice();
    return this.decoder.decode(bytes);
  }

  /**
   * 回放 `text`。`0` = 每一步都复现；`n > 0` = 第 `n` 步分叉；`-1` 没有槽；`-2` 拒绝。
   *
   * 脚本头自带 seed/ascension/内容指纹，所以**不需要先有局**（内核自己开局）。
   */
  replayFrom(text: string): number {
    const bytes = new TextEncoder().encode(text);
    const capacity = (this.ex.rd_run_script_capacity as () => number)();
    if (bytes.length > capacity) return -2;
    const ptr = Number((this.ex.rd_run_script_buf as () => number)());
    new Uint8Array(this.ex.memory.buffer, ptr, bytes.length).set(bytes);
    return (this.ex.rd_run_replay_from as (ptr: number, len: number) => number)(ptr, bytes.length);
  }

  /** 上一次回放验过多少步。 */
  replayChecked(): number {
    return (this.ex.rd_run_replay_checked as () => number)();
  }

  /** 上一次回放在第几步分叉（`0` = 没有）。 */
  replayDiverged(): number {
    return (this.ex.rd_run_replay_diverged as () => number)();
  }

  /** 最近一次拒绝的原因（`rd_run_last_error_*`）。 */''',
    ),
])

# ── 2. RunStore：导出 / 导入 ───────────────────────────────────────────────
patch('web-next/src/run/RunStore.ts', [
    (
        'replay actions',
        '''  // ── 存档 / 回档（第十五轮 Review §6 的缺口）──────────────────────────────''',
        '''  // ── 回放（`rd_run_script_*` / `rd_run_replay_*`）───────────────────────────
  /**
   * 导出回放脚本；`null` = 内核拒绝（战斗中 / 没有局 / 哈希缓冲不够）。
   *
   * 与存档**不同**：存档描述"现在这一局"，脚本描述"这一局是怎么走到现在的"（每步都带指纹）。
   */
  exportReplay(): string | null {
    const len = this.host.scriptFill();
    if (len <= 0) {
      this.note(`导出回放失败：${this.host.lastError() || `code ${len}`}`, "warn");
      this.refresh();
      return null;
    }
    const text = this.host.readScript(len);
    this.note(`导出回放：${len} 字节`, "good");
    this.refresh();
    return text;
  }

  /**
   * 导入并**逐步对拍**。
   *
   * 脚本头自带 seed/ascension/内容指纹 ⇒ 不需要先有局（内核自己 `rd_run_start`）。
   * 返回码：`0` 全部复现 / `n > 0` 第 n 步分叉 / `-1` 没有槽 / `-2` 拒绝（原因在 `lastError`）。
   */
  importReplay(text: string): { code: number; checked: number; diverged: number; message: string } {
    const code = this.host.replayFrom(text);
    const checked = this.host.replayChecked();
    const diverged = this.host.replayDiverged();
    const message =
      code === 0
        ? `已逐步对拍 ${checked} 步，无分叉`
        : code > 0
          ? `第 ${diverged || code} 步分叉（前 ${checked} 步一致）`
          : this.host.lastError() || `回放被拒绝（code ${code}）`;
    this.note(
      code === 0 ? `回放成功：${checked} 步` : `回放失败：${message}`,
      code === 0 ? "good" : "bad"
    );
    // 回放会把局面改成"脚本末尾那一刻" ⇒ 冻结要解（这是内核校验过的状态）。
    if (code === 0) {
      this.frozenReason = null;
      this.injectedViolation = null;
      this.lastAutosave = null;
    }
    this.refresh();
    return { code, checked, diverged, message };
  }

  // ── 存档 / 回档（第十五轮 Review §6 的缺口）──────────────────────────────''',
    ),
])
print('done')
