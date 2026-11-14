# Earth Verdict

**Fact-checking claims about our planet, backed by real NASA data.**

> NASA Space Apps Challenge 2026 · Challenge: *Be An Earth System Trend Detective!* · Team **Overflowers**

Hi! If you just landed on this repo — welcome. It's the beginning of the **NASA Space Apps 2026** hackathon weekend (Nov 14–15, 2026), and we're just kicking off the build here. After spending our prep time digging through NASA's datasets, APIs, and statistical pitfalls (and testing ideas in a separate throwaway prototype), we're starting cleanly from scratch in this repository to build **Earth Verdict**.

---

## Why we're building this

NASA publishes thousands of Earth science variables, and tools like [Giovanni](https://giovanni.gsfc.nasa.gov/) make it possible to plot time series and even toggle a trend line. Yet Giovanni's own manual explicitly warns that the line *"does not provide a scientific conclusion."*

For a high-school student, a journalist, or anyone simply curious about the planet, two things remain genuinely hard:
1. **Finding the right data** for a plain-language question like *"Are summers in Kyiv actually getting hotter?"* or *"Is there really less snow than there used to be?"*
2. **Knowing whether a line on a chart is real** or just noisy year-to-year weather pretending to be a trend.

That gap is literally what the challenge asks us to close: combine visualization and honest statistical analysis in one place, so someone can ask **what** is changing, **where**, **how fast**, and whether we actually have **enough evidence** to call it real.

---

## Our idea

Think of Earth Verdict as a **data-detective workspace**: **a 3D globe on the left, a conversation on the right.**

1. **You state a claim in plain words** — *"Summers in Odesa are getting hotter"* or *"City air is getting cleaner in Europe."*
2. **An AI assistant turns it into a check** — it picks the matching variable, geocodes the place, chooses the season and time span, and explains the steps without jargon.
3. **Code does all the math** — our backend pulls the real time series, runs statistical tests, and checks whether the signal actually rises above natural variability.
4. **The globe flies there and shows the verdict** — regions with statistically solid trends light up clearly, unproven ones stay muted, and a case card gives you the chart, the rate per decade, and one of three honest outcomes:
   - **Confirmed** — the data backs up the claim with a statistically significant trend.
   - **Not proven** — there might be something happening, or it might just be noise; either way, the record isn't long or clear enough yet (and we estimate roughly how many more years of observations it would take to know).
   - **Refuted** — there is a significant trend, and it goes the opposite way.

**One non-negotiable rule:** the language model **never invents or estimates a number**. Every rate, p-value, and year count on screen comes straight from Python code and traces back to an official dataset. The AI only translates your question into a query and translates the math back into human language.

---

## Where we're heading

This repo is at day zero right now, so here is the direction we're building toward over the hackathon:

1. **First: get the core loop alive end-to-end.**
   A Python / FastAPI backend talking to a MapLibre 3D globe and chat panel, powered initially by **NASA POWER** (instant, global MERRA-2 & CERES data from 1981 onward). Type a claim → see exactly what will be checked (variable, place, season, period) → watch the globe fly → get an honest verdict. The assistant picks only from a short, curated list of variables, and every field can also be filled in by hand.
2. **Bring in a "second witness".**
   Model reanalysis isn't a thermometer on the ground. Next to NASA's gridded data we show the nearest weather-station record from **NOAA NCEI** (many stretch back over a century; Kyiv goes back to 1881). If the two sources disagree, the verdict says so instead of picking a side.
3. **Make the statistics trustworthy, and show the work.**
   **Mann–Kendall** with autocorrelation correction and **Sen's slope** decide the verdict; classic **linear regression (t-test)** and 95% confidence intervals sit right next to them. A **robustness test** re-runs the check on shifted time windows, so a trend that only appears for one hand-picked period doesn't get called real. When the record is too short, we estimate how many more years it would take to know. A "How we checked this" panel lays it all out.
4. **Connect to NASA missions through Giovanni.**
   Selected variables from **GPM**, **GLDAS**, **GRACE** and **OMI** via the **Giovanni Time Series API** (proxied and cached on our backend), each with a plain-language definition based on Giovanni's own glossary.
5. **Answer "where", not just "whether".**
   Trend maps with false-discovery-rate correction, and side-by-side cases where the same variable rises in one region and falls in another.
6. **Watchable detective cases.**
   Built-in demo investigations that play out step by step and work offline: a confirmed shift, a claim that isn't supported yet, and one where a robust method changes the answer.

**What sets it apart:** we don't just find trends, we check whether you can trust them: two independent sources, an open protocol, and a test against cherry-picked time periods.

---

*Data sources planned and explored: NASA POWER, NASA GES DISC / Giovanni Time Series Service, and NOAA NCEI. Built for the NASA Space Apps Challenge 2026; not affiliated with or endorsed by NASA.*
