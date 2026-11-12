"""Export files shared by the import tests: YNAB register bytes (#619),
its header verbatim from real exports, and Excel sheets (#618).
"""

import io

from openpyxl import Workbook

BOM = "\ufeff"
YNAB_HEADER = (
    '"Account","Flag","Date","Payee","Category Group/Category","Category Group",'
    '"Category","Memo","Outflow","Inflow","Cleared"'
)


def ynab(*rows: str) -> bytes:
    return (BOM + "\r\n".join([YNAB_HEADER, *rows]) + "\r\n").encode()


def ynab_row(day: str, payee: str, out: str, into: str) -> str:
    return (
        f'"Joint Checking","","{day}","{payee}","Wants: Coffee","Wants",'
        f'"Coffee","",{out},{into},"Cleared"'
    )


CHASE = [
    "Transaction Date",
    "Post Date",
    "Description",
    "Category",
    "Type",
    "Amount",
    "Memo",
]


def xlsx(*rows: list[object]) -> bytes:
    """A workbook whose first sheet holds ``rows``, and a second that
    must not be read."""
    book = Workbook()
    sheet = book.active
    assert sheet is not None
    for row in rows:
        sheet.append(row)
    book.create_sheet("Notes").append(["not this sheet"])
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()
