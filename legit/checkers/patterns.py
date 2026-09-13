"""Known scam and pressure tactics, spotted by the extractor and explained with official consumer guidance."""
from __future__ import annotations

from dataclasses import dataclass

from ..models import Evidence, Extraction, Finding, Item

FTC_RENTAL = ("FTC: Rental listing scams", "https://consumer.ftc.gov/articles/rental-listing-scams")
FTC_JOBS = ("FTC: Job scams", "https://consumer.ftc.gov/articles/job-scams")
FTC_CHECKS = ("FTC: How to spot, avoid, and report fake check scams",
              "https://consumer.ftc.gov/articles/how-spot-avoid-and-report-fake-check-scams")
FTC_PHISHING = ("FTC: How to recognize and avoid phishing scams", "https://consumer.ftc.gov/articles/how-recognize-avoid-phishing-scams")
FTC_INVESTMENT = ("FTC: Investment scams", "https://consumer.ftc.gov/articles/investment-scams")
CAFC = ("Canadian Anti-Fraud Centre: Browse frauds", "https://antifraudcentre-centreantifraude.ca/scams-fraudes/index-eng.htm")


@dataclass(frozen=True)
class Pattern:
    status: str
    title: str
    explanation: str


PATTERNS: dict[str, Pattern] = {
    "upfront_payment": Pattern(
        "red_flag", "Pay before you can verify",
        "Asking for a deposit or fee before you've seen the place, signed a lease, or started a job is how most "
        "rental and job scams take money."),
    "unusual_payment_method": Pattern(
        "red_flag", "Hard-to-reverse payment method",
        "Wire transfers, gift cards, crypto, e-transfers, and instant payment apps are nearly impossible to get back "
        "once sent. Consumer-protection agencies in the US and Canada list requests to pay this way as a warning sign."),
    "overpayment_check": Pattern(
        "red_flag", "Deposit a check, send money back",
        "This is the fake check scam: the check bounces days later and you owe the bank everything you sent."),
    "pay_for_job": Pattern(
        "red_flag", "Paying to get or start a job",
        "Legitimate employers don't charge for training, starter kits, or equipment."),
    "guaranteed_returns": Pattern(
        "red_flag", "Guaranteed or unusually high returns",
        "No real investment can guarantee high returns. This promise is the core of investment scams."),
    "cannot_view_in_person": Pattern(
        "caution", "You can't see it in person",
        "Landlords who are abroad or can't show the unit are a common rental scam story."),
    "urgency": Pattern(
        "caution", "Pressure to decide fast",
        "Scammers rush you so you don't have time to check. A real offer survives a day of verification."),
    "asks_personal_info": Pattern(
        "caution", "Asks for sensitive personal info early",
        "Don't share your SIN, SSN, bank login, or card numbers before you've verified who you're dealing with."),
    "too_good_to_be_true": Pattern(
        "caution", "Too good to be true",
        "Far below-market prices or far above-market pay are the bait in many scams."),
    "impersonation": Pattern(
        "caution", "May be impersonating a real organization",
        "Contact the organization through its official website or phone number, not the details in this message."),
    "unsolicited_offer": Pattern(
        "caution", "Offer out of the blue",
        "Job offers from strangers you never applied to are a common start to job scams."),
}


def _references(pattern: str, ext: Extraction) -> list[tuple[str, str]]:
    if ext.location.is_canada:
        return [CAFC]
    if pattern == "overpayment_check":
        return [FTC_CHECKS]
    if pattern == "guaranteed_returns":
        return [FTC_INVESTMENT]
    if pattern in ("asks_personal_info", "impersonation") and ext.context not in ("housing", "job"):
        return [FTC_PHISHING]
    if ext.context == "job" or pattern in ("pay_for_job", "unsolicited_offer"):
        return [FTC_JOBS]
    if ext.context == "housing" or pattern == "cannot_view_in_person":
        return [FTC_RENTAL]
    if ext.context == "finance":
        return [FTC_PHISHING]
    return [FTC_RENTAL, FTC_JOBS]


def check(item: Item, ext: Extraction) -> Finding | None:
    if item.kind != "pattern":
        return None
    key = item.data.get("pattern")
    p = PATTERNS.get(key)
    if p is None:
        return None
    why = (item.data.get("why") or "").strip()
    summary = f"{why} {p.explanation}".strip() if why else p.explanation
    evidence = [Evidence(title, "Official consumer-protection guidance describing this warning sign", "guidance", url)
                for title, url in _references(key, ext)]
    data = {"type": "pattern", "pattern": key, "explanation": p.explanation, "why": why}
    return Finding(item, p.status, p.title, summary, "patterns", evidence, data=data)
