# Hispanic Heritage Historical Data Explorer

A Streamlit app for exploring official World Bank historical indicators, editing a working dataset, fitting centered-time polynomial models, calculating estimates, comparing countries, and exporting reports.

## Featured investigation

**Question:** How has the national-estimate unemployment rate changed over time in Colombia and Chile, and how does a polynomial model describe those historical patterns?

- Main country defaults to Colombia.
- Comparison country defaults to Chile.
- Indicator defaults to unemployment rate, World Bank code `SL.UEM.TOTL.NE.ZS`.
- Mathematics pathway: **Calculus**.

The application offers the nine required countries and all ten World Bank indicator mappings in the assignment. Brazil is included as a Latin American comparison; it is not a Spanish-speaking Hispanic country.

## Files

- `app.py` — complete Streamlit application.
- `requirements.txt` — Python dependencies.
- `sources.md` — primary and context research sources.
- `proposal.md` — 150–250-word project proposal draft.
- `research_brief.md` — research/math write-up scaffold; fill in findings after inspecting live data.
- `test_record.md` — required eight acceptance tests.
- `tests/test_model.py` — unit tests for core model and validation logic.

## Run locally

Use Python 3.10–3.12.

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
python -m streamlit run app.py
```

The app retrieves real data at runtime. Internet access is needed for live data. If the World Bank API is unavailable, the app explains the issue and does not fabricate replacement values.

## Deploy on Streamlit Community Cloud

1. Create a GitHub repository and upload the complete project files.
2. Visit [Streamlit Community Cloud](https://share.streamlit.io/) and connect GitHub.
3. Select **Create app**, choose the repository and branch, and set the main file path to `app.py`.
4. Deploy and inspect logs if startup fails.
5. Open the public app as a viewer and test country/indicator changes, editing/reset, estimates, comparisons, and all downloads.

Official instructions: https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy

## Deploy on Render

1. Push the project to GitHub.
2. In Render, create a **Web Service** and connect the repository.
3. Select Python. Leave Root Directory blank if `app.py` is in the repository root.
4. Build command:

```bash
pip install -r requirements.txt
```

5. Start command (one line):

```bash
python -m streamlit run app.py --server.address=0.0.0.0 --server.port=$PORT
```

6. Deploy, inspect build/runtime logs, and test the public `onrender.com` URL. Free services may sleep after inactivity; open the app before the presentation.

## Model and interpretation

The model uses `t = year - base_year` and fits a degree 3–8 polynomial. It requires at least `degree + 1` distinct years. R² and MAE are **in-sample fit metrics**, not forecast validation. The app reports a chronological holdout MAE only when enough observations remain to fit the chosen degree and reserve at least three later observations.

No statistically validated prediction interval is provided. MAE/residuals are not a complete estimate of future uncertainty. Polynomial extrapolation can become implausible, especially far outside the observed period.

Calculus pathway outputs include first and second derivatives, critical-point classification using the second derivative when applicable, and inflection candidates checked for a second-derivative sign change. These describe the fitted polynomial, not a directly measured annual statistic. When reporting extrema on a closed historical interval, also compare both endpoints.

## Known limitations / verification needed

- The World Bank API is live and may return missing years or later revisions. Always record actual coverage and retrieval date.
- National-estimate unemployment series may differ in methods across countries; inspect metadata before drawing a direct comparison.
- The app applies basic plausibility checks, not domain-expert validation of every value.
- The holdout method is a simple chronological check, not a complete time-series forecasting protocol.
- This code was generated for the assignment and should be run and tested in the student's environment. Do not claim deployment or successful execution until you verify it.
- Complete the research brief with sourced historical/cultural context and findings supported by the current data.

## AI-use disclosure

AI assistance was used to draft the application and project documentation. The student team must test the code, verify official data and calculations, document edits/debugging, understand the mathematics, and be able to explain the contribution of each team member.
