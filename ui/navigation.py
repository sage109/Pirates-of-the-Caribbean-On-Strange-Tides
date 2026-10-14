"""
ui/navigation.py

The single source of truth for NYASHA AI's pages: which sections they are
grouped into, their icons, their translation keys and the one-line
descriptions shown on the Home page cards.

Deliberately pure Python (no Streamlit import) so the structure can be unit
tested: every page needs a stable `label` that is used three ways -- as the
router key in app.py, as the argument to `services.auth.can_access_page`, and
as the identity of the active page in session state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class NavItem:
    label: str                      # canonical page id (router key + permission key)
    emoji: str
    translation_key: str | None     # locales/translations.py key; None = shown in English
    description: str = ""           # one line for the Home page card
    home_card: bool = False         # show as a card on the Home page?


NAV_SECTIONS: tuple[tuple[str, tuple[NavItem, ...]], ...] = (
    ("Overview", (
        NavItem("Home", "\U0001f3e0", "nav_home"),
        NavItem("Dashboard", "\U0001f4ca", "nav_dashboard",
                "Key numbers, revenue by currency and your financial health score at a glance.", True),
    )),
    ("Data", (
        NavItem("Upload Data", "\U0001f4c1", "nav_upload",
                "Load the demo dataset or upload your own CSV or Excel transactions.", True),
    )),
    ("Analysis", (
        NavItem("Financial Analysis", "\U0001f4b0", "nav_financial_analysis",
                "Profitability, liquidity and working-capital figures, with the health score explained.", True),
        NavItem("Anomaly Detection", "\U0001f50d", "nav_anomalies",
                "Spot unusual transactions, with a risk score, the reasons and a recommended action.", True),
        NavItem("Cash Flow Forecast", "\U0001f4b5", "nav_cashflow",
                "See where your cash balance is heading over the next 7 to 90 days.", True),
        NavItem("Customer Analysis", "\U0001f465", "nav_customers",
                "Rank customers by payment risk to see who needs a follow-up.", True),
        NavItem("VAT Analysis", "\U0001f9fe", "nav_vat",
                "Output, input and net VAT at the current rate, with flagged transactions.", True),
    )),
    ("AI & Reports", (
        NavItem("AI Financial Assistant", "✨", "nav_ai_assistant",
                "Ask questions about your numbers in plain language, by text or by voice.", True),
        NavItem("Reports & Export", "\U0001f4e5", None,
                "Download CSV exports and a printable report you can save as PDF.", True),
    )),
    ("Administration", (
        NavItem("Usage History", "\U0001f4da", "nav_usage_history"),
        NavItem("Audit Trail", "\U0001f4dc", "nav_audit_trail"),
        NavItem("User Management", "\U0001f511", "nav_user_management"),
    )),
)

HOME_LABEL = "Home"


def all_items() -> list[NavItem]:
    return [item for _, items in NAV_SECTIONS for item in items]


def all_labels() -> list[str]:
    return [item.label for item in all_items()]


def find_item(label: str) -> NavItem | None:
    return next((item for item in all_items() if item.label == label), None)


def visible_sections(can_access: Callable[[str], bool]) -> list[tuple[str, list[NavItem]]]:
    """The sections (and items within them) the current user is allowed to see.
    A section with no visible items is dropped entirely, so a viewer never sees
    an empty "Administration" heading."""
    sections = []
    for title, items in NAV_SECTIONS:
        allowed = [item for item in items if can_access(item.label)]
        if allowed:
            sections.append((title, allowed))
    return sections


def home_cards(can_access: Callable[[str], bool]) -> list[NavItem]:
    """Pages to advertise as cards on the Home page, in order, for this user."""
    return [item for item in all_items() if item.home_card and can_access(item.label)]
