"""
app.py -- Sarudzo AI

Main Streamlit entry point. Wires the UI to the deterministic, already
unit-tested modules in analytics/, rules/, services/, and database/, plus
the newer agents/ (orchestration), locales/ (multi-language), reports/
(export), and ui/ (watermark, gauge) modules.

NOTE: This file requires `streamlit` (not installed in the build sandbox
used to develop this project -- no network access there). It has been
written carefully against the tested module APIs but has NOT been run
live. Before your demo:
    pip install -r requirements.txt
    streamlit run app.py
and fix anything that surfaces -- treat this as a strong draft, not a
guaranteed-working final file. Every non-Streamlit piece it calls into
(orchestrator, locales, auth, reports, ui components) IS unit-tested.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd
import streamlit as st

from agents.orchestrator import run_full_analysis
from analytics.anomaly_detection import detect_anomalies
from analytics.currency_normalisation import normalise_to_reporting_currency
from analytics.customer_analysis import analyse_customer_risk
from analytics.financial_health import calculate_financial_health
from analytics.financial_metrics import (
    liquidity_summary, profitability_summary, revenue_by_currency, working_capital_summary,
)
from analytics.forecasting import forecast_all_horizons
from analytics.validation import validate_transactions
from database.database import init_db, log_audit, log_usage
from database.seed import seed_if_needed
from locales.translations import available_languages, t
from reports.report_generator import (
    build_anomalies_csv, build_customer_risk_csv, build_html_report,
    build_transactions_csv, export_pdf_if_available,
)
from rules.vat_rules import DISCLAIMER, VAT_RATES, calculate_vat_summary, vat_by_category
from services.auth import (
    ROLES, User, admin_count, attempt_login, attempt_setup, can_access_page, configured_setup_key,
    create_user, delete_user, ensure_users_table, get_user, list_users, log_session_expired,
    log_sign_out, password_strength, session_expired, session_timeout_seconds, set_role,
    update_password, user_count, validate_new_password, verify_user,
)
from services.exchange_rates import get_live_rate, get_supported_currencies
from services.llm_service import (
    answer_financial_question, answer_financial_question_from_audio, explain_financial_result,
)
from ui.components import (
    app_theme_css, demo_mode_banner_html, feature_card_html, health_score_gauge_svg, hero_html,
    nav_section_label_html, nyasha_watermark_html, step_card_html,
)
from ui.charts import CHART_FRAME_HEIGHT, ForecastPoint, chart_page_html, forecast_chart_svg, forecast_insight
from ui.login import (
    brand_panel_html, form_heading_html, help_text_html, login_css, login_error_message, notice_html,
    setup_error_message, strength_level_text, strength_meter_html,
)
from ui.navigation import HOME_LABEL, find_item, home_cards, visible_sections

st.set_page_config(page_title="Sarudzo AI", page_icon="\U0001f4a1", layout="wide")

DEMO_BUSINESS_NAME = "Moyo Retail & Services"

# --------------------------------------------------------------------------- Startup
init_db()
seed_if_needed()  # rebuilds demo data if the DB is empty (Section 0A.1 -- ephemeral filesystem)
ensure_users_table()

for key, default in {
    "reporting_currency": "USD",
    "language": "English",
    "transactions_df": None,
    "demo_mode": False,
    "current_user": None,
    "current_page": HOME_LABEL,
    "last_active": None,
    "login_notice": None,
}.items():
    if key not in st.session_state:
        st.session_state[key] = default


# --------------------------------------------------------------------------- Auth gate
def end_session(reason: str | None = None) -> None:
    """Sign the current user out and wipe what they had loaded. Their uploaded
    transactions must not be visible to whoever signs in next in this browser
    tab. `reason` ("signed_out" / "session_expired") picks the notice shown
    on the login page."""
    st.session_state.current_user = None
    st.session_state.current_page = HOME_LABEL
    st.session_state.transactions_df = None
    st.session_state.demo_mode = False
    st.session_state.last_active = None
    st.session_state.pop("rates_used", None)
    if reason == "session_expired":
        st.session_state.login_notice = {
            "kind": "warning", "key": "login_session_expired",
            "params": {"minutes": max(1, session_timeout_seconds() // 60)},
        }
    elif reason == "signed_out":
        st.session_state.login_notice = {"kind": "info", "key": "login_signed_out", "params": {}}


def _auth_page_frame() -> tuple[str, "st.delta_generator.DeltaGenerator"]:
    """Shared layout for the sign-in and first-run pages: language picker on
    top, branded panel on the left, the form column on the right. Returns the
    (already updated) language and the right-hand column to draw the form in."""
    st.markdown(login_css(), unsafe_allow_html=True)
    languages = available_languages()
    _, picker_col = st.columns([3, 2])
    with picker_col:
        st.session_state.language = st.radio(
            t("language_label", st.session_state.language), languages,
            index=languages.index(st.session_state.language),
            horizontal=True, label_visibility="collapsed", key="auth_language_picker",
        )
    lang = st.session_state.language
    left, right = st.columns([5, 4], gap="large")
    with left:
        st.markdown(
            brand_panel_html(
                "Sarudzo AI", t("app_tagline", lang),
                [t("login_trust_1", lang), t("login_trust_2", lang), t("login_trust_3", lang)],
                t("login_footer", lang),
            ),
            unsafe_allow_html=True,
        )
    return lang, right


def render_first_run_setup() -> None:
    """Shown only while no accounts exist. Streamlit Community Cloud's disk is
    ephemeral, so this page can reappear after a restart -- which is why a
    setup key (NYASHA_SETUP_KEY in the app's Secrets) is checked when one is
    configured: otherwise whoever opened the link first would become admin."""
    lang, right = _auth_page_frame()
    key_required = configured_setup_key() is not None
    with right:
        st.markdown(form_heading_html(t("setup_title", lang), t("setup_subtitle", lang)), unsafe_allow_html=True)
        if not key_required:
            st.markdown(notice_html("warning", t("setup_no_key_warning", lang)), unsafe_allow_html=True)
        # Plain widgets rather than st.form so the strength meter can update as
        # the password is typed.
        with st.container(border=True):
            username = st.text_input(t("setup_username", lang), help=t("setup_username_help", lang), key="setup_username")
            password = st.text_input(t("login_password", lang), type="password", key="setup_password")
            score = password_strength(password)
            st.markdown(
                strength_meter_html(score, t("pw_strength_label", lang), strength_level_text(score, lang)),
                unsafe_allow_html=True,
            )
            confirm = st.text_input(t("setup_confirm", lang), type="password", key="setup_confirm")
            setup_key = ""
            if key_required:
                setup_key = st.text_input(t("setup_key", lang), type="password", help=t("setup_key_help", lang), key="setup_key")
            submitted = st.button(t("setup_button", lang), type="primary", use_container_width=True, key="setup_submit")
        if submitted:
            result = attempt_setup(username, password, confirm, setup_key)
            if result.ok:
                st.session_state.login_notice = {"kind": "success", "key": "setup_success", "params": {}}
                st.rerun()
            st.markdown(
                notice_html("error", setup_error_message(result.error or "missing", lang, result.retry_after)),
                unsafe_allow_html=True,
            )
            if result.error == "setup_closed":
                st.rerun()


def render_login() -> None:
    lang, right = _auth_page_frame()
    with right:
        st.markdown(form_heading_html(t("login_title", lang), t("login_subtitle", lang)), unsafe_allow_html=True)
        notice = st.session_state.login_notice
        if notice:
            text = t(notice["key"], lang).format(**notice.get("params", {}))
            st.markdown(notice_html(notice["kind"], text), unsafe_allow_html=True)
        with st.form("login_form"):
            username = st.text_input(t("login_username", lang))
            password = st.text_input(t("login_password", lang), type="password")
            submitted = st.form_submit_button(t("login_button", lang), type="primary")
        if submitted:
            st.session_state.login_notice = None
            result = attempt_login(username, password)
            if result.status == "ok":
                st.session_state.current_user = result.user
                st.session_state.last_active = time.time()
                st.rerun()
            st.markdown(
                notice_html("error", login_error_message(result.status, lang, result.retry_after, result.attempts_left)),
                unsafe_allow_html=True,
            )
        st.markdown(help_text_html(t("login_help", lang)), unsafe_allow_html=True)


def require_login() -> User:
    current = st.session_state.current_user
    if current is not None:
        if session_expired(st.session_state.last_active, time.time(), session_timeout_seconds()):
            log_session_expired(current)
            end_session("session_expired")
        else:
            # Re-check the account on every run so an admin's changes take effect
            # immediately: a deleted user is logged out, a changed role applies now.
            fresh = get_user(current.username)
            if fresh is not None:
                st.session_state.current_user = fresh
                st.session_state.last_active = time.time()
                return fresh
            end_session()
            st.session_state.login_notice = {"kind": "warning", "key": "login_account_inactive", "params": {}}
    if user_count() == 0:
        render_first_run_setup()
    else:
        render_login()
    st.stop()  # never reached after st.stop(), but keeps type-checkers happy


# --------------------------------------------------------------------------- Sidebar / navigation
# The page list (sections, icons, translation keys) lives in ui/navigation.py.
def go_to(label: str) -> None:
    """Switch the active page and redraw. Used by the sidebar buttons, the Home
    page cards and the empty-state shortcuts."""
    st.session_state.current_page = label
    st.rerun()


def sidebar(user: User) -> str:
    current = st.session_state.current_page
    if current != HOME_LABEL and not can_access_page(user, current):
        # e.g. an admin changed this user's role since their last click
        current = st.session_state.current_page = HOME_LABEL

    with st.sidebar:
        st.markdown("## \U0001f4a1 Sarudzo AI")
        st.caption(t("app_tagline", st.session_state.language))
        st.caption(f"Logged in as **{user.username}** ({user.role})")
        # Layout order is fixed here (navigation on top, settings below); the
        # code below fills the settings box FIRST so that a language change is
        # already applied when the navigation labels are drawn.
        nav_box = st.container()
        st.divider()
        settings_box = st.container()
        st.divider()
        if st.button("Log out"):
            log_sign_out(user)
            end_session("signed_out")
            st.rerun()

    with settings_box:
        st.markdown(nav_section_label_html("Settings"), unsafe_allow_html=True)
        st.session_state.language = st.selectbox(
            f"\U0001f310 {t('language_label', st.session_state.language)}", available_languages(),
            index=available_languages().index(st.session_state.language),
        )
        st.session_state.reporting_currency = st.selectbox(
            t("reporting_currency_label", st.session_state.language), get_supported_currencies(),
            index=get_supported_currencies().index(st.session_state.reporting_currency),
        )
        st.session_state.demo_mode = st.toggle(
            f"\U0001f3ac {t('demo_mode', st.session_state.language)}", value=st.session_state.demo_mode,
        )
        if st.session_state.demo_mode and st.session_state.transactions_df is None:
            st.session_state.transactions_df = pd.read_csv("data/sample_transactions.csv")

    with nav_box:
        lang = st.session_state.language
        for title, items in visible_sections(lambda label: can_access_page(user, label)):
            st.markdown(nav_section_label_html(title), unsafe_allow_html=True)
            for item in items:
                display = t(item.translation_key, lang) if item.translation_key else item.label
                if st.button(
                    f"{item.emoji} {display}", key=f"nav_{item.label}",
                    type="primary" if item.label == current else "secondary",
                ):
                    go_to(item.label)

    return current


# --------------------------------------------------------------------------- Data loading helpers
def load_active_dataframe() -> pd.DataFrame | None:
    """Returns the currently active, VALIDATED + currency-normalised
    transactions, and stashes the FX rates actually used for this render
    in session_state so the UI can show live/cached/manual badges."""
    if st.session_state.transactions_df is None:
        return None
    result = validate_transactions(st.session_state.transactions_df)
    norm = normalise_to_reporting_currency(result.valid_rows, st.session_state.reporting_currency)
    st.session_state.rates_used = norm.rates_used
    return norm.df


def load_demo_dataset() -> pd.DataFrame:
    """Load the bundled Moyo Retail & Services demo transactions into the session."""
    df = pd.read_csv("data/sample_transactions.csv")
    st.session_state.transactions_df = df
    log_usage(user_action="Uploaded transactions", dataset=f"{DEMO_BUSINESS_NAME} (demo)",
              currency=st.session_state.reporting_currency, language=st.session_state.language)
    return df


def render_no_data_actions() -> None:
    """Empty-state shortcuts: a user who lands on an analysis page before
    loading data can fix that in one click instead of hunting in the sidebar."""
    user = st.session_state.current_user
    lang = st.session_state.language
    col_demo, col_upload, _ = st.columns([1, 1, 2])
    with col_demo:
        if st.button(f"\U0001f3ac {t('load_demo_dataset', lang)}", key="empty_state_demo"):
            load_demo_dataset()
            st.rerun()
    with col_upload:
        upload_item = find_item("Upload Data")
        if user is not None and can_access_page(user, "Upload Data"):
            if st.button(f"{upload_item.emoji} {t('nav_upload', lang)}", key="empty_state_upload"):
                go_to("Upload Data")


def require_data() -> pd.DataFrame | None:
    df = load_active_dataframe()
    if df is None or df.empty:
        st.info(t("no_data_loaded", st.session_state.language))
        render_no_data_actions()
        return None
    return df


def render_fx_badges() -> None:
    """Section 13: never let a cached/manual rate masquerade as live --
    surface exactly what kind of rate was used, right in the UI."""
    rates_used = st.session_state.get("rates_used") or {}
    if not rates_used:
        return
    badge_map = {"live": "\U0001f7e2 live", "cached": "\U0001f7e1 cached", "manual": "\U0001f535 manual", "historical": "\u26aa historical"}
    parts = []
    for currency, rr in rates_used.items():
        if rr is None:
            parts.append(f"`{currency}`: \u26a0\ufe0f unsupported (excluded)")
        else:
            parts.append(f"`{currency}\u2192{rr.to_currency}` {badge_map.get(rr.rate_type, rr.rate_type)}")
    st.caption("Exchange rates used: " + " \u00b7 ".join(parts))


# --------------------------------------------------------------------------- Pages
def render_home_snapshot() -> None:
    """Headline numbers for whatever data is currently loaded. A problem with
    an odd upload must never take the landing page down, so failures are
    reported in place instead of raised."""
    lang = st.session_state.language
    try:
        df = load_active_dataframe()
        if df is None or df.empty:
            st.warning("Your data is loaded but has no valid rows. Open Upload Data to see which rows failed validation.")
            return
        prof = profitability_summary(df)
        liq = liquidity_summary(df)
        health = calculate_financial_health(df)
        flagged = sum(1 for f in detect_anomalies(df) if f.risk_level in ("HIGH", "MEDIUM"))
    except Exception as exc:  # noqa: BLE001 -- see docstring
        st.warning(f"Couldn't build the snapshot for this data: {exc}")
        return

    cur = st.session_state.reporting_currency
    st.markdown("### Your snapshot")
    st.caption(f"{len(st.session_state.transactions_df):,} transactions loaded, shown in {cur}.")
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1, st.container(border=True):
        st.metric(t("revenue", lang), f"{cur} {prof.revenue:,.0f}")
    with c2, st.container(border=True):
        st.metric(t("net_profit", lang), f"{cur} {prof.net_profit:,.0f}",
                  f"{prof.net_margin_pct}%" if prof.net_margin_pct is not None else None)
    with c3, st.container(border=True):
        st.metric(t("cash_balance", lang), f"{cur} {liq.net_cash_flow:,.0f}")
    with c4, st.container(border=True):
        st.metric(t("financial_health", lang), f"{health.total_score:.0f}/100")
        st.caption(health.rating)
    with c5, st.container(border=True):
        st.metric("Needs review", f"{flagged}")
        st.caption("high / medium risk transactions")


def page_home(user: User):
    lang = st.session_state.language
    can = lambda label: can_access_page(user, label)  # noqa: E731
    data_loaded = st.session_state.transactions_df is not None

    st.markdown(
        hero_html(
            "Sarudzo AI", t("app_tagline", lang),
            "Sarudzo AI turns raw SME transaction data into financial analysis, risk detection, "
            "cash-flow forecasts, VAT summaries, and AI-explained recommendations -- with every "
            "figure computed deterministically in Python and never invented by the AI.",
        ),
        unsafe_allow_html=True,
    )

    if data_loaded:
        render_home_snapshot()

    st.markdown("### Get started")
    step1, step2, step3 = st.columns(3)
    with step1:
        st.markdown(step_card_html(
            1, "Load your data",
            "Your transactions are loaded and ready." if data_loaded
            else "Load the demo dataset to explore right away, or upload your own CSV or Excel file.",
            done=data_loaded,
        ), unsafe_allow_html=True)
        if not data_loaded:
            if st.button(f"\U0001f3ac {t('load_demo_dataset', lang)}", key="home_step_demo"):
                load_demo_dataset()
                st.rerun()
            if can("Upload Data") and st.button(f"\U0001f4c1 {t('upload_your_own', lang)}", key="home_step_upload"):
                go_to("Upload Data")
    with step2:
        st.markdown(step_card_html(
            2, "Explore the analysis",
            "Start with the Dashboard, then open the pages under Analysis for the detail.",
        ), unsafe_allow_html=True)
        if st.button(f"\U0001f4ca {t('nav_dashboard', lang)}", key="home_step_dashboard"):
            go_to("Dashboard")
    with step3:
        ask_label = "AI Financial Assistant" if can("AI Financial Assistant") else "Reports & Export"
        ask_item = find_item(ask_label)
        st.markdown(step_card_html(
            3, "Ask and export",
            "Ask questions in plain language, or download a report to share." if can("AI Financial Assistant")
            else "Download CSV exports and a printable report to share.",
        ), unsafe_allow_html=True)
        ask_text = t(ask_item.translation_key, lang) if ask_item.translation_key else ask_item.label
        if st.button(f"{ask_item.emoji} {ask_text}", key="home_step_ask"):
            go_to(ask_label)

    st.markdown("### What you can do here")
    cards = home_cards(can)
    per_row = 3  # 9 cards for an admin/accountant -> three even rows
    for row_start in range(0, len(cards), per_row):
        row = cards[row_start:row_start + per_row]
        cols = st.columns(per_row)
        for col, item in zip(cols, row):
            display = t(item.translation_key, lang) if item.translation_key else item.label
            with col:
                st.markdown(feature_card_html(item.emoji, display, item.description), unsafe_allow_html=True)
                if st.button("Open", key=f"home_open_{item.label}"):
                    go_to(item.label)

    if user.role == "viewer":
        st.caption("You're logged in as a viewer: Dashboard and Financial Analysis only. Ask an admin for accountant access to upload data or use the AI assistant.")


def page_upload():
    st.title(f"\U0001f4c1 {t('nav_upload', st.session_state.language)}")
    col1, col2 = st.columns(2)

    with col1:
        st.markdown(f"### {t('load_demo_dataset', st.session_state.language)}")
        st.caption(f"{DEMO_BUSINESS_NAME} -- 12 months, 7 currencies, deliberate anomalies for demonstration.")
        if st.button(t("load_demo_dataset", st.session_state.language)):
            demo_df = load_demo_dataset()
            st.success(f"Loaded {len(demo_df)} demo transactions.")

    with col2:
        st.markdown(f"### {t('upload_your_own', st.session_state.language)}")
        uploaded = st.file_uploader("CSV or Excel", type=["csv", "xlsx", "xls"])
        if uploaded is not None:
            df = pd.read_csv(uploaded) if uploaded.name.endswith(".csv") else pd.read_excel(uploaded)
            st.session_state.transactions_df = df
            log_usage(user_action="Uploaded transactions", dataset=uploaded.name,
                      currency=st.session_state.reporting_currency, language=st.session_state.language)
            st.success(f"Loaded {len(df)} transactions from {uploaded.name}.")

    if st.session_state.transactions_df is not None:
        st.divider()
        st.markdown("### Data Validation")
        result = validate_transactions(st.session_state.transactions_df)
        st.code(result.summary())
        with st.expander("See rows that failed validation"):
            st.dataframe(result.invalid_rows)


def page_dashboard():
    st.title(f"\U0001f4ca {t('nav_dashboard', st.session_state.language)}")
    if st.session_state.demo_mode:
        st.markdown(demo_mode_banner_html(), unsafe_allow_html=True)
    df = require_data()
    if df is None:
        return

    prof = profitability_summary(df)
    liq = liquidity_summary(df)
    health = calculate_financial_health(df)
    render_fx_badges()

    left, right = st.columns([2, 1])
    with left:
        c1, c2, c3, c4, c5 = st.columns(5)
        cur = st.session_state.reporting_currency
        c1.metric(t("revenue", st.session_state.language), f"{cur} {prof.revenue:,.2f}")
        c2.metric(t("expenses", st.session_state.language), f"{cur} {prof.expenses:,.2f}")
        c3.metric(t("net_profit", st.session_state.language), f"{cur} {prof.net_profit:,.2f}",
                  f"{prof.net_margin_pct}%" if prof.net_margin_pct is not None else None)
        c4.metric(t("cash_balance", st.session_state.language), f"{cur} {liq.net_cash_flow:,.2f}")
        c5.metric(t("profit_margin", st.session_state.language), f"{prof.net_margin_pct}%" if prof.net_margin_pct is not None else "N/A")

        st.divider()
        st.markdown("### \U0001f4b5 Revenue by currency (original amounts -- see Section 12)")
        st.bar_chart(pd.Series(revenue_by_currency(df)))

    with right:
        st.markdown(f"### {t('financial_health', st.session_state.language)}")
        st.markdown(health_score_gauge_svg(health.total_score, health.rating), unsafe_allow_html=True)
        if st.session_state.demo_mode:
            st.info(
                f"Demo commentary: {DEMO_BUSINESS_NAME} scores **{health.total_score}/100 "
                f"({health.rating})** this period, driven mainly by its profitability and "
                "cash-flow components below -- open Financial Analysis to see the full breakdown."
            )

    st.divider()
    render_live_rates_section()


def render_live_rates_section() -> None:
    """
    Live exchange rates for every currency Sarudzo AI supports, quoted
    against the current reporting currency -- independent of what's
    actually present in the uploaded dataset (that's what render_fx_badges()
    covers). Each rate is clearly tagged live/cached/manual per Section 13;
    a failed lookup for one currency doesn't take down the rest.
    """
    cur = st.session_state.reporting_currency
    others = [c for c in get_supported_currencies() if c != cur]
    if not others:
        return

    st.markdown("### \U0001f310 Live Exchange Rates")
    st.caption(f"1 unit of each currency, quoted in {cur}. Refreshes on every page load.")
    badge_map = {"live": "\U0001f7e2 live", "cached": "\U0001f7e1 cached", "manual": "\U0001f535 manual", "historical": "\u26aa historical"}

    cols = st.columns(min(len(others), 6))
    for i, currency in enumerate(others):
        with cols[i % len(cols)]:
            try:
                rr = get_live_rate(currency, cur)
                st.metric(currency, f"{rr.rate:,.4f}", badge_map.get(rr.rate_type, rr.rate_type))
                if currency == "ZWL":
                    st.caption("\u26a0\ufe0f Highly volatile -- verify before relying on this.")
            except ValueError:
                st.metric(currency, "N/A", "\u26a0\ufe0f unsupported")


def _safe_ai_text(text: str) -> str:
    """
    Escapes '$' before rendering AI-generated text through st.markdown/st.write/
    st.info. Streamlit treats text between two '$' characters as LaTeX math --
    harmless for most content, but financial answers are full of dollar
    amounts, so a real answer like "Revenue is $182,147.23 ... expenses are
    $138,137.01" gets its middle silently swallowed as a broken math block,
    which is exactly the truncated-response bug this fixes. Escaping to '\\$'
    keeps the literal dollar sign and disables math-mode for it.
    """
    return text.replace("$", "\\$")


def _fmt_currency(value: float, currency: str) -> str:
    return f"{currency} {value:,.2f}"


def _fmt_pct(value: float | None) -> str:
    return f"{value:.1f}%" if value is not None else "N/A"


def _fmt_ratio(value: float | None) -> str:
    return f"{value:.2f}" if value is not None else "N/A"


def page_financial_analysis():
    st.title(f"\U0001f4b0 {t('nav_financial_analysis', st.session_state.language)}")
    df = require_data()
    if df is None:
        return

    prof = profitability_summary(df)
    liq = liquidity_summary(df)
    wc = working_capital_summary(df)
    health = calculate_financial_health(df)
    render_fx_badges()
    cur = st.session_state.reporting_currency

    st.markdown("### Profitability")
    r1 = st.columns(4)
    r1[0].metric("Revenue", _fmt_currency(prof.revenue, cur))
    r1[1].metric("Expenses", _fmt_currency(prof.expenses, cur))
    r1[2].metric("COGS", _fmt_currency(prof.cogs, cur))
    r1[3].metric("Gross Profit", _fmt_currency(prof.gross_profit, cur), _fmt_pct(prof.gross_margin_pct))
    r2 = st.columns(4)
    r2[0].metric("Operating Profit", _fmt_currency(prof.operating_profit, cur), _fmt_pct(prof.operating_margin_pct))
    r2[1].metric("Net Profit", _fmt_currency(prof.net_profit, cur), _fmt_pct(prof.net_margin_pct))
    r2[2].metric("Gross Margin", _fmt_pct(prof.gross_margin_pct))
    r2[3].metric("Net Margin", _fmt_pct(prof.net_margin_pct))

    st.divider()
    st.markdown("### Liquidity")
    l1 = st.columns(4)
    l1[0].metric("Cash Inflows", _fmt_currency(liq.cash_inflows, cur))
    l1[1].metric("Cash Outflows", _fmt_currency(liq.cash_outflows, cur))
    l1[2].metric("Net Cash Flow", _fmt_currency(liq.net_cash_flow, cur))
    l1[3].metric("Current Ratio", _fmt_ratio(liq.current_ratio))
    st.caption("Quick Ratio: " + _fmt_ratio(liq.quick_ratio))

    st.divider()
    st.markdown("### Working Capital")
    w1 = st.columns(4)
    w1[0].metric("Receivables", _fmt_currency(wc.receivables, cur))
    w1[1].metric("Payables", _fmt_currency(wc.payables, cur))
    w1[2].metric("Receivables Trend", _fmt_pct(wc.receivables_trend_pct))
    w1[3].metric("Payables Trend", _fmt_pct(wc.payables_trend_pct))
    st.caption(
        "Receivables/payables and liquidity ratios are proxies derived from transaction "
        "categories (Customer Receipts / Supplier Payments) -- a raw transaction feed doesn't "
        "carry a formal balance sheet or AR/AP subledger."
    )

    st.divider()
    gauge_col, detail_col = st.columns([1, 2])
    with gauge_col:
        st.markdown(health_score_gauge_svg(health.total_score, health.rating), unsafe_allow_html=True)
    with detail_col:
        st.markdown(f"#### {t('how_score_calculated', st.session_state.language)}")
        for c in health.components:
            st.write(f"**{c.name}** ({c.weight_pct:.0f}% weight): {c.component_score:.1f}/100")
            st.caption(c.explanation)

    if st.button(t("explain_with_ai", st.session_state.language)):
        with st.spinner("Asking Sarudzo AI..."):
            lang_code = {"English": "en", "Shona": "sn", "Ndebele": "nd"}[st.session_state.language]
            explanation = explain_financial_result(
                {"profitability": prof, "liquidity": liq, "health_score": health}, language=lang_code,
            )
        st.info(_safe_ai_text(explanation))
        log_audit(user_action="AI explanation requested", analysis_type="financial_analysis",
                   calculation_results={"net_profit": prof.net_profit, "health_score": health.total_score})


def page_anomalies():
    st.title(f"\U0001f50d {t('nav_anomalies', st.session_state.language)}")
    df = require_data()
    if df is None:
        return

    findings = detect_anomalies(df)
    if not findings:
        st.success("No unusual transactions detected in the current dataset.")
        return

    if st.session_state.demo_mode and findings:
        top = findings[0]
        st.markdown(demo_mode_banner_html(), unsafe_allow_html=True)
        st.warning(
            f"Demo highlight -- **{top.transaction_id}** is the highest-risk finding "
            f"(score {top.risk_score}, {top.risk_level}): {top.reasons[0]}"
        )

    for f in findings:
        level_color = {"HIGH": "\U0001f534", "MEDIUM": "\U0001f7e1", "LOW": "\U0001f7e2"}[f.risk_level]
        with st.expander(f"{level_color} {f.transaction_id} -- {f.risk_level} (score {f.risk_score})"):
            st.write("**Reasons:**")
            for r in f.reasons:
                st.write(f"- {r}")
            st.write(f"**Recommended action:** {f.recommended_action}")

    st.divider()
    st.download_button(
        "Download anomalies as CSV", build_anomalies_csv(findings),
        file_name="nyasha_anomalies.csv", mime="text/csv",
    )


def page_cashflow():
    st.title(f"\U0001f4b5 {t('nav_cashflow', st.session_state.language)}")
    df = require_data()
    if df is None:
        return

    forecasts = forecast_all_horizons(df)
    cur = st.session_state.reporting_currency
    horizons = sorted(forecasts.keys())
    starting_balance = forecasts[horizons[0]].starting_balance

    st.markdown("### Projected balance")
    points = [ForecastPoint(0, starting_balance)] + [
        ForecastPoint(h, forecasts[h].expected_closing_balance, forecasts[h].status) for h in horizons
    ]
    insight = forecast_insight(points, cur)
    {"ok": st.info, "watch": st.warning, "risk": st.error}[insight.level](insight.headline)
    st.components.v1.html(chart_page_html(forecast_chart_svg(points, cur)), height=CHART_FRAME_HEIGHT)
    st.caption(
        "Straight-line projection from recent average daily cash flow -- the first point is today's "
        "actual balance; each later point is that day's expected closing balance. Marker colour is "
        "the cash status for that date (the same status shown in the cards below)."
    )

    st.divider()
    st.markdown("### At a glance")
    cols = st.columns(len(horizons))
    for col, h in zip(cols, horizons):
        f = forecasts[h]
        with col:
            st.metric(f"{h}-day", f"{cur} {f.expected_closing_balance:,.0f}", f"{f.status_emoji} {f.status.upper()}")

    st.divider()
    st.markdown("### Details by horizon")
    horizon_choice = st.selectbox("Choose a horizon", horizons, index=horizons.index(30) if 30 in horizons else 0)
    f = forecasts[horizon_choice]

    d1, d2, d3, d4 = st.columns(4)
    d1.metric("Starting Balance", f"{cur} {f.starting_balance:,.2f}")
    d2.metric("Expected Inflows", f"{cur} {f.expected_inflows:,.2f}")
    d3.metric("Expected Outflows", f"{cur} {f.expected_outflows:,.2f}")
    d4.metric("Expected Closing Balance", f"{cur} {f.expected_closing_balance:,.2f}")

    status_colors = {"healthy": "\U0001f7e2", "watch": "\U0001f7e1", "shortage": "\U0001f534"}
    st.markdown(f"**Status:** {status_colors.get(f.status, f.status_emoji)} {f.status.upper()}")
    st.caption(f"Main driver: {f.main_driver}")


def page_customers():
    st.title(f"\U0001f465 {t('nav_customers', st.session_state.language)}")
    df = require_data()
    if df is None:
        return

    risks = analyse_customer_risk(df)
    if not risks:
        st.info("No customer-attributed income transactions in this dataset.")
        return

    st.dataframe(pd.DataFrame([r.__dict__ for r in risks]))
    st.download_button(
        "Download customer risk as CSV", build_customer_risk_csv(risks),
        file_name="nyasha_customer_risk.csv", mime="text/csv",
    )


def page_vat():
    st.title(f"\U0001f9fe {t('nav_vat', st.session_state.language)}")
    df = require_data()
    if df is None:
        return

    vat = calculate_vat_summary(df)
    cur = st.session_state.reporting_currency

    st.markdown(
        f"Sarudzo AI classifies every transaction's VAT status (standard-rated at "
        f"**{VAT_RATES['standard']:.1%}**, zero-rated, or exempt) and calculates VAT the way a "
        f"Zimbabwean SME accountant would: **Output VAT** is VAT charged on sales (owed to ZIMRA), "
        f"**Input VAT** is VAT paid on purchases (claimable back), and **Net VAT Payable** is the "
        f"difference between the two for this period."
    )

    c1, c2, c3 = st.columns(3)
    c1.metric("Output VAT", _fmt_currency(vat.output_vat, cur), help="VAT charged on sales/income transactions this period.")
    c2.metric("Input VAT", _fmt_currency(vat.input_vat, cur), help="VAT paid on purchases/expense transactions this period.")
    c3.metric("Net VAT Payable", _fmt_currency(vat.net_vat_payable, cur), help="Output VAT minus Input VAT.")

    if vat.net_vat_payable > 0:
        st.info(
            f"**Net position: VAT owed.** Output VAT exceeds Input VAT by "
            f"{_fmt_currency(vat.net_vat_payable, cur)} -- this is the amount typically due to "
            f"the tax authority for the period, before any adjustments."
        )
    elif vat.net_vat_payable < 0:
        st.info(
            f"**Net position: potential refund/credit.** Input VAT exceeds Output VAT by "
            f"{_fmt_currency(abs(vat.net_vat_payable), cur)} -- this can indicate a refundable "
            f"credit position, but eligibility and timing depend on tax rules a professional "
            f"should confirm; it is not automatically a cash refund."
        )
    else:
        st.info("**Net position: balanced.** Output VAT and Input VAT are equal for this period.")

    st.divider()
    st.markdown("### VAT by category")
    st.caption("Where VAT is being generated or incurred, by transaction category.")
    by_cat = vat_by_category(df)
    if by_cat:
        st.bar_chart(pd.Series(by_cat).sort_values(ascending=False))
    else:
        st.caption("No VAT-bearing transactions in this dataset.")

    st.divider()
    if vat.transactions_flagged_for_review:
        st.warning(
            f"**{vat.transactions_missing_vat_status} transaction(s) are missing a recognised VAT "
            f"status** (not marked standard, zero-rated, or exempt) and were excluded from the VAT "
            f"totals above -- review and correct these in the source data before filing."
        )
        flagged_df = df[df["transaction_id"].astype(str).isin(vat.transactions_flagged_for_review)]
        display_cols = [c for c in [
            "transaction_id", "date", "description", "transaction_type", "category",
            "amount", "currency", "vat_status",
        ] if c in flagged_df.columns]
        with st.expander(f"See {len(flagged_df)} flagged transaction(s) in detail", expanded=True):
            st.dataframe(flagged_df[display_cols], use_container_width=True, hide_index=True)
            st.download_button(
                "Download flagged transactions as CSV",
                flagged_df[display_cols].to_csv(index=False),
                file_name="nyasha_vat_flagged_transactions.csv", mime="text/csv",
            )
    else:
        st.success("Every transaction has a recognised VAT status -- nothing flagged for review.")

    st.divider()
    st.caption(DISCLAIMER)
    st.caption(t("vat_disclaimer_note", st.session_state.language))


def page_ai_assistant():
    st.title(f"✨ {t('nav_ai_assistant', st.session_state.language)}")
    df = require_data()
    if df is None:
        return

    st.caption(
        "Ask about this business's numbers, or a general financial/accounting/tax "
        "question -- the assistant answers general questions from its own knowledge, "
        "and always checks this business's own figures against the verified data below."
    )

    def _build_context() -> dict:
        prof = profitability_summary(df)
        liq = liquidity_summary(df)
        health = calculate_financial_health(df)
        findings = detect_anomalies(df)[:5]
        forecasts = forecast_all_horizons(df)
        return {
            "profitability": prof, "liquidity": liq, "health_score": health,
            "top_anomalies": findings, "cash_flow_forecast_30_day": forecasts[30],
        }

    lang_code = {"English": "en", "Shona": "sn", "Ndebele": "nd"}[st.session_state.language]

    question = st.text_input("Ask a question")
    if st.button("Ask") and question:
        with st.spinner("Thinking..."):
            answer = answer_financial_question(question, _build_context(), language=lang_code)
        st.write(_safe_ai_text(answer))
        log_usage(user_action="AI inquiry", ai_inquiry=question, currency=st.session_state.reporting_currency,
                   language=st.session_state.language)

    st.divider()
    st.markdown("#### \U0001f3a4 Or ask by voice")
    st.caption("Needs a Gemini API key -- Claude's API doesn't accept audio input yet.")
    audio = st.audio_input("Record your question")
    if audio is not None and st.button("Ask (voice)"):
        with st.spinner("Listening and thinking..."):
            audio_bytes = audio.getvalue()
            mime_type = getattr(audio, "type", None) or "audio/wav"
            answer = answer_financial_question_from_audio(
                audio_bytes, mime_type, _build_context(), language=lang_code,
            )
        st.write(_safe_ai_text(answer))
        log_usage(user_action="AI inquiry (voice)", ai_inquiry="[voice question]",
                   currency=st.session_state.reporting_currency, language=st.session_state.language)


def page_reports():
    st.title("\U0001f4e5 Reports & Export")
    df = require_data()
    if df is None:
        return

    st.caption("Runs the full Sarudzo AI pipeline (agents/orchestrator.py) once and lets you export the results.")
    include_ai = st.checkbox("Include AI explanation in the report", value=False,
                              help="Calls the LLM (or its offline demo-mode fallback) -- leave off for a faster, purely deterministic report.")

    if st.button("Generate report"):
        with st.spinner("Running full analysis..."):
            summary = run_full_analysis(
                df, reporting_currency=st.session_state.reporting_currency,
                language={"English": "en", "Shona": "sn", "Ndebele": "nd"}[st.session_state.language],
                include_explanation=include_ai,
            )
        if summary.errors:
            st.warning("Some steps could not complete: " + "; ".join(summary.errors))

        html_report = build_html_report(
            business_name=DEMO_BUSINESS_NAME if st.session_state.demo_mode else "Uploaded business",
            reporting_currency=st.session_state.reporting_currency,
            profitability=summary.profitability, health_score=summary.health_score,
            anomalies=summary.anomalies, forecasts=summary.forecasts,
            vat_summary=summary.vat_summary, ai_explanation=summary.ai_explanation,
        )
        st.session_state["_last_report_html"] = html_report
        st.session_state["_last_report_summary"] = summary
        log_usage(user_action="Report generated", report_generated=True,
                   currency=st.session_state.reporting_currency, language=st.session_state.language)

    if "_last_report_html" in st.session_state:
        st.success("Report ready.")
        html_report = st.session_state["_last_report_html"]
        st.download_button("Download report (HTML -- open and Print to PDF)", html_report,
                            file_name="nyasha_report.html", mime="text/html")
        pdf_bytes = export_pdf_if_available(html_report)
        if pdf_bytes:
            st.download_button("Download report (PDF)", pdf_bytes, file_name="nyasha_report.pdf", mime="application/pdf")
        else:
            st.caption("No PDF backend installed (xhtml2pdf/weasyprint) -- use the HTML download and your browser's Print to PDF.")
        st.download_button("Download raw transactions (CSV)", build_transactions_csv(df),
                            file_name="nyasha_transactions.csv", mime="text/csv")
        with st.expander("Preview report"):
            st.components.v1.html(html_report, height=600, scrolling=True)


def page_usage_history():
    st.title(f"\U0001f4da {t('nav_usage_history', st.session_state.language)}")
    from database.database import fetch_all
    rows = fetch_all("SELECT * FROM usage_history ORDER BY id DESC LIMIT 200")
    st.dataframe(pd.DataFrame(rows))


def page_audit_trail():
    st.title(f"\U0001f4dc {t('nav_audit_trail', st.session_state.language)}")
    from database.database import fetch_all
    rows = fetch_all("SELECT * FROM audit_trail ORDER BY id DESC LIMIT 200")
    st.dataframe(pd.DataFrame(rows))


ROLE_DESCRIPTIONS = {
    "admin": "Full access, including Usage History, Audit Trail and User Management.",
    "accountant": "Full analysis access (upload, AI assistant, exports); no logs or user management.",
    "viewer": "Read-only: Dashboard and Financial Analysis only.",
}


def _audit_user_change(actor: User, description: str) -> None:
    """Record an account change in the audit trail. Never pass a password."""
    log_audit(user_action=f"{description} (by {actor.username})", analysis_type="user_management")


def page_user_management(user: User):
    """Admin-only. There is intentionally no public sign-up: every account
    is created here, by an administrator."""
    st.title(f"\U0001f511 {t('nav_user_management', st.session_state.language)}")
    st.caption("Only administrators can see this page. Accounts are created here -- there is no public sign-up.")
    # A message saved just before a rerun, so the table below shows fresh data AND the user sees confirmation.
    flash = st.session_state.pop("user_mgmt_flash", None)
    if flash:
        st.success(flash)

    # ---- Create ---------------------------------------------------------
    st.subheader("Create a new user")
    with st.form("create_user_form", clear_on_submit=True):
        new_username = st.text_input("Username")
        new_password = st.text_input("Temporary password", type="password")
        confirm_password = st.text_input("Confirm password", type="password")
        new_role = st.selectbox("Role", list(ROLES), index=ROLES.index("viewer"))
        create_clicked = st.form_submit_button("Create user")
    st.caption("  \n".join(f"**{r}** -- {d}" for r, d in ROLE_DESCRIPTIONS.items()))
    if create_clicked:
        username = new_username.strip()
        if not username:
            st.error("Username is required.")
        elif new_password != confirm_password:
            st.error("Passwords do not match.")
        elif (problem := validate_new_password(new_password)) is not None:
            st.error(problem)
        else:
            try:
                create_user(username, new_password, role=new_role)
            except ValueError as exc:
                st.error(str(exc))
            else:
                _audit_user_change(user, f"Created user '{username}' with role '{new_role}'")
                st.success(f"User '{username}' created as {new_role}. Share the temporary password with them privately.")

    # ---- List -----------------------------------------------------------
    st.subheader("Existing users")
    users = list_users()
    st.dataframe(pd.DataFrame(users), hide_index=True)

    # ---- Manage others --------------------------------------------------
    st.subheader("Manage a user")
    others = [u["username"] for u in users if u["username"] != user.username]
    if not others:
        st.info("There are no other accounts yet. Create one above.")
    else:
        target = st.selectbox("Select user", others)
        target_user = get_user(target)
        if target_user is None:
            st.warning("That user no longer exists.")
        else:
            with st.form("change_role_form"):
                role_choice = st.selectbox(
                    "New role", list(ROLES), index=ROLES.index(target_user.role), key="change_role_choice",
                )
                role_clicked = st.form_submit_button("Update role")
            if role_clicked:
                try:
                    set_role(target, role_choice)
                except ValueError as exc:
                    st.error(str(exc))
                else:
                    _audit_user_change(user, f"Changed role of '{target}' to '{role_choice}'")
                    st.session_state.user_mgmt_flash = f"'{target}' is now {role_choice}."
                    st.rerun()

            with st.form("reset_password_form", clear_on_submit=True):
                reset_password = st.text_input("New temporary password", type="password", key="reset_pw")
                reset_confirm = st.text_input("Confirm new password", type="password", key="reset_pw_confirm")
                reset_clicked = st.form_submit_button("Reset password")
            if reset_clicked:
                if reset_password != reset_confirm:
                    st.error("Passwords do not match.")
                elif (problem := validate_new_password(reset_password)) is not None:
                    st.error(problem)
                else:
                    update_password(target, reset_password)
                    _audit_user_change(user, f"Reset password of '{target}'")
                    st.success(f"Password for '{target}' reset.")

            with st.form("delete_user_form"):
                confirm_delete = st.checkbox(f"Yes, permanently remove '{target}'", key="confirm_delete_user")
                delete_clicked = st.form_submit_button("Remove user")
            if delete_clicked:
                if not confirm_delete:
                    st.error("Tick the confirmation box first.")
                else:
                    try:
                        delete_user(target)
                    except ValueError as exc:
                        st.error(str(exc))
                    else:
                        _audit_user_change(user, f"Removed user '{target}'")
                        st.session_state.user_mgmt_flash = f"User '{target}' removed."
                        st.rerun()

    # ---- Own password ---------------------------------------------------
    st.subheader("Change my password")
    with st.form("change_own_password_form", clear_on_submit=True):
        current_pw = st.text_input("Current password", type="password", key="own_pw_current")
        own_new_pw = st.text_input("New password", type="password", key="own_pw_new")
        own_confirm_pw = st.text_input("Confirm new password", type="password", key="own_pw_confirm")
        own_clicked = st.form_submit_button("Change my password")
    if own_clicked:
        if verify_user(user.username, current_pw) is None:
            st.error("Current password is incorrect.")
        elif own_new_pw != own_confirm_pw:
            st.error("New passwords do not match.")
        elif (problem := validate_new_password(own_new_pw)) is not None:
            st.error(problem)
        else:
            update_password(user.username, own_new_pw)
            _audit_user_change(user, "Changed own password")
            st.success("Your password has been changed.")


# --------------------------------------------------------------------------- Router
# "Home" and "User Management" are handled separately in main() since they
# need `user` -- every other page reads what it needs from st.session_state.
PAGES = {
    "Dashboard": page_dashboard,
    "Upload Data": page_upload,
    "Financial Analysis": page_financial_analysis,
    "Anomaly Detection": page_anomalies,
    "Cash Flow Forecast": page_cashflow,
    "Customer Analysis": page_customers,
    "VAT Analysis": page_vat,
    "AI Financial Assistant": page_ai_assistant,
    "Reports & Export": page_reports,
    "Usage History": page_usage_history,
    "Audit Trail": page_audit_trail,
}


def main():
    user = require_login()
    st.markdown(app_theme_css(), unsafe_allow_html=True)
    st.markdown(nyasha_watermark_html(), unsafe_allow_html=True)
    page = sidebar(user)
    if not can_access_page(user, page):
        st.error("You don't have access to this page.")
        return
    if page == "Home":
        page_home(user)
    elif page == "User Management":
        page_user_management(user)
    else:
        PAGES[page]()


if __name__ == "__main__":
    main()
