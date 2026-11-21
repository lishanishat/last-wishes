from chat import render as r


def test_money_unknown_is_never_zero():
    assert r.money(None) == "Unresolved"
    assert r.money(0) == "$0"
    assert r.money(2750) == "$2,750"
    assert r.money(1450.5) == "$1,450.50"


def test_range_text_open_ended():
    assert "no ceiling" in r.range_text(995, None)
    assert r.range_text(100, 100) == "$100"
    assert r.range_text(100, 200) == "$100 to $200"
    assert r.range_text(None, None) == "Unresolved"


def test_totals_line():
    t = r.totals_line(2100, 2100, None, ["Cremation"])
    assert t["known"] == "$2,100" and t["unresolved"] == "Cremation" and t["has_unresolved"]
    assert r.totals_line(1, 1, 1, [])["unresolved"] == "None"


def test_flag_columns_avoids_accusatory_words():
    c = r.flag_columns({"quote_id": "A-v1", "excerpt": "Casket required", "reference": "Illegal under rule",
                        "message": "This is a violation"})
    blob = " ".join(str(v) for v in c.values()).lower()
    assert "illegal" not in blob and "violation" not in blob
    assert c["provider"] == "Casket required"


def test_not_needed_and_savings():
    plan = {"not_needed": [{"name": "Embalming", "savings": 650}, {"name": "Limo", "savings": 300}]}
    assert r.total_savings(plan) == 950
    assert r.not_needed_rows(plan)[0] == {"Item": "Embalming", "Savings if left out": "$650"}
    assert r.total_savings({}) is None


def test_chip_and_approval_actions():
    item = {"label": "Go", "action": {"do": "x", "provider": "A"}}
    a = r.chip_action(item)
    assert a == {"do": "x", "provider": "A"} and a is not item["action"]
    assert r.chip_action({"action": "plain"}) == {"do": "plain"}
    assert r.approve_action({"approval_id": 7}) == {"do": "approve", "approval_id": 7}
    assert r.rebuild_action({"approval_id": 7})["do"] == "rebuild"
    assert r.card_is_stale({"valid": False}) and not r.card_is_stale({"valid": True})


def test_quote_rows_and_table_html_escapes():
    rows = r.quote_rows([{"name": "<b>x</b>", "category": "cash_advance", "price_type": "starting_at",
                          "amount_text": "from $5"}])
    assert rows[0]["Category"] == "cash advance"
    assert "<b>" not in r.table_html(rows)


def test_diff_rows_and_user_event():
    d = r.diff_rows({"rows": [{"name": "C", "v1": "Unresolved", "v2": "$9", "status": "resolved"}]})
    assert d[0]["After"] == "$9"
    assert r.is_user_event({"type": "user"}) and not r.is_user_event({"type": "text"})


def test_split_rows():
    rows = [{"Item": str(i)} for i in range(5)]
    assert r.split_rows(rows) == (rows, [])
    head, rest = r.split_rows([{"Item": str(i)} for i in range(30)])
    assert len(head) == 8 and len(rest) == 22
