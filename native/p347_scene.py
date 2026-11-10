"""§347：把场景表变成**可执行**的 `classifyScene(snapshot)`（ui-state-model §7b 的欠账）。

## 为什么

`docs/ui-state-model.md` §1 那张表是 18 行**散文**。它说"判定式按优先级从上到下，先成立的赢"，
但没有任何东西**执行**它 —— 于是：

* 表里排错一行（比如把兜底的 SC-02 排在 SC-02b 前面），只有读文档的人能发现；
* `describe()` 里那串 `if/switch` 是**第二份**同样的顺序，两份会漂；
* 3D 重写要从文档里重新推导一遍这个顺序。

⇒ 现在顺序只有一份：`SCENES`（数组即优先级），`classifyScene()` 取第一条命中的，
`describe()` 按它分派。文档 §1 的表格逐行对着这张数组。

## 判据的形状

`scenesMatching(s)` 返回**所有**命中的场景 id。判据：

* 每个夹具**恰好命中一个**基础场景（多重命中会被顺序藏起来 —— 那正是"排错一行"的形状）；
* **覆盖层例外**：SC-11a / SC-11b 是**叠在**别的屏上的（§3.13：遗物欠账可以压着奖励屏），
  所以它们与底下那一屏**同时命中是正确的**。判据显式允许这一种共命中，并要求
  `classifyScene` 选中的是覆盖层。

这一条修正了 §7b 原来那句"多重命中一律报错"——它对覆盖层是错的（覆盖层按定义就是叠着的）。

## 两个新字段

`classifyScene` 需要两个页面快照里原来没有的事实，都来自内核（§341 / §346）：

* `noRun`：`rd_run_seed() === i32::MIN` —— SC-00 的判据（原来靠 `pending === -1` 间接判断）；
* `inFight`：`rd_run_in_fight() === 1` —— SC-03 与 SC-03b 的分界（原来靠页面的 `mode`）。
"""

import io

PANELS = 'web/ui_panels.js'
PAGE = 'web/index.html'


def sub(text, old, new, label, count=1):
    n = text.count(old)
    assert n == count, '%s: 命中 %d 次（期望 %d）' % (label, n, count)
    return text.replace(old, new)


# ── ① ui_panels.js：SCENES + classifyScene + scenesMatching，describe 按它分派 ──
t = io.open(PANELS, encoding='utf-8').read()

OLD_DESCRIBE_START = '''  function describe(s) {
    // §274：遗物欠着的牌组编辑**优先于一切面板** —— 它可能叠在奖励屏/宝箱屏上，
    // 而"还要选几张"是玩家此刻唯一能做的事。
    if (s.pickupPicks > 0) return describePickupCard(s);
    // §293：加牌的欠账压过一切面板（与上面那条同一个理由）。
    if (s.pickupAdd > 0) return describePickupAdd(s);
    if (s.cleared) return describeCleared(s);
    if (s.runOver) return describeOver(s);
    switch (s.pending) {
      case 6:
        return describeBlessing(s);
      case 7:
        return describeBlessingCard(s);
      case 8:
        return describeEventCard(s);
      // §320：候选列表（事件摊开的新牌）。与 `EventCard` 分开：那一个收**牌组下标**，
      // 这一个收**候选槽号**，两个调用不同。
      case 9:
        return describeEventOffer(s);
      case 4:
        return describeReward(s);
      case 5:
        return describeEvent(s);
      case 3:
        return describeChest(s);
      case 2:
        return describeShop(s);
      case 1:
        return describeRest(s);
      case 0:
        // §272：`?` 房（5）掷出怪物（`unknownRoom === 2`）时是战斗。
        if (s.kind === 1 || s.kind === 2 || s.kind === 7) return describeFight(s);
        if (s.kind === 5 && s.unknownRoom === 2) return describeFight(s);
        // §286：事件把房间变成了一场战斗（`Dead Adventurer` 的伏击）。判据是内核记下的
        // **档位**，不是"kind 是 5 就该打" —— 事件、宝箱、商人都还是 kind 5。
        if (s.eventFight > 0) return describeFight(s);
        if (s.kind >= 0 && s.actionCount === 0) {
          // No moves and nothing to settle: the act has run out of map (the last row, with no way
          // onward). Saying so beats an empty panel that looks like a bug.
          return {
            title: "",
            lines: ["第一幕到此为止（这一步之后没有可走的节点）"],
            rows: [],
            buttons: [{ id: "done", label: "就到这里", action: { kind: "end_act" } }],
          };
        }
        return describeIdle(s);
      default:
        return describeIdle(s);
    }
  }'''

NEW_DESCRIBE = '''  // ---------------------------------------------------------------------------------------------
  // §347: the scene table, as code.
  //
  // `docs/ui-state-model.md` §1 是 18 行散文，而"先成立的赢"这个顺序以前**只有文档**在说。
  // 于是：表里排错一行没人能发现、`describe()` 里那串 if/switch 是第二份同样的顺序、
  // 3D 重写要重新推导一遍。现在顺序只有一份 —— **数组即优先级**，`classifyScene` 取第一条命中的。
  //
  // 每个谓词只用**内核事实**（`rd_run_*` / `rd_env_*` 经快照转述），不用页面自己的历史
  // （§341 的 `in_fight`、§344 的 `run_end` 就是为这件事加进来的）。
  // ---------------------------------------------------------------------------------------------

  /// 战斗节点（或"会打起来"的房间）。三个来源：节点种类、`?` 房掷出怪物、事件引来的伏击。
  function preFight(s) {
    if (s.kind === 1 || s.kind === 2 || s.kind === 7) return true;
    // §272：`?` 房（kind 5）掷出怪物（`unknownRoom === 2`）时是一场普通战斗。
    if (s.kind === 5 && s.unknownRoom === 2) return true;
    // §286：事件把房间变成了一场战斗（`Dead Adventurer` 的伏击）。判据是内核记下的**档位**，
    // 不是"kind 是 5 就该打" —— 事件、宝箱、商人都还是 kind 5。
    return s.eventFight > 0;
  }

  /// 地图上还有下一步可走吗？（`actionCount` 就是 `reachable().len()`。）
  function mapExhausted(s) {
    return s.kind >= 0 && s.actionCount === 0;
  }

  /// 场景表：**数组顺序就是优先级**（与 `ui-state-model.md` §1 的表格逐行对应）。
  ///
  /// `overlay: true` 的两条是**叠在**别的屏上的（§3.13：遗物欠账可以压着奖励屏），所以它们
  /// 与底下那一屏**同时命中是正确的** —— 判据显式允许这一种共命中。
  const SCENES = [
    // 1 未开局：没有局。`noRun` 来自 `rd_run_seed() == i32::MIN`。
    { id: "SC-00", overlay: false, test: (s) => !!s.noRun },
    // 2 战斗中：内核说"有一场在打"（§341 的 `rd_run_in_fight`）。它必须排在"预备战斗"之前，
    //   否则站在战斗节点上时两个屏都会命中，而顺序会替你选一个。
    { id: "SC-03b", overlay: false, test: (s) => !!s.inFight },
    // 3/4 遗物欠账（覆盖层）：它可能叠在奖励屏/宝箱屏上，而"还要选几张"是此刻唯一能做的事。
    { id: "SC-11a", overlay: true, test: (s) => s.pickupPicks > 0 },
    { id: "SC-11b", overlay: true, test: (s) => s.pickupAdd > 0 },
    // 5/6 终局。局终优先于"幕通关"（两者在页面侧本来就互斥，但顺序仍然写死）。
    { id: "SC-12b", overlay: false, test: (s) => !!s.runOver },
    { id: "SC-12a", overlay: false, test: (s) => !!s.cleared },
    // 7..15 具体的待决问句（`Pending` 的判别值）。
    { id: "SC-01", overlay: false, test: (s) => s.pending === 6 },
    { id: "SC-01b", overlay: false, test: (s) => s.pending === 7 },
    { id: "SC-09", overlay: false, test: (s) => s.pending === 8 },
    { id: "SC-10", overlay: false, test: (s) => s.pending === 9 },
    { id: "SC-04", overlay: false, test: (s) => s.pending === 4 },
    { id: "SC-08", overlay: false, test: (s) => s.pending === 5 },
    { id: "SC-07", overlay: false, test: (s) => s.pending === 3 },
    { id: "SC-05", overlay: false, test: (s) => s.pending === 2 },
    { id: "SC-06", overlay: false, test: (s) => s.pending === 1 },
    // 16 预备战斗：站在战斗节点上、还没开打。
    { id: "SC-03", overlay: false, test: (s) => s.pending === 0 && preFight(s) },
    // 17 幕尽头：没有下一步可走（M1 的地图走到最后一排）。
    { id: "SC-02b", overlay: false, test: (s) => s.pending === 0 && mapExhausted(s) },
    // 18 地图（兜底）：其余一切。
    { id: "SC-02", overlay: false, test: (s) => s.pending === 0 },
  ];

  /// 这个快照属于哪个场景。**取第一条命中的** —— 顺序就是 `SCENES` 的顺序。
  function classifyScene(s) {
    for (const scene of SCENES) {
      if (scene.test(s)) return scene.id;
    }
    // 走到这里说明 `pending` 是一个表外的值（`-1` 没有局、或以后新增的待决态）。
    return "SC-??";
  }

  /// **所有**命中的场景 id（按优先级）。判据用它验"唯一命中"：多重命中会被顺序藏起来，
  /// 而那正是"表里排错一行"的形状。
  function scenesMatching(s) {
    return SCENES.filter((scene) => scene.test(s)).map((scene) => scene.id);
  }

  /// 这个场景是覆盖层吗（可以叠在别的屏上）？
  function isOverlay(sceneId) {
    const found = SCENES.find((scene) => scene.id === sceneId);
    return !!(found && found.overlay);
  }

  /// **唯一**决策点：场景 → 那一屏怎么画。`describe` 不再自己判顺序。
  function describe(s) {
    switch (classifyScene(s)) {
      case "SC-11a":
        return describePickupCard(s);
      case "SC-11b":
        return describePickupAdd(s);
      case "SC-12a":
        return describeCleared(s);
      case "SC-12b":
        return describeOver(s);
      case "SC-01":
        return describeBlessing(s);
      case "SC-01b":
        return describeBlessingCard(s);
      case "SC-09":
        return describeEventCard(s);
      // §320：候选列表（事件摊开的新牌）。与 `EventCard` 分开：那一个收**牌组下标**，
      // 这一个收**候选槽号**，两个调用不同。
      case "SC-10":
        return describeEventOffer(s);
      case "SC-04":
        return describeReward(s);
      case "SC-08":
        return describeEvent(s);
      case "SC-07":
        return describeChest(s);
      case "SC-05":
        return describeShop(s);
      case "SC-06":
        return describeRest(s);
      case "SC-03":
        return describeFight(s);
      case "SC-02b":
        // No moves and nothing to settle: the act has run out of map (the last row, with no way
        // onward). Saying so beats an empty panel that looks like a bug.
        return {
          title: "",
          lines: ["第一幕到此为止（这一步之后没有可走的节点）"],
          rows: [],
          buttons: [{ id: "done", label: "就到这里", action: { kind: "end_act" } }],
        };
      // SC-00 / SC-02 / SC-03b / SC-?? 都落在 `describeIdle`：
      // 前三个是"这一屏不是节点面板"（战斗由 `render()` 画、地图由 `renderMap()` 画），
      // 而 `SC-??` 是表外状态 —— 给它一句"这个节点没有可做的事"比空白好。
      default:
        return describeIdle(s);
    }
  }'''

t = sub(t, OLD_DESCRIBE_START, NEW_DESCRIBE, 'describe rewrite')

# 导出
t = sub(t, '''  return { describe, effectText, KIND_NAMES, EFFECT_LABELS, statsLine, tone };''',
        '''  return {
    describe, effectText, KIND_NAMES, EFFECT_LABELS, statsLine, tone,
    // §347：场景表本身（数组即优先级）+ 分类器 + 判据用的"全部命中"
    SCENES, classifyScene, scenesMatching, isOverlay, preFight, mapExhausted,
  };''', 'exports')
io.open(PANELS, 'w', encoding='utf-8', newline='\n').write(t)

# ── ② 页面快照：补两个内核事实（noRun / inFight）──────────────────────────
t = io.open(PAGE, encoding='utf-8').read()
t = sub(t, '''  const snapshot = {
    mode,
    runOver: runOver(),''',
        '''  const snapshot = {
    mode,
    // §347：`classifyScene` 要的两个**内核事实**（都不是页面历史）。
    // `noRun`：SC-00 的判据（原来靠 `pending === -1` 间接判断）；`inFight`：SC-03 与 SC-03b 的分界。
    noRun: ex.rd_run_seed() === -2147483648,
    inFight: ex.rd_run_in_fight() === 1,
    runOver: runOver(),''', 'snapshot facts')
io.open(PAGE, 'w', encoding='utf-8', newline='\n').write(t)
print('§347: SCENES + classifyScene + describe dispatch + snapshot facts')
