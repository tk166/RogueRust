"""§347 判据：18 个场景各一份夹具 + "唯一命中"。

## 为什么夹具比文档强

`ui-state-model.md` §1 那张表说"先成立的赢"，但**没有任何东西执行它**。于是：

* 表里排错一行（比如把兜底的 SC-02 排在 SC-02b 前面）只有读文档的人能发现；
* 兜底写成**超集**（`pending === 0` 就够）会让"站在战斗节点上"同时命中 SC-03 与 SC-02，
  而顺序把这件事藏起来 —— 第一版就是这样，被 `scenesMatching` 当场抓出来。

所以判据是：

1. 每个夹具 `classifyScene` 命中**预期的那个**；
2. 每个夹具**恰好命中一个**（覆盖层例外：它们按定义叠在别的屏上，所以允许与底屏共命中）；
3. 夹具表覆盖 `SCENES` 里的**每一个** id（少一个夹具 = 那个场景没被验证过）；
4. `SCENES` 的顺序被字面量钉住（顺序即语义）。
"""

import io

TEST = 'web/ui_test.mjs'


def sub(text, old, new, label, count=1):
    n = text.count(old)
    assert n == count, '%s: 命中 %d 次（期望 %d）' % (label, n, count)
    return text.replace(old, new)


t = io.open(TEST, encoding='utf-8').read()

ANCHOR = '''console.log(`  display names     prettifyId rules; table > kernel name > prettified id`);'''

BLOCK = '''// ---------------------------------------------------------------------------------------------
// §347: the scene table is executable -- `classifyScene` + one fixture per scene.
//
// 18 个场景各一份夹具，每个断言三件事：命中预期的那一个、**恰好命中一个**（覆盖层例外）、
// 以及 `SCENES` 的顺序被字面量钉住。少一个夹具 = 那个场景从来没被验证过。
// ---------------------------------------------------------------------------------------------
{
  const scene = (s) => P.classifyScene({ ...BASE, ...s });

  // 期望顺序：与 `ui-state-model.md` §1 的表格逐行对应（**顺序即语义**）。
  const ORDER = [
    "SC-00", "SC-03b", "SC-11a", "SC-11b", "SC-12b", "SC-12a",
    "SC-01", "SC-01b", "SC-09", "SC-10", "SC-04", "SC-08", "SC-07", "SC-05", "SC-06",
    "SC-03", "SC-02b", "SC-02",
  ];
  const got = P.SCENES.map((entry) => entry.id);
  if (JSON.stringify(got) !== JSON.stringify(ORDER)) {
    fail(`SCENES order drifted:\\n  got  ${JSON.stringify(got)}\\n  want ${JSON.stringify(ORDER)}`);
  }

  // 一份夹具每个场景。字段只写**这个场景需要**的那些（其余从 BASE 来）。
  const FIXTURES = [
    ["SC-00", { noRun: true, pending: -1 }],
    ["SC-03b", { inFight: true, kind: 1, actionCount: 1 }],
    ["SC-11a", { pending: 4, pickupPicks: 2, rewardCards: [{ slot: 0, id: "anger", title: "Anger", chip: "" }] }],
    ["SC-11b", { pending: 4, pickupAdd: 2, pickupOffer: [{ slot: 0, title: "Anger" }] }],
    ["SC-12b", { runOver: true, runOverWhy: "第 3 层战败" }],
    ["SC-12a", { cleared: true, kind: 7 }],
    ["SC-01", { pending: 6, offers: [{ name: "治疗", gain: 1, gainAmount: 25, cost: 5, costAmount: 0 }] }],
    ["SC-01b", { pending: 7, blessingNeeds: 2 }],
    ["SC-09", { pending: 8, eventNeeds: 1 }],
    ["SC-10", { pending: 9, eventOffer: [{ slot: 0, id: "anger", title: "Anger" }] }],
    ["SC-04", { pending: 4, rewardCards: [{ slot: 0, id: "anger", title: "Anger", chip: "" }] }],
    ["SC-08", { pending: 5, eventText: "一块石头", choices: [{ slot: 0, label: "拿", effect: 2, amount: 10 }] }],
    ["SC-07", { pending: 3, kind: 6 }],
    ["SC-05", { pending: 2, kind: 4, shopCards: [] }],
    ["SC-06", { pending: 1, kind: 3, campfire: 3, restHeal: 24 }],
    ["SC-03", { kind: 1, actionCount: 1 }],
    ["SC-02b", { kind: 3, actionCount: 0 }],
    ["SC-02", { kind: 4, actionCount: 2 }],
  ];

  const seen = new Set();
  for (const [want, overrides] of FIXTURES) {
    const snapshot = { ...BASE, ...overrides };
    const hit = P.classifyScene(snapshot);
    if (hit !== want) fail(`scene fixture ${want} classified as ${hit}`);
    seen.add(want);

    const matches = P.scenesMatching(snapshot);
    if (matches.length === 0) fail(`scene fixture ${want} matched nothing`);
    if (matches[0] !== want) fail(`scene fixture ${want}: first match is ${matches[0]}`);
    // 覆盖层按定义叠在别的屏上 ⇒ 与底屏共命中是**对的**；其余必须唯一。
    if (!P.isOverlay(want)) {
      if (matches.length !== 1) {
        fail(`scene fixture ${want} matched ${JSON.stringify(matches)} -- base scenes must be unique`);
      }
    } else if (matches.length < 2) {
      fail(`overlay ${want} must also match the screen underneath, got ${JSON.stringify(matches)}`);
    }
  }

  // 覆盖：`SCENES` 里每一个 id 都要有夹具（少一个 = 那个场景从没被验证过）。
  for (const id of ORDER) {
    if (!seen.has(id)) fail(`no fixture for scene ${id}`);
  }
  if (seen.size !== P.SCENES.length) {
    fail(`fixtures ${seen.size} != scenes ${P.SCENES.length}`);
  }

  // `describe()` 与分类器必须一致：18 个夹具都要画出一份**有内容**的面板描述
  // （除了"战斗/地图"那几屏 —— 它们由 `render()` / `renderMap()` 画，节点面板只是兜底）。
  for (const [want, overrides] of FIXTURES) {
    const described = P.describe({ ...BASE, ...overrides });
    if (!described || typeof described !== "object" || !Array.isArray(described.buttons)) {
      fail(`scene fixture ${want}: describe() did not return a panel description`);
    }
    if (want === "SC-02b" && !(described.buttons || []).some((b) => b.action.kind === "end_act")) {
      fail("SC-02b must offer `end_act`");
    }
    if (want === "SC-03" && !(described.buttons || []).some((b) => b.action.kind === "begin_fight")) {
      fail("SC-03 must offer `begin_fight`");
    }
  }
}

console.log(`  scene table       classifyScene: 18 fixtures, base scenes unique, overlays stack`);'''

t = sub(t, ANCHOR, BLOCK + '\n' + ANCHOR, 'scene fixtures')
io.open(TEST, 'w', encoding='utf-8', newline='\n').write(t)
print('§347: 18 fixtures + uniqueness + describe agreement')
