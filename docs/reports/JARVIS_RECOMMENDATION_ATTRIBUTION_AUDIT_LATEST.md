# JARVIS Recommendation Attribution Audit

Generated: `2026-09-12T04:43:24.563847+00:00`

> Scope: read-only DB attribution. No live/risk/kill-switch/.env/symbol-routing changes.

## Verdict

- Recommendation attribution proven: **True**
- Queue order-id attribution proven: **False**
- Edge verdict: positive all-time linked ledger, but not enough to prove current recommendation edge without durable pipeline/queue linkage and baseline comparison
- Caveat: pipeline_approval_queue.order_id still does not match paper_trades.trade_id/idempotency_key

## Linkage summary

| paper_rows | pending_trade_approvals | pipeline_approval_queue_rows | pending_approval_paper_trade_id_links | strategy_params_approval_id_links | unique_linked_paper_trades | unlinked_paper_trades | queue_order_id_matches_to_paper | linked_rth_paper_trades |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 120 | 373 | 896 | 1 | 61 | 62 | 58 | 0 | 20 |

## P&L statistics

| cohort | closed | pnl | wins | losses | win_rate | profit_factor | avg_trade | median_trade | best | worst | max_closed_trade_drawdown |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| all_paper | 91 | 3181.32 | 28 | 62 | 0.3077 | 1.4211 | 34.96 | -3.53 | 3173.0 | -1284.0 | -2533.19 |
| pending_approval_linked | 1 | 100.0 | 1 | 0 | 1.0 | inf | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 |
| strategy_param_linked | 41 | 4658.66 | 13 | 27 | 0.3171 | 2.3415 | 113.63 | -70.88 | 3173.0 | -1284.0 | -1981.7 |
| all_unique_linked | 42 | 4758.66 | 14 | 27 | 0.3333 | 2.3703 | 113.3 | -58.27 | 3173.0 | -1284.0 | -1981.7 |
| unlinked | 49 | -1577.34 | 14 | 35 | 0.2857 | 0.6136 | -32.19 | -2.5 | 659.75 | -1245.25 | -2349.78 |
| rth_linked | 18 | 1885.33 | 8 | 9 | 0.4444 | 5.9318 | 104.74 | 0.0 | 880.0 | -102.1 | -187.9 |
| queue_order_id_matched | 0 | 0 | 0 | 0 | None | None | None | None | None | None | 0.0 |

## Approval status counts

### pending_trade_approvals
| status | rows |
| --- | --- |
| rejected | 372 |
| approved | 1 |

### pipeline_approval_queue
| status | rows |
| --- | --- |
| expired | 509 |
| approved | 387 |

## Queue confidence buckets

| bucket | rows | approved | expired | rejected |
| --- | --- | --- | --- | --- |
| 0.40-0.59 | 8 | 3 | 5 | 0 |
| 0.60-0.79 | 401 | 134 | 267 | 0 |
| 0.80-1.00 | 487 | 250 | 237 | 0 |

## Queue by symbol/status

| symbol | status | rows | avg_confidence |
| --- | --- | --- | --- |
| MES | approved | 356 | 0.7780898876404494 |
| MES | expired | 333 | 0.7651051051051051 |
| MGC | approved | 31 | 0.7580645161290323 |
| MGC | expired | 176 | 0.7791477272727273 |

## Pipeline actions by symbol

| symbol | final_action | rows | avg_confidence | first_run | last_run |
| --- | --- | --- | --- | --- | --- |
| AAPL | buy | 116 | None | 2026-06-15T17:37:11 | 2026-08-04T01:04:42 |
| AAPL | hold | 2186 | None | 2026-04-06T14:01:02 | 2026-09-11T20:03:11 |
| AAPL | sell | 289 | None | 2026-05-08T17:29:32 | 2026-08-18T16:25:10 |
| MCL | buy | 60 | None | 2026-04-07T09:24:25 | 2026-04-23T02:21:45 |
| MCL | hold | 1033 | None | 2026-04-05T00:52:19 | 2026-05-08T17:00:00 |
| MCL | sell | 2 | None | 2026-04-22T02:19:57 | 2026-04-22T16:57:16 |
| MES | buy | 103 | None | 2026-05-22T14:55:55 | 2026-08-18T16:10:42 |
| MES | hold | 3439 | None | 2026-04-05T07:50:29 | 2026-09-11T20:03:10 |
| MES | sell | 398 | None | 2026-04-10T16:26:24 | 2026-08-18T18:31:51 |
| MES_VA30 | hold | 9 | None | 2026-07-16T13:33:15 | 2026-07-31T13:37:09 |
| MGC | buy | 266 | None | 2026-05-08T10:18:17 | 2026-08-03T19:57:15 |
| MGC | hold | 2376 | None | 2026-05-07T13:38:14 | 2026-09-11T20:03:11 |
| MGC | sell | 111 | None | 2026-05-08T18:09:00 | 2026-08-12T15:15:11 |
| MNQ | hold | 1089 | None | 2026-04-05T00:52:19 | 2026-05-08T17:00:00 |
| QQQ | buy | 126 | None | 2026-05-22T14:57:35 | 2026-08-11T19:15:45 |
| QQQ | hold | 2310 | None | 2026-04-06T14:01:08 | 2026-09-11T20:03:11 |
| QQQ | sell | 200 | None | 2026-04-10T17:02:36 | 2026-08-18T16:30:00 |
| SPY | buy | 66 | None | 2026-06-15T19:02:17 | 2026-08-06T02:02:09 |
| SPY | hold | 2507 | None | 2026-04-06T14:01:13 | 2026-09-11T20:03:11 |
| SPY | sell | 133 | None | 2026-05-08T19:01:50 | 2026-08-03T19:31:04 |
| TSLA | buy | 63 | None | 2026-06-15T23:04:28 | 2026-08-04T01:04:46 |
| TSLA | hold | 1303 | None | 2026-06-15T20:21:30 | 2026-09-11T20:03:11 |
| TSLA | sell | 64 | None | 2026-06-18T14:08:27 | 2026-08-18T16:24:55 |

## Recent linked paper trades

| trade_id | symbol | side | entry_time | exit_time | pnl | status | strategy_id | quote_source | strategy_approval_id |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 35d9093e-cbee-4131-a9c6-13fb44f96811 | MGC | buy | 2026-07-31T06:29:16.516612+00:00 | 2026-07-31T08:22:09.069549+00:00 | -84.91200000000299 | closed | LONG_GAP_FILL | paper_simulator | 43408419-076e-4f46-b214-2e9c17e76764 |
| f1a53246-f4bf-4afe-aea5-11092ae9118d | MGC | buy | 2026-07-31T10:50:02.179928+00:00 | 2026-07-31T13:17:03.258622+00:00 | -84.76599999999871 | closed | LONG_GAP_FILL | paper_simulator | ea1266e1-53d5-4cf9-91ec-84954e0f0aa4 |
| d3fac269-08ea-436a-9a57-6dbfda939e30 | MGC | buy | 2026-07-31T13:52:03.186250+00:00 | 2026-07-31T14:11:34.627997+00:00 | -79.11700000000019 | closed | LONG_GAP_FILL | paper_simulator | 5083c77c-2848-4cdf-938c-994e211feff0 |
| 76eba8a2-0e07-4ca3-bd37-7654b1c3b141 | MES | buy | 2026-07-31T14:52:11.473217+00:00 | 2026-07-31T20:45:00.393827+00:00 | 277.25 | closed | LONG_MOMENTUM | paper_simulator | b041b500-a0f0-434a-a4cb-d3bd37bc0da7 |
| 73665367-1552-439c-9d7c-85533282e940 | MGC | buy | 2026-07-31T14:52:21.119624+00:00 | 2026-07-31T20:45:00.367351+00:00 | 77.50000000000091 | closed | LONG_GAP_FILL | paper_simulator | da49c20f-785d-4aac-b50f-0374e322aa8e |
| 2ddd5554-b7ef-4c40-a784-ac00dcb2f545 | MGC | buy | 2026-08-03T01:42:09.096735+00:00 | 2026-08-03T01:44:03 | -85.07100000000173 | closed | LONG_GAP_FILL | paper_simulator | 41dacaaf-953e-4faf-9a5a-7adbaa95e39f |
| 93584ad5-f5a6-4f3c-be0f-fc385c9868e9 | MGC | buy | 2026-08-03T01:56:48.922349+00:00 | 2026-08-03T02:06:49 | -85.07100000000173 | closed | LONG_GAP_FILL | paper_simulator | 4fb00c17-6eb3-42fc-9270-92b79cbf1e4e |
| f62eacd3-6fa8-4635-af7f-f2d2a668f38c | MGC | buy | 2026-08-03T02:08:06.695614+00:00 | 2026-08-03T02:11:48 | -85.07100000000173 | closed | LONG_GAP_FILL | paper_simulator | 279c5730-de3b-4f22-ae4a-c167d0269443 |
| 8a286d9d-a3ef-47a7-ab0e-45ef87efd6e3 | MGC | buy | 2026-08-03T02:42:38.933422+00:00 | 2026-08-03T02:46:48 | -79.10200000000168 | closed | LONG_GAP_FILL | paper_simulator | 5849ce2a-751f-4826-a212-340da448ed82 |
| 6dedc690-3d8d-431d-ad96-332b2684e82b | MGC | buy | 2026-08-03T02:51:24.992457+00:00 | 2026-08-03T02:56:48 | -79.10200000000168 | closed | LONG_GAP_FILL | paper_simulator | 0b350cb3-842b-4c29-88f2-b3c4c730a489 |
| debf2a4c-f099-4fb1-aace-f597f11f5e25 | MGC | buy | 2026-08-03T03:12:50.907492+00:00 | 2026-08-03T03:16:48 | -79.10200000000168 | closed | LONG_GAP_FILL | paper_simulator | 9cb0f1d1-3ee2-493a-aab2-00eafe0c4182 |
| 43394ed2-34c2-43e0-843f-22a631500147 | MGC | buy | 2026-08-03T08:56:20.148898+00:00 | 2026-08-03T10:13:00.923863+00:00 | -58.27099999999882 | closed | LONG_GAP_FILL | paper_simulator | 20fad592-e527-4259-b623-601f2a3872fe |
| 3e143a8a-c977-4acb-8e5b-51033afa388c | MES | buy | 2026-08-03T16:07:48.461717+00:00 | 2026-08-03T20:45:02.459669+00:00 | 209.5 | closed | LONG_MOMENTUM | legacy_unbackfilled | 79256598-3c83-4c5f-b412-3368af8ffd82 |
| 9060f589-aaac-45b1-8fd1-5651ca9bbe53 | AAPL | buy | 2026-08-03T16:08:17.579271+00:00 | 2026-08-18T20:45:03.151069+00:00 | 2.439992675781241 | closed | LONG_MOMENTUM | legacy_unbackfilled | 3349d2f7-e11d-40f8-bc23-82b18e12511f |
| 437d5360-515e-4597-b75b-c0dfd1b1e5d4 | TSLA | buy | 2026-08-03T16:08:18.768118+00:00 | 2026-08-17T05:05:41.314040+00:00 | -7.737799999999993 | closed | LONG_MOMENTUM | legacy_unbackfilled | 90468137-dc8d-4096-915f-83684d2a4f38 |
| 120cb2f8-2d9e-47d8-b56d-279e356bdfdb | QQQ | buy | 2026-08-03T18:05:41.454232+00:00 | 2026-08-17T05:05:40.962905+00:00 | -8.489399999999932 | closed | LONG_MOMENTUM | legacy_unbackfilled | a6c38a9b-28b3-40e8-ae0c-fbe95a7a4dfb |
| da9ba79a-eadc-48c6-b468-f60c8a7dab4d | MGC | buy | 2026-08-03T19:57:18.665068+00:00 | 2026-08-03T20:45:02.433987+00:00 | -16.5 | closed | LONG_GAP_FILL | legacy_unbackfilled | 612ed996-8a57-4480-a6d2-57681b8092e5 |
| 7a51f8a4-4763-4207-97b5-ce05c5416d49 | SPY | buy | 2026-08-03T19:57:29.141431+00:00 | 2026-08-18T20:45:03.116453+00:00 | 13.16998291015625 | closed | LONG_MOMENTUM | legacy_unbackfilled | 31788092-6d7f-40f6-86a5-bc39d865c110 |
| 3083f899-a8a2-42db-ac35-8155e43617c7 | MES | buy | 2026-08-05T15:56:49.009789+00:00 | 2026-08-05T16:18:39.389185+00:00 | -80.82650000000194 | closed | LONG_MOMENTUM | legacy_unbackfilled | d6873f08-4819-4d59-9605-7334e3014724 |
| 9d8db8fa-18a2-4dda-b0fe-d60b81ff49a9 | MES | buy | 2026-08-05T16:57:59.410811+00:00 | 2026-08-05T20:13:11.707315+00:00 | -80.82650000000194 | closed | LONG_MOMENTUM | legacy_unbackfilled | d092f5fe-e3a2-495f-88a6-be770da63b12 |
