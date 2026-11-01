"""Renumber the acceptance banners 1..20 and give the last four gates one each.

The labels used to read `[1/9]`..`[9/9]` then `[+1]`..`[+7]`, and the last four gates
(`web-browser`, `web-soak`, `web-slice`, `web-pixel`) had no banner at all -- they only had the
comment block above them. So the run printed "9" while producing twenty rows, and four of them
arrived without a heading. Both are the same class of lie as a stale comment: the number is a copy
of a fact that lives somewhere else (the list of gates).
"""
import io
import re

PATH = "tools/acceptance.ps1"

# (old label, new label). The old ones are unique strings in the file.
LABELS = [
    ("[1/9] 单元测试", "[1/20] 单元测试"),
    ("[2/20] 语料回环份数", "[2/20] 语料回环份数"),
    ("[+1] 内容镜像 byte-identity", "[10/20] 内容镜像 byte-identity"),
    ("[+2] 内容镜像结构不变量", "[11/20] 内容镜像结构不变量"),
    ("[+3] StS 内容包自洽", "[12/20] StS 内容包自洽"),
    ("[+4] 重编网页那一份 .wasm", "[13/20] 重编网页那一份 .wasm"),
    ("[+5] 页面 + 产物", "[14/20] 页面 + 产物"),
    ("[+6] 界面渲染的", "[15/20] 界面渲染的"),
    ("[+7] 地图页", "[16/20] 地图页"),
]

# The four gates that had no banner. Keyed by the line that must follow the new banner.
INSERT_BEFORE = [
    ("$results += Invoke-Gate -Name 'web-browser'",
     'Write-Output "`n[17/20] 真浏览器：点下去，断言渲染出来的文字"\n'),
    ("$results += Invoke-Gate -Name 'web-soak'",
     'Write-Output "`n[18/20] 随机 soak：每个启用中的控件点一下都必须有反应"\n'),
    ("$results += Invoke-Gate -Name 'web-slice'",
     'Write-Output "`n[19/20] 一幕垂直切片：自己算路线走遍每种节点"\n'),
    ("$results += Invoke-Gate -Name 'web-pixel'",
     'Write-Output "`n[20/20] 像素：画出来是什么样（不比基线，只断性质）"\n'),
]


def main():
    text = io.open(PATH, encoding="utf-8").read()
    for old, new in LABELS:
        assert text.count(old) == 1, (old, text.count(old))
        text = text.replace(old, new)

    # `[+2]` also said "5 张定长表"; the format has seven (§167).
    text = text.replace("段目录 + 5 张定长表的 count×stride", "段目录 + 7 张定长表的 count×stride")

    for anchor, banner in INSERT_BEFORE:
        assert text.count(anchor) == 1, (anchor, text.count(anchor))
        text = text.replace(anchor, banner + anchor)

    # Sanity: the labels must now be exactly 1..20, each once.
    seen = re.findall(r"\[(\d+)/20\]", text)
    numbers = sorted(int(n) for n in seen)
    assert numbers == list(range(1, 21)), numbers
    io.open(PATH, "w", encoding="utf-8", newline="").write(text)
    print("20 banners, numbered 1..20, each exactly once")


if __name__ == "__main__":
    main()
