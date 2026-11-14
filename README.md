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
   A working Python / FastAPI backend talking to a MapLibre 3D globe and chat panel, powered initially by **NASA POWER** (instant, global MERRA-2 & CERES data from 1981 onward). Type a claim → watch the globe fly → get an honest verdict.
2. **Make the statistics trustworthy (and easy to compare).**
   Combine outlier-resistant methods (**Sen's slope** and **Mann–Kendall** with autocorrelation correction) right alongside classic **linear regression (t-test)** and 95% confidence intervals—so when a single extreme year skews a naive trend line, users can actually see why. For regional maps, apply multiple-testing correction so random 5% grid cells don't light up as false alarms.
3. **Bring in a "second witness" and NASA satellite missions.**
   Model reanalysis isn't a thermometer on the ground. We plan to pull direct weather-station records from **NOAA NCEI** (many stretching back over a century—Kyiv goes back to 1881) right next to NASA's gridded data, and connect named satellite missions like **OMI** (urban NO₂), **GPM**, **GLDAS**, and **GRACE** via the **Giovanni Time Series API** (proxied and cached on our backend).
4. **Watchable detective cases.**
   Include built-in demo investigations that play out step by step—covering confirmed shifts, refuted claims, "too early to tell" cases, and mirror trends where the same driver pushes one region up and another down.

---

*Data sources planned and explored: NASA POWER, NASA GES DISC / Giovanni Time Series Service, and NOAA NCEI. Built for the NASA Space Apps Challenge 2026; not affiliated with or endorsed by NASA.*
