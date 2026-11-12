"""P7 文档：docs/ui-parity.md + port-plan §367 + README 的新前端一节。"""

import io


def edit(path, old, new, label):
    t = io.open(path, encoding='utf-8').read()
    assert t.count(old) == 1, '%s: 命中 %d 次' % (label, t.count(old))
    io.open(path, 'w', encoding='utf-8', newline='\n').write(t.replace(old, new))


# ── 1. 对等清单 ────────────────────────────────────────────────────────────
parity = '''# 新旧入口的功能对等清单（P7）

> 判据：plan P7 —— *"对照旧版功能清单逐项验收；保留 `web/` 直到关键能力齐备"*。
> 新入口 = `web-next/dist/run.html`，旧入口 = `web/index.html`（+ `web/map.html`）。
> 闸门 41 `ui-parity` 守"同一个内核、同一串输入同一串输出"；闸门 42 `ui-deploy` 守部署产物。

## 1. 场景（`docs/ui-state-model.md` 的 18 行表）

| 场景 | 旧入口 | 新入口 | 结论 |
|---|---|---|---|
| `SC-00` 未开局 | 有（种子输入 + 开始） | `TitleScene`（种子 + 进阶滑杆） | **对等**（新入口多了进阶滑杆） |
| `SC-01` 塔底祝福 | 有 | `BlessingScene` | 对等 |
| `SC-01b` 祝福选牌 | 有（牌组选择器） | `DeckSelectOverlay` | 对等（新入口多了过滤框、不可选原因） |
| `SC-02` 地图 | 有（SVG） | `MapScene`（DOM+SVG，可达高亮、你在这里、Boss 哨兵） | **更好**（Boss 哨兵在旧入口缺失：第 15 层之后旧页面也走不到，见下） |
| `SC-02b` 幕尽头 | 有 | `EndScene` | 对等（**当前内容下都不可达**，闸门 33 用合成夹具） |
| `SC-03` 战斗前 | 有 | `PreCombatScene` | 对等 |
| `SC-03b` 战斗中 | 有（DOM 卡片） | `CombatScreen`（3D 手牌 + 触摸/鼠标拖拽 + Beat 演出） | **更好**（3D + 演出 + 触控） |
| `SC-04` 战斗奖励 | 有 | `RewardScene` | 对等 |
| `SC-05` 商店 | 有（四排 + 删卡） | `ShopScene` | 对等（价格只显示内核给的那份） |
| `SC-06` 篝火 | 有（六选项） | `RestScene` | 对等 |
| `SC-07` 宝箱 | 有 | `ChestScene` | 对等（新入口用战利品横幅，因为 `open_chest` 打开即结束） |
| `SC-08` 事件 | 有 | `EventScene` | **更好**（事件名/正文/选项走官方中文，见 §4） |
| `SC-09` 事件选牌 | 有 | `DeckSelectOverlay` | 对等 |
| `SC-10` 事件候选 | 有 | `EventOfferScene` | 对等 |
| `SC-11a/b` 遗物欠账 | 有（弹窗） | `PickupOverlay`（覆盖层，关不掉） | 对等 |
| `SC-12a/b` 幕通关/局终 | 有 | `EndScene` | 对等 |

## 2. 旧入口有、新入口**没有**（如实记录）

| 功能 | 旧入口 | 影响 | 处置 |
|---|---|---|---|
| **存档 / 回档 / 回放** | `#archiveBox` + `rd_run_archive_*` / `rd_run_restore_from` / `rd_run_replay_*` | 新入口不能导出/恢复一局，也不能看回放 | **已知缺口**。内核导出都在，缺的是界面；`web/` 保留就是这个用途 |
| **bench 面板** | `#bench`（`rd_env_bench_sizes`） | 新入口没有开发用基准面板 | 诊断面板（设置里）覆盖了"看状态"，bench 留给需要时 |
| **script buffer** | `rd_run_script_*` | 新入口没有"脚本化一局"的输入框 | 闸门用探针代替；玩家不需要 |

## 3. 新入口有、旧入口**没有**

| 功能 | 说明 |
|---|---|
| 3D 手牌与拖拽 | P1/P2 的成果（旧入口是 DOM 卡片） |
| Beat 演出（1–13 类） | P5（旧入口只有文字 diff） |
| 触控 / 移动端 | P6（44px 触控目标、安全区、DPR 上限、触摸拖牌） |
| 设置与诊断面板 | 种子/进阶/场景/相位/**对账**/遗物/药水/日志 + 动效开关 |
| 牌堆浏览 | 抽/弃/耗三个牌堆（抽牌堆**按名字排序**，不泄露内部顺序） |
| 药水腰带（战斗外可用） | 旧入口只在战斗里给"用"（§158 的缺口） |
| **对账横幅** | `violations` 非空时红条 + 冻结推进（旧入口没有这一层） |

## 4. 中文覆盖

| 表 | 旧入口 | 新入口 |
|---|---|---|
| 卡牌 / 遗物 / 药水 / 怪物 / 状态 | 有（`i18n/zh.ts` 的前身） | 有（同一份生成物，530 条） |
| **事件**（名/正文/选项） | 无（显示英文） | 36 名 / 35 正文 / 32 标签（官方数据 + 人工确认，见 `native/zh_events.py`） |

## 5. 结论

* **关键能力齐备**：18 个场景全部可操作；战斗/地图/奖励/商店/篝火/宝箱/事件都有界面；
  移动端主要操作可完成（闸门 39）。
* **唯一实质缺口**：存档/回档/回放（旧入口有）。这不足以阻止切换 —— 但 `web/` 必须留着，
  而且**切换是可回退的单行改动**（`web-next/scripts/serve.mjs` 的 `DEFAULT_ENTRY`）。
'''
io.open('docs/ui-parity.md', 'w', encoding='utf-8', newline='\n').write(parity)

# ── 2. port-plan §367 ──────────────────────────────────────────────────────
PLAN = 'docs/port-plan.md'
t = io.open(PLAN, encoding='utf-8').read()
assert '## §367' not in t
section = '''

---

## §367 P7 交付：对等验收、部署产物、默认入口切换

plan P7 的退出条件：*"新旧入口同一内核版本下的关键游戏状态与动作结果一致；新 UI 没有无依据的
游戏规则分支。"* 完整对等清单在 `docs/ui-parity.md`。

### 367.1 同一个内核（闸门 41 `ui-parity`）

三件事：

1. **逐字节一致**：`web/rd_wasm.wasm`（唯一产物）== `web-next/dist/rd_wasm.wasm` ==
   `wasm.json` 的 sha256。"两个内核版本"在结构上不可能存在（`scripts/sync-wasm.mjs` 只复制，
   不重编）。
2. **内核侧脚本 ⇄ 新入口状态**：在 **Node 里直接跑 wasm**（原始导出，不经过任何界面）跑一段
   脚本（开局 → 祝福 → 走一格 → 结算 → 开战 → 出三张牌），再在浏览器里用**新入口**走同样的
   步骤，逐检查点比 8 个运行层字段（`env-abi.md` §11.3 的下标）。
   证据串：`UI_PARITY PASS checkpoints=8 fields=64 sha=match old=alive`。
3. **旧入口还活着**：`web/index.html` 仍能装载**同一份** wasm、开局、相位正确（19/148 长度）。

⚠️ 为什么不拿旧页面当参照物：界面是**被验收的对象**，拿它验另一个界面就是自己验自己。
共同底座是 wasm。

### 367.2 部署产物（闸门 42 `ui-deploy`）

`web-next/scripts/serve.mjs` 是一台**明确知道自己在干什么**的静态服务器：

| 项 | 规则 | 为什么 |
|---|---|---|
| MIME | `.wasm` → `application/wasm` | `instantiateStreaming` 只认它；用错就白屏 |
| 缓存 | `/assets/*` → `immutable` 一年；`*.html` / `wasm.json` / `rd_wasm.wasm` → `no-cache` + ETag | 带哈希的可以永久缓存；HTML 缓存住就会去要已删除的资源 |
| 版本 | 启动时校验 `wasm.json.sha256` == 磁盘 wasm 的 sha256，不一致**拒绝启动** | "换了 wasm 忘更新 manifest"这类错不该走到玩家屏幕上 |
| 入口 | `/` = 默认入口；`/legacy/*` = 旧入口（永远可达） | P7 要求保留 `web/`，且切换可回退 |

闸门还断言：页面引用的每个 `/assets/*` 都能取到、带哈希的是 immutable、没有 `.map` 可下载、
越界路径被拒绝。

### 367.3 默认入口切换（独立 commit）

`serve.mjs` 里 `export const DEFAULT_ENTRY = "legacy" | "run"` —— **切换就是改这一行**，
所以回退是一次单行 revert。切换本身放在**单独的 commit** 里（plan 的硬要求）。

### 367.4 中文覆盖补完

事件表（`native/zh_events.py`）在 §365.5 交付：36 个事件名、35 段正文（官方中文）、
32 条选项标签；子节点正文回退英文并计数。

### 367.5 已知缺口（如实记录，见 `docs/ui-parity.md` §2）

* **存档 / 回档 / 回放**：内核导出都在（`rd_run_archive_*` / `rd_run_restore_from` /
  `rd_run_replay_*`），**旧入口有界面、新入口没有**。`web/` 保留就是这个用途。
* **bench 面板**与**脚本化输入**：旧入口有，新入口用探针/设置面板代替。

### 367.6 数字

闸门 40 → **42**；units 1233、导出 234、四条对拍不动；新增 `docs/ui-parity.md`。
'''
io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(t.rstrip('\n') + section)

# ── 3. README：新前端一节 ──────────────────────────────────────────────────
edit(
    'README.md',
    '''**聚合验收**：40 道闸门''',
    '''**聚合验收**：42 道闸门''',
    'readme gate count',
)

readme_add = '''

---

## 10. 新前端 `web-next/`（P1–P7 的产物）

旧入口 `web/` 仍然保留（它是回归夹具，也是**存档/回放**的落点），但产品路径在 `web-next/`。

### 10.1 构建

```bash
cd web-next
npm ci                      # 只装前端依赖（three / r3f / vite / typescript）
node scripts/sync-wasm.mjs  # 把 web/rd_wasm.wasm 复制进 public/ 并记 sha256（**不重编**）
npm run build               # → dist/（产物入库，闸门不需要 npm 也能跑）
```

### 10.2 运行

```bash
node web-next/scripts/serve.mjs --port 8080 --entry run     # 新 UI
node web-next/scripts/serve.mjs --port 8080 --entry legacy  # 旧 UI（默认）
```

* `/`            → 默认入口（由 `--entry` 决定；默认值就是**切换开关**，单行可回退）
* `/legacy/*`    → 旧入口（永远可达）
* 这台服务器会校验 `wasm.json` 的 sha256 与磁盘 wasm 一致，不一致**拒绝启动**；
  `.wasm` 的 MIME 是 `application/wasm`（`instantiateStreaming` 的前提）。

### 10.3 测试

```bash
powershell -File tools/acceptance.ps1     # 42 道闸门（约 10 分钟）
node native/ui_parity_check.mjs           # 新旧入口同一内核（8 检查点 × 8 字段）
node native/ui_deploy_check.mjs           # MIME / 缓存 / 版本一致性 / 入口可切换
node native/ui_mobile_check.mjs           # 390×844 触控 + 安全区 + DPR 上限
node native/ui_soak_p6_check.mjs          # 重开/长局/重载/context lost/动效偏好
```

### 10.4 已知缺口

* **存档 / 回档 / 回放**：内核导出齐全，新入口**没有界面**（旧入口有）。见 `docs/ui-parity.md` §2。
* **GLB 角色资产**：没有资产管线，只有程序化外观表 + 降级（`docs/ui-p5-beats.md` §6）。
* **打赢 Boss 的幕间 E2E**：自动策略打不过第 16 层，只有拒绝路径与路由在守（§365.4）。
* **真机**：移动端结论全部来自 CDP 仿真（`docs/ui-p6-devices.md` §1）。
* 事件的**子节点正文**仍是英文（没有官方中文来源，已计数）。

### 10.5 许可证

* 本仓库的参考实现是 `RogueDeck-Core`（C#，**MIT**），按 commit `fd43e68…` 冻结，
  `ref/` 是只读浅克隆且**不入库**。
* 前端依赖：`three`（MIT）、`@react-three/fiber`（MIT）、`@react-three/uikit`（MIT）、
  `vite`（MIT）、`typescript`（Apache-2.0）。
* 中文文案来自 `spire-archive.com/api/sts1`（从游戏文件解析的社区数据）与
  `slaythespire.wiki.gg`；**游戏内容本身的版权属于 Mega Crit**，本仓库只用于学习与研究。
'''
t = io.open('README.md', encoding='utf-8').read()
io.open('README.md', 'w', encoding='utf-8', newline='\n').write(t.rstrip('\n') + readme_add)
print('docs written')
