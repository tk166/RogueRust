"""CombatScreen：接上 Beat 演出（导演 + 渲染层 + 跳过 + 关动画）。"""

import io

P = 'web-next/src/combat/CombatScreen.tsx'
t = io.open(P, encoding='utf-8').read()


def sub(old, new, label):
    global t
    assert t.count(old) == 1, '%s: 命中 %d 次' % (label, t.count(old))
    t = t.replace(old, new)


# 1) import
sub(
    '''import { MachineStore } from "../store";''',
    '''import { MachineStore } from "../store";
import {
  advance as advanceBeats,
  createDirector,
  describeDirector,
  enqueue as enqueueBeats,
  isBusy as beatsBusy,
  planBeats,
  skipAll as skipBeats,
  type DirectorState,
} from "./beats";
import { BeatLayer } from "./BeatLayer";''',
    'imports',
)

# 2) 关动画的判定 + 导演状态
sub(
    '''  const [modalOpen, setModalOpen] = useState(false);''',
    '''  const [modalOpen, setModalOpen] = useState(false);
  /**
   * 关掉动画的两个来源：`?motion=off`（闸门/玩家显式）与系统 `prefers-reduced-motion`。
   *
   * ⚠️ 关掉动画**不是另一条代码路径**：导演只是"一条都不播"，局面仍然完全由内核快照驱动，
   * 所以"关闭动画也能完整游戏"是结构上成立的（plan P5 的退出条件）。
   */
  const motionOff = useMemo(() => {
    if (new URLSearchParams(window.location.search).get("motion") === "off") return true;
    return typeof window.matchMedia === "function"
      ? window.matchMedia("(prefers-reduced-motion: reduce)").matches
      : false;
  }, []);
  const [director, setDirector] = useState<DirectorState>(() =>
    createDirector({ reducedMotion: motionOff })
  );
  const beatId = useRef(0);''',
    'director state',
)

# 3) 出牌被接受之后：规划演出
sub(
    '''          const outcome = wasm.game.dispatch(action);
          if (outcome.accepted) {''',
    '''          const outcome = wasm.game.dispatch(action);
          if (outcome.accepted) {
            // 演出只读 beat：**不改变任何状态**（局面仍然来自内核快照）。
            const planned = planBeats(outcome.beats, outcome.beatsDropped, {
              reducedMotion: motionOff,
            }, beatId.current);
            beatId.current += planned.effects.length;
            setDirector((current) => enqueueBeats(current, planned));''',
    'plan beats',
)

# 4) rAF 推进
sub(
    '''  // ── 待决选牌：勾选 / 清空 / 确认 ─────────────────────────────────────────''',
    '''  // ── Beat 导演：只在有东西在播时跑 rAF ───────────────────────────────────
  useEffect(() => {
    if (!beatsBusy(director)) return;
    let frame = 0;
    let last = performance.now();
    const tick = (now: number) => {
      const dt = now - last;
      last = now;
      setDirector((current) => advanceBeats(current, dt));
      frame = window.requestAnimationFrame(tick);
    };
    frame = window.requestAnimationFrame(tick);
    return () => window.cancelAnimationFrame(frame);
  }, [director]);

  // ── 待决选牌：勾选 / 清空 / 确认 ─────────────────────────────────────────''',
    'raf loop',
)

# 5) Esc 跳过演出（优先级最高：动画挡着的时候先关动画）
sub(
    '''      if (event.key === "Escape") {
        // ⚠️ 有问句时 Esc 什么都不做：动作表此时为空，关掉弹窗等于把玩家扔进"点不动"的界面。
        if (choice) return;''',
    '''      if (event.key === "Escape") {
        // 演出在播时，Esc 先"跳过演出"（这是玩家最想要的那件事）。
        if (beatsBusy(store.peek ? director : director)) {
          setDirector((current) => skipBeats(current));
          return;
        }
        // ⚠️ 有问句时 Esc 什么都不做：动作表此时为空，关掉弹窗等于把玩家扔进"点不动"的界面。
        if (choice) return;''',
    'esc skip',
)

sub(
    '''    window.addEventListener("keydown", onKey);
    return () => {''',
    '''    window.addEventListener("keydown", onKey);
    return () => {''',
    'noop',
)

# 6) 渲染演出层（在 Stage 之后、其它覆盖层之前）
sub(
    '''      {/*
        战斗有结果：**只有**外层给了 `onFinish` 才画"继续"（P2 回归页没有下一屏）。''',
    '''      {/* Beat 演出：DOM 飘字，坐标来自 `layout`（与 3D 同一套投影）。 */}
      <BeatLayer
        director={director}
        layout={layout}
        hero={layout.hero}
        onSkip={() => setDirector((current) => skipBeats(current))}
      />

      {/*
        战斗有结果：**只有**外层给了 `onFinish` 才画"继续"（P2 回归页没有下一屏）。''',
    'render beat layer',
)

# 7) 探针：把导演状态暴露给闸门
sub(
    '''      choice: () => choice,''',
    '''      choice: () => choice,
      // 演出诊断：闸门 38 用它断言"播放动画不改变最终状态"与"关动画也能玩"。
      beats: () => ({ ...director, summary: describeDirector(director) }),''',
    'probe beats',
)
io.open(P, 'w', encoding='utf-8', newline='\n').write(t)
print('CombatScreen: beats wired')
