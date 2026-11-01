"""Put the failure dump into the assertion message (the first `- ` line is all the摘录 shows)."""
import io

PATH = "web/browser_test.mjs"

OLD = """  `the modal's close button was covered by ${JSON.stringify(report.pointer.closeCover)} ` +
  `at ${JSON.stringify(report.pointer.closeBox)}`);"""

NEW = """  `the modal's close button was covered by ${JSON.stringify(report.pointer.closeCover)} ` +
  `at ${JSON.stringify(report.pointer.closeBox)} · layout ` +
  `${JSON.stringify(report.pointer.closeLayout || null)}`);"""


def main():
    text = io.open(PATH, encoding="utf-8").read()
    assert text.count(OLD) == 1, text.count(OLD)
    io.open(PATH, "w", encoding="utf-8", newline="").write(text.replace(OLD, NEW))
    print("layout goes into the message")


if __name__ == "__main__":
    main()
