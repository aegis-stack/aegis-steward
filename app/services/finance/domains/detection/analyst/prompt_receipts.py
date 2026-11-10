"""The assistant's prompt for filing paper: ``document.file``, and the
receipt that has no charge yet (#424). Split from ``prompt_changes`` at
the module-size budget, the way the plan's entries were."""

RECEIPT_CHANGES = """\
- `document.file` - payload {"paste_id": str, and exactly one of \
"account_id" (accounts()), "party_id" (parties()), "matter_id" \
(matters()), "transaction_id" (its receipt, from transactions()); \
optional "title", "kind", "form_type", "tax_year" - what it IS, when \
you have read it}: file an attached document - or a photo from the \
chat, by the #id its marker shows - where it belongs; a photo becomes a \
document on the shelf. A statement, an amortization schedule, a payoff \
letter is EVIDENCE about one account; an insurer's policy, an invoice, \
a claim statement is theirs and goes with the contact; a letter that \
opened a matter goes on the matter; a receipt goes on the charge it \
explains. Evidence that lives only in a conversation is evidence nobody \
can find again - each page lists what is filed against it. Propose it \
whenever you match a document to its place, in the same turn you read \
it: one card for one document, ONE propose_many for several. The \
paste_id is the one in the marker; pasted TEXT cannot be filed, only a \
document that was attached and read.
- A receipt whose charge is NOT on the ledger yet (the card posts days \
after the purchase): file it anyway, with "kind": "receipt" and NO \
place. It waits on the shelf, and every sync looks for its charge and \
proposes the match when it posts - nobody looks it up by hand later. \
Tell the user it is filed and WAITING for the charge, which is found \
for them when it posts: never that nothing matched, never that you \
will look later, and never leave the receipt only in your reading.
"""
