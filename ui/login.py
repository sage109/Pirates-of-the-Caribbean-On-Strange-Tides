"""
ui/login.py

Pure string-building pieces for the sign-in and first-run setup pages, kept
free of Streamlit so they can be unit tested (same approach as ui/components.py
and ui/charts.py). app.py does the actual widgets and calls these for the
branded panel, headings, notices and password-strength meter.

Everything user-visible goes through html.escape; text comes from
locales.translations so the page works in English, Shona and Ndebele.
"""

from __future__ import annotations

import html
import math

from locales.translations import t
from services.auth import MIN_PASSWORD_LENGTH

# Only injected while the login / setup page is on screen, so none of this
# affects the logged-in app. The data-testid selectors are Streamlit's own
# (stable across recent versions); if one stops matching, the page degrades to
# Streamlit's default form look rather than breaking.
LOGIN_CSS = """
<style>
.block-container { max-width: 1040px; padding-top: 2.2rem; padding-bottom: 2rem; }
[data-testid="stHeader"] { background: transparent; }
[data-testid="stForm"] {
    border: 1px solid #e3ddc6; border-radius: 14px; padding: 1.2rem 1.3rem 1.1rem 1.3rem;
    background: #ffffff; box-shadow: 0 6px 24px rgba(11, 31, 58, 0.08);
}
[data-testid="stForm"] [data-testid="stBaseButton-primaryFormSubmit"],
[data-testid="stForm"] button[kind="primaryFormSubmit"],
[data-testid="stForm"] button[kind="secondaryFormSubmit"] { width: 100%; font-weight: 700; padding: 0.55rem 1rem; }

.nyasha-login-panel {
    background: linear-gradient(150deg, #0b1f3a 0%, #1b4079 100%);
    border-radius: 16px; padding: 1.8rem 1.8rem 1.5rem 1.8rem; color: #dbe4f3;
}
.nyasha-login-panel .mark {
    display: inline-flex; align-items: center; justify-content: center;
    width: 2.6rem; height: 2.6rem; border-radius: 12px; background: #c9a227;
    font-size: 1.4rem; margin-bottom: 0.7rem;
}
.nyasha-login-panel .brand { color: #ffffff; font-size: 2rem; font-weight: 800; margin: 0; line-height: 1.15; }
.nyasha-login-panel .tagline { color: #f0d98a; font-weight: 600; font-size: 1.05rem; margin: 0.3rem 0 1.1rem 0; }
.nyasha-login-panel ul { list-style: none; margin: 0 0 1.1rem 0; padding: 0; }
.nyasha-login-panel li { display: flex; gap: 0.6rem; margin-bottom: 0.65rem; line-height: 1.4; font-size: 0.93rem; }
.nyasha-login-panel li .tick {
    flex: 0 0 1.25rem; height: 1.25rem; border-radius: 50%; background: rgba(240, 217, 138, 0.18);
    color: #f0d98a; text-align: center; font-size: 0.8rem; line-height: 1.25rem; font-weight: 700;
}
.nyasha-login-panel .footer { border-top: 1px solid rgba(255, 255, 255, 0.16); padding-top: 0.8rem; font-size: 0.8rem; color: #aebcd6; }

.nyasha-login-heading h2 { color: #0b1f3a; font-size: 1.6rem; font-weight: 800; margin: 0 0 0.2rem 0; padding: 0; }
.nyasha-login-heading p { color: #4b5563; margin: 0 0 0.9rem 0; }

.nyasha-notice { border-radius: 10px; padding: 0.65rem 0.85rem; margin: 0.6rem 0; font-size: 0.92rem; line-height: 1.45; border: 1px solid; }
.nyasha-notice.error   { background: #fdf0ef; border-color: #f0c4c0; color: #7a1c15; }
.nyasha-notice.warning { background: #fdf6e3; border-color: #e3ddc6; color: #5c4a0f; }
.nyasha-notice.info    { background: #eef3fb; border-color: #c9d7ee; color: #0b1f3a; }
.nyasha-notice.success { background: #f4faf4; border-color: #b9dbb9; color: #1f5a1f; }

.nyasha-strength { margin: 0.2rem 0 0.7rem 0; }
.nyasha-strength .bars { display: flex; gap: 4px; }
.nyasha-strength .bar { flex: 1; height: 6px; border-radius: 3px; background: #e5e7eb; }
.nyasha-strength .label { font-size: 0.8rem; color: #4b5563; margin-top: 0.25rem; }
@media (max-width: 640px) {
    .nyasha-login-panel { padding: 1.1rem 1.2rem; }
    .nyasha-login-panel .tagline { margin-bottom: 0; }
    .nyasha-login-panel ul, .nyasha-login-panel .footer { display: none; }
}
.nyasha-login-help { color: #6b7280; font-size: 0.85rem; margin-top: 0.8rem; line-height: 1.45; }
</style>
"""

_STRENGTH_COLORS = {1: "#b3261e", 2: "#c9622a", 3: "#c9a227", 4: "#1f6f4a"}
_NOTICE_ROLES = {"error": "alert", "warning": "status", "info": "status", "success": "status"}


def login_css() -> str:
    return LOGIN_CSS


def brand_panel_html(brand: str, tagline: str, points: list[str], footer: str) -> str:
    items = "".join(
        f'<li><span class="tick" aria-hidden="true">✓</span><span>{html.escape(p)}</span></li>' for p in points
    )
    return (
        '<div class="nyasha-login-panel">'
        '<div class="mark" aria-hidden="true">\U0001f4a1</div>'
        f'<p class="brand">{html.escape(brand)}</p>'
        f'<p class="tagline">{html.escape(tagline)}</p>'
        f"<ul>{items}</ul>"
        f'<div class="footer">{html.escape(footer)}</div>'
        "</div>"
    )


def form_heading_html(title: str, subtitle: str) -> str:
    return (
        '<div class="nyasha-login-heading">'
        f"<h2>{html.escape(title)}</h2><p>{html.escape(subtitle)}</p>"
        "</div>"
    )


def notice_html(kind: str, text: str) -> str:
    """A coloured message box. `kind` is error / warning / info / success;
    errors are announced to screen readers (role=alert)."""
    if kind not in _NOTICE_ROLES:
        raise ValueError(f"kind must be one of {sorted(_NOTICE_ROLES)}, got {kind!r}")
    return f'<div class="nyasha-notice {kind}" role="{_NOTICE_ROLES[kind]}">{html.escape(text)}</div>'


def strength_meter_html(score: int, label: str, level_text: str) -> str:
    """Four-segment password-strength bar. score 0 draws an empty bar and no
    level text (nothing typed yet)."""
    score = max(0, min(4, int(score)))
    color = _STRENGTH_COLORS.get(score, "#e5e7eb")
    bars = "".join(
        f'<span class="bar" style="background:{color if i < score else "#e5e7eb"}"></span>' for i in range(4)
    )
    caption = f"{html.escape(label)}: {html.escape(level_text)}" if score else html.escape(label)
    return (
        f'<div class="nyasha-strength" role="img" aria-label="{caption}">'
        f'<div class="bars">{bars}</div><div class="label">{caption}</div></div>'
    )


def help_text_html(text: str) -> str:
    return f'<div class="nyasha-login-help">{html.escape(text)}</div>'


def minutes_for_display(seconds: int) -> int:
    """Whole minutes for "try again in N minute(s)", never below 1."""
    return max(1, math.ceil(seconds / 60))


def login_error_message(status: str, language: str, retry_after: int = 0, attempts_left: int | None = None) -> str:
    """Text for a failed sign-in (status from services.auth.LoginResult).
    Deliberately the same wording whether the username or the password was
    wrong; the only extra hint is how many tries remain once few are left."""
    if status == "missing":
        return t("login_err_missing", language)
    if status == "locked":
        return t("login_err_locked", language).format(minutes=minutes_for_display(retry_after))
    message = t("login_err_invalid", language)
    if attempts_left is not None and 0 < attempts_left <= 2:
        message += " " + t("login_attempts_left", language).format(n=attempts_left)
    return message


def setup_error_message(code: str, language: str, retry_after: int = 0) -> str:
    """Text for a services.auth.SetupResult.error code."""
    if code == "locked":
        return t("login_err_locked", language).format(minutes=minutes_for_display(retry_after))
    if code == "password_short":
        return t("setup_err_password_short", language).format(n=MIN_PASSWORD_LENGTH)
    key = f"setup_err_{code}"
    return t(key, language)


def strength_level_text(score: int, language: str) -> str:
    return t(f"pw_strength_{max(1, min(4, score))}", language) if score else ""
