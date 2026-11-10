"""§329 负控：三条相位规则各弄坏一次，判据必须在**预期位置**红。

每条都要重编内容镜像（内核读的是 `out/content.sts.rdcf`），跑完一定还原。
"""

import io
import json
import subprocess
import sys

CONTENT = 'tools/contentc/packages/sts/sts.roguedeck.json'


def build():
    subprocess.run(['python', '-X', 'utf8', 'tools/contentc/build.py', '--package', 'sts'],
                   capture_output=True, text=True, encoding='utf-8', errors='replace')


def run(crate, name):
    p = subprocess.run(['cargo', 'test', '-p', crate, '--release', '--', '--test-threads=1', name],
                       cwd='kernel', capture_output=True, text=True, encoding='utf-8',
                       errors='replace')
    return p.stdout + p.stderr


def check():
    p = subprocess.run(['python', '-X', 'utf8', 'native/sts_content_check.py'],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    return p.stdout + p.stderr


def report(label, needle, out, crate='rd-wasm'):
    hit = needle in out
    print('  %-46s %s' % (label, 'RED at %r' % needle if hit else 'NOT CAUGHT'))
    if hit:
        for line in out.splitlines():
            if needle in line:
                print('      ', line.strip()[:130])
                break
    return hit


ok = True
raw = io.open(CONTENT, encoding='utf-8').read()
doc = json.loads(raw)


def save(mutate):
    mutate(doc)
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    build()


try:
    # ① rebirth 的清 Debuff 删掉
    action = [a for a in doc['EnemyActions'] if a['Id'] == 'awakened_one.rebirth'][0]
    action['Program']['Root']['value']['Children'] = [
        c for c in action['Program']['Root']['value']['Children']
        if c.get('kind') != 'node.removeDebuffs']
    save(lambda d: None)
    ok &= report('rebirth 不清 Debuff（行为）', 'must be gone',
                 run('rd-wasm', 'the_two_phase_heals'))
    ok &= report('rebirth 不清 Debuff（清单）', 'action.awakened_one.rebirth',
                 check())

    # ② haste 的清 Debuff 删掉（基础档）
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(raw)
    doc = json.loads(raw)
    action = [a for a in doc['EnemyActions'] if a['Id'] == 'time_eater.haste'][0]
    action['Program']['Root']['value']['Children'] = [
        c for c in action['Program']['Root']['value']['Children']
        if c.get('kind') != 'node.removeDebuffs']
    save(lambda d: None)
    ok &= report('haste 不清 Debuff', 'action.time_eater.haste', check())

    # ③ spawn 回到"无条件 2 只"
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(raw)
    doc = json.loads(raw)
    action = [a for a in doc['EnemyActions'] if a['Id'] == 'the_collector.spawn'][0]
    children = action['Program']['Root']['value']['Children']
    branch_at = next(i for i, c in enumerate(children) if c.get('kind') == 'node.conditional')
    two = {
        'kind': 'node.sequence',
        'value': {'Children': [
            {'kind': 'node.createCombatant',
             'value': {'DefinitionId': 'torch_head', 'TeamId': 'enemy',
                       'Health': {'kind': 'const', 'value': {'Value': 38}}}},
            {'kind': 'node.createCombatant',
             'value': {'DefinitionId': 'torch_head', 'TeamId': 'enemy',
                       'Health': {'kind': 'const', 'value': {'Value': 38}}}},
        ]},
    }
    children[branch_at] = two
    save(lambda d: None)
    ok &= report('spawn 无条件 2 只', 'Torch Heads alive after Spawn',
                 run('rd-wasm', 'the_collector_summons'))

    # ④ 删掉 Collector 的 "0-1 只" 分支（意图侧）
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(raw)
    doc = json.loads(raw)
    for enc in doc['Encounters']:
        for enemy in enc['Enemies']:
            if enemy.get('Id') == 'the_collector':
                enemy['IntentRules'] = [
                    r for r in enemy['IntentRules']
                    if 'the_collector.spawn' not in json.dumps(r) or r['Priority'] != 45]
    for monster in doc['Monsters']:
        if monster['Id'] == 'the_collector':
            monster['IntentRules'] = [
                r for r in monster['IntentRules']
                if 'the_collector.spawn' not in json.dumps(r) or r['Priority'] != 45]
    save(lambda d: None)
    ok &= report('删掉 "0-1 只" 分支', 'wiki says 25%',
                 run('rd-core', 'the_collector'))
finally:
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(raw)
    build()

out = run('rd-core', 'the_collector')
print('  还原后：%s' % ('green' if 'test result: ok' in out else 'STILL RED'))
print('NEGATIVE CONTROL', 'PASS' if ok else 'FAIL')
sys.exit(0 if ok else 1)
