#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""coverage_matrix.py -- 工作包 D：把"每个实体被验证到什么程度"生成成一页，并当闸门用。

WHY
---
§195.9 / §213 / §214 这几轮里，"某只怪与 wiki 对不上"是这样被发现的：**我先想起来它可疑**，
然后去翻 `native/wiki_asc/` 与 `docs/spec/`。这条流程靠记性，而记性没有闸门：`chosen` 的 HP
错了很久（48 vs 95-99）、`spiker.spike` 根本不是 wiki 的那一招、`spire_growth.strategic` 甚至
不在遭遇的 `Actions` 名单里 —— 期间 20 道闸门全绿。闸门看不见 wiki（`sts-wiki-gap.md` §4 写过
这一句），但闸门**能**看见"这个实体没有任何来源、没有任何测试、也没有声明过偏差"。这一页是那张账。

五列的口径（**每一列都是派生的**，没有一处手抄清单）
------------------------------------------------------
Implemented   实体在内容里且**可达**：monster 在某个遭遇名单里（或被 spawn 点到）；action 被某只怪
              的动作表/AI 规则引用（或在 `INV_UNWIRED` 里声明"故意没接线"）；status 被某段程序或
              起始状态引用；card 在起始牌组里或被某段程序塞进来；encounter/event 在某张幕池里。
              不可达 = `orphan` ⇒ **红**（内容长出一条没人引用的行，是最"绿"的形态）。
RuntimeTested `test:<函数名>` = 某条内核测试的函数体里出现了这个 id 字符串（扫描器见 `tests()`）；
              否则 `harness:<名字>` = 只有通用对拍层遍历到它（`ENEMY_DIFF` 跑**每一条** `EACT`、
              `CARD_DIFF` 跑**每一张**卡）；否则 `—`。⚠️ 强弱不同：`harness` 只说明"它被跑过、
              程序文本与参考实现一致"，不说明"它按 wiki 的数在跑"。
WikiVerified  `wiki:<dump>` = `native/wiki_asc/*.txt`（或 `native/wiki_*.txt`）里有它的
              `{{Enemy Infobox|Name=…}}`，**并且** checker 钉了它的数字（`INV_ASC_HP` /
              `INV_ASC_VARIANTS` / `INV_ROLLS` / `INV_SPAWN_COUNTERS`）。否则 `spec:<TABLE>` =
              只对上了 `native/sts_content_check.py` 里那份**也是人抄的**清单（§195.9 抓到过它错）。
Deviation     声明过的偏差：`INV_UNWIRED` / `INV_NO_ASC` / `INV_NO_ASC_HP`，加上
              `docs/sts-wiki-gap.md` §G 的"故意不修"表与 §H 的 Boss 剩余差异表
              （**直接解析那张表**，不抄第二份；解析出的 id 必须存在，否则红）。
Evidence      `§N`（该实体在 checker 里被引用到的 port-plan 小节）+ 表名 + 测试名。

用法：
  python -X utf8 native/coverage_matrix.py            # 重新生成 docs/coverage-matrix.md
  python -X utf8 native/coverage_matrix.py --check     # 只校验：磁盘上的文件必须与重新生成的一致
退出码：0 = 新/一致；1 = 陈旧或不变量红；2 = 前提缺失。
"""

import argparse
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import sts_content_check as C          # noqa: E402  (不变量表只有这一份)

SRC = os.path.join(ROOT, 'tools', 'contentc', 'packages', 'sts', 'sts.roguedeck.json')
OUT = os.path.join(ROOT, 'docs', 'coverage-matrix.md')
GAP = os.path.join(ROOT, 'docs', 'sts-wiki-gap.md')
CHECKER = os.path.join(HERE, 'sts_content_check.py')
KERNEL = os.path.join(ROOT, 'kernel')
TEST_CRATES = ['rd-core', 'rd-run', 'rd-wasm']

# 一张 wiki 页面覆盖多只怪、名字也对不上的，只有这几处；每条都要**真的用到**（见 invariants）。
PAGE_ALIASES = {
    'donu_and_deca': ['donu', 'deca'],
    'louses': ['louse_red', 'louse_green'],
    'shapes': ['spiker'],
    'thieves': ['looter'],
    'slavers': ['slaver_red', 'blue_slaver', 'taskmaster'],
}

# 扫描器自身的探针：这几个 id 一定有具名测试。名字改了 ⇒ 这里红，逼着同步（故意的）。
TEST_PROBES = ['spiker', 'chosen', 'standard.hex', 'bash']

MIN_TESTS = 500          # 扫不到 500 条测试 = 扫描器坏了，不是"测试变少了"

# 内容里**故意**没人引用的行。和 `INV_UNWIRED` 同一个道理：把"我知道它是孤的"写下来，比让它
# 悄悄消失好；而声明本身也要被检查 —— 有一天它被接进遭遇了（或者 id 被删了），这里会红，
# 逼着把声明删掉。
ORPHAN_OK = {
    'acid_slime_s': '`enc_small_slimes` 只放 `acid_slime_m` + `spike_slime_s`（StS 的 Small Slimes 是'
                    '随机 1-3 只混编，这里钉了一种组合）；记录与两条动作保留给扩池用',
    'spike_slime_m': '同上：中号尖刺史莱姆只在 Boss 分裂路径上出现过，遭遇池里没有它',
    'louse_green': '`enc_louse` 只有红虱（§193：绿虱的动作仍在 `EACT` 里、读常量而不是计数器）；'
                   '记录保留，接线那天连同 `Rolls` 一起写',
}


def die(code, message):
    print(message)
    raise SystemExit(code)


# ── 内容 ──────────────────────────────────────────────────────────────────────────────────────────
def load_content():
    if not os.path.isfile(SRC):
        die(2, 'STALE: 找不到源文档 %s' % SRC)
    return json.load(io.open(SRC, encoding='utf-8'))


def collect_strings(node, out):
    """收集 JSON 里所有字符串（键名也算）：用来判"内容深处有没有引用它"。"""
    if isinstance(node, dict):
        for key, value in node.items():
            out.add(key)
            collect_strings(value, out)
    elif isinstance(node, list):
        for value in node:
            collect_strings(value, out)
    elif isinstance(node, str):
        out.add(node)


def build_entities(doc, by_test=None):
    monsters = {m['Id']: m for m in doc['Monsters']}
    actions = {a['Id']: a for a in doc['EnemyActions']}
    cards = {c['Id']: c for c in doc['Cards']}
    statuses = {s['Id']: s for s in doc['Statuses']}
    relics = {r['Id']: r for r in doc['Relics']}
    potions = {p['Id']: p for p in doc['Potions']}
    encounters = {e['Id']['Value']: e for e in doc['Encounters']}

    roster = set()
    for enc in doc['Encounters']:
        for enemy in enc.get('Enemies') or []:
            roster.add(enemy['Id'])

    listed_actions = set()
    for monster in doc['Monsters']:
        for entry in monster.get('Actions') or []:
            listed_actions.add(entry['value'])
        for rule in monster.get('IntentRules') or []:
            for match in re.finditer(r'"value":\s*"([a-z0-9_]+\.[a-z0-9_]+)"',
                                     json.dumps(rule)):
                if match.group(1) in actions:
                    listed_actions.add(match.group(1))

    # ⚠️ 每个类型都要把**它自己的定义表**排除在外：否则每个实体都因为"它自己被定义了"
    # 而"可达"，orphan 永远报不出来（第一版就是这样：贴一只没人引用的
    # `ghost_slime` 进去，报的却是"没有证据列"）。
    tables = ('EnemyActions', 'Cards', 'Statuses', 'Relics', 'Encounters', 'Monsters',
              'Start', 'Deck', 'EventTables', 'EncounterTables', 'Potions')
    everywhere = {}
    for skip in ('Monsters', 'Cards', 'Statuses', 'Relics', 'Potions', 'Encounters'):
        bag = set()
        for key in tables:
            if key != skip:
                collect_strings(doc.get(key), bag)
        # 避免误伤：`Deck` 里的卡 id 属于"真的被引用"，但它在上面的循环里已经
        # 被收进去了；这里只需要把 `Deck`/`Start` 重新盖一遍。
        collect_strings(doc.get('Deck'), bag)
        collect_strings(doc.get('Start'), bag)
        everywhere[skip] = bag

    decks = {entry['value'] for entry in doc['Deck']}
    pools = set()
    for table in (doc.get('EncounterTables') or {}).values():
        if isinstance(table, list):
            pools.update(entry.get('Id') for entry in table)
    events = set()
    for table in (doc.get('EventTables') or {}).values():
        if isinstance(table, list):
            events.update(entry.get('Id') for entry in table)

    out = {kind: {} for kind in
           ('monster', 'action', 'card', 'status', 'relic', 'potion', 'encounter', 'event')}

    monster_refs = everywhere['Monsters']
    for mid in monsters:
        reachable, why = mid in roster, 'encounter roster'
        if not reachable and mid in monster_refs:
            reachable, why = True, 'spawned by a program'
        out['monster'][mid] = {'record': monsters[mid], 'reachable': reachable, 'why': why}
    for aid in actions:
        owner = aid.split('.')[0]
        reachable, why = aid in listed_actions, 'listed by a monster'
        if not reachable and aid in C.INV_UNWIRED:
            reachable, why = True, 'declared unwired (INV_UNWIRED)'
        # ⚠️ §217: 这里曾经写的是 `aid in everywhere` —— 而 `everywhere` 是**按类别的 dict**，
        # 于是它在比"动作 id 与 dict 的键"，永远不成立（审阅 P2-A 点出来的正是这一行）。
        if not reachable and aid in everywhere['EnemyActions']:
            reachable, why = True, 'referenced elsewhere'
        if owner in monsters:
            owning = owner
        else:
            owning = next((mid for mid in sorted(monsters) if mid.startswith(owner + '_')), None)
        out['action'][aid] = {'record': actions[aid], 'reachable': reachable, 'why': why,
                              'owner': owning}
    # 牌堆的可达性不在内容里：奖励牌是内核按**稀有度**从整张 `Cards` 表里抽的，
    # 所以"在牌池里"对每一行都成立；`why` 只说明它**还**因为什么更近。
    card_refs = everywhere['Cards']
    for cid in cards:
        if cid in decks:
            why = 'start deck'
        elif cid in card_refs:
            why = 'named by a program/event'
        else:
            why = 'card reward pool (by rarity)'
        out['card'][cid] = {'record': cards[cid], 'reachable': True, 'why': why}
    # ⚠️ 不能用"字符串相等"判状态可达：药水的 `Effect` 是
    # `combat_status:standard.duplication` 这种原子列表（§158），状态 id 只是子串。
    blob = chr(10).join(sorted(everywhere['Statuses']))
    for sid in statuses:
        found = re.search(r'(?<![a-z0-9_])' + re.escape(sid) + r'(?![a-z0-9_])', blob)
        tested = bool((by_test or {}).get(sid))
        if found:
            why, reachable = 'applied by a program/trigger/potion', True
        elif tested:
            # 内容里没有任何一行施它（本内容没有那张牌），但内核测试直接按 id
            # 施它—— 它不是死行，但也不是"内容驱动的"。
            why, reachable = 'test-only (no content row applies it)', True
        else:
            why, reachable = 'nothing applies it', False
        out['status'][sid] = {'record': statuses[sid], 'reachable': reachable, 'why': why}
    for rid in relics:
        out['relic'][rid] = {'record': relics[rid], 'reachable': True, 'why': 'relic pool (Rarity)'}
    for pid in potions:
        out['potion'][pid] = {'record': potions[pid], 'reachable': True,
                              'why': 'potion pool (Rarity)'}
    for eid, enc in encounters.items():
        out['encounter'][eid] = {'record': enc, 'reachable': eid in pools,
                                 'why': 'act encounter pool'}
    out['_meta'] = {'event_slots': sum(len(table) for table in (doc.get('EventTables') or {}).values()
                                       if isinstance(table, list)),
                    'event_ids': len(events)}
    for eid in events:
        out['event'][eid] = {'record': {}, 'reachable': eid in events, 'why': 'act event pool'}
    return out


# ── wiki dump ─────────────────────────────────────────────────────────────────────────────────────
def normalize_name(text):
    # ⚠️ 体型后缀必须**保留**：FS 的 `Spike Slime (S)` / `(M)` / `(L)` 是三种不同的怪，
    # 一律砍掉括号会让它们挤成同一个键（第一版就这样，于是 `spike_slime_s` 被前缀规则
    # 分给了 `acid_slime.txt`）。
    def size(match):
        inner = match.group(1).strip().lower()
        return '_' + inner if inner in ('s', 'm', 'l') else ' '
    text = re.sub(r'\((.*?)\)', size, text)
    text = text.lower().replace('&', ' and ')
    text = re.sub(r'[^a-z0-9]+', '_', text).strip('_')
    if text.startswith('the_') and len(text) > 4:
        text = text[4:]
    return text


def name_keys(text):
    """一个名字 → **有序**的键列表：先"带体型后缀"，再"纯字母"。

    `Spike Slime (S)` → ['spike_slime_s', 'spike_slime']；`Bronze Orb` → ['bronze_orb']；
    `bronze_orb`（id）同样 → ['bronze_orb']。两条都要，是因为下划线在页名里是空格、在 id 里
    是分隔符：只保留一种写法时必然有一半名字对不上（第一版把 `bronze_orb` 分给了
    `bronze_automaton.txt` —— 那一页里也有一个 Bronze Orb 的 Infobox，于是"能对上"变成了
    "对到了别人的页面"，比报错更糟）。
    """
    full = normalize_name(text)
    keys = [full]
    bare = re.sub(r'_(s|m|l|1|2|3)$', '', full)
    if bare != full:
        keys.append(bare)
    return keys


def wiki_dumps():
    """→ {relpath: [normalized infobox names]}。只认 `{{Enemy Infobox` 的 `Name=`（Power Infobox 也有 Name）。"""
    out = {}
    dirs = [('wiki_asc', os.path.join(HERE, 'wiki_asc')), ('', HERE)]
    for tag, directory in dirs:
        if not os.path.isdir(directory):
            continue
        for name in sorted(os.listdir(directory)):
            if not name.endswith('.txt'):
                continue
            if tag == '' and not name.startswith('wiki_'):
                continue
            path = os.path.join(directory, name)
            text = io.open(path, encoding='utf-8', errors='replace').read()
            names = []
            for chunk in text.split('{{Enemy Infobox')[1:]:
                match = re.search(r'\|\s*Name\s*=\s*([^\n|}]+)', chunk)
                if match:
                    names.append(normalize_name(match.group(1)))
            if names:
                out[os.path.relpath(path, HERE).replace('\\', '/')] = names
    return out


def map_monsters_to_wiki(monster_ids, dumps):
    """monster id → dump 路径。精确（去 the/去括号）→ 前缀（sentry_1 → sentry）→ 别名表。"""
    page_of = {}
    for rel, names in dumps.items():
        for name in names:
            for key in name_keys(name):
                page_of.setdefault(key, []).append(rel)
    def score(rel, key):
        base = normalize_name(os.path.basename(rel).split('.')[0])
        if base == key:
            tier = 0
        elif base.startswith('wiki_') and base[5:] == key:
            tier = 0
        elif key.startswith(base) and len(base) >= 4:
            tier = 1
        elif base.startswith(key) and len(key) >= 4:
            tier = 2
        else:
            tier = 3
        # 同名页面有两份时优先 `wiki_asc/`（§195.9 起 §号引用的就是这一目录里的文件）
        return (tier, 0 if rel.startswith('wiki_asc/') else 1, rel)

    mapping, used = {}, set()
    for mid in sorted(monster_ids):
        keys = name_keys(mid)
        hits = []
        for key in keys:
            hits = list(page_of.get(key, []))
            if hits:
                break
        if not hits:
            for name, rels in sorted(page_of.items()):
                if keys[0].startswith(name) and len(name) >= 4:
                    hits.extend(rels)
        if hits:
            best = sorted(set(hits), key=lambda rel: score(rel, keys[0]))[0]
            mapping[mid] = best
            used.add(best)
    for page, ids in PAGE_ALIASES.items():
        rel = sorted(r for r in dumps if os.path.basename(r).split('.')[0] == page)
        if not rel:
            continue
        for mid in ids:
            if mid in monster_ids and mid not in mapping:
                mapping[mid] = rel[0]
                used.add(rel[0])
    return mapping, used


# ── 内核测试 ─────────────────────────────────────────────────────────────────────────────────────
def strip_rust(text):
    """把字符串/字符/注释替换成**等长**的空格，只留结构。

    ⚠️ 必须是等长的：第一版直接把它们**删掉**，于是 `{`/`}` 的偏移是在缩短后的文本里数出来的，
    函数体被切在很早的一个 `}` 上 —— `the_potions_are_readable` 只剩 4675 字节（真实长度是它的
    几倍），33 瓶药水因此全部报"没有任何证据"。截断的扫描器看起来完全正常，这正是项目里反复
    出现的"工具骗人"形状。
    """
    out = list(text)
    i, n = 0, len(text)

    def blank(a, b):
        for position in range(a, min(b, n)):
            if out[position] != chr(10):
                out[position] = ' '

    while i < n:
        ch = text[i]
        if ch == '/' and i + 1 < n and text[i + 1] == '/':
            j = text.find(chr(10), i)
            j = n if j < 0 else j
            blank(i, j)
            i = j
        elif ch == '/' and i + 1 < n and text[i + 1] == '*':
            j = text.find('*/', i + 2)
            j = n if j < 0 else j + 2
            blank(i, j)
            i = j
        elif ch == 'r' and i + 1 < n and text[i + 1] in '#"':
            j, hashes = i + 1, 0
            while j < n and text[j] == '#':
                hashes += 1
                j += 1
            if j < n and text[j] == '"':
                closing = '"' + '#' * hashes
                k = text.find(closing, j + 1)
                stop = n if k < 0 else k + len(closing)
                blank(i, stop)
                i = stop
            else:
                i += 1
        elif ch == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == chr(92) else 1
            blank(i, j + 1)
            i = j + 1
        elif ch == "'":
            if i + 2 < n and text[i + 2] == "'":
                blank(i, i + 3)
                i += 3
            elif i + 2 < n and text[i + 1] == chr(92):
                j = text.find("'", i + 2)
                stop = n if j < 0 else j + 1
                blank(i, stop)
                i = stop
            else:
                i += 1
        else:
            i += 1
    return ''.join(out)


def tests(kernel_root=None, crates=None):
    """→ [(crate, fn_name, body)]，递归扫 `<kernel>/<crate>/src/**/*.rs`。

    §217 补的两处盲区（都是"对账"发现的，不是猜的）：

    * **不递归** ⇒ `rd-run/src/state/archive.rs` 的 8 条测试从来没被扫到；
    * **`#[test]` 与 `fn` 之间隔着 doc 注释** ⇒ 旧的 head 正则只允许中间有更多 `#[...]`，
      于是 `rd-wasm/src/run.rs:7041` 那 1 条也漏掉。

    对账（ground truth 是 `cargo test -p <crate> -- --list`，不是 grep 的行数）：

    ```text
    cargo --list    rd-core 704 + rd-run 108 + rd-wasm 94 = 906   （其中 2 条 #[ignore]）
    修前扫描器      893   （缺 9：8 条在嵌套目录 + 1 条被 doc 注释挡住）
    修后扫描器      906   == cargo 的清单
    ```

    （grep 得到的"906 行含 `#[test]`"里另有 4 处是**注释里提到的** `#[test]` —— 它们本来就不是
    测试，扫描器用 `strip_rust` 的位置检查把它们排除了。第一版按行数推"真实 902"是错的，
    因为同一行里可能出现两个属性。）

    ⚠️ 注释里提到的 `#[test]` 必须**不算**测试：判据是"这个位置在 `strip_rust` 之后是空格"
    —— 那说明它落在注释或字符串里。（`strip_rust` 是等长替换，所以偏移可以直接比对。）
    """
    found = []
    root = kernel_root or KERNEL
    for crate in (crates or TEST_CRATES):
        src_dir = os.path.join(root, crate, 'src')
        if not os.path.isdir(src_dir):
            continue
        for directory, _dirs, files in os.walk(src_dir):
            for name in sorted(files):
                if not name.endswith('.rs'):
                    continue
                text = io.open(os.path.join(directory, name), encoding='utf-8',
                               errors='replace').read()
                skeleton = strip_rust(text)
                for match in re.finditer(r'#\[test\]', text):
                    if skeleton[match.start()] != "#":
                        continue          # 这条 `#[test]` 在注释或字符串里
                    got = head_of(text, match.end())
                    if not got:
                        continue
                    brace = text.find("{", got.end())
                    if brace < 0:
                        continue
                    depth, end = 0, len(text) - 1
                    for offset, ch in enumerate(strip_rust(text[brace:])):
                        if ch == "{":
                            depth += 1
                        elif ch == "}":
                            depth -= 1
                            if depth == 0:
                                end = brace + offset
                                break
                    found.append((crate, got.group(1), text[brace:end + 1]))
    return found


def head_of(text, position):
    """从 `#[test]` 之后找 `fn <名字>`：允许更多 `#[...]` 属性**和 doc/行注释**。

    ⚠️ 注释那一半是 §217 补的：`rd-wasm/src/run.rs:7041` 的 `#[test]` 与 `fn` 之间夹着
    `/// ...`，旧写法（只允许 `#[...]`）把那条测试整个丢掉了。
    """
    pattern = re.compile(r"\s*(?:#\[[^\]\n]*\]\s*|//[^\n]*\n\s*)*fn\s+([A-Za-z0-9_]+)")
    return pattern.match(text, position)


def strip_comments(text):
    """把注释替换成等长空格，**字符串原样保留**。

    为什么要与 `strip_rust` 分开：抽"测试体里出现的字符串字面量"时，注释里的 `"spiker"` 不能算
    引用（夹具 4 就是打这个）。花括号配对才需要连字符串一起抹掉。
    """
    out = list(text)
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            j = text.find(chr(10), i)
            j = n if j < 0 else j
            for position in range(i, j):
                out[position] = " "
            i = j
        elif ch == "/" and i + 1 < n and text[i + 1] == "*":
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            for position in range(i, j):
                if out[position] != chr(10):
                    out[position] = " "
            i = j
        elif ch == '"' or (ch == "r" and i + 1 < n and text[i + 1] in '#"'):
            # 字符串整体跳过（不抹），其中的 `//` 不是注释。
            if ch == '"':
                j = i + 1
                while j < n and text[j] != '"':
                    j += 2 if text[j] == chr(92) else 1
                i = j + 1
            else:
                j, hashes = i + 1, 0
                while j < n and text[j] == "#":
                    hashes += 1
                    j += 1
                if j < n and text[j] == '"':
                    closing = '"' + "#" * hashes
                    k = text.find(closing, j + 1)
                    i = n if k < 0 else k + len(closing)
                else:
                    i += 1
        elif ch == "'":
            if i + 2 < n and text[i + 2] == "'":
                i += 3
            elif i + 2 < n and text[i + 1] == chr(92):
                j = text.find("'", i + 2)
                i = n if j < 0 else j + 1
            else:
                i += 1
        else:
            i += 1
    return "".join(out)


def table_sweeps(found):
    """kind → [测试名]：函数体里出现 `…_count()` / `Table::X` / `rows(Table::X)` 形式的整表遍历。

    ⚠️ 方法名有**单数也有复数**：`content.potion_count()`（一条）与 `content.rows(Table::Cards)`
    都在用；第一版只认复数，于是 33 瓶药水全部报"没有证据"（而那条测试其实跑得挺好）。
    排序：真的按这张表的计数走一遍的排前面，`xxx.len()` 那种顺带遍历的排后面。
    """
    hits = {}
    for _crate, fn, body in found:
        for kind, plural in TABLE_WORDS.items():
            singular = plural[:-1]
            strong = bool(re.search(r'(?:^|[^A-Za-z0-9_])' + singular + r'_count\s*\(', body)
                          or re.search(r'(?:^|[^A-Za-z0-9_])' + plural + r'_count\s*\(', body)
                          or re.search(r'Table::' + singular.capitalize(), body))
            weak = bool(re.search(r'(?:^|[^A-Za-z0-9_])' + plural + r'\.len\s*\(', body))
            if strong or weak:
                hits.setdefault(kind, []).append((0 if strong else 1, fn))
    return {kind: [fn for _tier, fn in sorted(set(entries))] for kind, entries in hits.items()}


def tests_by_entity(found):
    """token → [(crate, fn)]。token 是测试体里出现的字符串字面量（id 就写在里面）。"""
    index = {}
    for crate, fn, body in found:
        tokens = set()
        # §217：先剥注释 —— 注释里写 `"spiker"` 不算引用（夹具 4 钉这个）。
        for match in re.finditer(r'"([^"\\\n]{1,60})"', strip_comments(body)):
            tokens.add(match.group(1))
        for token in tokens:
            index.setdefault(token, []).append((crate, fn))
    return index


# ── checker：§ 号、表名、状态引用 ────────────────────────────────────────────────────────────────
def sections_of_ids():
    """id → 它在 checker 里被引用到的 § 号（含紧邻前几行注释 —— § 常写在注释里）。"""
    if not os.path.isfile(CHECKER):
        die(2, 'STALE: 找不到 %s' % CHECKER)
    lines = io.open(CHECKER, encoding='utf-8').read().splitlines()
    out = {}
    id_re = re.compile(r'["\']([a-z0-9_]+(?:\.[a-z0-9_]+)?)["\']')
    sec_re = re.compile(r'§\s*(\d+(?:\.\d+)?)')
    for position, line in enumerate(lines):
        ids = id_re.findall(line)
        if not ids:
            continue
        sections = []
        for chunk in lines[max(0, position - 4):position + 1]:
            sections.extend(sec_re.findall(chunk))
        if not sections:
            continue
        for ident in ids:
            bucket = out.setdefault(ident, [])
            for section in sections:
                if section not in bucket:
                    bucket.append(section)
    return out


CHECKER_TABLES = {
    'INV_MONSTERS': 'monster', 'INV_ACTIONS': 'action', 'INV_CARDS': 'card',
    'INV_STATUSES': 'status', 'INV_ASC_VARIANTS': 'action', 'INV_ASC_HP': 'monster',
    'INV_ROLLS': 'monster', 'INV_SPAWN_COUNTERS': 'monster', 'INV_NO_ASC': 'action',
    'INV_NO_ASC_HP': 'monster', 'INV_UNWIRED': 'action',
}


def checker_table_of():
    """id → 它被钉在哪几张不变量表里。"""
    out = {}
    for table in CHECKER_TABLES:
        value = getattr(C, table, None)
        if value is None:
            die(1, 'MATRIX FAIL: checker 里没有 %s（表名漂了？）' % table)
        keys = value.keys() if isinstance(value, dict) else [row[0] for row in value]
        for key in keys:
            out.setdefault(key, set()).add(table)
    return out


def status_refs(doc):
    """status id → {'card', 'action'}：谁的程序里提到了它。"""
    refs = {}

    def walk(node, where):
        if isinstance(node, dict):
            for key, value in node.items():
                if isinstance(value, str) and key in ('StatusDefinitionId',):
                    refs.setdefault(value, set()).add(where)
                elif isinstance(value, dict) and key == 'StatusDefinitionId' and 'value' in value:
                    refs.setdefault(value['value'], set()).add(where)
                walk(value, where)
        elif isinstance(node, list):
            for value in node:
                walk(value, where)

    for card in doc['Cards']:
        walk(card.get('Program'), 'card')
    for action in doc['EnemyActions']:
        walk(action.get('Program'), 'action')
        walk(action.get('ProgramAsc'), 'action')
    return refs


# ── gap 文档里的偏差（直接解析，不抄第二份） ─────────────────────────────────────────────────────
def gap_deviations():
    """→ (id → [偏差文本], [(名字, 剩余差异)])。§G 的"故意不修"表 + §H 的 Boss 表。"""
    if not os.path.isfile(GAP):
        die(2, 'STALE: 找不到 %s' % GAP)
    lines = io.open(GAP, encoding='utf-8').read().splitlines()
    deviations, bosses, g_rows = {}, [], 0

    def cell(c):
        return re.sub(r'\s+', ' ', c.replace('**', '')).strip()

    in_g = in_h = False
    armed = False          # §217：只在"仍然故意不修" / "放宽"那两张表下解析
    for line in lines:
        if line.startswith('### G.'):
            in_g, in_h = True, False
            # §217：§G 有**两张**表 —— "已修"（历史：原值 → 现在）与"仍然故意不修"（现存偏差）。
            # §215 把两张都解析了，于是 8 条早已修好的招式（`spiker.cut`、`chosen.poke` …）
            # 在矩阵里被列成"现存偏差"，读起来像"ours 8 / wiki 7"。只认后一张。
            armed = ('不修' in line) or ('放宽' in line)
            continue
        if line.startswith('## H.'):
            in_g, in_h = False, True
            armed = False
            continue
        if line.startswith('### ') or line.startswith('## '):
            in_g = in_h = armed = False
        if not armed and in_g:
            # "仍然**故意不修**"这句在表格**之前**，是那一表的开关。
            if '故意不修' in line:
                armed = True
            continue
        if not (in_g or in_h) or not line.startswith('|'):
            continue
        cells = line.strip().strip('|').split('|')
        if len(cells) < 3 or set(cells[0].strip()) <= set('-: '):
            continue
        if cells[0].strip() in ('招式', 'Boss'):
            continue
        if in_g:
            raw = re.findall(r'`([a-z0-9_]+(?:\.[a-z0-9_]+)?)`', cells[0])
            if not raw:
                continue
            dotted = [token for token in raw if '.' in token]
            prefix = dotted[0].split('.')[0] if dotted else ''
            ids = [token if '.' in token else (prefix + '.' + token if prefix else token)
                   for token in raw]
            g_rows += 1
            text = 'ours %s / wiki %s —— %s' % (cell(cells[1]), cell(cells[2]), cell(cells[3]))
            for ident in ids:
                deviations.setdefault(ident, []).append(text)
        else:
            remaining = cell(cells[-1])
            if remaining.startswith('无'):
                continue
            bosses.append((cells[0].strip(), remaining))
    if not g_rows:
        die(1, 'MATRIX FAIL: gap §G 的"故意不修"表一行都没解析出来（格式变了？）')
    return deviations, bosses


# ── 组装 ─────────────────────────────────────────────────────────────────────────────────────────
KIND_LABEL = {
    'monster': '怪物', 'action': '敌人动作', 'card': '卡牌', 'status': '状态',
    'encounter': '遭遇', 'event': '事件', 'relic': '遗物', 'potion': '药水',
}
KIND_ORDER = ['monster', 'action', 'card', 'status', 'encounter', 'event', 'relic', 'potion']
HARNESS = {'action': 'ENEMY_DIFF', 'card': 'CARD_DIFF'}

# 内核里"遍历整张表"的测试（`for index in 0..content.potion_count()` / `Table::Potion`）：它们
# 一条测试管一整类实体，所以**每一条**都被覆盖，而测试体里不会出现任何一个具体 id。
# 这是"派生"而不是"手抄"：认出遍历形状就够，不需要知道是哪条测试。`ENEMY_DIFF`/`CARD_DIFF`
# 是同一类东西的仓库外版本（`native/fight_diff.py`），已经写进 HARNESS。
TABLE_WORDS = {'card': 'cards', 'action': 'enemy_actions', 'potion': 'potions',
               'monster': 'monsters', 'status': 'statuses', 'relic': 'relics',
               'encounter': 'encounters'}
WIKI_TIE = {'monster': {'INV_ASC_HP', 'INV_MONSTERS'},
            'action': {'INV_ASC_VARIANTS', 'INV_ROLLS', 'INV_SPAWN_COUNTERS'}}


def section_key(value):
    return [int(part) if part.isdigit() else 0 for part in value.split('.')]


def build_rows(doc):
    found_early = tests()
    entities = build_entities(doc, tests_by_entity(found_early))
    dumps = wiki_dumps()
    wiki_of, used_dumps = map_monsters_to_wiki(set(entities['monster']), dumps)
    found = found_early
    if len(found) < MIN_TESTS:
        die(1, 'MATRIX FAIL: 只扫到 %d 条测试（下限 %d）—— 扫描器坏了，不是测试变少了'
            % (len(found), MIN_TESTS))
    by_test = tests_by_entity(found)
    sweeps = table_sweeps(found)
    sections = sections_of_ids()
    table_of = checker_table_of()
    gap_dev, boss_rows = gap_deviations()
    refs = status_refs(doc)

    page_monsters = {}
    for mid, rel in wiki_of.items():
        for name in dumps.get(rel, []):
            bucket = page_monsters.setdefault(name, [])
            if mid not in bucket:
                bucket.append(mid)
        # §H 的表头写的是**页面名**（`Donu & Deca`），而那一页里是两个独立的 Infobox。
        page_monsters.setdefault(normalize_name(os.path.basename(rel).split('.')[0]), []).append(mid)
    problems = []
    for name, remaining in boss_rows:
        ids = None
        for key in name_keys(name):
            ids = page_monsters.get(key)
            if ids:
                break
        if not ids:
            problems.append('gap §H 的 `%s` 找不到对应怪物（wiki dump 里没有这个 Infobox 名字）' % name)
            continue
        for mid in ids:
            bucket = gap_dev.setdefault(mid, [])
            entry = 'gap §H: %s' % remaining
            if entry not in bucket:
                bucket.append(entry)

    # §217：偏差表现在也会指到**状态**（`standard.slow` 的"只放大直接伤害"），所以存在性检查
    # 要走全部类别 —— 只查动作与怪物时，一条合法的状态偏差会被判成"表漂了"。
    all_ids = {ident for kind in KIND_ORDER for ident in entities[kind]}
    for ident in gap_dev:
        if ident not in all_ids:
            problems.append('gap 文档里的 `%s` 在内容里不存在（偏差表漂了）' % ident)

    rows, summary = [], {}
    entity_meta = entities.pop('_meta', {})
    for kind in KIND_ORDER:
        stats = {'rows': 0, 'named': 0, 'harness': 0, 'none': 0, 'wiki': 0, 'spec': 0,
                 'dev': 0, 'orphan': 0}
        for eid in sorted(entities[kind]):
            info = entities[kind][eid]
            if info['reachable']:
                implemented = 'yes'
                if kind == 'status' and info['why'].startswith('test-only'):
                    implemented = 'yes (test-only)'
                elif info['reachable'] and info['why'] in ('spawned by a program',
                                                           'declared unwired (INV_UNWIRED)'):
                    implemented = 'yes (%s)' % info['why']
            elif eid in ORPHAN_OK:
                implemented = 'orphan (declared)'
            else:
                implemented = 'orphan'
                stats['orphan'] += 1
                problems.append('%s `%s` 不可达：没有任何遭遇/程序/池引用它' % (kind, eid))

            names = []
            for _crate, fn in by_test.get(eid, []):
                if fn not in names:
                    names.append(fn)
            # `TestNamed`：这个 id 以**字符串字面量**出现在某条测试的函数体里。
            # ⚠️ 它是"被引用"，不是"行为被断言"：`assert_eq!(id, "spiker")` 与"真打一场 spiker"
            # 在这一列里长得一模一样（审阅 P2-A 的原话，这也是列名从 `RuntimeTested` 改过来的原因）。
            test_named = '—'
            harness = '—'
            if names:
                test_named = ', '.join(names[:2])
                if len(names) > 2:
                    test_named += ' …(+%d)' % (len(names) - 2)
                stats['named'] += 1
            elif kind in HARNESS:
                harness = HARNESS[kind]
                stats['harness'] += 1
            elif kind in sweeps:
                harness = sweeps[kind][0]
                if len(sweeps[kind]) > 1:
                    harness += ' …(+%d)' % (len(sweeps[kind]) - 1)
                stats['harness'] += 1
            elif kind == 'status' and eid in refs:
                harness = '+'.join(sorted(
                    {'CARD_DIFF' if where == 'card' else 'ENEMY_DIFF' for where in refs[eid]}))
                stats['harness'] += 1
            else:
                stats['none'] += 1

            tied = table_of.get(eid, set())
            source = None
            if kind == 'monster' and eid in wiki_of:
                source = 'wiki:%s' % wiki_of[eid]
                if not (tied & WIKI_TIE['monster']):
                    source += ' (未钉数字)'
            elif kind == 'action':
                owner = info['owner']
                if owner and owner in wiki_of:
                    # §217：**写明"继承"** —— 动作的页面来自所属怪物，不是这条动作自己核过
                    # （`maw.nom_nom` 就是反例：有 wiki 标签、时间变量却是错的）。
                    source = 'wiki:%s (via %s)' % (wiki_of[owner], owner)
                    if not (tied & WIKI_TIE['action']):
                        # §190 之后的升档表才是“招式对上 wiki”的证据；只有 INV_ACTIONS 时，钉的是**基础值**。
                        source += ' · 仅基础值' if 'INV_ACTIONS' in tied else ' · 未钉数字'
            if source and source.startswith('wiki:'):
                stats['wiki'] += 1
            elif tied:
                source = 'spec:' + '+'.join(sorted(tied))
                stats['spec'] += 1
            else:
                source = '—'

            chunks = []
            if eid in C.INV_UNWIRED:
                chunks.append('unwired：没有敌人记录列出它（`INV_UNWIRED`）')
            if eid in C.INV_NO_ASC:
                chunks.append('无升档：%s' % C.INV_NO_ASC[eid])
            if eid in C.INV_NO_ASC_HP:
                chunks.append('无 AscHP：%s' % C.INV_NO_ASC_HP[eid])
            chunks.extend(gap_dev.get(eid, []))
            deviation = '；'.join(chunks) if chunks else '—'
            if chunks:
                stats['dev'] += 1

            evidence = []
            if eid in sections:
                ordered = sorted(sections[eid], key=section_key)
                evidence.append('§' + '/§'.join(ordered[-2:]))
            if tied:
                evidence.append('+'.join(sorted(tied)))
            if names:
                evidence.append(names[0])
            rows.append({'kind': kind, 'id': eid, 'implemented': implemented,
                         'named': test_named, 'harness': harness, 'source': source,
                         'deviation': deviation, 'evidence': '/'.join(evidence) or '—'})
            stats['rows'] += 1
        summary[kind] = stats

    problems.extend(declaration_problems(entities))

    unused, duplicates = [], []
    covered = set()
    for rel in used_dumps:
        covered.update(dumps.get(rel, []))
    for rel in sorted(set(dumps) - used_dumps):
        if set(dumps.get(rel, [])) & covered:
            duplicates.append(rel)          # 同一页面抓了两份（root 的 `wiki_*.txt` 是早期副本）
        else:
            unused.append(rel)
            problems.append('wiki dump `%s` 没有对应的怪物记录（抓了页面但没有模型）' % rel)

    for probe in TEST_PROBES:
        if not by_test.get(probe):
            problems.append('测试探针 `%s` 扫不到任何具名测试 —— 扫描器坏了，或那个测试被改名了'
                            % probe)

    if entity_meta.get('event_slots') and entity_meta['event_slots'] != entity_meta['event_ids']:
        # 事件池里有 12 个位次、9 个不同 id（三张池跨幕复用同一批事件）—— 两个数都要写出来，
        # 否则 `gap_check.py` 的 "events 12" 与这一页的 9 会像两份互相矛盾的账。
        meta_note = ('事件：池里有 **%d** 个位次、**%d** 个不同 id（`golden_idol` / `ancient_forge` / '
                     '`purification_shrine` 跨幕复用）。' % (entity_meta['event_slots'],
                                                          entity_meta['event_ids']))
    else:
        meta_note = ''
    return rows, summary, problems, {'note': meta_note,
                                     'tests': len(found), 'dumps': len(dumps),
                                     'unused': unused, 'duplicates': duplicates,
                                     'wiki': len(wiki_of)}


# ── 输出 ─────────────────────────────────────────────────────────────────────────────────────────
HEADER = '''# 覆盖矩阵（**生成物，别手改**）

> 生成：`python -X utf8 native/coverage_matrix.py`；校验：`... --check`（闸门 13 就是它）。
> 手改这一页会让闸门红 —— 这是故意的：一张"人维护的覆盖表"活不过下一次内容变更。

回答一个问题：**每一个实体（怪/动作/卡/状态/遭遇/事件/遗物/药水）被验证到哪里了？**
下面这张 %d 行的表靠记性是维护不了的，所以每一列都是派生的（口径见 `native/coverage_matrix.py` 顶部）：

**⚠️ 这七列没有一列声称"行为正确"。** 它们回答的是三个更弱、但可以被机器检查的问题：
*这个实体有没有出处？有没有被任何测试引用？有没有人写下"它和 wiki 不一样"？*

* **Implemented** —— 在内容里且**可达**（`orphan` = 内容长出一条没人引用的行，闸门红）。
  可达性的口径按类别不同（怪=遭遇名单/`spawn`；动作=动作表/AI 规则；状态=程序/触发器/药水原子；
  卡=起始牌组或按稀有度的牌池），逐条写在 `coverage_matrix.py` 的 `build_entities` 里。
* **TestNamed** —— 这个 id 以**字符串字面量**出现在某条内核测试的函数体里（注释里的不算）。
  ⚠️ **它是"被引用"，不是"行为被断言"**：`assert_eq!(id, "spiker")` 与"真打一场 spiker 的战斗"
  在这一列里长得一模一样。§217 之前这一列叫 `RuntimeTested`，那个名字把"引用"读成了"验证"。
  测试名来自递归扫描（`cargo test -- --list` 是它的独立对账：906 条）。
* **HarnessOnly** —— 没有具名引用，但**整表遍历**盖到它了：`ENEMY_DIFF`（跑每一条 `EACT`）、
  `CARD_DIFF`（跑每一张卡）、或内核里"遍历整张表"的测试（`the_potions_are_readable` 之类）。
  这比 `TestNamed` 更弱：它只说明"跑过、程序文本与参考实现一致"。
* **SourceTie** —— `wiki:<dump>`：`native/wiki_asc/`（或 `native/wiki_*.txt`）里有它的 Infobox
  **并且** checker 钉了它的数字；动作那侧的括号 `(via <怪物>)` 是**必须写出来**的 ——
  页面来自所属怪物，不是这条动作自己核过（`maw.nom_nom` 有 wiki 标签、时间变量却错了，就是反例）。
  `spec:<TABLE>`：只对上了 `sts_content_check.py` 里那份**也是人抄的**清单。
  `—`：没有任何独立来源 —— **这一列是本页最大的洞，不粉饰**。
* **DeclaredDeviation** —— 声明过的偏差（`INV_UNWIRED` / `INV_NO_ASC` / `INV_NO_ASC_HP` /
  `docs/sts-wiki-gap.md` §G、§H 两张表，直接解析）。
* **Evidence** —— `§N`（`sts_content_check.py` 引用到的 port-plan 小节）+ 不变量表 + 测试名。

**怎么用**：想找下一件该干的活，按 `SourceTie = —` 或 `TestNamed = —` 排下去就是待办。
**不要**把 `TestNamed` 当成"已经验证过"——要验证语义，得去看那条测试**断言了什么**。
'''


def declaration_problems(entities):
    """`ORPHAN_OK` 每一条都要**仍然成立**：id 还在、而且**仍然**没人引用。

    抽成函数是为了让 `--selftest` 能直接问它（夹具 5）—— 这条检查是"恒真谓词"的反面，
    必须能被证明会红。
    """
    reachable_ids = {row_id for kind in entities for row_id, info in entities[kind].items()
                     if info['reachable']}
    known_ids = {row_id for kind in entities for row_id in entities[kind]}
    problems = []
    for ident in sorted(ORPHAN_OK):
        if ident not in known_ids:
            problems.append('`ORPHAN_OK` 声明的 `%s` 在内容里不存在（声明烂了）' % ident)
        elif ident in reachable_ids:
            problems.append('`%s` 已经被引用了，`ORPHAN_OK` 里那一条声明该删掉' % ident)
    return problems


def render(rows, summary, meta):
    out = [HEADER % len(rows), '']
    out.append('## 汇总（每类实体数 × 证据强度）')
    out.append('')
    out.append('| 类别 | 行数 | TestNamed | HarnessOnly | 两层都没有 | SourceTie:wiki | '
               'SourceTie:spec | 有偏差声明 | orphan |')
    out.append('|---|---|---|---|---|---|---|---|---|')
    total = {key: 0 for key in ('rows', 'named', 'harness', 'none', 'wiki', 'spec', 'dev',
                                'orphan')}
    for kind in KIND_ORDER:
        stats = summary[kind]
        out.append('| %s | %d | %d | %d | %d | %d | %d | %d | %d |' % (
            KIND_LABEL[kind], stats['rows'], stats['named'], stats['harness'], stats['none'],
            stats['wiki'], stats['spec'], stats['dev'], stats['orphan']))
        for key in total:
            total[key] += stats[key]
    out.append('| **合计** | %d | %d | %d | %d | %d | %d | %d | %d |' % (
        total['rows'], total['named'], total['harness'], total['none'], total['wiki'],
        total['spec'], total['dev'], total['orphan']))
    out.append('')
    out.append('扫描到的具名测试：**%d** 条；wiki dump：**%d** 份（其中 %d 只怪有 dump）。'
               % (meta['tests'], meta['dumps'], meta['wiki']))
    if meta['unused']:
        out.append('')
        out.append('无主的 dump（抓了页面但没有对应记录）：%s'
                   % '、'.join('`%s`' % rel for rel in meta['unused']))
    if meta.get('note'):
        out.append('')
        out.append(meta['note'])
    if meta['duplicates']:
        out.append('')
        out.append('同一页面的早期副本（内容同源，矩阵只用 `wiki_asc/` 那一份）：%s'
                   % '、'.join('`%s`' % rel for rel in meta['duplicates']))
    for kind in KIND_ORDER:
        out.append('')
        out.append('## %s（%d）' % (KIND_LABEL[kind], summary[kind]['rows']))
        out.append('')
        out.append('| Entity | Implemented | TestNamed | HarnessOnly | SourceTie | '
                   'DeclaredDeviation | Evidence |')
        out.append('|---|---|---|---|---|---|---|')
        for row in rows:
            if row['kind'] != kind:
                continue
            cells = [row['id'], row['implemented'], row['named'], row['harness'], row['source'],
                     row['deviation'], row['evidence']]
            out.append('| ' + ' | '.join(cell.replace('|', '\\|') for cell in cells) + ' |')
    out.append('')
    return '\n'.join(out)


def invariants(rows, problems):
    if problems:
        for problem in problems:
            print('  !! ' + problem)
        die(1, 'MATRIX FAIL: %d 条不变量红' % len(problems))
    empty = [row for row in rows if row['evidence'] == '—']
    if empty:
        for row in empty[:10]:
            print('  !! %s `%s` 没有任何证据列' % (row['kind'], row['id']))
        die(1, 'MATRIX FAIL: %d 行没有任何证据' % len(empty))


def selftest():
    """五个夹具，逐条打"扫描器能骗自己"的一种方式。任何一条不过 ⇒ 退出码 1。"""
    import tempfile

    failures = []

    def check(name, got, expected):
        if got != expected:
            failures.append('%s: got %r, expected %r' % (name, got, expected))

    root = tempfile.mkdtemp(prefix='coverage-selftest-')
    crate = os.path.join(root, 'rd-core', 'src')
    nested = os.path.join(crate, 'deep')
    os.makedirs(nested)

    io.open(os.path.join(crate, 'top.rs'), 'w', encoding='utf-8', newline=chr(10)).write(
        '#[test]' + chr(10) + 'fn top_level() {' + chr(10) +
        '    let _ = "spiker";' + chr(10) + '}' + chr(10) + chr(10) +
        '#[test]' + chr(10) + '/// doc comment between attribute and fn' + chr(10) +
        'fn behind_a_doc_comment() {' + chr(10) + '}' + chr(10) + chr(10) +
        '/// this one had lost its `#[test]` (a comment mention)' + chr(10) +
        '/// it mentions #[test] twice: #[test]' + chr(10) + 'fn not_a_test() {' + chr(10) + '}' +
        chr(10) + chr(10) +
        '#[test]' + chr(10) + 'fn id_only_in_a_comment() {' + chr(10) +
        '    // "darkling" is only mentioned here, never used' + chr(10) +
        '    assert!(true);' + chr(10) + '}' + chr(10))

    io.open(os.path.join(nested, 'deep.rs'), 'w', encoding='utf-8', newline=chr(10)).write(
        '#[test]' + chr(10) + 'fn nested_one() {' + chr(10) +
        '    let _ = "chosen";' + chr(10) + '}' + chr(10))

    found = tests(kernel_root=root, crates=['rd-core'])
    names = sorted(fn for _crate, fn, _body in found)
    # 夹具 1 / 2 / 3
    check('nested', 'nested_one' in names, True)
    check('doc comment between attribute and fn', 'behind_a_doc_comment' in names, True)
    check('a #[test] inside a comment is not a test', 'not_a_test' in names, False)
    check('exactly four real tests', len(names), 4)

    # 夹具 4：id 只出现在**注释**里 ⇒ 不算 TestNamed（`darkling` 只在注释里；
    # `spiker` / `chosen` 是字面量，必须被抓到）。
    by_test = tests_by_entity(found)
    check('id in a comment is not a reference', 'darkling' in by_test, False)
    check('id in a string literal is a reference', 'spiker' in by_test, True)
    check('id in a string literal in a nested file is a reference', 'chosen' in by_test, True)

    # 夹具 5：自己提到自己不算"可达"；过时的声明必须红
    entities = {
        'monster': {
            'ghost': {'reachable': False, 'why': 'nothing applies it', 'record': {}},
            'real': {'reachable': True, 'why': 'encounter roster', 'record': {}},
        },
        'action': {'declared': {'reachable': True, 'why': 'declared unwired', 'record': {},
                                'owner': None}},
        'card': {}, 'status': {}, 'relic': {}, 'potion': {}, 'encounter': {}, 'event': {},
    }
    saved = dict(ORPHAN_OK)
    try:
        ORPHAN_OK.clear()
        ORPHAN_OK['ghost'] = 'declared, and still an orphan'
        check('declared orphan is fine', declaration_problems(entities), [])
        ORPHAN_OK['real'] = 'no longer an orphan'
        problems = declaration_problems(entities)
        check('stale declaration is red', any('已经' in problem for problem in problems), True)
        ORPHAN_OK.clear()
        ORPHAN_OK['missing'] = 'the id is gone'
        problems = declaration_problems(entities)
        check('declaration for a missing id is red',
              any('不存在' in problem for problem in problems), True)
    finally:
        ORPHAN_OK.clear()
        ORPHAN_OK.update(saved)

    if failures:
        for failure in failures:
            print('  !! selftest ' + failure)
        die(1, 'MATRIX FAIL: 自检 %d 条不通过' % len(failures))
    print('COVERAGE_MATRIX SELFTEST PASS (5 fixtures)')


def main():
    parser = argparse.ArgumentParser(description='generate/verify docs/coverage-matrix.md')
    parser.add_argument('--check', action='store_true', help='只校验，不写盘')
    parser.add_argument('--selftest', action='store_true',
                        help='先跑扫描器自己的对抗性夹具（闸门里也跑）')
    args = parser.parse_args()

    if args.selftest:
        selftest()

    doc = load_content()
    rows, summary, problems, meta = build_rows(doc)
    invariants(rows, problems)
    text = render(rows, summary, meta)
    data = text.encode('utf-8')

    if args.check:
        if not os.path.isfile(OUT):
            die(1, 'MATRIX FAIL: %s 不存在（先跑一次不带 --check 的）' % os.path.relpath(OUT, ROOT))
        current = io.open(OUT, 'rb').read()
        if current != data:
            now = current.decode('utf-8', 'replace').splitlines()
            want = text.splitlines()
            for position, (left, right) in enumerate(zip(now, want)):
                if left != right:
                    print('  第一处不同在第 %d 行：' % (position + 1))
                    print('    盘上: %s' % left[:160])
                    print('    应为: %s' % right[:160])
                    break
            else:
                print('  行数不同：盘上 %d 行，应为 %d 行' % (len(now), len(want)))
            die(1, 'MATRIX FAIL: docs/coverage-matrix.md 陈旧 —— 跑 `python -X utf8 '
                   'native/coverage_matrix.py` 重新生成')
        print('COVERAGE_MATRIX PASS (rows=%d, tests=%d, fresh)' % (len(rows), meta['tests']))
        return

    io.open(OUT, 'w', encoding='utf-8', newline='\n').write(text)
    print('COVERAGE_MATRIX WRITE (rows=%d, tests=%d, wiki=%d, unused dumps=%d) → %s'
          % (len(rows), meta['tests'], meta['wiki'], len(meta['unused']),
             os.path.relpath(OUT, ROOT)))


if __name__ == '__main__':
    main()
