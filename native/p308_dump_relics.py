"""把几件遗物的内容程序原样打出来（审阅报告 §5/§6 的对账用）。"""
import io
import json

PATH = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'
WANT = ['orange_pellets', 'nilry_codex', 'dead_branch', 'cauldron', 'matryoshka',
        'tiny_house', 'orrery', 'runic_pyramid']


def main():
    doc = json.load(io.open(PATH, encoding='utf-8'))
    print('keys:', list(doc.keys()))
    for table in ('Relics', 'RelicRows', 'RELIC'):
        rows = doc.get(table)
        if isinstance(rows, list) and rows and isinstance(rows[0], dict) and 'Id' in rows[0]:
            ids = [r['Id'] for r in rows]
            print(table, len(ids), 'has orange_pellets:', 'orange_pellets' in ids)
    for r in doc['Relics']:
        if r['Id'] in WANT:
            print('=' * 72)
            print(r['Id'])
            print(json.dumps(r, ensure_ascii=False, indent=1)[:1800])


main()
