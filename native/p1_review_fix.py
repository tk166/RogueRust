"""第十二轮 Review 的 P1-A / P1-B / P2-A / P2-B：把 `--report` 的"假通过"堵掉。

## 四条，都是"报告看起来通过、实际没证实"

| # | 问题 | 修法 |
|---|---|---|
| **P1-A** | `--report` 只检查 `sceneMismatch`；`raw: null`（UNREACHED）的**被跳过** ⇒ 缺场景也能 PASS | 引入 `SCENE_PLAN`：每条标 `real` / `synthetic`；`real` 的没到达或不匹配就 **FAIL**；`SC-11a` 还要断言 overlay |
| **P1-B** | `--check-fixtures` 只比内容指纹与长度 ⇒ **同内容、不同 wasm 行为**的旧快照仍算新鲜 | 记录 **wasm sha256**；`--check-fixtures` 也比它，并把"元数据新鲜"与"语义一致"分开说 |
| **P2-A** | 先 `writeFile` 再验证 ⇒ 失败的采集会**覆盖**上一份有效 fixture | 先构造 + 验证，再写临时文件并 `rename`（原子替换） |
| **P2-B** | "所有值未经解释"不准确 —— 文件里还有 `facts`（派生）与 `scene`（旧分类器算的） | 加 `provenance` 字段，明确三者的来路 |
"""

import io

PATH = 'native/ui_abi_dump.mjs'


def edit(old, new, label):
    t = io.open(PATH, encoding='utf-8').read()
    assert t.count(old) == 1, '%s: 命中 %d' % (label, t.count(old))
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t.replace(old, new))


# ── ① 头部：要 sha256 ─────────────────────────────────────────────────────
edit('''import { readFile, writeFile, mkdir } from "node:fs/promises";''',
     '''import { readFile, writeFile, mkdir, rename } from "node:fs/promises";
import { createHash } from "node:crypto";''', 'imports')

edit('''const bytes = await readFile(WASM);
const { instance } = await WebAssembly.instantiate(bytes, {});''',
     '''const bytes = await readFile(WASM);
/// wasm 的 sha256。**`--check-fixtures` 要比它**：内容指纹只看镜像，看不出"内核代码变了、
/// 内容没变"（第十二轮 Review P1-B）。
const WASM_SHA256 = createHash("sha256").update(bytes).digest("hex");
const { instance } = await WebAssembly.instantiate(bytes, {});''', 'wasm sha')

# ── ② report 尾部：计划驱动的判定 + 原子写 + provenance ────────────────────
edit('''  // 场景 parity：每个真实快照都要落到**预期的那个**场景
  const expected = {
    "SC-00-no-run": "SC-00",
    "SC-01-blessing": "SC-01",
    "SC-02-map": "SC-02",
    "SC-03-pre-fight": "SC-03",
    "SC-03b-run-facts": "SC-03b",
    "SC-04-reward": "SC-04",
    "SC-05-shop": "SC-05",
    "SC-07-treasure": "SC-07",
    "SC-08-event": "SC-08",
    "SC-12b-defeat": "SC-12b",
    "SC-11a-pickup-debt": null, // 覆盖层压在底屏上（这里是 SC-02），不单独成 base
  };
  for (const scene of scenes) {
    if (!scene.raw || !scene.facts) continue;
    const want = expected[scene.label];
    scene.scene = P.resolveScene(scene.facts);
    if (want && scene.scene.base !== want) {
      scene.sceneMismatch = `want ${want}, got ${JSON.stringify(scene.scene)}`;
    }
  }

  await mkdir(FIXTURES, { recursive: true });
  const payload = {
    note: "P0 raw ABI dumps. Values are exactly what the wasm said; nothing here is interpreted.",
    contentFingerprint: `0x${(ex.rd_content_fingerprint() >>> 0).toString(16).padStart(8, "0")}`,
    runObserveLen: ex.rd_run_observe_len(),
    combatObserveLen: ex.rd_env_observe_len(),
    scenes,
  };
  await writeFile(join(FIXTURES, "p0-scenes.json"), JSON.stringify(payload, null, 1) + "\\n", "utf8");

  console.log(
    `UI_ABI_REPORT content=${payload.contentFingerprint} runObs=${payload.runObserveLen} combatObs=${payload.combatObserveLen}`
  );
  for (const scene of scenes) {
    const state = !scene.raw ? "UNREACHED" : scene.sceneMismatch ? "MISMATCH" : "ok";
    const where = scene.scene
      ? `${scene.scene.base}${scene.scene.overlays.length ? "+" + scene.scene.overlays.join("+") : ""}`
      : "-";
    console.log(`  ${scene.label.padEnd(24)} ${state.padEnd(9)} ${where.padEnd(14)} ${scene.note}`);
  }
  const bad = scenes.filter((s) => s.sceneMismatch);
  if (bad.length) fail(`${bad.length} scene(s) did not land on the expected base scene`);
  console.log("UI_ABI_REPORT PASS");''',
     '''  // ── 场景判定：**计划驱动**，不是"有 mismatch 才红" ──────────────────────────
  //
  // 第十二轮 Review P1-A：第一版只检查 `sceneMismatch`，于是 `raw: null`（UNREACHED）的条目
  // **被跳过** —— 少采几个场景照样 `UI_ABI_REPORT PASS`。现在每条场景先声明它是
  // `real`（必须真实到达）还是 `synthetic`（允许合成，但要写明理由），没到达就 FAIL。
  //
  // `SC-11a` 的判据是**覆盖层真的出现在 `overlays` 里**（`pickupPicks > 0` 只是前提，
  // 不是"这一屏画对了"）。
  const SCENE_PLAN = [
    { label: "SC-00-no-run", expect: "SC-00", kind: "real" },
    { label: "SC-01-blessing", expect: "SC-01", kind: "real" },
    { label: "SC-02-map", expect: "SC-02", kind: "real" },
    { label: "SC-03-pre-fight", expect: "SC-03", kind: "real" },
    { label: "SC-03b-combat", expect: null, kind: "real" }, // 战斗向量本身，没有运行层 base
    { label: "SC-03b-run-facts", expect: "SC-03b", kind: "real" },
    { label: "SC-04-reward", expect: "SC-04", kind: "real" },
    { label: "SC-05-shop", expect: "SC-05", kind: "real" },
    { label: "SC-07-treasure", expect: "SC-07", kind: "real" },
    { label: "SC-08-event", expect: "SC-08", kind: "real" },
    { label: "SC-11a-pickup-debt", expect: null, overlay: "SC-11a", kind: "real" },
    { label: "SC-12b-defeat", expect: "SC-12b", kind: "real" },
    { label: "SC-12a-act-clear", expect: "SC-12a", kind: "synthetic", why: "needs the boss fight" },
  ];

  const byLabel = new Map(scenes.map((scene) => [scene.label, scene]));
  for (const plan of SCENE_PLAN) {
    const scene = byLabel.get(plan.label);
    if (!scene || !scene.raw) {
      plan.state = "UNREACHED";
      continue;
    }
    if (scene.facts) scene.scene = P.resolveScene(scene.facts);
    if (plan.expect && scene.scene && scene.scene.base !== plan.expect) {
      plan.state = "INVALID";
      plan.detail = `want ${plan.expect}, got ${JSON.stringify(scene.scene)}`;
      continue;
    }
    if (plan.overlay && !(scene.scene && scene.scene.overlays.includes(plan.overlay))) {
      plan.state = "INVALID";
      plan.detail = `want overlay ${plan.overlay}, got ${JSON.stringify(scene.scene)}`;
      continue;
    }
    plan.state = "REAL";
  }

  const broken = SCENE_PLAN.filter(
    (plan) => plan.kind === "real" && plan.state !== "REAL"
  );
  const synthetic = SCENE_PLAN.filter((plan) => plan.kind === "synthetic");

  // ── 先验证、再原子写（P2-A：失败的采集不许覆盖上一份有效 fixture）──────────
  const payload = {
    note:
      "P0 ABI dumps. `raw` is exactly what the wasm exports returned (uninterpreted); " +
      "`facts` and `scene` are DERIVED by this script -- see `provenance`.",
    provenance: {
      raw: "verbatim return values of the wasm exports",
      facts: "derived from raw by this script (the ten Adapter fields); not an ABI claim",
      scene: "computed by web/ui_panels.js resolveScene() from facts",
    },
    wasmSha256: WASM_SHA256,
    contentFingerprint: `0x${(ex.rd_content_fingerprint() >>> 0).toString(16).padStart(8, "0")}`,
    runObserveLen: ex.rd_run_observe_len(),
    combatObserveLen: ex.rd_env_observe_len(),
    plan: SCENE_PLAN,
    scenes,
  };

  console.log(
    `UI_ABI_REPORT content=${payload.contentFingerprint} wasm=${WASM_SHA256.slice(0, 12)} ` +
    `runObs=${payload.runObserveLen} combatObs=${payload.combatObserveLen}`
  );
  for (const plan of SCENE_PLAN) {
    const scene = byLabel.get(plan.label);
    const where = scene && scene.scene
      ? `${scene.scene.base}${scene.scene.overlays.length ? "+" + scene.scene.overlays.join("+") : ""}`
      : "-";
    const note = plan.detail || (scene ? scene.note : "") || plan.why || "";
    console.log(`  ${plan.label.padEnd(24)} ${plan.state.padEnd(9)} ${where.padEnd(14)} ${note}`);
  }

  if (broken.length) {
    // ⚠️ **不写盘**：失败的采集不能污染上一份有效 fixture。
    fail(
      `${broken.length} required-real scene(s) not proven: ` +
      broken.map((plan) => `${plan.label}=${plan.state}`).join(", ")
    );
  }

  await mkdir(FIXTURES, { recursive: true });
  const target = join(FIXTURES, "p0-scenes.json");
  const temp = `${target}.tmp`;
  await writeFile(temp, JSON.stringify(payload, null, 1) + "\\n", "utf8");
  await rename(temp, target);

  if (synthetic.length) {
    console.log(
      `  (synthetic, allowed: ${synthetic.map((plan) => `${plan.label} -- ${plan.why}`).join("; ")})`
    );
  }
  console.log(`UI_ABI_REPORT PASS (real ${SCENE_PLAN.length - synthetic.length}/${SCENE_PLAN.length - synthetic.length})`);''',
     'plan-driven verdict')

# ── ③ checkFixtures：也比 wasm sha，并把两种"新鲜"分开说 ───────────────────
edit('''async function checkFixtures() {
  const path = join(FIXTURES, "p0-scenes.json");
  if (!existsSync(path)) fail("no fixtures yet -- run `--report` first");
  const onDisk = JSON.parse(await readFile(path, "utf8"));
  const live = `0x${(ex.rd_content_fingerprint() >>> 0).toString(16).padStart(8, "0")}`;
  if (onDisk.contentFingerprint !== live) {
    fail(`fixtures are from content ${onDisk.contentFingerprint}, this build is ${live} -- re-run --report`);
  }
  if (onDisk.runObserveLen !== ex.rd_run_observe_len()) fail("runObserveLen drifted");
  if (onDisk.combatObserveLen !== ex.rd_env_observe_len()) fail("combatObserveLen drifted");
  console.log(`UI_ABI_FIXTURES PASS (${onDisk.scenes.length} scenes, content ${live})`);
}''',
     '''async function checkFixtures() {
  const path = join(FIXTURES, "p0-scenes.json");
  if (!existsSync(path)) fail("no fixtures yet -- run `--report` first");
  const onDisk = JSON.parse(await readFile(path, "utf8"));
  const live = `0x${(ex.rd_content_fingerprint() >>> 0).toString(16).padStart(8, "0")}`;

  // ⚠️ 第十二轮 Review P1-B：**内容指纹看不出"内核代码变了、内容没变"**。
  // 所以这里比三样：wasm sha256（代码）、内容指纹（内容）、两个向量长度（形状）。
  // 三种"新鲜"是不同的事，报错要说清是哪一种：
  //   metadata current  ≠  语义一致  ≠  场景仍可达
  const drift = [];
  if (onDisk.wasmSha256 !== WASM_SHA256) {
    drift.push(`wasm sha256 ${String(onDisk.wasmSha256).slice(0, 12)} -> ${WASM_SHA256.slice(0, 12)} (the kernel changed)`);
  }
  if (onDisk.contentFingerprint !== live) {
    drift.push(`content ${onDisk.contentFingerprint} -> ${live} (the image changed)`);
  }
  if (onDisk.runObserveLen !== ex.rd_run_observe_len()) drift.push("runObserveLen drifted");
  if (onDisk.combatObserveLen !== ex.rd_env_observe_len()) drift.push("combatObserveLen drifted");
  if (drift.length) {
    fail(
      "fixtures are stale:\\n  " + drift.join("\\n  ") +
      "\\n  re-run `--report` (this check proves *metadata* freshness only, not semantic equality)"
    );
  }
  const real = (onDisk.plan || []).filter((plan) => plan.kind === "real");
  const proven = real.filter((plan) => plan.state === "REAL").length;
  console.log(
    `UI_ABI_FIXTURES PASS (metadata current: wasm ${WASM_SHA256.slice(0, 12)}, content ${live}, ` +
    `${proven}/${real.length} required-real scenes were REAL when captured)`
  );
}''', 'checkFixtures')
print('P1-A / P1-B / P2-A / P2-B patched')
