"""P6 代码改动：自适应 DPR / WebGL context lost / 动效开关持久化 / 安全区 / 触控目标。"""

import io


def patch(path, pairs):
    t = io.open(path, encoding='utf-8').read()
    for label, old, new in pairs:
        assert t.count(old) == 1, '%s %s: 命中 %d 次' % (path, label, t.count(old))
        t = t.replace(old, new)
    io.open(path, 'w', encoding='utf-8', newline='\n').write(t)
    print('patched', path)


# ── 1. CombatScreen：DPR 自适应 + context lost + 动效开关读 localStorage ────────
patch(
    'web-next/src/combat/CombatScreen.tsx',
    [
        (
            'motion preference',
            '''  const motionOff = useMemo(() => {
    // `?motion=off` / `?motion=on` 是**显式**开关（闸门两边都要能测）；
    // 没给参数时听系统。
    // ⚠️ 无头 Chrome 的 `prefers-reduced-motion` 实测是 `reduce` ⇒ 闸门里默认**不播**动画。
    // 所以"动画开着"必须由 `?motion=on` 显式要求，不能靠默认值。
    const param = new URLSearchParams(window.location.search).get("motion");
    if (param === "off") return true;
    if (param === "on") return false;
    return typeof window.matchMedia === "function"
      ? window.matchMedia("(prefers-reduced-motion: reduce)").matches
      : false;
  }, []);''',
            '''  const motionOff = useMemo(() => {
    // 优先级：URL 参数（闸门/临时覆盖）> 玩家在设置里选的（localStorage）> 系统偏好。
    // ⚠️ 无头 Chrome 的 `prefers-reduced-motion` 实测是 `reduce` ⇒ 闸门里默认**不播**动画，
    // 所以"动画开着"必须由 `?motion=on` 显式要求，不能靠默认值。
    const param = new URLSearchParams(window.location.search).get("motion");
    if (param === "off") return true;
    if (param === "on") return false;
    try {
      const stored = window.localStorage.getItem("rd.motion");
      if (stored === "off") return true;
      if (stored === "on") return false;
    } catch {
      // 隐私模式/禁用 storage：忽略，回落到系统偏好。
    }
    return typeof window.matchMedia === "function"
      ? window.matchMedia("(prefers-reduced-motion: reduce)").matches
      : false;
  }, []);

  /**
   * WebGL 上下文丢失（P6 的稳定性要求）。
   *
   * 真机上这会发生（切后台、GPU 重置、驱动崩溃）。**不能什么都不做**：canvas 会变成一片黑，
   * 而玩家会以为游戏卡死。这里做两件事：挂一条诊断横幅 + 给一个"重新初始化"按钮（换 key
   * 重挂 Canvas）。局面在内核里，所以重挂之后**不需要重打**。
   */
  const [contextLost, setContextLost] = useState(false);
  const [canvasKey, setCanvasKey] = useState(0);

  /**
   * 窄屏把 DPR 上限压到 1.5（P6 的性能项）。
   *
   * 390×700 的画布：dpr 2 ⇒ 780×1400 ≈ 1.09M 像素；dpr 1.5 ⇒ 585×1050 ≈ 0.61M（**-44%**）。
   * 手机 GPU 上这是最直接的一刀，而且肉眼看不出差别（390 CSS px 宽、1.5 倍已经超过 1080p 的
   * 横向采样）。宽屏保持 2（桌面字更锐）。
   */
  const dprCap = useMemo(() => {
    const width = typeof window === "undefined" ? 1280 : window.innerWidth;
    return width < 600 ? 1.5 : 2;
  }, []);''',
        ),
        (
            'canvas dpr + context lost',
            '''      <Canvas
        className="stage"
        shadows={false}
        dpr={[1, 2]}''',
            '''      <Canvas
        key={canvasKey}
        className="stage"
        shadows={false}
        dpr={[1, dprCap]}''',
        ),
        (
            'onCreated context lost',
            '''        onCreated={({ camera }) => camera.lookAt(0, 0.1, 0)}''',
            '''        onCreated={({ camera, gl }) => {
          camera.lookAt(0, 0.1, 0);
          // `webglcontextlost` 必须 `preventDefault()` 才有机会恢复；恢复交给"重新初始化"按钮。
          gl.domElement.addEventListener("webglcontextlost", (event) => {
            event.preventDefault();
            setContextLost(true);
          });
          gl.domElement.addEventListener("webglcontextrestored", () => setContextLost(false));
        }}''',
        ),
        (
            'context lost banner',
            '''      {/* 致命错误（ABI 违约 / 驱动损坏）：冻结操作并显示诊断，**不进半可用**。 */}''',
            '''      {/* WebGL 上下文丢失：真机上会真的发生。给诊断 + 一键重新初始化。 */}
      {contextLost && (
        <div className="wasm-status" data-context-lost>
          <div>显卡上下文丢失了（切后台 / GPU 重置）。局面还在内核里，重新初始化就能继续。</div>
          <button
            type="button"
            data-context-retry
            onClick={() => {
              setContextLost(false);
              setCanvasKey((key) => key + 1);
            }}
          >
            重新初始化
          </button>
        </div>
      )}

      {/* 致命错误（ABI 违约 / 驱动损坏）：冻结操作并显示诊断，**不进半可用**。 */}''',
        ),
        (
            'probe metrics',
            '''      beats: () => ({ ...directorRef.current, summary: describeDirector(directorRef.current) }),''',
            '''      beats: () => ({ ...directorRef.current, summary: describeDirector(directorRef.current) }),
      // P6：移动端/性能的**可复现**度量（闸门 39/40 读它，不读像素）。
      metrics: () => ({
        width: window.innerWidth,
        height: window.innerHeight,
        dpr: window.devicePixelRatio,
        dprCap,
        canvas: (() => {
          const canvas = document.querySelector("canvas");
          if (!canvas) return null;
          const rect = canvas.getBoundingClientRect();
          return {
            cssWidth: Math.round(rect.width),
            cssHeight: Math.round(rect.height),
            backingWidth: canvas.width,
            backingHeight: canvas.height,
            backingPixels: canvas.width * canvas.height,
          };
        })(),
        contextLost,
        motionOff,
        overflowX: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      }),''',
        ),
    ],
)

# ── 2. probe.ts：类型 ────────────────────────────────────────────────────────
patch(
    'web-next/src/probe.ts',
    [
        (
            'probe options metrics',
            '''  /** Beat 演出导演的状态（plan P5：闸门断言"播放动画不改变最终状态"）。 */
  beats?: () => unknown;
}''',
            '''  /** Beat 演出导演的状态（plan P5：闸门断言"播放动画不改变最终状态"）。 */
  beats?: () => unknown;
  /** P6：视口 / DPR / 画布后备像素 / 上下文状态（闸门 39/40 的度量来源）。 */
  metrics?: () => unknown;
}''',
        ),
        (
            'probe interface metrics',
            '''  /** Beat 演出导演的状态（`playing` / `queue` / `dropped` / `unknownKinds`）。 */
  beats: () => unknown;''',
            '''  /** Beat 演出导演的状态（`playing` / `queue` / `dropped` / `unknownKinds`）。 */
  beats: () => unknown;
  /** P6：视口 / DPR / 画布后备像素 / 上下文状态。 */
  metrics: () => unknown;''',
        ),
        (
            'probe impl metrics',
            '''    beats: () => options.beats?.() ?? null,''',
            '''    beats: () => options.beats?.() ?? null,
    metrics: () => options.metrics?.() ?? null,''',
        ),
    ],
)
print('done')
