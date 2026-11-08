"""审阅报告 §7 的对账：我们 `ancient_writing` / `old_shrine` 到底是 wiki 的哪条事件。"""
import io
import json

PATH = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'


def main():
    doc = json.load(io.open(PATH, encoding='utf-8'))
    rows = doc['EventNodes']
    for e in rows:
        if e['Id'].split('.')[0] in ('ancient_writing', 'old_shrine', 'purification_shrine',
                                     'ancient_forge', 'wandering_merchant', 'the_mausoleum'):
            print('-' * 68)
            print(e['Id'], '|', e.get('TextKey', '')[:200])
            for option in e.get('Options') or []:
                print('   ', option.get('Label'), '|', json.dumps(
                    {k: v for k, v in option.items() if k != 'Label'},
                    ensure_ascii=False)[:220])


main()
