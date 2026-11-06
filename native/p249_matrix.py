"""§249.3 矩阵探针：逐个"可疑节目"单独构建，让 `report.md` 点名回退字段。

为什么要逐个：一个字段一旦回退成 `F_JSON`，**同一 opcode 的所有实例都读不出来** ——
所以四张牌一起加时，真实的"罪犯"只有一个，其余三张是被它拖红的（§249.1 的
`omega` 单独跑是好的，这就是证据）。

每个变体：改 JSON → 构建 → 从 `report.md` 摘 "Fields that fell back to F_JSON" → 还原 JSON。
"""
import io
import json
import re
import subprocess

ROOT = 'D:/Vibe/sts-tui/'
CONTENT = ROOT + 'tools/contentc/packages/sts/sts.roguedeck.json'
REPORT = ROOT + 'tools/contentc/packages/sts/out/report.md'

SELF = {"kind": "sel.source",
        "value": {"Cardinality": "ZeroOrOne", "RequiredContextCapabilities": "Source"}}
ALL_ENEMIES = {"kind": "sel.allEnemies",
               "value": {"Cardinality": "Any", "RequiredContextCapabilities": "Source"}}
TARGET = {"kind": "sel.eventTarget",
          "value": {"Cardinality": "ZeroOrOne", "RequiredContextCapabilities": "EventTarget"}}


def node(kind, **value):
    value.setdefault("ResultKey", None)
    return {"kind": kind, "value": value}


def const(n):
    return {"kind": "const", "value": {"Value": n}}


def seq(*children):
    return node("node.sequence", Children=list(children))


def stacks_of(status_id):
    return {"kind": "combatantStatusStacks",
            "value": {"Selector": SELF, "StatusId": {"value": status_id}}}


def damage_all(amount):
    return node("node.dealDamage", TargetSelector=ALL_ENEMIES, Amount=amount,
                IgnoresBlock=False, Element=None)


def compare(left, right, op):
    return {"kind": "compare", "value": {"Left": left, "Right": right, "Op": op}}


def conditional(condition, then, otherwise=None):
    return node("node.conditional", Condition=condition, Then=then, Else=otherwise)


def fact(key):
    return {"kind": "event.bool", "value": {"FieldKey": key}}


VARIANTS = {}

# A. Panache 原版：remainder 判断"每 5 张"
VARIANTS['A_panache_remainder'] = conditional(
    both_ := {"kind": "and", "value": {
        "Left": compare({"kind": "remainder",
                         "value": {"Left": {"kind": "cardsPlayedThisTurn", "value": {}},
                                   "Right": const(5)}}, const(0), "Equal"),
        "Right": compare({"kind": "cardsPlayedThisTurn", "value": {}}, const(0), "Greater")}},
    damage_all(stacks_of('standard.omega')))

# B. Panache 计数器版：combatantCounter + setCombatantCounter
VARIANTS['B_panache_counter'] = seq(
    node("node.setCombatantCounter", TargetSelector=SELF,
         CounterId={"value": "panache_count"}, Amount=const(1), Relative=True),
    conditional(compare({"kind": "combatantCounter",
                         "value": {"Selector": SELF, "CounterId": "panache_count"}},
                        const(5), "GreaterOrEqual"),
                seq(damage_all(stacks_of('standard.omega')),
                    node("node.setCombatantCounter", TargetSelector=SELF,
                         CounterId={"value": "panache_count"}, Amount=const(0),
                         Relative=False))))

# C. Sadistic Nature：两个事实位 + 打 eventTarget
VARIANTS['C_sadistic'] = conditional(
    {"kind": "and", "value": {"Left": fact('status.isDebuff'),
                              "Right": fact('status.appliedToOther')}},
    node("node.dealDamage", TargetSelector=TARGET, Amount=stacks_of('standard.omega'),
         IgnoresBlock=False, Element=None))

# D. The Bomb：sequence + 自减层数
VARIANTS['D_bomb'] = seq(
    conditional(compare(stacks_of('standard.omega'), const(1), 'LessOrEqual'),
                damage_all(stacks_of('standard.omega'))),
    node("node.modifyStatusStacks", TargetSelector=SELF,
         StatusDefinitionId={"value": "standard.omega"}, Delta=const(-1)))


def fallbacks():
    text = io.open(REPORT, encoding='utf-8').read()
    if 'No field needed the `F_JSON` escape hatch' in text:
        return []
    match = re.search(r'### Fields that fell back to .F_JSON.\n\n(.*?)\n\n', text, re.S)
    if not match:
        return ['(fallback section unreadable)']
    return [line.strip() for line in match.group(1).splitlines() if line.strip()]


def build():
    run = subprocess.run(['python', '-X', 'utf8', 'tools/contentc/build.py', '--package', 'sts'],
                         cwd=ROOT, capture_output=True, text=True)
    ok = 'CONTENTC_BUILD OK' in run.stdout
    return ok, run.stdout.strip().splitlines()[-1:] if not ok else []


ALL = {
    'standard.omega': [],
    'standard.probe_a': VARIANTS['A_panache_remainder'],
    'standard.probe_b': VARIANTS['B_panache_counter'],
    'standard.probe_c': VARIANTS['C_sadistic'],
    'standard.probe_d': VARIANTS['D_bomb'],
}


def main():
    original = io.open(CONTENT, encoding='utf-8').read()
    base = json.loads(original)
    for name in sorted(VARIANTS):
        data = json.loads(original)
        data['Statuses'].append({
            'Id': 'standard.probe', 'PackageId': 'sts', 'NameKey': 'Probe',
            'DescriptionKey': 'probe', 'Polarity': 'Buff', 'UsesStacks': True,
            'UsesDuration': False, 'UsesCharges': False,
            'StackingBehavior': 'MergeWithExistingInstance', 'Tags': ['buff'],
            'PassiveModifiers': [],
            'Triggers': [{'Event': 'TurnEnded',
                          'Program': {'Id': {'Value': '(unnamed)'},
                                      'Root': VARIANTS[name],
                                      'MaxNodeDepth': 64, 'MaxProgramSteps': 1024}}]})
        data['Statuses'].append({
            'Id': 'standard.omega', 'PackageId': 'sts', 'NameKey': 'Omega',
            'DescriptionKey': 'probe twin', 'Polarity': 'Buff', 'UsesStacks': True,
            'UsesDuration': False, 'UsesCharges': False,
            'StackingBehavior': 'MergeWithExistingInstance', 'Tags': ['buff'],
            'PassiveModifiers': [], 'Triggers': []})
        io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
            json.dumps(data, ensure_ascii=False, indent=2) + '\n')
        ok, tail = build()
        found = fallbacks() if ok else tail
        print('%-22s %s' % (name, 'OK' if ok else 'BUILD FAIL'))
        for line in found or ['(no fallback)']:
            print('    %s' % line)
    # 组合：五个节目同时上（这才是当初失败的那次构建的形状）。
    data = json.loads(original)
    for status_id, root in sorted(ALL.items()):
        triggers = [] if not root else [{'Event': 'TurnEnded',
                                         'Program': {'Id': {'Value': '(unnamed)'},
                                                     'Root': root,
                                                     'MaxNodeDepth': 64,
                                                     'MaxProgramSteps': 1024}}]
        data['Statuses'].append({
            'Id': status_id, 'PackageId': 'sts', 'NameKey': 'Probe',
            'DescriptionKey': 'probe', 'Polarity': 'Buff', 'UsesStacks': True,
            'UsesDuration': False, 'UsesCharges': False,
            'StackingBehavior': 'MergeWithExistingInstance', 'Tags': ['buff'],
            'PassiveModifiers': [], 'Triggers': triggers})
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    ok, tail = build()
    print('%-22s %s' % ('E_all_five', 'OK' if ok else 'BUILD FAIL'))
    for line in (fallbacks() if ok else tail) or ['(no fallback)']:
        print('    %s' % line)

    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(original)
    print('restored (statuses %d, cards %d)' % (len(base['Statuses']), len(base['Cards'])))


main()
