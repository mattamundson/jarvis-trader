USE rice_park_practice;

/* ============================================================================
   MAGNUM OPUS v4: Credit Risk Survival Analytics Dashboard
   ----------------------------------------------------------------------------
   v1 techniques (10):
     1-10. KM via LOG/EXP, Greenwood, log-log CI, Wilson CI, vintage curves,
           dual-filter hazard, Spearman, MAD Z-scores, GROUPING SETS, APPLY

   v2 additions (6):
    11-16. Nelson-Aalen, log-rank test, competing-risks CIF,
           Kolmogorov-Smirnov, Gini/Lorenz, Cramér's V

   v3 additions (2):
    17-18. Harrell's C-statistic, dynamic PIVOT (STRING_AGG + sp_executesql)

   v4 additions (7):
    19. Weight of Evidence (WOE) & Information Value (IV)
    20. Restricted Mean Survival Time (RMST) via trapezoidal integration
    21. Abramowitz-Stegun normal CDF polynomial approximation
    22. Exact p-values for log-rank chi-square (via 21)
    23. Benjamini-Hochberg FDR correction (multiple testing)
    24. Acklam's inverse normal CDF rational approximation
    25. Basel III IRB regulatory capital formula (via 24)

   Total: 25 distinct world-class techniques.

   References (v4 additions):
     Good, I. J. (1950). Probability and the Weighing of Evidence.   [WOE/IV]
     Royston, P. & Parmar, M. (2013). BMC Med. Res. Method. 13, 152. [RMST]
     Abramowitz, M. & Stegun, I. (1964). Handbook of Math. Functions.  [N-CDF]
     Benjamini, Y. & Hochberg, Y. (1995). J.R. Statist. Soc. B 57, 289.  [FDR]
     Acklam, P. J. (2003). An algorithm for computing the inverse normal CDF.
     BCBS (2006). Basel II: Int'l Convergence of Capital Measurement.   [IRB]

   Earlier references:
     Kaplan, E. L. & Meier, P. (1958). J. Am. Stat. Assoc. 53, 457.
     Greenwood, M. (1926). Reports on Public Health and Medical Subjects. 33.
     Wilson, E. B. (1927). J. Am. Stat. Assoc. 22, 209.
     Nelson, W. (1972). Technometrics 14, 945.
     Aalen, O. (1978). Annals of Statistics 6, 701.
     Mantel, N. (1966). Cancer Chemother. Rep. 50, 163.
     Fine, J. & Gray, R. (1999). J. Am. Stat. Assoc. 94, 496.
     Kolmogorov, A. (1933). G. Ist. Ital. Attuari 4, 83.
     Gini, C. (1912). Variabilità e mutabilità.
     Cramér, H. (1946). Mathematical Methods of Statistics.
     Harrell, F. E. et al. (1982). JAMA 247, 2543.
============================================================================ */


WITH

/* ============================================================================
   LAYER 1: TEMPORAL FOUNDATION
============================================================================ */

loan_origination AS (
    SELECT
        loan_id,
        MIN(as_of_date)  AS origination_date,
        MIN(upb)         AS original_upb,
        DATEFROMPARTS(
            YEAR(MIN(as_of_date)),
            ((MONTH(MIN(as_of_date)) - 1) / 3) * 3 + 1,
            1
        ) AS vintage_quarter
    FROM dbo.loan_snapshots
    GROUP BY loan_id
),

seasoned_observations AS (
    SELECT
        s.loan_id,
        s.as_of_date,
        s.upb,
        s.dq_status,
        s.days_past_due,
        o.origination_date,
        o.vintage_quarter,
        o.original_upb,
        DATEDIFF(MONTH, o.origination_date, s.as_of_date) AS mob,
        CASE s.dq_status
            WHEN 'CURRENT'     THEN 0
            WHEN '30_DAY'      THEN 1
            WHEN '60_DAY'      THEN 2
            WHEN '90_DAY'      THEN 3
            WHEN '120_DAY'     THEN 4
            WHEN 'FORECLOSURE' THEN 5
            ELSE 0
        END AS severity,
        LEAD(s.dq_status)    OVER (PARTITION BY s.loan_id ORDER BY s.as_of_date) AS next_status,
        LEAD(s.days_past_due)OVER (PARTITION BY s.loan_id ORDER BY s.as_of_date) AS next_dpd,
        LEAD(s.upb)          OVER (PARTITION BY s.loan_id ORDER BY s.as_of_date) AS next_upb,
        LAG(s.dq_status)     OVER (PARTITION BY s.loan_id ORDER BY s.as_of_date) AS prev_status,
        LAG(s.days_past_due) OVER (PARTITION BY s.loan_id ORDER BY s.as_of_date) AS prev_dpd,
        LAG(s.upb)           OVER (PARTITION BY s.loan_id ORDER BY s.as_of_date) AS prev_upb
    FROM dbo.loan_snapshots s
    INNER JOIN loan_origination o ON s.loan_id = o.loan_id
),

/* ============================================================================
   LAYER 2: SURVIVAL EVENT DEFINITION (cause-specific for default)
============================================================================ */

first_default_event AS (
    SELECT
        o.loan_id,
        o.vintage_quarter,
        fd.first_default_mob
    FROM loan_origination o
    OUTER APPLY (
        SELECT MIN(so.mob) AS first_default_mob
        FROM seasoned_observations so
        WHERE so.loan_id = o.loan_id AND so.severity >= 2
    ) fd
),

loan_observation_window AS (
    SELECT
        loan_id,
        vintage_quarter,
        MAX(mob) AS last_mob
    FROM seasoned_observations
    GROUP BY loan_id, vintage_quarter
),

survival_data AS (
    SELECT
        low.loan_id,
        low.vintage_quarter,
        COALESCE(fde.first_default_mob, low.last_mob) AS duration,
        CASE WHEN fde.first_default_mob IS NOT NULL THEN 1 ELSE 0 END AS event_occurred
    FROM loan_observation_window low
    LEFT JOIN first_default_event fde ON low.loan_id = fde.loan_id
),

/* ============================================================================
   LAYER 3-4: KAPLAN-MEIER via LOG/EXP TRICK (from v1)
============================================================================ */

km_event_times AS (
    SELECT
        vintage_quarter,
        duration AS t,
        SUM(event_occurred) AS d_events,
        COUNT(*)            AS reached_t
    FROM survival_data
    GROUP BY vintage_quarter, duration
),

km_at_risk AS (
    SELECT
        vintage_quarter,
        t,
        d_events,
        SUM(reached_t) OVER (
            PARTITION BY vintage_quarter ORDER BY t DESC
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS n_at_risk
    FROM km_event_times
),

km_hazard AS (
    SELECT
        vintage_quarter, t, n_at_risk, d_events,
        CAST(d_events AS FLOAT) / NULLIF(n_at_risk, 0) AS hazard_rate,
        CASE WHEN n_at_risk > d_events AND n_at_risk > 0
             THEN CAST(d_events AS FLOAT) / (CAST(n_at_risk AS FLOAT) * (n_at_risk - d_events))
             ELSE 0 END AS greenwood_term
    FROM km_at_risk
    WHERE d_events > 0
),

kaplan_meier AS (
    SELECT
        vintage_quarter, t AS months_on_book, n_at_risk, d_events, hazard_rate,
        EXP(SUM(LOG(NULLIF(1.0 - hazard_rate, 0))) OVER (
                PARTITION BY vintage_quarter ORDER BY t
                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW))
            AS survival_prob,
        SUM(greenwood_term) OVER (
            PARTITION BY vintage_quarter ORDER BY t
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS cum_greenwood,
        /* LAYER 11: NELSON-AALEN cumulative hazard — additive sibling of KM.
           H(t) = Σ d_i/n_i.  Related via S(t) ≈ exp(-H(t)) but NA is more
           numerically stable when hazard rates are small. */
        SUM(CAST(d_events AS FLOAT) / NULLIF(n_at_risk, 0)) OVER (
            PARTITION BY vintage_quarter ORDER BY t
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS nelson_aalen_H,
        /* Nelson-Aalen variance (Aalen 1978): Σ d_i/n_i² */
        SUM(CAST(d_events AS FLOAT) / NULLIF(CAST(n_at_risk AS FLOAT) * n_at_risk, 0)) OVER (
            PARTITION BY vintage_quarter ORDER BY t
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS nelson_aalen_var
    FROM km_hazard
),

km_with_ci AS (
    SELECT
        vintage_quarter,
        months_on_book,
        n_at_risk,
        d_events,
        hazard_rate,
        survival_prob,
        SQRT(POWER(survival_prob, 2) * cum_greenwood) AS survival_std_err,
        CASE WHEN survival_prob > 0 AND survival_prob < 1 AND cum_greenwood > 0
             THEN POWER(survival_prob, EXP(-1.96 * SQRT(cum_greenwood) / LOG(survival_prob)))
             ELSE survival_prob END AS ci_upper_95,
        CASE WHEN survival_prob > 0 AND survival_prob < 1 AND cum_greenwood > 0
             THEN POWER(survival_prob, EXP( 1.96 * SQRT(cum_greenwood) / LOG(survival_prob)))
             ELSE survival_prob END AS ci_lower_95,
        1 - POWER(1 - hazard_rate, 12) AS annualized_CDR,
        hazard_rate AS SMM,
        /* Nelson-Aalen estimator and its implied survival */
        nelson_aalen_H,
        EXP(-nelson_aalen_H) AS NA_implied_survival,
        /* NA 95% CI using log-transform (stays positive) */
        nelson_aalen_H * EXP(-1.96 * SQRT(nelson_aalen_var) / NULLIF(nelson_aalen_H, 0))
            AS NA_H_lower,
        nelson_aalen_H * EXP( 1.96 * SQRT(nelson_aalen_var) / NULLIF(nelson_aalen_H, 0))
            AS NA_H_upper
    FROM kaplan_meier
),

/* ============================================================================
   LAYER 20: RESTRICTED MEAN SURVIVAL TIME (RMST)
   ----------------------------------------------------------------------------
   A single-number summary of a KM curve: the area under S(t) from 0 to τ.

     RMST(τ) = ∫₀^τ S(t) dt

   Interpretation: "average time-to-default within the observation window."

   Computed via trapezoidal rule numerical integration:
     RMST ≈ Σᵢ (tᵢ₊₁ - tᵢ) · (S(tᵢ) + S(tᵢ₊₁)) / 2

   Has been displacing hazard ratios in clinical-trial and credit-risk
   reporting (Royston & Parmar 2013) because it doesn't require the
   proportional-hazards assumption and is interpretable in time units
   everyone understands (months/years).
============================================================================ */

rmst_trapezoids AS (
    SELECT
        vintage_quarter,
        months_on_book AS t,
        survival_prob AS S_current,
        LAG(months_on_book) OVER (PARTITION BY vintage_quarter ORDER BY months_on_book) AS t_prev,
        LAG(survival_prob) OVER (PARTITION BY vintage_quarter ORDER BY months_on_book) AS S_prev
    FROM km_with_ci
),

rmst_increments AS (
    /* Area of each trapezoid: width × mean height */
    SELECT
        vintage_quarter,
        t,
        t - t_prev AS width,
        (S_current + S_prev) / 2.0 AS mean_height,
        (t - t_prev) * (S_current + S_prev) / 2.0 AS area_increment
    FROM rmst_trapezoids
    WHERE t_prev IS NOT NULL
),

rmst_by_vintage AS (
    /* Include the initial "triangle" from t=0 to first event time,
       where S=1.0 throughout (no events yet) */
    SELECT
        v.vintage_quarter,
        /* Width from 0 to first event time × height of 1.0 (no events yet) */
        COALESCE(MIN(r.t) - 0, 0) AS pre_event_width,
        /* Trapezoidal sum over actual event times */
        ISNULL(SUM(r.area_increment), 0) AS trapezoidal_area,
        /* Total RMST = pre-event survival time + integrated curve */
        COALESCE(
            (SELECT MIN(t) FROM km_with_ci WHERE vintage_quarter = v.vintage_quarter), 0
        ) + ISNULL(SUM(r.area_increment), 0) AS RMST_months,
        MAX(t) AS tau_horizon
    FROM (SELECT DISTINCT vintage_quarter FROM km_with_ci) v
    LEFT JOIN rmst_increments r ON r.vintage_quarter = v.vintage_quarter
    GROUP BY v.vintage_quarter
),

/* ============================================================================
   LAYER 12: LOG-RANK TEST (vintage-vs-rest comparison)
   ----------------------------------------------------------------------------
   Tests whether a given vintage's survival curve differs significantly from
   the rest of the portfolio.  At each portfolio-wide event time t:
     - O_g = observed events in group g
     - E_g = expected events = d_total × n_g / n_total
     - V_g = hypergeometric variance contribution
   Test statistic: χ² = (O_g - E_g)² / V_g, distributed χ²(1).
   Reject H0 (curves identical) at 95% if χ² > 3.841.
   Mantel (1966).
============================================================================ */

portfolio_event_times AS (
    /* Unified timeline of all event times across all vintages */
    SELECT DISTINCT duration AS t
    FROM survival_data
    WHERE event_occurred = 1
),

all_vintages AS (
    SELECT DISTINCT vintage_quarter
    FROM survival_data
),

/* For each (vintage, event_time): compute at-risk and events in that vintage */
vintage_risk_at_portfolio_times AS (
    SELECT
        v.vintage_quarter,
        pet.t,
        SUM(CASE WHEN sd.duration >= pet.t THEN 1 ELSE 0 END) AS n_g,
        SUM(CASE WHEN sd.duration  = pet.t
                   AND sd.event_occurred = 1 THEN 1 ELSE 0 END) AS d_g
    FROM all_vintages v
    CROSS JOIN portfolio_event_times pet
    LEFT JOIN survival_data sd
        ON sd.vintage_quarter = v.vintage_quarter
    GROUP BY v.vintage_quarter, pet.t
),

log_rank_contribs AS (
    SELECT
        vintage_quarter,
        t,
        n_g,
        d_g,
        SUM(n_g) OVER (PARTITION BY t) AS n_total,
        SUM(d_g) OVER (PARTITION BY t) AS d_total
    FROM vintage_risk_at_portfolio_times
),

log_rank_calcs AS (
    SELECT
        vintage_quarter,
        t,
        d_g,
        CAST(d_total AS FLOAT) * n_g / NULLIF(n_total, 0) AS e_g,
        CASE WHEN n_total > 1 AND d_total > 0 AND n_g > 0
             THEN (CAST(d_total AS FLOAT) * (n_total - d_total)
                   * n_g * (CAST(n_total AS FLOAT) - n_g))
                  / (POWER(CAST(n_total AS FLOAT), 2) * (n_total - 1))
             ELSE 0 END AS v_g
    FROM log_rank_contribs
    WHERE n_total > 0 AND d_total > 0
),

log_rank_result AS (
    SELECT
        vintage_quarter,
        SUM(d_g)                                                AS O,
        SUM(e_g)                                                AS E,
        SUM(v_g)                                                AS V,
        POWER(SUM(d_g) - SUM(e_g), 2) / NULLIF(SUM(v_g), 0)     AS chi_square,
        CASE WHEN SUM(v_g) > 0
             THEN (SUM(d_g) - SUM(e_g)) / SQRT(SUM(v_g))
             ELSE 0 END                                         AS z_score,
        CASE
            WHEN POWER(SUM(d_g) - SUM(e_g), 2) / NULLIF(SUM(v_g), 0) > 10.828 THEN 'p<0.001'
            WHEN POWER(SUM(d_g) - SUM(e_g), 2) / NULLIF(SUM(v_g), 0) > 6.635  THEN 'p<0.01'
            WHEN POWER(SUM(d_g) - SUM(e_g), 2) / NULLIF(SUM(v_g), 0) > 3.841  THEN 'p<0.05'
            ELSE 'not significant'
        END AS p_value_band
    FROM log_rank_calcs
    GROUP BY vintage_quarter
),

/* ============================================================================
   LAYERS 21-23: EXACT P-VALUES + BENJAMINI-HOCHBERG FDR CORRECTION
   ----------------------------------------------------------------------------
   The log-rank bands above (p<0.05, p<0.01, ...) are approximations.  For
   publication quality, we need EXACT p-values.  That requires evaluating
   the standard-normal CDF — a transcendental function SQL doesn't have
   natively.

   LAYER 21: Abramowitz-Stegun formula 26.2.17 (accurate to 7.5e-8):
     For x ≥ 0:
       k = 1 / (1 + 0.2316419·x)
       φ(x) = exp(-x²/2) / √(2π)
       Φ(x) ≈ 1 - φ(x)·(b₁k + b₂k² + b₃k³ + b₄k⁴ + b₅k⁵)
     where b = [0.319381530, -0.356563782, 1.781477937,
                -1.821255978, 1.330274429]

   LAYER 22: χ² with 1 df ⟹ p = 2·(1 - Φ(√χ²))

   LAYER 23: Benjamini-Hochberg false discovery rate correction
     Sort p-values ascending, rank them.  BH-adjusted p-value:
       p*(i) = min_{j≥i} [ min(p(j) · n/j, 1) ]
     (enforced monotonicity via running min from right to left)
     When running multiple comparisons (N vintages), raw α = 0.05 inflates
     false-positive rate.  BH controls the expected FDR at α.
============================================================================ */

log_rank_with_pvalues AS (
    SELECT
        vintage_quarter,
        O, E, V, chi_square, z_score,
        /* Exact two-sided p-value from chi-square(1) via A-S polynomial */
        CASE
            WHEN chi_square > 0 AND V > 0 THEN
                /* p = 2·(1 - Φ(√χ²)) ; compute Φ via A-S 26.2.17 */
                2.0 * (
                    EXP(-chi_square / 2.0) / SQRT(2.0 * PI())   -- φ(√χ²)
                    *
                    (   0.319381530  * (1.0 / (1.0 + 0.2316419 * SQRT(chi_square)))
                      - 0.356563782  * POWER(1.0 / (1.0 + 0.2316419 * SQRT(chi_square)), 2)
                      + 1.781477937  * POWER(1.0 / (1.0 + 0.2316419 * SQRT(chi_square)), 3)
                      - 1.821255978  * POWER(1.0 / (1.0 + 0.2316419 * SQRT(chi_square)), 4)
                      + 1.330274429  * POWER(1.0 / (1.0 + 0.2316419 * SQRT(chi_square)), 5)
                    )
                )
            ELSE 1.0
        END AS p_value_exact
    FROM log_rank_result
),

log_rank_bh_ranked AS (
    /* Rank p-values ascending for BH procedure */
    SELECT
        vintage_quarter,
        chi_square, z_score, p_value_exact,
        ROW_NUMBER() OVER (ORDER BY p_value_exact) AS p_rank,
        COUNT(*)    OVER ()                       AS n_tests,
        /* Raw BH-adjusted value: p · n / rank, capped at 1 */
        CASE
            WHEN p_value_exact * CAST(COUNT(*) OVER () AS FLOAT)
                 / ROW_NUMBER() OVER (ORDER BY p_value_exact) > 1.0
            THEN 1.0
            ELSE p_value_exact * CAST(COUNT(*) OVER () AS FLOAT)
                 / ROW_NUMBER() OVER (ORDER BY p_value_exact)
        END AS p_bh_raw
    FROM log_rank_with_pvalues
),

log_rank_bh_adjusted AS (
    /* Enforce monotonicity: BH-adjusted p-value is the running MIN from
       the largest raw p (bottom) upward — classic isotonic regression. */
    SELECT
        vintage_quarter,
        chi_square, z_score, p_value_exact,
        p_rank, n_tests, p_bh_raw,
        /* Running minimum in reverse rank order — preserves monotonicity */
        MIN(p_bh_raw) OVER (
            ORDER BY p_rank DESC
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS p_bh_adjusted,
        CASE
            WHEN MIN(p_bh_raw) OVER (ORDER BY p_rank DESC
                                     ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) < 0.001
                 THEN 'SIGNIFICANT_AFTER_FDR (p<0.001)'
            WHEN MIN(p_bh_raw) OVER (ORDER BY p_rank DESC
                                     ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) < 0.01
                 THEN 'SIGNIFICANT_AFTER_FDR (p<0.01)'
            WHEN MIN(p_bh_raw) OVER (ORDER BY p_rank DESC
                                     ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) < 0.05
                 THEN 'SIGNIFICANT_AFTER_FDR (p<0.05)'
            ELSE 'NOT SIGNIFICANT AFTER FDR'
        END AS fdr_verdict
    FROM log_rank_bh_ranked
),

/* ============================================================================
   LAYER 13: COMPETING RISKS — CUMULATIVE INCIDENCE FUNCTION (CIF)
   ----------------------------------------------------------------------------
   When events compete (default vs prepayment), cause-specific KM OVERSTATES
   the cumulative probability of each event.  The correct estimator is
     CIF_k(t) = Σ_{t_i <= t} S(t_i^-) · (d_{k,i} / n_i)
   where S(t^-) is the overall "any-event" survival just before t.
   Fine & Gray (1999).
============================================================================ */

/* Define a prepayment event: UPB drops to <= 10% of original */
loan_first_events AS (
    SELECT
        lo.loan_id,
        lo.vintage_quarter,
        /* First default (60+ DPD) */
        (SELECT MIN(so.mob) FROM seasoned_observations so
         WHERE so.loan_id = lo.loan_id AND so.severity >= 2) AS default_mob,
        /* First prepayment (UPB collapsed) */
        (SELECT MIN(so.mob) FROM seasoned_observations so
         WHERE so.loan_id = lo.loan_id
           AND so.upb <= 0.10 * lo.original_upb
           AND so.upb > 0) AS prepay_mob
    FROM loan_origination lo
),

competing_events AS (
    SELECT
        lfe.loan_id,
        lfe.vintage_quarter,
        /* Time and cause of first event (or censoring) */
        CASE
            WHEN lfe.default_mob IS NOT NULL AND
                 (lfe.prepay_mob IS NULL OR lfe.default_mob <= lfe.prepay_mob)
                THEN lfe.default_mob
            WHEN lfe.prepay_mob IS NOT NULL
                THEN lfe.prepay_mob
            ELSE low.last_mob
        END AS duration,
        CASE
            WHEN lfe.default_mob IS NOT NULL AND
                 (lfe.prepay_mob IS NULL OR lfe.default_mob <= lfe.prepay_mob)
                THEN 1                  -- cause 1: default
            WHEN lfe.prepay_mob IS NOT NULL
                THEN 2                  -- cause 2: prepayment
            ELSE 0                       -- censored
        END AS event_type
    FROM loan_first_events lfe
    INNER JOIN loan_observation_window low ON low.loan_id = lfe.loan_id
),

cr_event_counts AS (
    SELECT
        duration AS t,
        SUM(CASE WHEN event_type = 1 THEN 1 ELSE 0 END) AS d_default,
        SUM(CASE WHEN event_type = 2 THEN 1 ELSE 0 END) AS d_prepay,
        SUM(CASE WHEN event_type > 0 THEN 1 ELSE 0 END) AS d_any,
        COUNT(*) AS reached_t
    FROM competing_events
    GROUP BY duration
),

cr_at_risk AS (
    SELECT
        t, d_default, d_prepay, d_any,
        SUM(reached_t) OVER (
            ORDER BY t DESC
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS n_at_risk
    FROM cr_event_counts
),

cr_overall_survival AS (
    /* Overall survival S(t) from ANY event — computed via LOG/EXP trick */
    SELECT
        t,
        d_default, d_prepay, d_any, n_at_risk,
        CAST(d_any AS FLOAT) / NULLIF(n_at_risk, 0) AS overall_hazard,
        EXP(SUM(LOG(NULLIF(1.0 - CAST(d_any AS FLOAT) / NULLIF(n_at_risk, 0), 0)))
            OVER (ORDER BY t ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW))
            AS overall_S
    FROM cr_at_risk
    WHERE d_any > 0
),

cr_with_lagged_S AS (
    /* S(t^-) = survival at the PREVIOUS event time, defaulting to 1 at first */
    SELECT
        t, d_default, d_prepay, n_at_risk, overall_S,
        COALESCE(LAG(overall_S) OVER (ORDER BY t), 1.0) AS S_prev
    FROM cr_overall_survival
),

cumulative_incidence AS (
    /* CIF_k(t) = Σ S(t_i^-) · d_{k,i} / n_i */
    SELECT
        t,
        d_default, d_prepay, n_at_risk,
        SUM(S_prev * CAST(d_default AS FLOAT) / NULLIF(n_at_risk, 0)) OVER (
            ORDER BY t ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS CIF_default,
        SUM(S_prev * CAST(d_prepay AS FLOAT) / NULLIF(n_at_risk, 0)) OVER (
            ORDER BY t ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS CIF_prepay,
        overall_S
        /* Check: CIF_default(∞) + CIF_prepay(∞) + S(∞) = 1 */
    FROM cr_with_lagged_S
),

/* ============================================================================
   LAYER 14: KOLMOGOROV-SMIRNOV STATISTIC
   ----------------------------------------------------------------------------
   Credit-scoring standard: measures how well a risk score separates the
   "bad" population (e.g., foreclosed) from the "good" population.
     KS = max | F_bad(s) - F_good(s) |
   where F_bad(s) and F_good(s) are CDFs of the score within each population.
   KS ∈ [0, 1].  0 = no discrimination, 1 = perfect separation.
   Industry benchmarks: KS > 0.3 "acceptable", > 0.5 "excellent".
============================================================================ */

loan_scored AS (
    /* "Risk score" = peak DPD.  "Bad" = foreclosed.  Tests whether peak DPD
       is a good discriminator of eventual foreclosure. */
    SELECT
        loan_id,
        MAX(days_past_due) AS score,
        MAX(CASE WHEN severity = 5 THEN 1 ELSE 0 END) AS is_bad
    FROM seasoned_observations
    GROUP BY loan_id
),

ks_ranked AS (
    SELECT
        loan_id,
        score,
        is_bad,
        SUM(is_bad)     OVER () AS total_bad,
        SUM(1 - is_bad) OVER () AS total_good
    FROM loan_scored
),

ks_cumulative AS (
    /* Cumulative % of each population at each score threshold */
    SELECT
        score,
        SUM(is_bad)     OVER (ORDER BY score
                              ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
            AS cum_bad,
        SUM(1 - is_bad) OVER (ORDER BY score
                              ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
            AS cum_good,
        total_bad,
        total_good
    FROM ks_ranked
),

ks_distances AS (
    SELECT
        score,
        CAST(cum_bad  AS FLOAT) / NULLIF(total_bad,  0) AS F_bad,
        CAST(cum_good AS FLOAT) / NULLIF(total_good, 0) AS F_good,
        ABS(CAST(cum_bad  AS FLOAT) / NULLIF(total_bad,  0)
          - CAST(cum_good AS FLOAT) / NULLIF(total_good, 0)) AS distance
    FROM ks_cumulative
),

ks_statistic AS (
    SELECT
        MAX(distance) AS KS,
        /* Score threshold where max separation occurs (the "KS point") */
        (SELECT TOP 1 score FROM ks_distances
         ORDER BY distance DESC, score) AS KS_score_point,
        CASE
            WHEN MAX(distance) > 0.6 THEN 'EXCEPTIONAL'
            WHEN MAX(distance) > 0.5 THEN 'EXCELLENT'
            WHEN MAX(distance) > 0.4 THEN 'STRONG'
            WHEN MAX(distance) > 0.3 THEN 'ACCEPTABLE'
            WHEN MAX(distance) > 0.2 THEN 'WEAK'
            ELSE 'POOR'
        END AS discrimination_quality
    FROM ks_distances
),

/* ============================================================================
   LAYER 15: GINI COEFFICIENT + LORENZ CURVE
   ----------------------------------------------------------------------------
   Measures INEQUALITY of a distribution.  Applied to portfolio UPB, it
   quantifies loan-balance concentration — "what % of balance is held by
   the largest loans?"
   Discrete formula (Dorfman 1979):
     G = Σ_i (2i - n - 1) · x_{(i)}  /  (n · Σ x_i)
   where x_{(i)} is the i-th smallest value.
   G ∈ [0, 1].  0 = perfect equality, 1 = total concentration.
============================================================================ */

loan_balances AS (
    SELECT
        loan_id,
        MAX(upb) AS value   -- could also use peak_dpd, max_loss, etc.
    FROM seasoned_observations
    GROUP BY loan_id
    HAVING MAX(upb) > 0
),

gini_buildup AS (
    SELECT
        loan_id,
        value,
        ROW_NUMBER() OVER (ORDER BY value) AS rank_asc,
        COUNT(*)     OVER () AS n,
        SUM(value)   OVER () AS total_sum
    FROM loan_balances
),

gini_result AS (
    SELECT
        SUM((2.0 * rank_asc - n - 1) * value)
            / (CAST(MAX(n) AS FLOAT) * MAX(total_sum))
            AS gini_coefficient,
        MAX(n) AS n_loans,
        MAX(total_sum) AS portfolio_total
    FROM gini_buildup
),

lorenz_curve AS (
    /* 10-point Lorenz curve for portfolio visualization */
    SELECT
        decile,
        MAX(pct_loans)   AS pct_loans,
        MAX(pct_balance) AS pct_balance
    FROM (
        SELECT
            NTILE(10) OVER (ORDER BY value) AS decile,
            CAST(rank_asc AS FLOAT) / n AS pct_loans,
            SUM(value) OVER (ORDER BY rank_asc
                             ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
                / total_sum AS pct_balance
        FROM gini_buildup
    ) lorenz_points
    GROUP BY decile
),

/* ============================================================================
   LAYER 16: CRAMÉR'S V (categorical association)
   ----------------------------------------------------------------------------
   Chi-square based measure of association between two categorical variables.
   Unlike raw χ², it is normalized to [0, 1]:
     V = √( χ² / (n · min(r-1, c-1)) )
   where χ² = Σ (O_ij - E_ij)² / E_ij  and  E_ij = (row_i · col_j) / n.
   V ∈ [0, 1].  0 = independence, 1 = perfect association.
   Rule of thumb: >0.25 = strong, 0.15–0.25 = moderate, <0.15 = weak.
============================================================================ */

loan_categorized AS (
    SELECT
        lo.loan_id,
        lo.vintage_quarter,
        CASE
            WHEN lpm.peak_dpd = 0    THEN '0_Never_DQ'
            WHEN lpm.peak_dpd <= 30  THEN '1_30_Day'
            WHEN lpm.peak_dpd <= 60  THEN '2_60_Day'
            WHEN lpm.peak_dpd <= 90  THEN '3_90_Day'
            ELSE '4_Serious'
        END AS severity_bucket
    FROM loan_origination lo
    INNER JOIN (
        SELECT loan_id,
               MAX(days_past_due) AS peak_dpd
        FROM seasoned_observations GROUP BY loan_id
    ) lpm ON lo.loan_id = lpm.loan_id
),

contingency_observed AS (
    SELECT
        vintage_quarter,
        severity_bucket,
        COUNT(*) AS observed
    FROM loan_categorized
    GROUP BY vintage_quarter, severity_bucket
),

contingency_marginals AS (
    SELECT
        vintage_quarter,
        severity_bucket,
        observed,
        SUM(observed) OVER (PARTITION BY vintage_quarter)  AS row_total,
        SUM(observed) OVER (PARTITION BY severity_bucket)  AS col_total,
        SUM(observed) OVER ()                               AS grand_total
    FROM contingency_observed
),

chi_square_cells AS (
    SELECT
        vintage_quarter,
        severity_bucket,
        observed,
        CAST(row_total AS FLOAT) * col_total / NULLIF(grand_total, 0) AS expected,
        POWER(observed - CAST(row_total AS FLOAT) * col_total / NULLIF(grand_total, 0), 2)
            / NULLIF(CAST(row_total AS FLOAT) * col_total / NULLIF(grand_total, 0), 0)
            AS chi_sq_contribution
    FROM contingency_marginals
),

cramers_v_result AS (
    SELECT
        SUM(chi_sq_contribution) AS chi_square_total,
        (SELECT COUNT(DISTINCT vintage_quarter)  FROM contingency_observed) AS r,
        (SELECT COUNT(DISTINCT severity_bucket)  FROM contingency_observed) AS c,
        (SELECT SUM(observed) FROM contingency_observed)                   AS n,
        SQRT(
            SUM(chi_sq_contribution) /
            NULLIF(
                (SELECT SUM(observed) FROM contingency_observed) *
                CASE
                    WHEN (SELECT COUNT(DISTINCT vintage_quarter) FROM contingency_observed) - 1
                         < (SELECT COUNT(DISTINCT severity_bucket) FROM contingency_observed) - 1
                    THEN (SELECT COUNT(DISTINCT vintage_quarter) FROM contingency_observed) - 1
                    ELSE (SELECT COUNT(DISTINCT severity_bucket) FROM contingency_observed) - 1
                END
            , 0)
        ) AS cramers_v,
        CASE
            WHEN SUM(chi_sq_contribution) > 0 THEN
                CASE
                    WHEN SQRT(SUM(chi_sq_contribution) / NULLIF(
                         (SELECT SUM(observed) FROM contingency_observed) *
                         CASE WHEN (SELECT COUNT(DISTINCT vintage_quarter) FROM contingency_observed) - 1
                                   < (SELECT COUNT(DISTINCT severity_bucket) FROM contingency_observed) - 1
                                THEN (SELECT COUNT(DISTINCT vintage_quarter) FROM contingency_observed) - 1
                                ELSE (SELECT COUNT(DISTINCT severity_bucket) FROM contingency_observed) - 1 END, 0)) > 0.25
                    THEN 'STRONG_ASSOCIATION'
                    WHEN SQRT(SUM(chi_sq_contribution) / NULLIF(
                         (SELECT SUM(observed) FROM contingency_observed) *
                         CASE WHEN (SELECT COUNT(DISTINCT vintage_quarter) FROM contingency_observed) - 1
                                   < (SELECT COUNT(DISTINCT severity_bucket) FROM contingency_observed) - 1
                                THEN (SELECT COUNT(DISTINCT vintage_quarter) FROM contingency_observed) - 1
                                ELSE (SELECT COUNT(DISTINCT severity_bucket) FROM contingency_observed) - 1 END, 0)) > 0.15
                    THEN 'MODERATE_ASSOCIATION'
                    ELSE 'WEAK_ASSOCIATION'
                END
            ELSE 'INDEPENDENCE'
        END AS interpretation
    FROM chi_square_cells
),

/* ============================================================================
   LAYERS 5-10: remainder from v1 (vintage curve, hazard smoothing, Spearman,
   robust Z-scores, GROUPING SETS).  Retained for full output.
============================================================================ */

transition_raw AS (
    SELECT dq_status AS from_state, next_status AS to_state, COUNT(*) AS transitions
    FROM seasoned_observations WHERE next_status IS NOT NULL
    GROUP BY dq_status, next_status
),

roll_rate_matrix AS (
    SELECT from_state, to_state, transitions,
           SUM(transitions) OVER (PARTITION BY from_state) AS total_from,
           CAST(transitions AS FLOAT) / SUM(transitions) OVER (PARTITION BY from_state) AS p_hat
    FROM transition_raw
),

roll_rate_with_wilson AS (
    SELECT from_state, to_state, transitions, total_from, p_hat,
        (p_hat + 3.8416/(2.0*total_from)
               - 1.96*SQRT((p_hat*(1-p_hat) + 3.8416/(4.0*total_from))/total_from))
         / (1 + 3.8416/total_from) AS wilson_lower,
        (p_hat + 3.8416/(2.0*total_from)
               + 1.96*SQRT((p_hat*(1-p_hat) + 3.8416/(4.0*total_from))/total_from))
         / (1 + 3.8416/total_from) AS wilson_upper
    FROM roll_rate_matrix
),

vintage_mob_stats AS (
    SELECT vintage_quarter, mob,
           COUNT(DISTINCT loan_id) AS loans_observed_at_mob,
           COUNT(DISTINCT CASE WHEN severity >= 2 THEN loan_id END) AS loans_ever_defaulted_by_mob
    FROM seasoned_observations
    GROUP BY vintage_quarter, mob
),

vintage_curve AS (
    SELECT vintage_quarter, mob, loans_observed_at_mob, loans_ever_defaulted_by_mob,
        CAST(loans_ever_defaulted_by_mob AS FLOAT)
            / NULLIF(loans_observed_at_mob, 0) * 100 AS cumul_default_rate_pct,
        AVG(CAST(loans_ever_defaulted_by_mob AS FLOAT) / NULLIF(loans_observed_at_mob, 0))
            OVER (PARTITION BY mob) * 100 AS portfolio_avg_pct,
        (CAST(loans_ever_defaulted_by_mob AS FLOAT) / NULLIF(loans_observed_at_mob, 0)
          - AVG(CAST(loans_ever_defaulted_by_mob AS FLOAT) / NULLIF(loans_observed_at_mob, 0))
                OVER (PARTITION BY mob)) * 10000 AS deviation_bps,
        RANK() OVER (PARTITION BY mob ORDER BY
            CAST(loans_ever_defaulted_by_mob AS FLOAT) / NULLIF(loans_observed_at_mob, 0)) AS vintage_rank
    FROM vintage_mob_stats
),

monthly_new_defaults AS (
    SELECT mob, COUNT(DISTINCT loan_id) AS loans_at_mob,
           SUM(CASE WHEN severity >= 2 AND prev_status = 'CURRENT' THEN 1 ELSE 0 END) AS new_defaults
    FROM seasoned_observations
    WHERE prev_status IS NOT NULL
    GROUP BY mob
),

hazard_curve AS (
    SELECT mob, loans_at_mob, new_defaults,
        CAST(new_defaults AS FLOAT) / NULLIF(loans_at_mob, 0) AS raw_hazard,
        AVG(CAST(new_defaults AS FLOAT) / NULLIF(loans_at_mob, 0))
            OVER (ORDER BY mob ROWS BETWEEN 1 PRECEDING AND 1 FOLLOWING) AS smoothed_3mo,
        SUM((CAST(new_defaults AS FLOAT) / NULLIF(loans_at_mob, 0))
            * POWER(0.7, 5 - ROW_NUMBER() OVER (ORDER BY mob)))
            OVER (ORDER BY mob ROWS BETWEEN 5 PRECEDING AND CURRENT ROW) * 0.3 AS ewma_hazard
    FROM monthly_new_defaults
),

loan_pair_metrics AS (
    SELECT loan_id,
           MAX(days_past_due) AS peak_dpd,
           MAX(upb)           AS max_upb,
           MAX(CASE WHEN severity = 5 THEN 1 ELSE 0 END) AS foreclosed_flag
    FROM seasoned_observations GROUP BY loan_id
),

loan_ranks AS (
    SELECT loan_id, peak_dpd, max_upb,
           RANK() OVER (ORDER BY peak_dpd) AS rank_dpd,
           RANK() OVER (ORDER BY max_upb)  AS rank_upb
    FROM loan_pair_metrics
),

spearman AS (
    SELECT COUNT(*) AS n,
           SUM(POWER(1.0 * (rank_dpd - rank_upb), 2)) AS sum_d_sq,
           1 - (6.0 * SUM(POWER(1.0 * (rank_dpd - rank_upb), 2)))
             / (CAST(COUNT(*) AS FLOAT) * (POWER(CAST(COUNT(*) AS FLOAT), 2) - 1)) AS spearman_rho
    FROM loan_ranks
),

dpd_median AS (
    SELECT DISTINCT
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY 1.0 * peak_dpd) OVER () AS med_dpd
    FROM loan_pair_metrics
),

dpd_mad AS (
    SELECT DISTINCT
        PERCENTILE_CONT(0.5) WITHIN GROUP
            (ORDER BY ABS(1.0 * l.peak_dpd - m.med_dpd)) OVER () * 1.4826 AS mad_dpd,
        m.med_dpd
    FROM loan_pair_metrics l
    CROSS JOIN dpd_median m
),

robust_z_scores AS (
    SELECT l.loan_id, l.peak_dpd, m.med_dpd, m.mad_dpd,
           (1.0 * l.peak_dpd - m.med_dpd) / NULLIF(m.mad_dpd, 0) AS robust_z
    FROM loan_pair_metrics l
    CROSS JOIN dpd_mad m
),

loan_attribution AS (
    SELECT lo.loan_id, lo.vintage_quarter,
           CASE WHEN lpm.peak_dpd = 0   THEN '0_Never_DQ'
                WHEN lpm.peak_dpd <= 30 THEN '1_30_Day'
                WHEN lpm.peak_dpd <= 60 THEN '2_60_Day'
                WHEN lpm.peak_dpd <= 90 THEN '3_90_Day'
                ELSE '4_Serious_Plus' END AS severity_bucket,
           NTILE(5) OVER (ORDER BY lpm.max_upb) AS upb_quintile,
           lpm.foreclosed_flag, lpm.max_upb
    FROM loan_origination lo
    INNER JOIN loan_pair_metrics lpm ON lo.loan_id = lpm.loan_id
),

risk_rollup AS (
    SELECT
        COALESCE(CAST(vintage_quarter AS VARCHAR), '** ALL VINTAGES **') AS vintage_label,
        COALESCE(severity_bucket,                  '** ALL SEVERITY **')  AS severity_label,
        COALESCE(CAST(upb_quintile AS VARCHAR),    '** ALL QUINTILES **') AS quintile_label,
        COUNT(*) AS loan_count,
        SUM(foreclosed_flag) AS foreclosures,
        CAST(SUM(foreclosed_flag) AS FLOAT) / NULLIF(COUNT(*), 0) * 100 AS foreclosure_rate_pct,
        SUM(max_upb) AS total_upb,
        GROUPING(vintage_quarter) + GROUPING(severity_bucket) + GROUPING(upb_quintile) AS rollup_level
    FROM loan_attribution
    GROUP BY GROUPING SETS (
        (vintage_quarter, severity_bucket, upb_quintile),
        (vintage_quarter, severity_bucket),
        (vintage_quarter),
        (severity_bucket),
        ()
    )
),

/* ============================================================================
   LAYER 17: HARRELL'S C-STATISTIC (Concordance Index)
   ----------------------------------------------------------------------------
   The survival-analysis equivalent of AUC.  For every comparable pair of
   subjects, the C-index measures the fraction where the subject with the
   higher risk score also experienced the event first.

     C = (concordant_pairs + 0.5 × tied_pairs) / comparable_pairs

   A pair is COMPARABLE if:
     - both had the event at different times, OR
     - one had the event and the other was censored later

   A pair is CONCORDANT if:
     - the subject with higher risk score had the earlier event

   C ∈ [0.5, 1]:
     0.5   = random (no discrimination)
     0.7   = acceptable
     0.8   = excellent
     0.9+  = outstanding

   Harrell, F. E. et al. (1982).  JAMA 247, 2543.
   The gold standard for validating survival-risk models.
============================================================================ */

c_index_subjects AS (
    /* Duration, event flag, and "risk score" (here: original balance).
       Tests whether loan size predicts time-to-default. */
    SELECT
        sd.loan_id,
        sd.duration,
        sd.event_occurred,
        lpm.max_upb AS risk_score
    FROM survival_data sd
    INNER JOIN loan_pair_metrics lpm ON sd.loan_id = lpm.loan_id
),

c_index_pairs AS (
    /* Every unordered pair {a, b} exactly once via a.loan_id < b.loan_id */
    SELECT
        /* COMPARABLE flag: can we tell which of a, b had the event first? */
        CASE
            /* Both events at different times — comparable */
            WHEN a.event_occurred = 1 AND b.event_occurred = 1
                 AND a.duration <> b.duration THEN 1
            /* a had event, b censored AFTER a's event time */
            WHEN a.event_occurred = 1 AND b.event_occurred = 0
                 AND a.duration < b.duration THEN 1
            /* b had event, a censored AFTER b's event time */
            WHEN a.event_occurred = 0 AND b.event_occurred = 1
                 AND b.duration < a.duration THEN 1
            ELSE 0
        END AS comparable,

        /* CONCORDANCE value: 1.0 concordant, 0.5 tied scores, 0 discordant */
        CASE
            /* a had earlier event AND higher risk score → concordant */
            WHEN a.event_occurred = 1
                 AND (b.event_occurred = 0 OR a.duration < b.duration)
                 AND a.risk_score > b.risk_score
                 THEN 1.0
            /* b had earlier event AND higher risk score → concordant */
            WHEN b.event_occurred = 1
                 AND (a.event_occurred = 0 OR b.duration < a.duration)
                 AND b.risk_score > a.risk_score
                 THEN 1.0
            /* Tied risk scores within a comparable pair → half-credit
               (standard Harrell convention to preserve expectation = 0.5 under H0) */
            WHEN a.risk_score = b.risk_score
                 AND ((a.event_occurred = 1 AND b.event_occurred = 1 AND a.duration <> b.duration)
                   OR (a.event_occurred = 1 AND b.event_occurred = 0 AND a.duration < b.duration)
                   OR (a.event_occurred = 0 AND b.event_occurred = 1 AND b.duration < a.duration))
                 THEN 0.5
            ELSE 0.0
        END AS concordance_value
    FROM c_index_subjects a
    CROSS JOIN c_index_subjects b
    WHERE a.loan_id < b.loan_id   -- unique unordered pairs
),

c_statistic AS (
    SELECT
        CAST(SUM(concordance_value) AS FLOAT)
            / NULLIF(SUM(CAST(comparable AS FLOAT)), 0) AS c_index,
        SUM(comparable)          AS n_comparable_pairs,
        SUM(concordance_value)   AS n_concordant_weighted,
        CASE
            WHEN CAST(SUM(concordance_value) AS FLOAT)
                  / NULLIF(SUM(CAST(comparable AS FLOAT)), 0) > 0.9 THEN 'OUTSTANDING'
            WHEN CAST(SUM(concordance_value) AS FLOAT)
                  / NULLIF(SUM(CAST(comparable AS FLOAT)), 0) > 0.8 THEN 'EXCELLENT'
            WHEN CAST(SUM(concordance_value) AS FLOAT)
                  / NULLIF(SUM(CAST(comparable AS FLOAT)), 0) > 0.7 THEN 'ACCEPTABLE'
            WHEN CAST(SUM(concordance_value) AS FLOAT)
                  / NULLIF(SUM(CAST(comparable AS FLOAT)), 0) > 0.6 THEN 'POOR'
            WHEN ABS(CAST(SUM(concordance_value) AS FLOAT)
                  / NULLIF(SUM(CAST(comparable AS FLOAT)), 0) - 0.5) < 0.05 THEN 'NO_DISCRIMINATION'
            ELSE 'INVERTED (score predicts OPPOSITE direction)'
        END AS discrimination_band
    FROM c_index_pairs
    WHERE comparable = 1
),

/* ============================================================================
   LAYER 19: WEIGHT OF EVIDENCE (WOE) & INFORMATION VALUE (IV)
   ----------------------------------------------------------------------------
   The foundation of every credit scorecard built in the last 50 years.
   For a candidate predictor variable, bin it and compute:

     WOE(bin) = ln( (% of GOOD in bin) / (% of BAD in bin) )
     IV       = Σ (%good − %bad) · WOE(bin)

   Good, I. J. (1950).  Used at Fair Isaac, Experian, TransUnion, Moody's.

   Information Value interpretation (Siddiqi, 2006):
     IV < 0.02    → useless predictor
     0.02 - 0.1   → weak
     0.1  - 0.3   → medium
     0.3  - 0.5   → strong
     IV > 0.5     → suspicious (likely leakage from the outcome)

   Laplace smoothing (add 0.5 to numerator/denominator) prevents LOG(0)
   when a bin has zero goods or zero bads.
============================================================================ */

woe_bins AS (
    /* Bin the candidate variable.  Here: max_upb (loan balance) in deciles.
       Outcome = foreclosed_flag (bad=1, good=0). */
    SELECT
        loan_id,
        NTILE(10) OVER (ORDER BY max_upb) AS upb_decile,
        max_upb,
        foreclosed_flag
    FROM loan_pair_metrics
),

woe_bin_counts AS (
    SELECT
        upb_decile,
        MIN(max_upb)              AS bin_lower,
        MAX(max_upb)              AS bin_upper,
        COUNT(*)                  AS n_total,
        SUM(foreclosed_flag)      AS n_bad,
        COUNT(*) - SUM(foreclosed_flag) AS n_good
    FROM woe_bins
    GROUP BY upb_decile
),

woe_with_totals AS (
    SELECT
        upb_decile,
        bin_lower, bin_upper,
        n_total, n_good, n_bad,
        SUM(n_good) OVER () AS total_good,
        SUM(n_bad)  OVER () AS total_bad
    FROM woe_bin_counts
),

woe_calc AS (
    SELECT
        upb_decile,
        bin_lower, bin_upper, n_total, n_good, n_bad,
        CAST(n_good AS FLOAT) / NULLIF(total_good, 0) AS pct_good,
        CAST(n_bad  AS FLOAT) / NULLIF(total_bad,  0) AS pct_bad,
        /* Laplace-smoothed WOE: ln(((good + 0.5) / total_good) / ((bad + 0.5) / total_bad)) */
        LOG(
            ((CAST(n_good AS FLOAT) + 0.5) / (total_good + 0.5 * 10))
          / NULLIF(((CAST(n_bad AS FLOAT)  + 0.5) / (total_bad  + 0.5 * 10)), 0)
        ) AS woe,
        /* IV contribution per bin */
        (CAST(n_good AS FLOAT) / NULLIF(total_good, 0)
         - CAST(n_bad AS FLOAT) / NULLIF(total_bad, 0))
        *
        LOG(
            ((CAST(n_good AS FLOAT) + 0.5) / (total_good + 0.5 * 10))
          / NULLIF(((CAST(n_bad AS FLOAT)  + 0.5) / (total_bad  + 0.5 * 10)), 0)
        ) AS iv_contribution
    FROM woe_with_totals
),

iv_summary AS (
    SELECT
        SUM(iv_contribution) AS total_iv,
        CASE
            WHEN SUM(iv_contribution) > 0.5  THEN 'SUSPICIOUS (likely leakage)'
            WHEN SUM(iv_contribution) > 0.3  THEN 'STRONG_PREDICTOR'
            WHEN SUM(iv_contribution) > 0.1  THEN 'MEDIUM_PREDICTOR'
            WHEN SUM(iv_contribution) > 0.02 THEN 'WEAK_PREDICTOR'
            ELSE 'USELESS_PREDICTOR'
        END AS iv_interpretation
    FROM woe_calc
),

/* ============================================================================
   LAYERS 24-25: BASEL III IRB CAPITAL REQUIREMENT
   ----------------------------------------------------------------------------
   LAYER 24: Acklam's inverse normal CDF — rational polynomial approximation
             accurate to 1.15e-9.  Implemented inline in the Basel formula.

   LAYER 25: Basel III Internal Ratings-Based (IRB) capital formula for
             residential mortgages (BCBS 2006, §328-330).

     K = LGD · [ Φ( (Φ⁻¹(PD) + √R · Φ⁻¹(0.999)) / √(1 - R) ) − PD ]

     where:
       Φ   = standard normal CDF     (computed via A-S above)
       Φ⁻¹ = inverse standard normal (computed via Acklam below)
       R   = correlation = 0.15 (fixed for residential mortgages)
       LGD = loss-given-default = 40% (industry standard assumption)
       PD  = 12-month probability of default per vintage

     RWA (Risk-Weighted Assets) = K · 12.5 · EAD
     Regulatory Capital Requirement = K · EAD  (≥ 8% of RWA)

   This is NOT a theoretical exercise — it is literally the formula every
   bank worldwide uses to compute the capital reserve it must hold against
   its mortgage portfolio.  Implementing it in pure SQL is a portfolio-level
   showcase.
============================================================================ */

basel_vintage_pd AS (
    /* 12-month probability of default per vintage = 1 - S(12) */
    SELECT
        km.vintage_quarter,
        1.0 - km.survival_prob AS pd_12m,
        km.n_at_risk,
        /* Get EAD (exposure at default) = sum of current UPB for vintage */
        vo.total_exposure
    FROM km_with_ci km
    INNER JOIN (
        SELECT vintage_quarter, SUM(max_upb) AS total_exposure
        FROM loan_origination lo
        INNER JOIN loan_pair_metrics lpm ON lo.loan_id = lpm.loan_id
        GROUP BY vintage_quarter
    ) vo ON vo.vintage_quarter = km.vintage_quarter
    /* Pick the month closest to 12 MOB per vintage, using ROW_NUMBER */
    WHERE km.months_on_book = (
        SELECT MAX(km2.months_on_book)
        FROM km_with_ci km2
        WHERE km2.vintage_quarter = km.vintage_quarter
          AND km2.months_on_book <= 12
    )
),

basel_capital AS (
    SELECT
        vintage_quarter,
        pd_12m,
        total_exposure AS EAD,

        /* --- Acklam inverse normal applied to PD ---
           Uses central region coefficients for PD in [0.02425, 0.97575].
           For small PDs (mortgage typical), uses lower tail branch. */
        CASE
            /* Central region — |q| <= 0.42475 i.e. PD in [0.02425, 0.97575] */
            WHEN pd_12m BETWEEN 0.02425 AND 0.97575 THEN
                (pd_12m - 0.5) * (
                    ((((-39.69683028665376 * POWER(pd_12m - 0.5, 2)
                       + 220.9460984245205) * POWER(pd_12m - 0.5, 2)
                       - 275.9285104469687) * POWER(pd_12m - 0.5, 2)
                       + 138.3577518672690) * POWER(pd_12m - 0.5, 2)
                       - 30.66479806614716) * POWER(pd_12m - 0.5, 2)
                       + 2.506628277459239
                ) / (
                    ((((-54.47609879822406 * POWER(pd_12m - 0.5, 2)
                       + 161.5858368580409) * POWER(pd_12m - 0.5, 2)
                       - 155.6989798598866) * POWER(pd_12m - 0.5, 2)
                       + 66.80131188771972) * POWER(pd_12m - 0.5, 2)
                       - 13.28068155288572) * POWER(pd_12m - 0.5, 2) + 1
                )
            /* Lower tail — PD < 0.02425 (typical for mortgages) */
            WHEN pd_12m > 0 AND pd_12m < 0.02425 THEN
                (((((-7.784894002430293e-03 * SQRT(-2.0 * LOG(pd_12m))
                    - 0.3223964580411365) * SQRT(-2.0 * LOG(pd_12m))
                    - 2.400758277161838)   * SQRT(-2.0 * LOG(pd_12m))
                    - 2.549732539343734)   * SQRT(-2.0 * LOG(pd_12m))
                    + 4.374664141464968)   * SQRT(-2.0 * LOG(pd_12m))
                    + 2.938163982698783
                ) / (
                    ((( 7.784695709041462e-03 * SQRT(-2.0 * LOG(pd_12m))
                    + 0.3224671290700398)   * SQRT(-2.0 * LOG(pd_12m))
                    + 2.445134137142996)   * SQRT(-2.0 * LOG(pd_12m))
                    + 3.754408661907416)   * SQRT(-2.0 * LOG(pd_12m)) + 1
                )
            /* Upper tail or undefined — fall back to 0 (flat default) */
            ELSE 0
        END AS phi_inv_pd,

        /* Φ⁻¹(0.999) = 3.09023230616781 — hardcoded (single constant) */
        3.09023230616781 AS phi_inv_999,

        /* Basel correlation R for residential mortgages — fixed at 0.15 */
        0.15 AS R_correlation,

        /* LGD assumption — industry standard for first-lien residential */
        0.40 AS LGD
    FROM basel_vintage_pd
    WHERE pd_12m > 0 AND pd_12m < 1  -- Valid PD range
),

basel_capital_final AS (
    /* Compute K via Basel IRB formula.  Requires evaluating Φ on the
       composite expression — use A-S polynomial approximation again. */
    SELECT
        vintage_quarter,
        pd_12m,
        EAD,
        phi_inv_pd,

        /* Inner argument of outer Φ:
           z = (Φ⁻¹(PD) + √R · Φ⁻¹(0.999)) / √(1 - R)  */
        (phi_inv_pd + SQRT(R_correlation) * phi_inv_999)
            / SQRT(1 - R_correlation) AS basel_z,

        /* Evaluate Φ(basel_z) via A-S 26.2.17 polynomial.
           For z ≥ 0: Φ(z) = 1 - φ(z)·poly(k); for z < 0: Φ(z) = 1 - Φ(-z). */
        CASE
            WHEN (phi_inv_pd + SQRT(R_correlation) * phi_inv_999)
                 / SQRT(1 - R_correlation) >= 0
            THEN 1.0 - (
                EXP(-POWER((phi_inv_pd + SQRT(R_correlation) * phi_inv_999)
                           / SQRT(1 - R_correlation), 2) / 2.0)
                / SQRT(2.0 * PI())
                * (
                    0.319381530 * (1.0 / (1.0 + 0.2316419 *
                        ((phi_inv_pd + SQRT(R_correlation) * phi_inv_999)
                         / SQRT(1 - R_correlation))))
                  - 0.356563782 * POWER(1.0 / (1.0 + 0.2316419 *
                        ((phi_inv_pd + SQRT(R_correlation) * phi_inv_999)
                         / SQRT(1 - R_correlation))), 2)
                  + 1.781477937 * POWER(1.0 / (1.0 + 0.2316419 *
                        ((phi_inv_pd + SQRT(R_correlation) * phi_inv_999)
                         / SQRT(1 - R_correlation))), 3)
                  - 1.821255978 * POWER(1.0 / (1.0 + 0.2316419 *
                        ((phi_inv_pd + SQRT(R_correlation) * phi_inv_999)
                         / SQRT(1 - R_correlation))), 4)
                  + 1.330274429 * POWER(1.0 / (1.0 + 0.2316419 *
                        ((phi_inv_pd + SQRT(R_correlation) * phi_inv_999)
                         / SQRT(1 - R_correlation))), 5)
                )
            )
            ELSE
                /* z < 0: Φ(z) = 1 - Φ(-z) = φ(-z)·poly(k) */
                EXP(-POWER(-(phi_inv_pd + SQRT(R_correlation) * phi_inv_999)
                           / SQRT(1 - R_correlation), 2) / 2.0)
                / SQRT(2.0 * PI())
                * (
                    0.319381530 * (1.0 / (1.0 + 0.2316419 *
                        (-(phi_inv_pd + SQRT(R_correlation) * phi_inv_999)
                         / SQRT(1 - R_correlation))))
                  - 0.356563782 * POWER(1.0 / (1.0 + 0.2316419 *
                        (-(phi_inv_pd + SQRT(R_correlation) * phi_inv_999)
                         / SQRT(1 - R_correlation))), 2)
                  + 1.781477937 * POWER(1.0 / (1.0 + 0.2316419 *
                        (-(phi_inv_pd + SQRT(R_correlation) * phi_inv_999)
                         / SQRT(1 - R_correlation))), 3)
                  - 1.821255978 * POWER(1.0 / (1.0 + 0.2316419 *
                        (-(phi_inv_pd + SQRT(R_correlation) * phi_inv_999)
                         / SQRT(1 - R_correlation))), 4)
                  + 1.330274429 * POWER(1.0 / (1.0 + 0.2316419 *
                        (-(phi_inv_pd + SQRT(R_correlation) * phi_inv_999)
                         / SQRT(1 - R_correlation))), 5)
                )
        END AS phi_of_basel_z,

        LGD, R_correlation
    FROM basel_capital
),

basel_output AS (
    SELECT
        vintage_quarter,
        pd_12m,
        EAD,
        phi_of_basel_z AS conditional_pd,
        /* K = LGD · [Φ(basel_z) - PD]  (per-dollar capital requirement) */
        LGD * (phi_of_basel_z - pd_12m) AS K_per_dollar,
        /* Total capital required = K · EAD */
        LGD * (phi_of_basel_z - pd_12m) * EAD AS capital_required,
        /* Risk-weighted assets = K · 12.5 · EAD (Basel minimum ratio 8%) */
        LGD * (phi_of_basel_z - pd_12m) * 12.5 * EAD AS RWA,
        /* Risk weight % (for comparison with 35% standardized residential) */
        LGD * (phi_of_basel_z - pd_12m) * 12.5 * 100 AS risk_weight_pct
    FROM basel_capital_final
)


/* ============================================================================
   UNIFIED DASHBOARD OUTPUT
   Each analysis keyed by `section`.
============================================================================ */

SELECT
    '01_KM_SURVIVAL' AS section,
    CAST(vintage_quarter AS VARCHAR)         AS dim_a,
    CAST(months_on_book AS VARCHAR)          AS dim_b,
    NULL                                     AS dim_c,
    ROUND(hazard_rate, 6)                    AS metric_1,
    ROUND(survival_prob, 6)                  AS metric_2,
    ROUND(ci_lower_95, 6)                    AS metric_3,
    ROUND(ci_upper_95, 6)                    AS metric_4,
    ROUND(annualized_CDR, 6)                 AS metric_5,
    CAST(n_at_risk AS FLOAT)                 AS metric_6
FROM km_with_ci

UNION ALL

SELECT '02_NELSON_AALEN',
       CAST(vintage_quarter AS VARCHAR),
       CAST(months_on_book AS VARCHAR),
       NULL,
       ROUND(nelson_aalen_H, 6),
       ROUND(NA_implied_survival, 6),
       ROUND(NA_H_lower, 6),
       ROUND(NA_H_upper, 6),
       ROUND(survival_prob, 6),   -- KM survival for direct comparison
       CAST(n_at_risk AS FLOAT)
FROM km_with_ci

UNION ALL

SELECT '03_LOG_RANK_TEST',
       CAST(vintage_quarter AS VARCHAR),
       p_value_band,
       NULL,
       ROUND(chi_square, 4),
       ROUND(z_score, 4),
       ROUND(O, 4),
       ROUND(E, 4),
       ROUND(V, 4),
       NULL
FROM log_rank_result

UNION ALL

SELECT '04_COMPETING_RISKS_CIF',
       NULL,
       CAST(t AS VARCHAR),
       NULL,
       ROUND(CIF_default, 6),
       ROUND(CIF_prepay, 6),
       ROUND(overall_S, 6),
       ROUND(CIF_default + CIF_prepay + overall_S, 6),   -- sanity: should = 1.0
       CAST(d_default AS FLOAT),
       CAST(d_prepay AS FLOAT)
FROM cumulative_incidence

UNION ALL

SELECT '05_KS_STATISTIC',
       discrimination_quality,
       CAST(KS_score_point AS VARCHAR),
       NULL,
       ROUND(KS, 6),
       NULL, NULL, NULL, NULL, NULL
FROM ks_statistic

UNION ALL

SELECT '06_KS_DISTRIBUTION',
       NULL,
       CAST(score AS VARCHAR),
       NULL,
       ROUND(F_bad, 6),
       ROUND(F_good, 6),
       ROUND(distance, 6),
       NULL, NULL, NULL
FROM ks_distances

UNION ALL

SELECT '07_GINI_LORENZ',
       NULL,
       'SUMMARY',
       NULL,
       ROUND(gini_coefficient, 6),
       CAST(n_loans AS FLOAT),
       CAST(portfolio_total AS FLOAT),
       NULL, NULL, NULL
FROM gini_result

UNION ALL

SELECT '08_LORENZ_CURVE',
       NULL,
       CAST(decile AS VARCHAR),
       NULL,
       ROUND(pct_loans, 6),
       ROUND(pct_balance, 6),
       NULL, NULL, NULL, NULL
FROM lorenz_curve

UNION ALL

SELECT '09_CRAMERS_V',
       interpretation,
       NULL,
       NULL,
       ROUND(cramers_v, 6),
       ROUND(chi_square_total, 4),
       CAST(r AS FLOAT),
       CAST(c AS FLOAT),
       CAST(n AS FLOAT),
       NULL
FROM cramers_v_result

UNION ALL

SELECT '10_CONTINGENCY_TABLE',
       CAST(vintage_quarter AS VARCHAR),
       severity_bucket,
       NULL,
       CAST(observed AS FLOAT),
       ROUND(expected, 4),
       ROUND(chi_sq_contribution, 4),
       NULL, NULL, NULL
FROM chi_square_cells

UNION ALL

SELECT '11_ROLL_RATES_WILSON',
       from_state, to_state, NULL,
       ROUND(p_hat, 6),
       ROUND(wilson_lower, 6),
       ROUND(wilson_upper, 6),
       CAST(transitions AS FLOAT),
       CAST(total_from AS FLOAT),
       NULL
FROM roll_rate_with_wilson

UNION ALL

SELECT '12_VINTAGE_CURVE',
       CAST(vintage_quarter AS VARCHAR),
       CAST(mob AS VARCHAR),
       CAST(vintage_rank AS VARCHAR),
       ROUND(cumul_default_rate_pct, 4),
       ROUND(portfolio_avg_pct, 4),
       ROUND(deviation_bps, 2),
       CAST(loans_observed_at_mob AS FLOAT),
       CAST(loans_ever_defaulted_by_mob AS FLOAT),
       NULL
FROM vintage_curve

UNION ALL

SELECT '13_HAZARD_SMOOTHED',
       NULL,
       CAST(mob AS VARCHAR),
       NULL,
       ROUND(raw_hazard, 6),
       ROUND(smoothed_3mo, 6),
       ROUND(ewma_hazard, 6),
       CAST(new_defaults AS FLOAT),
       CAST(loans_at_mob AS FLOAT),
       NULL
FROM hazard_curve

UNION ALL

SELECT '14_SPEARMAN_RHO',
       'peak_dpd vs max_upb',
       NULL, NULL,
       ROUND(spearman_rho, 6),
       CAST(n AS FLOAT),
       ROUND(sum_d_sq, 2),
       NULL, NULL, NULL
FROM spearman

UNION ALL

SELECT '15_ROBUST_OUTLIERS',
       CAST(loan_id AS VARCHAR),
       NULL, NULL,
       CAST(peak_dpd AS FLOAT),
       med_dpd,
       mad_dpd,
       ROUND(robust_z, 4),
       NULL, NULL
FROM robust_z_scores
WHERE ABS(robust_z) > 2.5

UNION ALL

SELECT '16_MULTIDIM_ROLLUP',
       vintage_label,
       severity_label,
       quintile_label,
       ROUND(foreclosure_rate_pct, 4),
       CAST(loan_count AS FLOAT),
       CAST(foreclosures AS FLOAT),
       CAST(total_upb AS FLOAT),
       CAST(rollup_level AS FLOAT),
       NULL
FROM risk_rollup

UNION ALL

SELECT '17_HARRELLS_C',
       discrimination_band,
       'max_upb vs time_to_default',
       NULL,
       ROUND(c_index, 6),
       CAST(n_comparable_pairs AS FLOAT),
       ROUND(n_concordant_weighted, 2),
       NULL, NULL, NULL
FROM c_statistic

UNION ALL

SELECT '19_WOE_BINS',
       CAST(upb_decile AS VARCHAR),
       CAST(bin_lower AS VARCHAR),
       CAST(bin_upper AS VARCHAR),
       ROUND(woe, 6),
       ROUND(iv_contribution, 6),
       CAST(n_good AS FLOAT),
       CAST(n_bad AS FLOAT),
       ROUND(pct_good, 6),
       ROUND(pct_bad, 6)
FROM woe_calc

UNION ALL

SELECT '20_IV_SUMMARY',
       iv_interpretation,
       'max_upb → foreclosure',
       NULL,
       ROUND(total_iv, 6),
       NULL, NULL, NULL, NULL, NULL
FROM iv_summary

UNION ALL

SELECT '21_RMST',
       CAST(vintage_quarter AS VARCHAR),
       NULL, NULL,
       ROUND(RMST_months, 4),
       ROUND(trapezoidal_area, 4),
       ROUND(pre_event_width, 4),
       CAST(tau_horizon AS FLOAT),
       NULL, NULL
FROM rmst_by_vintage

UNION ALL

SELECT '22_LOG_RANK_EXACT_P',
       CAST(vintage_quarter AS VARCHAR),
       NULL, NULL,
       ROUND(chi_square, 4),
       ROUND(p_value_exact, 8),
       ROUND(p_bh_raw, 8),
       ROUND(p_bh_adjusted, 8),
       CAST(p_rank AS FLOAT),
       CAST(n_tests AS FLOAT)
FROM log_rank_bh_adjusted

UNION ALL

SELECT '23_FDR_VERDICTS',
       CAST(vintage_quarter AS VARCHAR),
       fdr_verdict,
       NULL,
       ROUND(p_value_exact, 8),
       ROUND(p_bh_adjusted, 8),
       NULL, NULL, NULL, NULL
FROM log_rank_bh_adjusted

UNION ALL

SELECT '25_BASEL_IRB_CAPITAL',
       CAST(vintage_quarter AS VARCHAR),
       NULL, NULL,
       ROUND(pd_12m, 6),
       ROUND(conditional_pd, 6),
       ROUND(K_per_dollar, 6),
       ROUND(capital_required, 2),
       ROUND(RWA, 2),
       ROUND(risk_weight_pct, 4)
FROM basel_output

ORDER BY section, dim_a, dim_b, dim_c;


/* ============================================================================
   ============================================================================
   STATEMENT 18: DYNAMIC PIVOT — Vintage × MOB Default Matrix
   ----------------------------------------------------------------------------
   A rectangular matrix where rows are origination vintages and columns are
   Months-on-Book.  Each cell is the cumulative default rate for that cohort
   at that seasoning.  The column list is GENERATED AT RUNTIME from the data
   — no hardcoded MOB columns.

   This uses three advanced techniques together:
     1. Temp table materialization of CTE output
     2. STRING_AGG to build a comma-separated column list
     3. Dynamic SQL execution via sp_executesql with PIVOT

   Why it matters:  This is how credit analysts at Freddie/Fannie actually
   display vintage curves.  A long result set is worthless on a trading desk
   — you need the matrix.
   ============================================================================
============================================================================ */

IF OBJECT_ID('tempdb..#vintage_matrix') IS NOT NULL DROP TABLE #vintage_matrix;

/* Step 1: materialize vintage × MOB cumulative default rates */
;WITH lo AS (
    SELECT
        loan_id,
        MIN(as_of_date) AS orig_date,
        DATEFROMPARTS(YEAR(MIN(as_of_date)),
                      ((MONTH(MIN(as_of_date)) - 1) / 3) * 3 + 1, 1) AS vintage_q
    FROM dbo.loan_snapshots
    GROUP BY loan_id
),
ss AS (
    SELECT
        s.loan_id,
        lo.vintage_q,
        DATEDIFF(MONTH, lo.orig_date, s.as_of_date) AS mob,
        CASE WHEN s.dq_status IN ('60_DAY', '90_DAY', '120_DAY', 'FORECLOSURE')
             THEN 1 ELSE 0 END AS is_severe
    FROM dbo.loan_snapshots s
    INNER JOIN lo ON s.loan_id = lo.loan_id
),
vmx AS (
    SELECT
        vintage_q,
        mob,
        CAST(ROUND(
            CAST(COUNT(DISTINCT CASE WHEN is_severe = 1 THEN loan_id END) AS FLOAT)
            / NULLIF(COUNT(DISTINCT loan_id), 0) * 100, 2) AS DECIMAL(8,2)) AS cumul_pct
    FROM ss
    WHERE mob BETWEEN 0 AND 11
    GROUP BY vintage_q, mob
)
SELECT
    vintage_q,
    'MOB_' + RIGHT('00' + CAST(mob AS VARCHAR), 2) AS mob_col,
    cumul_pct
INTO #vintage_matrix
FROM vmx;

/* Step 2: build the dynamic column list */
DECLARE @cols NVARCHAR(MAX), @sql NVARCHAR(MAX);

SELECT @cols = STRING_AGG(col_expr, ', ') WITHIN GROUP (ORDER BY col_expr)
FROM (
    SELECT DISTINCT QUOTENAME(mob_col) AS col_expr
    FROM #vintage_matrix
) d;

/* Step 3: construct and execute the PIVOT */
SET @sql = N'
SELECT ''Vintage'' AS cohort,
       CONVERT(VARCHAR(10), vintage_q, 23) AS vintage_quarter,
       ' + @cols + N'
FROM (SELECT vintage_q, mob_col, cumul_pct FROM #vintage_matrix) src
PIVOT (MAX(cumul_pct) FOR mob_col IN (' + @cols + N')) p
ORDER BY vintage_q;';

PRINT N'-- Executing dynamic PIVOT with columns: ' + @cols;
EXEC sp_executesql @sql;

DROP TABLE #vintage_matrix;
