# AI usage

Keep all three headings exactly as they are. If this file is missing or any heading is
missing, the grader stops and gives 0 ("AI_USAGE.md missing or incomplete"). The content
is not scored, but your Track Mentor reads it and the W8 defence can ask about it.

## Tools

<!-- Which tools you used (ChatGPT, Copilot, Claude, Cursor, none...) and for which parts. -->
tools -> claude
some explanations and one part it writes.
the part is:
  #1) debit the sender (only if the balance is enough)
    debit = session.execute(
        update(Account)
        .where(Account.id == from_id, Account.balance_piastres >= amount)
        .values(balance_piastres=Account.balance_piastres - amount)
    )
    if debit.rowcount == 0:
        raise CustomException(title="Insufficient funds or account not found", status=422)

    #2) credit the receiver
    credit = session.execute(
        update(Account)
        .where(Account.id == to_id)
        .values(balance_piastres=Account.balance_piastres + amount)
    )
    if credit.rowcount == 0:
        raise CustomException(title="Receiver not found", status=404)

    #3) record the transfer
    transfer = Transfer(
        id=f"trf_{uuid.uuid4().hex}",
        from_account_id=from_id,
        to_account_id=to_id,
        amount_piastres=amount,
        memo=memo,
        status="completed",
    )
    session.add(transfer)
## What AI got wrong

<!-- At least one thing an assistant got wrong that you changed, and how you noticed
(a test failed, the docs said otherwise, you ran it). -->
this line -> raise CustomException(title="Insufficient funds or account not found", status=422)
but you must check first that if account not found by source to send status=404
as docs said -> 404 source account not owned by caller (or not existing)
## In my own words

<!-- Answer without AI, one or two sentences each. -->

1. Why does a transfer to someone else's account return 404 and not 403?
so sending tranfer from from_account_id is not yours or from_account_id is not found both give 404
No Extra info whether they are real or not.

2. What would happen to a customer if your idempotency record were written in a separate transaction after the transfer?
may the transfer get recorded and server crashes before idempotency get recorded, and when the same request replayed again it will execute the request and make the tranfer again and so on (1 transfer request -> happens more than 1).
