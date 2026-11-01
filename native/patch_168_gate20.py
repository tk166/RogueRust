"""§168: register the pixel gate as gate 20, and note the caveat it replaces.

Gate 17's comment says "不做截图像素比对（那个在不同字体/缩放下太脆）" -- that was the right call for a
gate whose job is *behaviour*, and it is why the pixel gate is a separate gate with its own promises:
a fixed viewport, no baseline image, and properties that fail for a class of visual bug and nothing
else.
"""
import io

PATH = "tools/acceptance.ps1"

OLD = """Write-Output "`n" + ("-" * 78)
Write-Output ("{0,-18}{1,6}  {2,-22}{3}" -f '闸门', '退出', '证据', '备注')"""

NEW = """# 门 20：**像素**（§168）。前面 19 道都在问"状态对不对 / 文字对不对"，没有一道问"**画出来是什么样**"——
# 一个把文字画成背景色的主题、一张 DOM 里有而屏幕上没有的牌、一行溢出面板的卡，都能让 19 道全绿。
# 这一道**不比基线图**（字体/缩放一变就红，而且人只会重录它），只断言可度量的性质：
# 棋盘上确实有墨、墨与底色**看得清**、每张牌自己的矩形在"藏起卡牌"前后**变过**、卡牌没有画到条带外面、
# 两次同状态截图**逐像素相同**。最后一段是**故障注入**：把 `--ink` 设成底色、藏掉一张牌、压扁手牌条带、
# 藏掉棋盘，逐个确认**同一批探测器会红** —— 否则"像素门通过"什么也没证明。
$results += Invoke-Gate -Name 'web-pixel' -Exe 'C:\\Program Files\\nodejs\\node.exe' `
  -ArgLine (Join-Path $ROOT 'web\\pixel_test.mjs') -Workdir $ROOT `
  -MustMatch 'PIXEL_TEST PASS' -TimeoutSec 600

Write-Output "`n" + ("-" * 78)
Write-Output ("{0,-18}{1,6}  {2,-22}{3}" -f '闸门', '退出', '证据', '备注')"""


def main():
    text = io.open(PATH, encoding="utf-8").read()
    assert text.count(OLD) == 1, text.count(OLD)
    io.open(PATH, "w", encoding="utf-8", newline="").write(text.replace(OLD, NEW))
    print("gate 20 registered")


if __name__ == "__main__":
    main()
