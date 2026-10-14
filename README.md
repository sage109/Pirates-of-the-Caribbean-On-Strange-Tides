# NYASHA AI
### Multilingual & Multi-Currency SME Financial Intelligence Agent
*"From Financial Data to Smarter Decisions."*

## Status

Built and tested in a sandboxed environment with **no network access** and
without `streamlit`/`langgraph`/`langchain`/`pydantic`/`anthropic` installed.
Everything that could be built and verified with just `pandas`, `numpy`,
`scikit-learn`, and the stdlib has been -- this is the deterministic core the
whole system depends on for accuracy (Section 0A.3 of the master prompt).
`app.py` has additionally been smoke-tested end-to-end against a hand-built
Streamlit stub (every page, every role, demo mode on and off) to catch
control-flow bugs before a networked environment is available -- but it has
**not** run against real `streamlit`, so still treat it as a strong draft to
verify, not a guaranteed-working final file.

### ✅ Implemented and tested (123/123 tests passing)

- [x] Project structure (Section 4)
- [x] SQLite schema + seed/reset script that survives ephemeral deploys (0A.1)
- [x] Sample dataset generator -- "Moyo Retail & Services", 365 transactions,
      12 months, 7 currencies, deliberate anomalies + data-quality issues (Section 28)
- [x] Data validation (Section 5) -- `analytics/validation.py`
- [x] Multi-currency normalisation with live/cached/manual rate labeling (12, 13)
      -- `services/exchange_rates.py`, `analytics/currency_normalisation.py`
- [x] Financial calculations engine -- revenue, expenses, profitability,
      liquidity, working capital (Section 6) -- `analytics/financial_metrics.py`
- [x] Financial health score, fully explainable (Section 7) -- `analytics/financial_health.py`
- [x] Anomaly detection -- Isolation Forest + rule-based duplicate/z-score
      checks, plus FX-rate anomaly check (Section 8, 0A.4) -- `analytics/anomaly_detection.py`
- [x] Cash-flow forecasting, 7/14/30/60/90-day horizons (Section 9) -- `analytics/forecasting.py`
- [x] Customer payment risk (Section 10) -- `analytics/customer_analysis.py`
- [x] VAT rules engine, configurable rates (Section 11) -- `rules/vat_rules.py`
- [x] LLM service with a hard Python-computes/AI-explains boundary (17, 37)
      -- `services/llm_service.py`, supporting **either Anthropic or Google
      Gemini** (auto-selected by which API key is set; Anthropic wins if
      both are present), with a labeled offline demo-mode fallback when
      neither is available -- **prompt/provider-selection logic tested;
      neither real API has been called yet** (test this first once you have
      network + a key)
- [x] **AI Financial Assistant, including voice questions** -- `app.py`'s
      AI Financial Assistant page. Answers both business-specific questions
      (grounded strictly in this business's verified data) and general
      financial/accounting/tax/business-management questions (from the
      model's own knowledge) -- the system prompt only refuses when asked
      for a business-specific figure that isn't in the verified data.
      Voice input uses Streamlit's built-in `st.audio_input` (needs
      Streamlit 1.40+) and always routes to Gemini via
      `answer_financial_question_from_audio()`, since Claude's Messages API
      doesn't accept raw audio input as of this writing -- if only an
      Anthropic key is set, voice questions degrade to a clear demo-mode
      message explaining a Gemini key is needed specifically for that
      feature, while text questions keep working normally. **Untested
      against a live Gemini call in this sandbox** (no network) -- test the
      actual transcription+answer quality once you have a Gemini key.
- [x] **LangGraph orchestrator** (Section 18) -- `agents/orchestrator.py`. The
      real node logic (validate -> normalise -> metrics -> health score ->
      anomalies -> forecast -> customer risk -> VAT -> explain) is plain
      Python, fully tested, and runs today with zero extra dependencies via
      `run_full_analysis()`. `build_graph()` wraps the same nodes in a real
      LangGraph `StateGraph` once `langgraph` is installed -- untested against
      the real library in this sandbox, but the node functions it wires up
      ARE tested, so behaviour should be identical.
- [x] **Streamlit dashboard, navigation, result cards, health-score gauge**
      (Sections 25-26, 29) -- `app.py`. Includes a pure-SVG gauge (no
      plotly dependency needed) and FX rate-type badges (live/cached/manual)
      so a cached rate is never shown as if it were live (Section 13).
- [x] **Per-user login accounts with roles** -- `services/auth.py`
      (admin/accountant/viewer), salted PBKDF2-SHA256 hashes, no plaintext
      ever stored. In-app first-run setup form provisions the first admin
      (Streamlit Community Cloud gives no shell access, so `scripts/create_user.py`
      only works for local/self-hosted use -- same constraint and same fix
      already verified on the sibling investment-dashboard project).
- [x] **Admin-only User Management page** -- `app.py` (`page_user_management`)
      on top of `services/auth.py`. There is deliberately no public sign-up:
      once the first admin exists, every other account is created by an admin
      from the sidebar's "User Management" page (username, temporary password,
      role). Admins can also change a user's role, reset a password, remove a
      user, and change their own password. Rules enforced in `services/auth.py`
      (not just the UI): usernames are unique ignoring case, new passwords must
      be at least 8 characters, and the last remaining administrator can never
      be deleted or demoted. Every change is written to the Audit Trail (never
      the password). The signed-in account is re-checked from the database on
      every page run, so a removed user is logged out and a changed role takes
      effect immediately. The account list never exposes password hashes.
- [x] **Usability and design pass** -- `ui/navigation.py`, `ui/components.py`,
      `.streamlit/config.toml`, `app.py`. The page list (sections, icons,
      translation keys, Home-card descriptions) now lives in one place,
      `ui/navigation.py`, and the sidebar is grouped into Overview / Data /
      Analysis / AI & Reports / Administration (sections a role can't open are
      hidden entirely) with the settings (language, currency, demo mode) below
      the navigation. The Home page has a hero banner, a three-step "Get
      started" row (step 1 ticks green once data is loaded), a live snapshot of
      the headline numbers when data is loaded (revenue, net profit, cash,
      health score, transactions needing review) and a card for every page the
      user can open. Pages opened before any data is loaded now offer "Load demo
      dataset" / "Upload Data" buttons instead of a dead-end message. The AI
      assistant icon changed from the robot emoji (which renders as a tiny glyph
      on some Windows setups) to a sparkle. The Streamlit theme is pinned to a
      light navy/cream palette, since several components use fixed light colours.
      Tests: `tests/test_navigation.py` (registry vs router vs permissions) and
      new cases in `tests/test_ui_components.py`.
- [x] **Multi-language UI** (Section 15) -- `locales/translations.py`,
      English/Shona/Ndebele, wired into navigation, headers, and key labels
      in `app.py`; full-sentence AI explanations are translated by the LLM
      itself via `services/llm_service.py`'s `language` parameter, which is
      the right layer for prose that depends on the actual data.
- [x] **Report generation / export** (Section 27) -- `reports/report_generator.py`.
      CSV exports (transactions, anomalies, customer risk) plus a
      self-contained styled HTML report (health score, anomalies, forecast,
      VAT, AI explanation) that opens in any browser and prints cleanly to
      PDF. Optional in-app PDF download via `xhtml2pdf`/`weasyprint` if
      either is installed, with a clean, tested fallback to "download the
      HTML instead" when neither is.
- [x] **NYASHA watermark** (Section 31) -- `ui/components.py`, a low-opacity,
      click-through, full-page watermark. Done last, as planned (Section 0A.3
      says cosmetic work goes last).
- [x] **Demo Mode** -- sidebar toggle that auto-loads the Moyo Retail &
      Services dataset and adds guided commentary banners on the Dashboard
      and Anomaly Detection pages, calling out the highest-risk finding by
      name -- built for the 15-20 minute presentation so you're narrating a
      story instead of clicking around raw screens.
- [x] Usage history / analysis history / audit trail UI -- wired into
      `app.py`'s pages on top of the existing `database/database.py` writes;
      restricted to admin accounts only (viewers/accountants can't see other
      staff's activity logs).
- [x] Automated tests for all of the above, including edge cases (empty
      dataset, zero/negative amounts, unknown currency, missing VAT status,
      unavailable exchange-rate API, wrong/missing passwords, HTML-injection
      in report inputs, out-of-range health scores) -- `tests/`

### Still worth doing in a networked environment

- [ ] Help & Inquiry Centre UI (Section 20-21) -- not yet built.
- [ ] Exercise `services/llm_service.py` against a real API -- only the
      offline demo-mode path has been tested here. Set either
      `ANTHROPIC_API_KEY` or `GEMINI_API_KEY`/`GOOGLE_API_KEY` and verify a
      real response comes back correctly formatted and on-topic.
- [ ] Run `app.py` against real `streamlit` (only stub-tested here) and fix
      anything the stub couldn't catch (real widget rendering, `st.rerun()`
      timing, file-uploader edge cases with actual files).
- [ ] Try `agents.orchestrator.build_graph()` against real `langgraph` and
      confirm it matches `run_pipeline_sync()` (it's designed to, but
      untested against the real library).
- [ ] If the rubric wants a true PDF (not "download HTML, print to PDF"),
      install `xhtml2pdf` or `weasyprint` and test `export_pdf_if_available()`
      for real -- it's wired up but has never run against a real backend.

## Running what's built so far

```bash
pip install pandas numpy scikit-learn   # already covers everything below

# Regenerate the demo dataset (optional -- one is already committed)
python3 data/generate_sample_data.py

# Seed the database
python3 database/seed.py --force

# Run the full test suite (67 tests)
python3 -m unittest discover -s tests -v
```

## Continuing the build (Claude Code / networked environment)

1. `pip install -r requirements.txt`
2. Copy `.env.example` to `.env` and add your `ANTHROPIC_API_KEY`.
3. `streamlit run app.py` -- create the first admin account on the setup
   screen, then click through every page and fix whatever the real
   Streamlit runtime surfaces that the offline stub couldn't (see the list
   above).
4. Test `services/llm_service.py` against a real API before the demo --
   set `ANTHROPIC_API_KEY` (Anthropic) or `GEMINI_API_KEY`/`GOOGLE_API_KEY`
   (Gemini) in `.env`, then toggle "Include AI explanation" on the Reports
   & Export page, or use the AI Financial Assistant page directly.
   `services.llm_service.active_provider()` tells you which one the app
   will use.
5. Optionally swap `agents.orchestrator.run_full_analysis()` (works today,
   zero extra deps) for `agents.orchestrator.build_graph()` once `langgraph`
   is installed, if you specifically need LangGraph's graph features
   (branching, checkpointing, visualisation) for the write-up.
6. Provision accounts: on a fresh deployment, create the first admin via the
   in-app first-run form, then log in and add everyone else from the
   **User Management** page (admin only). For local/self-hosted use,
   `python3 scripts/create_user.py --username <name> --role <admin|accountant|viewer>`
   still works.
7. Follow Section 41's 21-step demo script as your integration test -- Demo
   Mode (sidebar toggle) is built to support exactly this.

## Known limitations to flag in the writeup

- Streamlit Community Cloud's filesystem is ephemeral -- `database/seed.py`
  handles this, but say so explicitly in the presentation rather than let it
  surprise you live (Section 0A.1). The same applies to `users` accounts:
  they'll need re-provisioning after a redeploy unless you move to a hosted
  database. If the database is wiped, the app shows the first-run setup form
  again and whoever opens the link first becomes the admin -- so after any
  redeploy or reboot, open the app yourself and recreate the admin before
  sharing the link.
- Liquidity ratios and receivables/payables are computed as proxies from
  transaction categories, since a transaction feed alone doesn't carry a
  formal balance sheet or AR/AP subledger -- documented inline in
  `analytics/financial_metrics.py` and `analytics/customer_analysis.py`.
- The bundled FX rate table (`services/exchange_rates.py`) is illustrative
  and will be stale by demo day, especially for ZWL -- always let it attempt
  a live fetch first; only fall back for the offline rehearsal. The FX-rate
  anomaly check in `agents/orchestrator.py` uses this same bundled table as
  its only offline reference point, so it's a coarse gross-outlier check,
  not a precise one.
- The in-app PDF export depends on an optional third-party library that
  isn't installed by default; without one, the HTML report (always
  available) is the fallback -- mention this rather than assuming PDF export
  "just works" on stage.
- Role-based access (admin/accountant/viewer) is enforced in the UI layer
  (`app.py`/`services/auth.py`), not at the database layer -- fine for a
  single-deployment course project, but worth naming as a limitation if
  asked about production hardening.
- The grouped sidebar navigation is styled with CSS that targets Streamlit's
  internal `data-testid` attributes (`ui/components.py`, `APP_THEME_CSS`). The
  layout and logic are tested against a Streamlit stub, but the look has only
  been checked as rendered HTML, not in a live Streamlit session -- if a future
  Streamlit release renames those attributes, the nav buttons fall back to
  Streamlit's default (centred, bordered) button style but keep working.
