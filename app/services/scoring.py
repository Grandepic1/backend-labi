from decimal import Decimal, ROUND_HALF_UP

IU_MET = "met"
IU_NOT_MET = "not_met"
IU_UNCLEAR = "unclear"
IU_STATUSES = (IU_MET, IU_NOT_MET, IU_UNCLEAR)
FINAL_IU_STATUSES = (IU_MET, IU_NOT_MET)

SESSION_CREATED = "created"
SESSION_RECORDING_UPLOADED = "recording_uploaded"
SESSION_ASSESSMENT_IN_PROGRESS = "assessment_in_progress"
SESSION_COMPLETED = "completed"
SESSION_CANCELLED = "cancelled"

TASK_IMMEDIATE_RECALL = "immediate_recall"


def iu_recall_percent(met_count: int, total_iu: int) -> Decimal | None:
    if total_iu <= 0:
        return None
    return (Decimal(met_count) / Decimal(total_iu) * Decimal(100)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


def summarize_statuses(statuses: list[str]) -> tuple[int, int, int]:
    met = sum(1 for s in statuses if s == IU_MET)
    not_met = sum(1 for s in statuses if s == IU_NOT_MET)
    unclear = sum(1 for s in statuses if s == IU_UNCLEAR)
    return met, not_met, unclear
