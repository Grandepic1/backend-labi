from decimal import Decimal

from app.services.scoring import (
    IU_MET,
    IU_NOT_MET,
    IU_UNCLEAR,
    iu_recall_percent,
    summarize_statuses,
)


def test_iu_recall_percent() -> None:
    assert iu_recall_percent(0, 0) is None
    assert iu_recall_percent(0, 10) == Decimal("0.00")
    assert iu_recall_percent(5, 10) == Decimal("50.00")
    assert iu_recall_percent(10, 10) == Decimal("100.00")
    # Round half up check: 1/3 = 33.33%
    assert iu_recall_percent(1, 3) == Decimal("33.33")
    # 2/3 = 66.67%
    assert iu_recall_percent(2, 3) == Decimal("66.67")


def test_summarize_statuses() -> None:
    statuses = [IU_MET, IU_MET, IU_NOT_MET, IU_UNCLEAR, "unknown"]
    met, not_met, unclear = summarize_statuses(statuses)
    assert met == 2
    assert not_met == 1
    assert unclear == 1
