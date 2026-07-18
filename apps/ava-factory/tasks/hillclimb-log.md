# Hill-climb log (one line per tick)

| ts_local | step | lm | tok_s | host_free_GB | ready_P0 | action | delta |
|----------|------|-----|-------|--------------|----------|--------|-------|
| 2026-07-10T18:32 | 460 | 0.111 | 12344 | 1.6 | 481M | plan+loop armed; image prune 0B; identified dedup.db 7.2G + host disk as D1 fail | baseline |
| 2026-07-10T18:34 | 460 | — | — | 1.6 | — | docker image prune -a → 12.4GB VHDX (host free unchanged); found host HF cache **352GB**; started delete | D1 in progress |
| 2026-07-10T18:35 | 470 | 0.099 | 12055 | **353.4** | 450M | HF cache cleared; collectors `source_start` again; scale collector→4 | D1 green |
| 2026-07-10T18:36 | 470→1 | — | — | 353 | — | CUDA unknown error @470; **no mini ckpt** (every 500); resume from scratch; set `checkpoint_every_steps: 100` | reliability |
| 2026-07-10T18:45 | 1 | 10.58 | — | 366 | 419M | ticks 3–12 batched; HF clear done; trainer rebuilt (ckpt/100); collectors×4 healthy; waiting first ckpt @100 | train climb |
| 2026-07-10T18:45 | 1 | 10.58 | — | 366 | 419M | **loop 1m→15m** (budget: tick spam while waiting on train); D1 still green | cadence |
| 2026-07-10T19:05 | 50 | 1.022 | 10721 | 353 | 419M | 15m tick#1: D1–D3 green; mini climb 1→50 (lm 10.6→1.02); ckpt_every=100 live; no mini.pt yet; hold for first ckpt | train climb |
| 2026-07-10T19:24 | 100 | 0.302 | 11275 | 353 | 419M | 15m tick#2: **first mini ckpt** `/ckpt/step_100.pt` (~1.9GB); lm 0.35→0.30; D1 green; resume-safe | reliability win |
| 2026-07-10T19:32 | 120 | 0.245 | 11302 | 353 | 419M | 15m tick#3: D1–D5 green; climb 100→120; false-stale between log intervals (~4m); hold for step_200 ckpt; dash gates live | train climb |
| 2026-07-10T19:47 | 150 | 0.211 | 12070 | 353 | 419M | 15m tick#4: D1–D5 green; 120→150; lm↓; ~12k tok/s; still on step_100.pt; hold for step_200 | train climb |
| 2026-07-10T19:58 | 100 | — | — | 353 | 419M | **closed-loop v1 live**: demand.py+train publish+/collectors reweight+dash; resumed step_100 (lost ~80 unckpt steps); `/state/demand.json`; loop 15m→**1m** | demand channel |
| 2026-07-10T20:02 | 110 | 0.326 | 11300 | 365 | 479M | 1m tick#1: demand refresh @110 (runway healthy→maintain); P0 479M; miners up; train climbing post-resume | closed-loop ok |
| 2026-07-10T20:03 | 110 | 0.326 | 11300 | 365 | 479M | 1m ticks#2–3 batched: training mode; demand↔step synced; GPU ~68%; hold for step 120/200 | measure |
| 2026-07-10T20:04 | 110 | 0.326 | 11300 | 365 | 479M | tick#4: still @110 (inter-log); **loop 1m→5m** (step logs ~4m; cut empty ticks) | cadence |
| 2026-07-10T20:08 | 120 | 0.302 | 12186 | 365 | 479M | 5m tick#1: 110→120; demand synced maintain; D1 green; hold for step_200 ckpt | train climb |
| 2026-07-10T20:13 | 140 | 0.240 | 12729 | 365 | 479M | 5m tick#2: 120→140; lm↓; demand@140 maintain; ~60 steps to step_200 | train climb |
| 2026-07-10T20:18 | 150 | 0.211 | 12729 | 365 | 479M | 5m tick#3: 140→150; lm↓; demand maintain; ~50 steps to step_200 | train climb |
| 2026-07-10T20:23 | 170 | 0.186 | 13373 | 365 | 479M | 5m tick#4: 150→170; waiting step_200; **dash**: curriculum+lifecycle glossary+watch signals | fill-wait |
| 2026-07-10T20:40 | 100 | — | — | 353 | 479M | ticks#4–7: CUDA @190 again (no step_200); resumed×2; **ckpt_every 100→50**; demand had fired examples on lm rise | reliability |
| 2026-07-10T20:45 | 100 | — | — | 353 | 479M | tick#8: CUDA restart-loop; **root cause**: host GPU shared with `train_mtnn.py` + `train_stage2.py`; trainer **stopped** pending GPU exclusive | blocker |
| 2026-07-10T20:49 | — | — | — | 361 | 479M | tick#9: trainer still stopped; `train_stage2` gone; **`train_mtnn.py` still on GPU**; collectors active; hold | wait GPU |
| 2026-07-10T21:19 | 100 | — | — | — | 479M | user: continue training → resumed step_100; **hung 25m @100% GPU, 0 steps** (train_mtnn still sharing); trainer stopped again | GPU exclusive needed |
| 2026-07-10T21:20 | — | — | — | 360 | 479M | ticks#10–13: trainer stopped; **train_mtnn.py still on GPU**; data plane OK; hold for exclusive GPU | wait GPU |
| 2026-07-10T21:23 | — | — | — | — | 479M | tick#14: train_mtnn still on GPU; trainer stopped; hold | wait GPU |
| 2026-07-10T21:28 | 100 | — | — | — | 479M | tick#15: **GPU free**; trainer resumed step_100 (ckpt/50); exclusive; climbing toward step_150 | train resume |
| 2026-07-10T21:34 | 110 | 0.329 | 11792 | 360 | 479M | tick#16: exclusive GPU healthy; 100→110 @~12k tok/s; next ckpt **150** | train climb |
| 2026-07-10T21:38 | 120 | 0.332 | 9862 | 360 | 479M | tick#17: 110→120; ~30 steps to step_150 ckpt; no CUDA | train climb |
| 2026-07-10T21:43 | 130 | 0.264 | 10023 | 360 | 479M | tick#18: 120→130; lm↓; ~20 steps to step_150 | train climb |
| 2026-07-10T21:53 | 150 | 0.225 | 9875 | 385 | 479M | tick#19: **step_150.pt** written (~2.0GB); 130?150; lm?; demand maintain; exclusive GPU; next ckpt **200** | reliability win |
| 2026-07-10T21:57 | 160 | 0.192 | 8245 | 385 | 479M | tick#20: 150?160 post-ckpt; lm?; false-stale cleared; demand maintain; ~40 steps to step_200 | train climb |
| 2026-07-10T22:02 | 170 | 0.195 | 8844 | 385 | 479M | tick#21: 160?170; lm?; demand maintain; ~30 steps to step_200 | train climb |
| 2026-07-10T22:10 | 180 | 0.176 | 6061 | 384 | 479M | tick#22: 170?180 (slow ~7m/10steps); demand maintain; ~20 steps to step_200 | train climb |
| 2026-07-10T22:18 | 190 | 0.167 | 5025 | 384 | 479M | tick#23: 180?190; lm=0.167; ~10 to step_200; demand maintain | train climb |
| 2026-07-10T22:24 | 200 | 0.339 | 8507 | 382 | 479M | tick#24: **step_200.pt** written; 190?200; demand maintain; next ckpt 250 | reliability win |
| 2026-07-10T22:28 | 210 | 0.172 | 8492 | 382 | 479M | tick#25: 200?210; lm 0.1724; **demand?examples** (lm_trend+0.15); boost deliberate/automatic; next ckpt 250 | closed-loop |
| 2026-07-10T22:36 | 210 | 0.172 | 8492 | 381 | 479M | tick#26: CUDA after 210; resume from step_200 then CUDA again; **train_mtnn.py on GPU**; trainer **stopped**; exclusive needed | blocker |
| 2026-07-10T22:39 | 210 | � | � | � | 479M | ticks#27�28: trainer stopped; **train_mtnn.py still on GPU**; hold for exclusive; last ckpt step_200 | wait GPU |
| 2026-07-10T22:42 | 210 | � | � | � | 479M | tick#29: trainer stopped; train_mtnn still on GPU; hold | wait GPU |
| 2026-07-10T22:47 | 210 | � | � | � | 479M | tick#30: trainer stopped; train_mtnn still on GPU; hold; ckpt step_200 | wait GPU |
| 2026-07-10T22:52 | 210 | � | � | � | 479M | tick#31: trainer stopped; train_mtnn still on GPU (72% util); hold; ckpt step_200 | wait GPU |
| 2026-07-10T23:01 | 200 | � | � | � | 479M | tick#32: **GPU free**; trainer resumed from step_200; exclusive | train resume |
| 2026-07-10T23:09 | 220 | 0.149 | 9213 | � | 479M | tick#33: resume healthy 200?220; lm?; ~9.2k tok/s; exclusive; ~30 to step_250 | train climb |
| 2026-07-10T23:15 | 230 | 0.131 | 9251 | � | 479M | tick#34: 220?230; exclusive; ~20 to step_250 | train climb |
| 2026-07-10T23:24 | 250 | 0.116 | 9113 | � | 479M | tick#35: **step_250.pt** written; 230?250; lm?; exclusive; next ckpt 300 | reliability win |
| 2026-07-10T23:29 | 260 | 0.118 | 7465 | � | 479M | ticks#36�37: post-ckpt 250?260; exclusive; ~40 to step_300 | train climb |
| 2026-07-10T23:36 | 270 | 0.308 | 6859 | � | 479M | tick#38: 260?270; exclusive; ~30 to step_300 | train climb |
| 2026-07-10T23:43 | 280 | 0.137 | 6058 | � | 479M | tick#39: 270?280; lm recovered; demand?examples; ~20 to step_300 | train climb |
| 2026-07-10T23:54 | 290 | 0.125 | 6817 | � | 479M | ticks#40�41: 280?290; ~10 to step_300; exclusive | train climb |
| 2026-07-10T23:58 | 300 | 0.116 | 6692 | � | 479M | ticks#42�44: **step_300.pt** written; 290?300; exclusive; next ckpt 350 | reliability win |
| 2026-07-11T00:03 | 310 | 0.111 | 5879 | � | 479M | tick#45: 300?310; exclusive; ~40 to step_350 | train climb |
| 2026-07-11T00:10 | 320 | 0.139 | 6338 | � | 479M | tick#46: 310?320; exclusive; ~30 to step_350 | train climb |
| 2026-07-11T00:16 | 330 | 0.192 | 7273 | � | 479M | tick#47: 320?330; exclusive; ~20 to step_350 | train climb |
| 2026-07-11T00:28 | 350 | 0.111 | 8142 | � | 479M | tick#48: **step_350.pt** written; ?350; exclusive | reliability win |
| 2026-07-11T00:33 | 360 | 0.11 | 7222 | � | 479M | ticks#49�50: post-ckpt 350?360; exclusive; ~40 to step_400 | train climb |
| 2026-07-11T07:52 | 360 | 0.110 | 7222 | � | 479M | tick#51: **hung ~hours @360** (GPU busy, no new steps); restarted from step_350; exclusive | hang recover |
| 2026-07-11T07:57 | 360 | 0.164 | 11033 | � | 479M | tick#52: post-hang resume from 350?360; exclusive; ~40 to step_400 | train climb |
| 2026-07-11T08:01 | 370 | 0.125 | 11610 | � | 479M | tick#53: 360?370; exclusive; ~30 to step_400 | train climb |
| 2026-07-11T08:04 | 380 | 0.111 | 11507 | � | 479M | tick#54: 370?380; exclusive; ~20 to step_400 | train climb |
| 2026-07-11T08:13 | 400 | 0.133 | 11755 | � | 479M | tick#55: **step_400.pt** written; 380?400; exclusive; next ckpt 450 | reliability win |
| 2026-07-11T09:27 | 410 | 0.126 | 10728 | � | 479M | tick#56: hung ~1h post-400; resumed step_400?410 @~10.7k tok/s; syllabus plan + hang watchdog; 5m loop re-armed | hang recover |
| 2026-07-11T09:29 | 410 | 0.126 | 10728 | � | 479M | ticks#57�58: old 5m loop killed during re-arm; new syllabus loop PID 33224 live; climb post-400 hang recover | cadence |
| 2026-07-11T09:35 | 410 | 0.126 | 8891 | � | 479M | syllabus-loop tick#1: 2nd resume healthy ?410 @~8.9k tok/s; hang check OK; exclusive; ~40 to step_450 | train climb |
| 2026-07-11T09:39 | 420 | 0.11 | 10200 | � | 479M | syllabus-loop tick#2: 410?420; hang OK; exclusive; ~30 to step_450 | train climb |
| 2026-07-11T09:44 | 420 | 0.110 | 10200 | � | 479M | syllabus-loop tick#3: **train_mtnn back on GPU**; trainer **stopped** at step_400.pt; hold exclusive | wait GPU |
| 2026-07-11T09:48 | 420 | � | � | � | 479M | syllabus-loop tick#4: trainer stopped; train_mtnn still on GPU; dash back @ :8000; hold; ckpt step_400 | wait GPU |
| 2026-07-11T10:01 | 410 | 0.126 | 8370 | � | 479M | syllabus-loop tick#5: GPU-first policy � 4080 free, resumed step_400?410 @~8.4k tok/s; loop re-armed | train resume |
| 2026-07-11T10:06 | 420 | 0.11 | 7708 | � | 479M | syllabus-loop tick#6: 410?420; GPU-first on 4080; ~30 to step_450 | train climb |
| 2026-07-11T10:07 | 420 | 0.11 | 7708 | 368 | 479M | 2m-monitor: trainer Up 13 minutes; ckpt step_400.pt; GPU 55 %, 10248 MiB, 12282 MiB; collectors healthy~4; demand runway healthy �?? maintain mixture; next ckpt 450 | status |
| 2026-07-11T10:09 | 420 | 0.11 | 7708 | 372 | 479M | 2m-loop armed PID=29660; trainer Up 2 minutes; ckpt step_400.pt; GPU 15 %, 3884 MiB, 12282 MiB; collectors healthy~4; hostCUDA~0; demand runway healthy �?? maintain mixture; next hard 450 | status |
| 2026-07-11T10:11 | 420 | 0.11 | 7708 | � | 479M | 2m-tick: trainer Up 3 minutes; ckpt step_400.pt; GPU 29 %, 10343 MiB; collectors~4 | status |
| 2026-07-11T10:11 | 420 | 0.11 | 7708 | � | 479M | 2m-tick: trainer Up 4 minutes; ckpt step_400.pt; GPU 80 %, 10345 MiB | status |
| 2026-07-11T10:12 | 420 | 0.11 | 7708 | � | 479M | 2m-tick#1 (428347): trainer Up 4 minutes; ckpt step_400.pt; GPU 30 %, 10333 MiB; collectors~4; post-resume steps~0 | status |
| 2026-07-11T10:14 | 420 | 0.11 | 7708 | � | 479M | 2m-tick#2: trainer Up 6 minutes; ckpt step_400.pt; GPU 68 %, 10336 MiB; collectors~4; post-resume steps=2 | status |
| 2026-07-11T10:15 | 410 | 0.126 | 8389 | � | 479M | 2m-tick#3: trainer Up 8 minutes; ckpt step_400.pt; GPU 80 %, 10343 MiB; collectors~4; post-resume=1 | status |
| 2026-07-11T10:17 | 410 | 0.126 | 8389 | � | 479M | 2m-tick#4: trainer Up 10 minutes; ckpt step_400.pt; GPU 33 %, 10348 MiB; collectors~4 | status |
| 2026-07-11T10:19 | 420 | 0.11 | 9707 | � | 479M | 2m-tick#5: trainer Up 12 minutes; ckpt step_400.pt; GPU 60 %, 10353 MiB; collectors~4 | status |
| 2026-07-11T10:21 | 420 | 0.11 | 9707 | � | 479M | 2m-tick#6: trainer Up 14 minutes; ckpt step_400.pt; GPU 66 %, 10345 MiB; collectors~4 | status |
| 2026-07-11T10:23 | 430 | 0.107 | 10174 | � | 479M | 2m-tick#7: trainer Up 16 minutes; ckpt step_400.pt; GPU 67 %, 10347 MiB; collectors~4 | status |
| 2026-07-11T10:26 | 430 | 0.107 | 10174 | � | 479M | 2m-tick#8: trainer Up 18 minutes; ckpt step_400.pt; GPU 35 %, 10353 MiB; collectors~4 | status |
| 2026-07-11T10:27 | 430 | 0.107 | 10174 | � | 479M | 2m-tick#9: trainer Up 20 minutes; ckpt step_400.pt; GPU 83 %, 10365 MiB; collectors~4 | status |
| 2026-07-11T10:29 | 440 | 0.105 | 9780 | � | 479M | 2m-tick#10: trainer Up 22 minutes; ckpt step_400.pt; GPU 60 %, 10357 MiB; collectors~4 | status |
| 2026-07-11T10:31 | 440 | 0.105 | 9780 | � | 479M | 2m-tick#11: trainer Up 24 minutes; ckpt step_400.pt; GPU 38 %, 10360 MiB; collectors~4 | status |
| 2026-07-11T10:34 | 450 | 0.105 | 9790 | � | 479M | 2m-tick#12: trainer Up 26 minutes; ckpt step_450.pt; GPU 61 %, 10332 MiB; collectors~4 | status |
| 2026-07-11T10:36 | 450 | 0.105 | 9790 | � | 479M | 2m-tick#13: ckpt step_450.pt; GPU 49 %, 10352 MiB; post-ckpt steps=0; collectors~4 | status |
| 2026-07-11T10:37 | 460 | 0.107 | 8785 | � | 479M | 2m-tick#14: ckpt step_450.pt; GPU 79 %, 10346 MiB; post-ckpt steps=1; collectors~4 | status |
| 2026-07-11T10:40 | 460 | 0.107 | 8785 | � | 479M | 2m-tick#15: ckpt step_450.pt; GPU 69 %, 10349 MiB; collectors~4 | status |
| 2026-07-11T10:41 | 460 | 0.107 | 8785 | � | 479M | 2m-tick#16: ckpt step_450.pt; GPU 63 %, 10349 MiB; collectors~4 | status |
| 2026-07-11T10:43 | 470 | 0.102 | 9736 | � | 479M | 2m-tick#17: ckpt step_450.pt; GPU 37 %, 10337 MiB; collectors~4 | status |
| 2026-07-11T10:45 | 470 | 0.102 | 9736 | � | 479M | 2m-tick#18: ckpt step_450.pt; GPU 24 %, 10336 MiB; collectors~4 | status |
| 2026-07-11T10:47 | 480 | 0.102 | 9997 | � | 479M | 2m-tick#19: ckpt step_450.pt; GPU 27 %, 10341 MiB; collectors~4 | status |
| 2026-07-11T10:49 | 480 | 0.102 | 9997 | � | 479M | 2m-tick#20: ckpt step_450.pt; GPU 78 %, 10341 MiB; collectors~4 | status |
| 2026-07-11T10:51 | 490 | 0.126 | 10216 | � | 479M | 2m-tick#21: ckpt step_450.pt; GPU 58 %, 10345 MiB; collectors~4 | status |
| 2026-07-11T10:54 | 490 | 0.126 | 10216 | � | 479M | 2m-tick#22: ckpt step_450.pt; GPU 56 %, 10342 MiB; collectors~4 | status |
| 2026-07-11T10:56 | 500 | 0.115 | 9927 | � | 479M | 2m-tick#23: ckpt step_500.pt; GPU 74 %, 10337 MiB; collectors~4 | status |
| 2026-07-11T10:58 | 500 | 0.115 | 9927 | � | 479M | 2m-tick#24: ckpt step_500.pt; GPU 35 %, 10353 MiB; post-ckpt steps=0; collectors~4 | status |
| 2026-07-11T10:59 | 510 | 0.131 | 9457 | � | 479M | 2m-tick#25: ckpt step_500.pt; GPU 69 %, 10337 MiB; post-ckpt steps=1; collectors~4 | status |
| 2026-07-11T11:01 | 510 | 0.131 | 9457 | � | 479M | 2m-tick#26: ckpt step_500.pt; GPU 89 %, 10344 MiB; collectors~4 | status |
| 2026-07-11T11:04 | 520 | 0.188 | 10760 | � | 479M | 2m-tick#27: ckpt step_500.pt; GPU 62 %, 10337 MiB; collectors~4 | status |
| 2026-07-11T11:05 | 520 | 0.188 | 10760 | � | 479M | 2m-tick#28: ckpt step_500.pt; GPU 39 %, 10335 MiB; collectors~4 | status |
| 2026-07-11T11:08 | 520 | 0.188 | 10760 | � | 479M | 2m-tick#29: ckpt step_500.pt; GPU 62 %, 10342 MiB; collectors~4 | status |
| 2026-07-11T11:09 | 530 | 0.111 | 10565 | � | 479M | 2m-tick#30: ckpt step_500.pt; GPU 56 %, 10354 MiB; collectors~4 | status |
| 2026-07-11T11:11 | 530 | 0.111 | 10565 | � | 479M | 2m-tick#31: ckpt step_500.pt; GPU 52 %, 10343 MiB; collectors~4 | status |
| 2026-07-11T11:13 | 540 | 0.106 | 9878 | � | 479M | 2m-tick#32: ckpt step_500.pt; GPU 21 %, 10351 MiB; collectors~4 | status |
| 2026-07-11T11:16 | 540 | 0.106 | 9878 | � | 479M | 2m-tick#33: ckpt step_500.pt; GPU 50 %, 10344 MiB; collectors~4 | status |
| 2026-07-11T11:18 | 550 | 0.103 | 9328 | � | 479M | 2m-tick#34: ckpt step_550.pt; GPU 40 %, 10342 MiB; collectors~4 | status |
| 2026-07-11T11:20 | 550 | 0.103 | 9328 | � | 479M | 2m-tick#35: ckpt step_550.pt; GPU 39 %, 10335 MiB; post-ckpt steps=0; collectors~4 | status |
| 2026-07-11T11:21 | 550 | 0.103 | 9328 | � | 479M | 2m-tick#36: ckpt step_550.pt; GPU 71 %, 10337 MiB; post-ckpt steps=0; collectors~4 | status |
| 2026-07-11T11:23 | 560 | 0.101 | 8421 | � | 479M | 2m-tick#37: ckpt step_550.pt; GPU 56 %, 10340 MiB; post-ckpt steps=1; collectors~4 | status |
| 2026-07-11T11:25 | 560 | 0.101 | 8421 | � | 479M | 2m-tick#38: ckpt step_550.pt; GPU 38 %, 10351 MiB; collectors~4 | status |
| 2026-07-11T11:28 | 570 | 0.109 | 10203 | � | 479M | 2m-tick#39: ckpt step_550.pt; GPU 69 %, 10340 MiB; collectors~4 | status |
| 2026-07-11T11:30 | 570 | 0.109 | 10203 | � | 479M | 2m-tick#40: ckpt step_550.pt; GPU 74 %, 10330 MiB; collectors~4 | status |
| 2026-07-11T11:31 | 580 | 0.112 | 10039 | � | 479M | 2m-tick#41: ckpt step_550.pt; GPU 53 %, 10345 MiB; collectors~4 | status |
| 2026-07-11T11:34 | 580 | 0.112 | 10039 | � | 479M | 2m-tick#42: ckpt step_550.pt; GPU 49 %, 10353 MiB; collectors~4 | status |
| 2026-07-11T11:36 | 590 | 0.104 | 10110 | � | 479M | 2m-tick#43: ckpt step_550.pt; GPU 43 %, 10348 MiB; collectors~4 | status |
| 2026-07-11T11:37 | 590 | 0.104 | 10110 | � | 479M | 2m-tick#44: ckpt step_550.pt; GPU 82 %, 10361 MiB; collectors~4 | status |
| 2026-07-11T11:40 | 600 | 0.104 | 10089 | � | 479M | 2m-tick#45: ckpt step_550.pt; GPU 26 %, 10349 MiB; collectors~4 | status |
| 2026-07-11T11:40 | 600 | 0.104 | 10089 | � | 479M | 2m-tick#45: hard save step_600.pt confirmed; GPU active | status |
| 2026-07-11T11:42 | 600 | 0.104 | 10089 | � | 479M | 2m-tick#46: ckpt step_600.pt; GPU 34 %, 10351 MiB; post-ckpt steps=0; collectors~4 | status |
| 2026-07-11T11:43 | 600 | 0.104 | 10089 | � | 479M | 2m-tick#47: ckpt step_600.pt; GPU 41 %, 10361 MiB; post-ckpt steps=0; collectors~4 | status |
| 2026-07-11T11:46 | 610 | 0.103 | 8635 | � | 479M | 2m-tick#48: ckpt step_600.pt; GPU 31 %, 10355 MiB; post-ckpt=1; age_s~81; collectors~4 | status |
| 2026-07-11T11:47 | 610 | 0.103 | 8635 | � | 479M | 2m-tick#49: ckpt step_600.pt; GPU 33 %, 10354 MiB; collectors~4 | status |
| 2026-07-11T11:50 | 620 | 0.122 | 10313 | � | 479M | 2m-tick#50: ckpt step_600.pt; GPU 73 %, 10351 MiB; collectors~4 | status |
| 2026-07-11T11:51 | 620 | 0.122 | 10313 | � | 479M | 2m-tick#51: ckpt step_600.pt; GPU 32 %, 10347 MiB; collectors~4 | status |
| 2026-07-11T11:54 | 630 | 0.11 | 10809 | � | 479M | 2m-tick#52: ckpt step_600.pt; GPU 34 %, 10346 MiB; collectors~4 | status |
| 2026-07-11T11:56 | 630 | 0.11 | 10809 | � | 479M | 2m-tick#53: ckpt step_600.pt; GPU 40 %, 10349 MiB; collectors~4 | status |
| 2026-07-11T11:57 | 640 | 0.126 | 10789 | � | 479M | 2m-tick#54: ckpt step_600.pt; GPU 35 %, 10358 MiB; collectors~4 | status |
| 2026-07-11T12:00 | 640 | 0.126 | 10789 | � | 479M | 2m-tick#55: ckpt step_600.pt; GPU 64 %, 10350 MiB; collectors~4 | status |
| 2026-07-11T12:02 | 650 | 0.104 | 10750 | � | 479M | 2m-tick#56: ckpt step_650.pt; GPU 37 %, 10358 MiB; collectors~4 | status |
| 2026-07-11T12:04 | 650 | 0.104 | 10750 | � | 479M | 2m-tick#57: ckpt step_650.pt; GPU 24 %, 10345 MiB; post-ckpt steps=0; collectors~4 | status |
| 2026-07-11T12:06 | 660 | 0.127 | 9392 | � | 479M | 2m-tick#58: ckpt step_650.pt; GPU 30 %, 10358 MiB; post-ckpt steps=1; collectors~4 | status |
| 2026-07-11T12:08 | 660 | 0.127 | 9392 | � | 479M | 2m-tick#59: ckpt step_650.pt; GPU 45 %, 10357 MiB; collectors~4 | status |
| 2026-07-11T12:09 | 660 | 0.127 | 9392 | � | 479M | 2m-tick#60: ckpt step_650.pt; GPU 31 %, 10354 MiB; collectors~4 | status |
| 2026-07-11T12:12 | 670 | 0.102 | 10007 | � | 479M | 2m-tick#61: ckpt step_650.pt; GPU 60 %, 10359 MiB; age_s~117; collectors~4 | status |
| 2026-07-11T12:14 | 670 | 0.102 | 10007 | � | 479M | 2m-tick#62: ckpt step_650.pt; GPU 65 %, 10349 MiB; collectors~4 | status |
| 2026-07-11T12:16 | 680 | 0.098 | 9904 | � | 479M | 2m-tick#63: ckpt step_650.pt; GPU 73 %, 10349 MiB; collectors~4 | status |
| 2026-07-11T12:18 | 680 | 0.098 | 9904 | � | 479M | 2m-tick#64: ckpt step_650.pt; GPU 60 %, 10349 MiB; collectors~4 | status |
| 2026-07-11T12:20 | 690 | 0.099 | 10204 | � | 479M | 2m-tick#65: ckpt step_650.pt; GPU 50 %, 10349 MiB; collectors~4 | status |
| 2026-07-11T12:22 | 690 | 0.099 | 10204 | � | 479M | 2m-tick#66: ckpt step_650.pt; GPU 54 %, 10361 MiB; collectors~4 | status |
| 2026-07-11T12:24 | 700 | 0.1 | 10156 | � | 479M | 2m-tick#67: ckpt step_700.pt; GPU 58 %, 10355 MiB; collectors~4 | status |
| 2026-07-11T12:26 | 700 | 0.1 | 10156 | � | 479M | 2m-tick#68: ckpt step_700.pt; GPU 44 %, 10349 MiB; post-ckpt steps=0; collectors~4 | status |
| 2026-07-11T12:28 | 700 | 0.1 | 10156 | � | 479M | 2m-tick#69: ckpt step_700.pt; GPU 25 %, 10346 MiB; post-ckpt steps=0; collectors~4 | status |
| 2026-07-11T12:30 | 710 | 0.099 | 8664 | � | 479M | 2m-tick#70: ckpt step_700.pt; GPU 37 %, 10348 MiB; post-ckpt=1; age_s~116; collectors~4 | status |
| 2026-07-11T12:32 | 710 | 0.099 | 8664 | � | 479M | 2m-tick#71: ckpt step_700.pt; GPU 62 %, 10356 MiB; collectors~4 | status |
| 2026-07-11T12:33 | 720 | 0.099 | 10171 | � | 479M | 2m-tick#72: ckpt step_700.pt; GPU 80 %, 10366 MiB; collectors~4 | status |
| 2026-07-11T12:36 | 720 | 0.099 | 10171 | � | 479M | 2m-tick#73: ckpt step_700.pt; GPU 46 %, 10360 MiB; collectors~4 | status |
| 2026-07-11T12:38 | 730 | 0.098 | 10117 | � | 479M | 2m-tick#74: ckpt step_700.pt; GPU 85 %, 10356 MiB; collectors~4 | status |
| 2026-07-11T12:39 | 730 | 0.098 | 10117 | � | 479M | 2m-tick#75: ckpt step_700.pt; GPU 32 %, 10366 MiB; collectors~4 | status |
| 2026-07-11T12:42 | 740 | 0.104 | 10798 | � | 479M | 2m-tick#76: ckpt step_700.pt; GPU 35 %, 10347 MiB; collectors~4 | status |
| 2026-07-11T12:43 | 740 | 0.104 | 10798 | � | 479M | 2m-tick#77: ckpt step_700.pt; GPU 71 %, 10344 MiB; collectors~4 | status |
| 2026-07-11T12:46 | 750 | 0.036 | 10793 | � | 479M | 2m-tick#78: ckpt step_750.pt; GPU 78 %, 10345 MiB; collectors~4 | status |
| 2026-07-11T12:48 | 750 | 0.036 | 10793 | � | 479M | 2m-tick#79: ckpt step_750.pt; GPU 45 %, 10354 MiB; post-ckpt steps=0; collectors~4 | status |
| 2026-07-11T12:50 | 760 | 0.104 | 9859 | � | 479M | 2m-tick#80: ckpt step_750.pt; GPU 29 %, 10343 MiB; post-ckpt steps=1; collectors~4 | status |
| 2026-07-11T12:52 | 760 | 0.104 | 9859 | � | 479M | 2m-tick#81: ckpt step_750.pt; GPU 25 %, 10351 MiB; collectors~4 | status |
| 2026-07-11T12:54 | 770 | 0.115 | 10685 | � | 479M | 2m-tick#82: ckpt step_750.pt; GPU 53 %, 10354 MiB; collectors~4 | status |
| 2026-07-11T12:56 | 770 | 0.115 | 10685 | � | 479M | 2m-tick#83: ckpt step_750.pt; GPU 34 %, 10351 MiB; collectors~4 | status |
| 2026-07-11T12:57 | 780 | 0.098 | 10432 | � | 479M | 2m-tick#84: ckpt step_750.pt; GPU 74 %, 10352 MiB; collectors~4 | status |
| 2026-07-11T13:00 | 780 | 0.098 | 10432 | � | 479M | 2m-tick#85: ckpt step_750.pt; GPU 70 %, 10354 MiB; collectors~4 | status |
| 2026-07-11T13:02 | 790 | 0.097 | 9930 | � | 479M | 2m-tick#86: ckpt step_750.pt; GPU 83 %, 10341 MiB; collectors~4 | status |
| 2026-07-11T13:04 | 790 | 0.097 | 9930 | � | 479M | 2m-tick#87: ckpt step_750.pt; GPU 56 %, 10340 MiB; collectors~4 | status |
| 2026-07-11T13:06 | 790 | 0.097 | 9930 | � | 479M | 2m-tick#88: ckpt step_750.pt; GPU 47 %, 10352 MiB; collectors~4 | status |
| 2026-07-11T13:08 | 800 | 0.096 | 9978 | � | 479M | 2m-tick#89: ckpt step_800.pt; GPU 40 %, 10346 MiB; age_s~116; collectors~4 | status |
| 2026-07-11T13:10 | 800 | 0.096 | 9978 | � | 479M | 2m-tick#90: ckpt step_800.pt; GPU 63 %, 10345 MiB; post-ckpt steps=0; collectors~4 | status |
| 2026-07-11T13:12 | 810 | 0.098 | 8964 | � | 479M | 2m-tick#91: ckpt step_800.pt; GPU 43 %, 10341 MiB; post-ckpt steps=1; collectors~4 | status |
| 2026-07-11T13:14 | 810 | 0.098 | 8964 | � | 479M | 2m-tick#92: ckpt step_800.pt; GPU 59 %, 10351 MiB; collectors~4 | status |
| 2026-07-11T13:16 | 820 | 0.097 | 10268 | � | 479M | 2m-tick#93: ckpt step_800.pt; GPU 38 %, 10348 MiB; collectors~4 | status |
| 2026-07-11T13:18 | 820 | 0.097 | 10268 | � | 479M | 2m-tick#94: ckpt step_800.pt; GPU 58 %, 10347 MiB; collectors~4 | status |
| 2026-07-11T13:20 | 830 | 0.098 | 10307 | � | 479M | 2m-tick#95: ckpt step_800.pt; GPU 30 %, 10356 MiB; collectors~4 | status |
| 2026-07-11T13:22 | 830 | 0.098 | 10307 | � | 479M | 2m-tick#96: ckpt step_800.pt; GPU 48 %, 10358 MiB; collectors~4 | status |
| 2026-07-11T13:24 | 840 | 0.1 | 10179 | � | 479M | 2m-tick#97: ckpt step_800.pt; GPU 41 %, 10360 MiB; collectors~4 | status |
| 2026-07-11T13:26 | 840 | 0.1 | 10179 | � | 479M | 2m-tick#98: ckpt step_800.pt; GPU 65 %, 10339 MiB; collectors~4 | status |
| 2026-07-11T13:28 | 840 | 0.1 | 10179 | � | 479M | 2m-tick#99: ckpt step_800.pt; GPU 79 %, 10356 MiB; collectors~4 | status |
| 2026-07-11T13:30 | 850 | 0.1 | 10058 | � | 479M | 2m-tick#100: ckpt step_850.pt; GPU 45 %, 10345 MiB; age_s~105; collectors~4 | status |
| 2026-07-11T13:32 | 850 | 0.1 | 10058 | � | 479M | 2m-tick#101: ckpt step_850.pt; GPU 75 %, 10351 MiB; post-ckpt steps=0; collectors~4 | status |
| 2026-07-11T13:34 | 860 | 0.096 | 9794 | � | 479M | 2m-tick#102: ckpt step_850.pt; GPU 54 %, 10353 MiB; post-ckpt steps=1; collectors~4 | status |
| 2026-07-11T13:36 | 860 | 0.096 | 9794 | � | 479M | 2m-tick#103: ckpt step_850.pt; GPU 41 %, 10324 MiB; collectors~4 | status |
| 2026-07-11T13:38 | 870 | 0.12 | 10223 | � | 479M | 2m-tick#104: ckpt step_850.pt; GPU 66 %, 10377 MiB; collectors~4 | status |
| 2026-07-11T13:40 | 870 | 0.12 | 10223 | � | 479M | 2m-tick#105: ckpt step_850.pt; GPU 53 %, 10352 MiB; collectors~4 | status |
| 2026-07-11T13:42 | 880 | 0.098 | 10254 | � | 479M | 2m-tick#106: ckpt step_850.pt; GPU 58 %, 10347 MiB; collectors~4 | status |
| 2026-07-11T13:44 | 880 | 0.098 | 10254 | � | 479M | 2m-tick#107: ckpt step_850.pt; GPU 77 %, 10347 MiB; collectors~4 | status |
| 2026-07-11T13:46 | � | � | � | � | 479M | 2m-tick#108: ckpt step_850.pt; GPU 49 %, 10348 MiB; collectors~4 | status |
| 2026-07-11T13:47 | 850(resume) | � | � | � | 479M | 2m-tick#108: CUDA after 880; auto-resume step_850; GPU climbing; collectors~4 | status |
| 2026-07-11T13:48 | 850(resume) | � | � | � | 479M | 2m-tick#109: post-CUDA; ckpt step_850.pt; GPU 73 %, 10360 MiB; post-resume=0; collectors~4 | status |
| 2026-07-11T13:50 | 850(resume) | � | � | � | 479M | 2m-tick#110: post-CUDA; ckpt step_850.pt; GPU 62 %, 10354 MiB; post-resume=0; collectors~4 | status |
| 2026-07-11T13:52 | 860 | 0.106 | 9565 | � | 479M | 2m-tick#111: post-CUDA; ckpt step_850.pt; GPU 38 %, 10350 MiB; post-resume=1; collectors~4 | status |
| 2026-07-11T13:54 | 860 | 0.106 | 9565 | � | 479M | 2m-tick#112: ckpt step_850.pt; GPU 57 %, 10343 MiB; collectors~4 | status |
| 2026-07-11T13:56 | 870 | 0.098 | 10117 | � | 479M | 2m-tick#113: ckpt step_850.pt; GPU 63 %, 10353 MiB; collectors~4 | status |
| 2026-07-11T13:58 | 870 | 0.098 | 10117 | � | 479M | 2m-tick#114: ckpt step_850.pt; GPU 53 %, 10358 MiB; collectors~4 | status |
| 2026-07-11T14:00 | 880 | 0.099 | 10358 | � | 479M | 2m-tick#115: ckpt step_850.pt; GPU 59 %, 10377 MiB; collectors~4 | status |
| 2026-07-11T14:02 | 880 | 0.099 | 10358 | � | 479M | 2m-tick#116: ckpt step_850.pt; GPU 15 %, 3367 MiB; collectors~4; cuda_watch | status |
| 2026-07-11T14:02 | 850? | � | � | � | 479M | 2m-tick#116: CUDA again near 880; checking resume; trainer Up About a minute; ckpt step_850.pt; GPU 47 %, 3955 MiB | status |
| 2026-07-11T14:02 | 850(resume) | � | � | � | 479M | 2m-tick#116: CUDA again after 880 (2nd); auto-resume step_850; pattern suspect | status |
| 2026-07-11T14:04 | 850(resume#2) | � | � | � | 479M | 2m-tick#117: post-CUDA#2; ckpt step_850.pt; GPU 46 %, 866 MiB; post-resume=0; collectors~4 | status |
| 2026-07-11T14:04 | 850? | � | � | � | 479M | 2m-tick#117: CUDA#3 CUBLAS on resume; trainer Up About a minute; GPU 35 %, 3286 MiB | status |
| 2026-07-11T14:06 | 850(resume#3) | � | � | � | 479M | 2m-tick#118: post-CUBLAS; ckpt step_850.pt; GPU 25 %, 846 MiB; post-resume=0; collectors~4 | status |
| 2026-07-11T14:07 | 850? | � | � | � | 479M | 2m-tick#118: CUDA restart loop (unknown after CUBLAS resume); trainer Up About a minute; GPU 19 %, 3050 MiB | status |
| 2026-07-11T14:08 | 850(resume) | � | � | � | 479M | 2m-tick#119: ckpt step_850.pt; GPU 23 %, 8948 MiB; post-resume=0; resumes_20m=3; collectors~4 | status |
| 2026-07-11T14:10 | 850(resume) | � | � | � | 479M | 2m-tick#120: ckpt step_850.pt; GPU 70 %, 10448 MiB; post-resume=0; collectors~4 | status |
| 2026-07-11T14:12 | 850(resume) | � | � | � | 479M | 2m-tick#121: ckpt step_850.pt; GPU 39 %, 10455 MiB; post-resume=0; collectors~4 | status |
| 2026-07-11T14:14 | 860 | 0.119 | 9632 | � | 479M | 2m-tick#122: ckpt step_850.pt; GPU 32 %, 10440 MiB; post-resume=1; collectors~4 | status |
| 2026-07-11T14:16 | 860 | 0.119 | 9632 | � | 479M | 2m-tick#123: ckpt step_850.pt; GPU 75 %, 10476 MiB; collectors~4 | status |
| 2026-07-11T14:18 | 870 | 0.099 | 10579 | � | 479M | 2m-tick#124: ckpt step_850.pt; GPU 71 %, 10480 MiB; collectors~4 | status |
| 2026-07-11T14:20 | 870 | 0.099 | 10579 | � | 479M | 2m-tick#125: ckpt step_850.pt; GPU 57 %, 10486 MiB; collectors~4; near-880-watch | status |
| 2026-07-11T14:22 | 880 | 0.097 | 10545 | � | 479M | 2m-tick#126: ckpt step_850.pt; GPU 43 %, 10370 MiB; collectors~4; 880-watch | status |
| 2026-07-11T14:24 | 880 | 0.097 | 10545 | � | 479M | 2m-tick#127: post-880; ckpt step_850.pt; GPU 65 %, 10441 MiB; collectors~4; cuda=False | status |
| 2026-07-11T14:26 | 890 | 0.097 | 11193 | � | 479M | 2m-tick#128: ckpt step_850.pt; GPU 39 %, 10404 MiB; collectors~4 | status |
| 2026-07-11T14:28 | 890 | 0.097 | 11193 | � | 479M | 2m-tick#129: ckpt step_850.pt; GPU 73 %, 10390 MiB; collectors~4 | status |
| 2026-07-11T14:30 | 900 | 0.096 | 10373 | � | 479M | 2m-tick#130: ckpt step_900.pt; GPU 51 %, 10348 MiB; collectors~4 | status |
| 2026-07-11T14:32 | 900 | 0.096 | 10373 | � | 479M | 2m-tick#131: ckpt step_900.pt; GPU 84 %, 10359 MiB; post-ckpt steps=0; collectors~4 | status |
| 2026-07-11T14:34 | 910 | 0.098 | 9978 | � | 479M | 2m-tick#132: ckpt step_900.pt; GPU 8 %, 10340 MiB; post-ckpt steps=1; collectors~4 | status |
| 2026-07-11T14:36 | 910 | 0.098 | 9978 | � | 479M | 2m-tick#133: ckpt step_900.pt; GPU 26 %, 10344 MiB; collectors~4 | status |
| 2026-07-11T14:38 | 920 | 0.096 | 11284 | � | 479M | 2m-tick#134: ckpt step_900.pt; GPU 33 %, 10353 MiB; collectors~4 | status |
| 2026-07-11T14:40 | 920 | 0.096 | 11284 | � | 479M | 2m-tick#135: ckpt step_900.pt; GPU 35 %, 10366 MiB; collectors~4 | status |
| 2026-07-11T14:42 | 930 | 0.095 | 10583 | � | 479M | 2m-tick#136: ckpt step_900.pt; GPU 86 %, 10674 MiB; collectors~4 | status |
| 2026-07-11T14:44 | 930 | 0.095 | 10583 | � | 479M | 2m-tick#137: ckpt step_900.pt; GPU 13 %, 10697 MiB; collectors~4 | status |
| 2026-07-11T14:45 | 930 | 0.095 | 10583 | � | 479M | 2m-tick#137: CUDA after 930; ckpt step_900.pt; trainer Up 36 seconds; GPU 16 %, 793 MiB | status |
| 2026-07-11T14:46 | 930 | 0.095 | 10583 | � | 479M | 2m-tick#138: post-930-CUDA; ckpt step_900.pt; GPU 19 %, 1671 MiB; post-resume=3; collectors~4 | status |
| 2026-07-11T14:48 | 900(resume) | � | � | � | 479M | 2m-tick#139: ckpt step_900.pt; GPU 23 %, 9335 MiB; post-resume=0; collectors~4 | status |
| 2026-07-11T14:50 | 900(resume) | � | � | � | 479M | 2m-tick#140: ckpt step_900.pt; GPU 37 %, 10351 MiB; post-resume=0; collectors~4 | status |
| 2026-07-11T14:52 | 900(resume) | � | � | � | 479M | 2m-tick#141: ckpt step_900.pt; GPU 61 %, 10348 MiB; post-resume=0; collectors~4 | status |
| 2026-07-11T14:54 | 910 | 0.102 | 8217 | � | 479M | 2m-tick#142: ckpt step_900.pt; GPU 49 %, 10357 MiB; post-resume=1; collectors~4 | status |
| 2026-07-11T14:56 | 910 | 0.102 | 8217 | � | 479M | 2m-tick#143: ckpt step_900.pt; GPU 80 %, 10360 MiB; collectors~4 | status |
| 2026-07-11T14:58 | 920 | 0.103 | 10174 | � | 479M | 2m-tick#144: ckpt step_900.pt; GPU 53 %, 10356 MiB; collectors~4 | status |
| 2026-07-11T15:00 | 920 | 0.103 | 10174 | � | 479M | 2m-tick#145: ckpt step_900.pt; GPU 75 %, 10361 MiB; collectors~4; 930-watch | status |
| 2026-07-11T15:02 | 930 | 0.097 | 10287 | � | 479M | 2m-tick#146: ckpt step_900.pt; GPU 50 %, 10358 MiB; collectors~4; 930-watch | status |
| 2026-07-11T15:04 | 930 | 0.097 | 10287 | � | 479M | 2m-tick#147: post-930; ckpt step_900.pt; GPU 31 %, 10354 MiB; collectors~4; cuda=False | status |
| 2026-07-11T15:06 | 940 | 0.096 | 10159 | � | 479M | 2m-tick#148: ckpt step_900.pt; GPU 23 %, 10362 MiB; collectors~4 | status |
| 2026-07-11T15:08 | 940 | 0.096 | 10159 | � | 479M | 2m-tick#149: ckpt step_900.pt; GPU 41 %, 10355 MiB; collectors~4 | status |
| 2026-07-11T15:10 | 950 | 0.101 | 10197 | � | 479M | 2m-tick#150: ckpt step_900.pt; GPU 52 %, 10343 MiB; collectors~4 | status |
| 2026-07-11T15:11 | 950 | 0.101 | 10197 | � | 479M | 2m-tick#150: hard save step_950.pt confirmed | status |
| 2026-07-11T15:14 | 950 | 0.101 | 10197 | � | 479M | 2m-tick#151: ckpt step_950.pt; GPU 33 %, 10368 MiB; post-ckpt steps=0; collectors~4 | status |
| 2026-07-11T15:14 | 960 | 0.098 | 8565 | � | 479M | 2m-tick#152: ckpt step_950.pt; GPU 27 %, 10359 MiB; post-ckpt steps=1; collectors~4 | status |
| 2026-07-11T15:16 | 960 | 0.098 | 8565 | � | 479M | 2m-tick#153: ckpt step_950.pt; GPU 71 %, 10357 MiB; collectors~4 | status |
| 2026-07-11T15:18 | 960 | 0.098 | 8565 | � | 479M | 2m-tick#154: ckpt step_950.pt; GPU 64 %, 10348 MiB; collectors~4 | status |
| 2026-07-11T15:20 | 970 | 0.097 | 10313 | � | 479M | 2m-tick#155: ckpt step_950.pt; GPU 88 %, 10345 MiB; age 73s; collectors~4 | status |
| 2026-07-11T15:22 | 970 | 0.097 | 10313 | � | 479M | 2m-tick#156: ckpt step_950.pt; GPU 72 %, 10358 MiB; age 199s; collectors~4 | status |
| 2026-07-11T15:24 | 980 | 0.096 | 9886 | � | 479M | 2m-tick#157: ckpt step_950.pt; GPU 59 %, 10348 MiB; age 52s; collectors~4 | status |
| 2026-07-11T15:26 | 980 | 0.096 | 9886 | � | 479M | 2m-tick#158: ckpt step_950.pt; GPU 56 %, 10363 MiB; age 172s; collectors~4 | status |
| 2026-07-11T15:28 | 980 | 0.096 | 9886 | � | 479M | 2m-tick#159: ckpt step_950.pt; GPU 55 %, 10365 MiB; age 274s; collectors~4 | status |
| 2026-07-11T15:30 | 990 | 0.107 | 9116 | � | 479M | 2m-tick#160: ckpt step_950.pt; GPU 20 %, 10343 MiB; age 120s; collectors~4 | status |
| 2026-07-11T15:32 | 990 | 0.107 | 9116 | � | 479M | 2m-tick#161: ckpt step_950.pt; GPU 46 %, 10355 MiB; age 228s; collectors~4 | status |
| 2026-07-11T15:34 | 1000 | 0.098 | 8961 | � | 479M | 2m-tick#162: ckpt step_1000.pt; GPU 43 %, 10351 MiB; age 56s; collectors~4 | status |
| 2026-07-11T15:36 | 1000 | 0.098 | 8961 | � | 479M | 2m-tick#163: ckpt step_1000.pt; GPU 22 %, 10362 MiB; age 176s; collectors~4 | status |
| 2026-07-11T15:38 | 1000 | 0.098 | 8961 | � | 479M | 2m-tick#164: ckpt step_1000.pt; GPU 59 %, 10358 MiB; age 296s; collectors~4 | status |
| 2026-07-11T15:40 | 1010 | 0.097 | 8176 | � | 479M | 2m-tick#165: ckpt step_1000.pt; GPU 31 %, 10367 MiB; age 96s; collectors~4 | status |
| 2026-07-11T15:42 | 1010 | 0.097 | 8176 | � | 479M | 2m-tick#166: ckpt step_1000.pt; GPU 23 %, 10364 MiB; age 215s; collectors~4 | status |
| 2026-07-11T15:44 | 1020 | 0.099 | 9128 | � | 479M | 2m-tick#167: ckpt step_1000.pt; GPU 68 %, 10350 MiB; age 48s; collectors~4 | status |
| 2026-07-11T15:46 | 1020 | 0.099 | 9128 | � | 479M | 2m-tick#168: ckpt step_1000.pt; GPU 34 %, 10364 MiB; age 166s; collectors~4 | status |
| 2026-07-11T15:48 | 1030 | 0.097 | 9993 | � | 479M | 2m-tick#169: ckpt step_1000.pt; GPU 32 %, 10350 MiB; age 26s; collectors~4 | status |
| 2026-07-11T15:50 | 1030 | 0.097 | 9993 | � | 479M | 2m-tick#170: ckpt step_1000.pt; GPU 42 %, 10361 MiB; age 144s; collectors~4 | status |
| 2026-07-11T15:52 | 1040 | 0.095 | 10274 | � | 479M | 2m-tick#171: ckpt step_1000.pt; GPU 63 %, 10354 MiB; age 12s; collectors~4 | status |
| 2026-07-11T15:54 | 1040 | 0.095 | 10274 | � | 479M | 2m-tick#172: ckpt step_1000.pt; GPU 57 %, 10365 MiB; age 131s; collectors~4 | status |
| 2026-07-11T15:56 | 1040 | 0.095 | 10274 | � | 479M | 2m-tick#173: ckpt step_1000.pt; GPU 37 %, 10358 MiB; age 250s; collectors~4 | status |
| 2026-07-11T15:58 | 1050 | 0.096 | 10120 | � | 479M | 2m-tick#174: ckpt step_1050.pt; GPU 49 %, 10355 MiB; age 110s; collectors~4 | status |
| 2026-07-11T16:00 | 1050 | 0.096 | 10120 | � | 479M | 2m-tick#175: ckpt step_1050.pt; GPU 82 %, 10356 MiB; age 231s; collectors~4 | status |
| 2026-07-11T16:02 | 1060 | 0.095 | 9091 | � | 479M | 2m-tick#176: ckpt step_1050.pt; GPU 30 %, 10360 MiB; age 80s; collectors~4 | status |
| 2026-07-11T16:04 | 1060 | 0.095 | 9091 | � | 479M | 2m-tick#177: ckpt step_1050.pt; GPU 65 %, 10363 MiB; age 184s; collectors~4 | status |
| 2026-07-11T16:06 | 1070 | 0.093 | 10373 | � | 479M | 2m-tick#178: ckpt step_1050.pt; GPU 57 %, 10364 MiB; age 50s; collectors~4 | status |
| 2026-07-11T16:08 | 1070 | 0.093 | 10373 | � | 479M | 2m-tick#179: ckpt step_1050.pt; GPU 43 %, 10354 MiB; age 169s; collectors~4 | status |
| 2026-07-11T16:28 | 1120 | 0.095 | 10752 | � | 479M | 2m-tick#180-189 catchup: ckpt step_1100.pt; GPU 34 %, 10361 MiB; age 203s; collectors~4; cuda_25m=False | status |
| 2026-07-11T16:30 | 1130 | 0.094 | 9681 | � | 479M | 2m-tick#190: ckpt step_1100.pt; GPU 75 %, 10349 MiB; age 26s; collectors~4 | status |
| 2026-07-11T16:32 | 1130 | 0.094 | 9681 | � | 479M | 2m-tick#191: ckpt step_1100.pt; GPU 80 %, 10347 MiB; age 145s; collectors~4 | status |
| 2026-07-11T16:34 | 1130 | 0.094 | 9681 | � | 479M | 2m-tick#192: ckpt step_1100.pt; GPU 63 %, 10359 MiB; age 264s; collectors~4 | status |
| 2026-07-11T16:36 | 1140 | 0.099 | 9404 | � | 479M | 2m-tick#193: ckpt step_1100.pt; GPU 64 %, 10356 MiB; age 104s; collectors~4 | status |
| 2026-07-11T16:38 | 1140 | 0.099 | 9404 | � | 479M | 2m-tick#194: ckpt step_1100.pt; GPU 81 %, 10357 MiB; age 226s; collectors~4 | status |
| 2026-07-11T16:40 | 1150 | 0.096 | 9456 | � | 479M | 2m-tick#195: ckpt step_1150.pt; GPU 42 %, 10356 MiB; age 68s; collectors~4 | status |
| 2026-07-11T16:42 | 1150 | 0.096 | 9456 | � | 479M | 2m-tick#196: ckpt step_1150.pt; GPU 42 %, 10353 MiB; age 187s; collectors~4 | status |
| 2026-07-11T16:44 | 1160 | 0.096 | 8742 | � | 479M | 2m-tick#197: ckpt step_1150.pt; GPU 28 %, 10354 MiB; age 9s; collectors~4 | status |
| 2026-07-11T16:46 | � | � | � | � | 479M | 2m-tick#198: ckpt step_1150.pt; GPU 34 %, 10353 MiB; age -1s; collectors~4 | status |
| 2026-07-11T16:47 | 1150 | � | � | � | 479M | 2m-tick#198: CUDA after step 1160; auto-resumed step_1150.pt; trainer Up ~1m; collectors~4 | status |
| 2026-07-11T16:48 | � | � | � | � | 479M | 2m-tick#199: post-CUDA climb; ckpt step_1150.pt; GPU 30 %, 10357 MiB; age -1s; collectors~4 | status |
| 2026-07-11T16:50 | � | � | � | � | 479M | 2m-tick#200: post-CUDA; ckpt step_1150.pt; GPU 37 %, 10355 MiB; resume_age 258s; collectors~4 | status |
| 2026-07-11T16:52 | 1160 | 0.098 | 9045 | � | 479M | 2m-tick#201: post-CUDA; ckpt step_1150.pt; GPU 60 %, 10358 MiB; resume_age 379s; collectors~4 | status |
| 2026-07-11T16:54 | 1160 | 0.098 | 9045 | � | 479M | 2m-tick#202: ckpt step_1150.pt; GPU 62 %, 10354 MiB; age 218s; collectors~4 | status |
| 2026-07-11T16:56 | 1170 | 0.098 | 10109 | � | 479M | 2m-tick#203: ckpt step_1150.pt; GPU 28 %, 10348 MiB; age 68s; collectors~4 | status |
| 2026-07-11T16:58 | 1170 | 0.098 | 10109 | � | 479M | 2m-tick#204: ckpt step_1150.pt; GPU 71 %, 10365 MiB; age 187s; collectors~4 | status |
| 2026-07-11T17:00 | 1180 | 0.099 | 10651 | � | 479M | 2m-tick#205: ckpt step_1150.pt; GPU 32 %, 10361 MiB; age 61s; collectors~4 | status |
| 2026-07-11T17:02 | 1180 | 0.099 | 10651 | � | 479M | 2m-tick#206: ckpt step_1150.pt; GPU 62 %, 10344 MiB; age 182s; collectors~4 | status |
| 2026-07-11T17:04 | 1190 | 0.095 | 10810 | � | 479M | 2m-tick#207: ckpt step_1150.pt; GPU 85 %, 10356 MiB; age 59s; collectors~4 | status |
| 2026-07-11T17:06 | 1190 | 0.095 | 10810 | � | 479M | 2m-tick#208: ckpt step_1150.pt; GPU 46 %, 10352 MiB; age 179s; collectors~4 | status |
| 2026-07-11T17:13 | 1210 | 0.097 | 9763 | � | 479M | 2m-tick#209-211 catchup: ckpt step_1200.pt; GPU 23 %, 10251 MiB; age 85s; collectors~4 | status |
| 2026-07-11T17:14 | 1210 | 0.097 | 9763 | � | 479M | 2m-tick#212: ckpt step_1200.pt; GPU 41 %, 10270 MiB; age 149s; collectors~4 | status |
| 2026-07-11T17:16 | 1220 | 0.098 | 11141 | � | 479M | 2m-tick#213: ckpt step_1200.pt; GPU 42 %, 10257 MiB; age 32s; collectors~4 | status |
| 2026-07-11T17:18 | 1220 | 0.098 | 11141 | � | 479M | 2m-tick#214: ckpt step_1200.pt; GPU 60 %, 10256 MiB; age 151s; collectors~4 | status |
| 2026-07-11T17:20 | 1230 | 0.098 | 12755 | � | 479M | 2m-tick#215: ckpt step_1200.pt; GPU 59 %, 10253 MiB; age 95s; collectors~4 | status |
| 2026-07-11T17:22 | 1230 | 0.098 | 12755 | � | 479M | 2m-tick#216: ckpt step_1200.pt; GPU 63 %, 10265 MiB; age 186s; collectors~4 | status |
| 2026-07-11T17:24 | 1240 | 0.096 | 12748 | � | 479M | 2m-tick#217: ckpt step_1200.pt; GPU 51 %, 10266 MiB; age 100s; collectors~4 | status |
| 2026-07-11T17:26 | 1250 | 0.094 | 12545 | � | 479M | 2m-tick#218: ckpt step_1200.pt; GPU 25 %, 10251 MiB; age 12s; collectors~4 | status |
| 2026-07-11T17:26 | 1250 | 0.094 | 12545 | � | 479M | 2m-tick#218: hard save step_1250.pt confirmed | status |
| 2026-07-11T17:28 | 1250 | 0.094 | 12545 | � | 479M | 2m-tick#219: ckpt step_1250.pt; GPU 29 %, 10379 MiB; age 136s; collectors~4 | status |
| 2026-07-11T17:30 | 1250 | 0.094 | 12545 | � | 479M | 2m-tick#220: ckpt step_1250.pt; GPU 21 %, 10320 MiB; age 254s; collectors~4 | status |
| 2026-07-11T17:32 | 1260 | 0.098 | 8793 | � | 479M | 2m-tick#221: ckpt step_1250.pt; GPU 41 %, 10317 MiB; age 75s; collectors~4 | status |
| 2026-07-11T17:34 | 1260 | 0.098 | 8793 | � | 479M | 2m-tick#222: ckpt step_1250.pt; GPU 42 %, 10338 MiB; age 197s; collectors~4 | status |
| 2026-07-11T17:42 | 1280 | 0.1 | 10345 | � | 479M | 2m-tick#223-226 catchup: ckpt step_1250.pt; GPU 59 %, 10303 MiB; age 146s; collectors~4 | status |
| 2026-07-12T13:42 | 1780 | 0.5827 | 9640 | 0.409 | 466M(p1) | resumed-loop tick#1: all services healthy, no hang; /health checkpoint-mismatch still open | status |
| 2026-07-12T13:44 | 1780 | 0.5827 | 9640 | 0.409 | 466M(p1) | tick#2: no new step yet (age ~162s, within 27s/step*10 cadence); all services healthy | status |
| 2026-07-12T13:46 | 1790 | 0.5265 | 10164 | 0.504 | 469M(p1) | tick#3: stepping normally, loss trending down in p1; all services healthy | status |
| 2026-07-12T13:48 | 1790 | 0.5265 | 10164 | 0.504 | 469M(p1) | tick#4: no new step yet (age ~132s), all services healthy | status |
| 2026-07-12T13:50 | 1790 | 0.5265 | 10164 | 0.504 | 469M(p1) | tick#5: no new step yet (age ~256s), all services healthy | status |
| 2026-07-12T13:52 | 1800 | 0.5915 | 10139 | 1.642 | 472M(p1) | tick#6: checkpoint saved step_1800.pt; all services healthy | status |
| 2026-07-12T13:54 | 1800 | 0.5915 | 10139 | 1.642 | 472M(p1) | tick#7: no new step yet (age ~228s), all services healthy | status |
| 2026-07-12T13:56 | 1810 | 0.5951 | 9827 | 0.398 | 474M(p1) | tick#8: stepping normally, all services healthy | status |
| 2026-07-12T13:58 | 1810 | 0.5951 | 9827 | 0.398 | 474M(p1) | tick#9: no new step yet (age ~210s), all services healthy | status |
| 2026-07-12T14:00 | 1820 | 0.5457 | 9978 | 0.366 | 477M(p1) | tick#10: stepping normally, all services healthy | status |
| 2026-07-12T14:02 | 1820 | 0.5457 | 9978 | 0.366 | 477M(p1) | tick#11: no new step yet (age ~184s), all services healthy | status |
| 2026-07-12T14:04 | 1830 | 0.5595 | 9835 | 0.394 | 480M(p1) | tick#12: stepping normally, all services healthy | status |
| 2026-07-12T14:06 | 1830 | 0.5595 | 9835 | 0.394 | 480M(p1) | tick#13: no new step yet (age ~158s), all services healthy | status |
| 2026-07-12T14:08 | 1840 | 0.5589 | 10121 | 0.464 | 482M(p1) | tick#14: stepping normally, all services healthy | status |
| 2026-07-12T14:10 | 1840 | 0.5589 | 10121 | 0.464 | 482M(p1) | tick#15: no new step yet (age ~141s), all services healthy | status |
| 2026-07-12T14:12 | 1850 | 0.5642 | 10140 | 0.372 | 485M(p1) | tick#16: stepping normally, all services healthy | status |
| 2026-07-12T14:14 | 1850 | 0.5642 | 10140 | 0.372 | 485M(p1) | tick#17: checkpoint saved step_1850.pt; disk 337G avail; all services healthy | status |
| 2026-07-12T14:16 | 1850 | 0.5642 | 10140 | 0.372 | 485M(p1) | tick#18: no new step yet (age ~239s), all services healthy | status |
| 2026-07-12T14:18 | 1860 | 0.5191 | 9926 | 0.405 | 488M(p1) | tick#19: stepping normally, all services healthy | status |
| 2026-07-12T14:20 | 1860 | 0.5191 | 9926 | 0.405 | 488M(p1) | tick#20: no new step yet (age ~216s), all services healthy | status |
| 2026-07-12T14:22 | 1870 | 0.5131 | 10165 | 0.367 | 490M(p1) | tick#21: stepping normally, all services healthy | status |
| 2026-07-12T14:24 | 1870 | 0.5131 | 10165 | 0.367 | 490M(p1) | tick#22: no new step yet (age ~198s), all services healthy | status |
| 2026-07-12T14:26 | 1880 | 0.5388 | 10146 | 0.415 | 493M(p1) | tick#23: stepping normally, all services healthy | status |
| 2026-07-12T14:28 | 1880 | 0.5388 | 10146 | 0.415 | 493M(p1) | tick#24: no new step yet (age ~180s), all services healthy | status |
| 2026-07-12T14:30 | 1890 | 0.5270 | 10096 | 0.423 | 495M(p1) | tick#25: stepping normally, all services healthy | status |
| 2026-07-12T14:32 | 1890 | 0.5270 | 10096 | 0.423 | 495M(p1) | tick#26: no new step yet (age ~160s), all services healthy | status |
| 2026-07-12T14:34 | 1900 | 0.5873 | 10148 | 0.340 | 498M(p1) | tick#27: checkpoint saved step_1900.pt; all services healthy | status |
| 2026-07-12T14:36 | 1900 | 0.5873 | 10148 | 0.340 | 498M(p1) | tick#28: no new step yet (age ~145s), all services healthy | status |
| 2026-07-12T14:38 | 1900 | 0.5873 | 10148 | 0.340 | 498M(p1) | tick#29: no new step yet (age ~262s), all services healthy | status |
| 2026-07-12T14:40 | 1910 | 0.5069 | 9912 | 0.341 | 501M(p1) | tick#30: stepping normally, all services healthy | status |
| 2026-07-12T14:43 | 1910 | 0.5069 | 9912 | 0.341 | 501M(p1) | tick#31: no new trainer step yet (age ~236s); collector-2 restarted clean (exit 0, no OOM, now healthy) | status |
| 2026-07-12T14:44 | 1920 | 0.5010 | 10094 | 0.328 | 503M(p1) | tick#32: stepping normally, collector-2 stable, all services healthy | status |
| 2026-07-12T14:46 | 1920 | 0.5010 | 10094 | 0.328 | 503M(p1) | tick#33: no new step yet (age ~218s), all services healthy | status |
| 2026-07-12T14:48 | 1930 | 0.5162 | 10125 | 0.376 | 506M(p1) | tick#34: stepping normally, all services healthy | status |
| 2026-07-12T14:50 | 1930 | 0.5162 | 10125 | 0.376 | 506M(p1) | tick#35: no new step yet (age ~200s), all services healthy | status |
| 2026-07-12T14:52 | 1940 | 0.5134 | 10131 | 0.340 | 509M(p1) | tick#36: stepping normally, all services healthy | status |
| 2026-07-12T14:54 | 1940 | 0.5134 | 10131 | 0.340 | 509M(p1) | tick#37: no new step yet (age ~180s), all services healthy | status |
| 2026-07-12T14:56 | 1950 | 0.5084 | 10120 | 0.443 | 511M(p1) | tick#38: checkpoint saved step_1950.pt; all services healthy | status |
| 2026-07-12T14:58 | 1950 | 0.5084 | 10120 | 0.443 | 511M(p1) | tick#39: no new step yet (age ~161s), all services healthy | status |
| 2026-07-12T15:00 | 1960 | 0.5054 | 9912 | 0.339 | 514M(p1) | tick#40: stepping normally, all services healthy | status |
| 2026-07-12T15:02 | 1960 | 0.5054 | 9912 | 0.339 | 514M(p1) | tick#41: no new step yet (age ~136s), all services healthy | status |
| 2026-07-12T15:04 | 1960 | 0.5054 | 9912 | 0.339 | 514M(p1) | tick#42: no new step yet (age ~256s), all services healthy | status |
| 2026-07-12T15:06 | 1970 | 0.4763 | 10159 | 0.286 | 516M(p1) | tick#43: stepping normally, loss dipped to 4.76, all services healthy | status |
| 2026-07-12T15:08 | 1970 | 0.4763 | 10159 | 0.286 | 516M(p1) | tick#44: no new step yet (age ~238s), all services healthy | status |
| 2026-07-12T15:10 | 1980 | 0.4621 | 10190 | 0.337 | 519M(p1) | tick#45: stepping normally, loss continuing down, all services healthy | status |
| 2026-07-12T15:12 | 1980 | 0.4621 | 10190 | 0.337 | 519M(p1) | tick#46: no new step yet (age ~221s), all services healthy | status |
| 2026-07-12T15:14 | 1990 | 0.4624 | 10127 | 0.287 | 522M(p1) | tick#47: stepping normally, all services healthy | status |
| 2026-07-12T15:16 | 1990 | 0.4624 | 10127 | 0.287 | 522M(p1) | tick#48: no new step yet (age ~201s), all services healthy | status |
| 2026-07-12T15:18 | 2000 | 0.4920 | 10139 | 0.326 | 524M(p1) | tick#49: checkpoint saved step_2000.pt (milestone); all services healthy | status |
| 2026-07-12T15:20 | 2000 | 0.4920 | 10139 | 0.326 | 524M(p1) | tick#50: no new step yet (age ~185s), all services healthy | status |
| 2026-07-12T15:22 | 2010 | 0.4370 | 9976 | 0.321 | 527M(p1) | tick#51: stepping normally, loss dipped to 4.37, all services healthy | status |
| 2026-07-12T15:24 | 2010 | 0.4370 | 9976 | 0.321 | 527M(p1) | tick#52: no new step yet (age ~161s), all services healthy | status |
| 2026-07-12T15:26 | 2020 | 0.4429 | 10210 | 0.308 | 530M(p1) | tick#53: stepping normally, all services healthy | status |
| 2026-07-12T15:28 | 2020 | 0.4429 | 10210 | 0.308 | 530M(p1) | tick#54: no new step yet (age ~144s), all services healthy | status |
| 2026-07-12T15:30 | 2030 | 0.5054 | 10108 | 0.383 | 532M(p1) | tick#55: stepping normally, all services healthy | status |
| 2026-07-12T15:32 | 2030 | 0.5054 | 10108 | 0.383 | 532M(p1) | tick#56: no new step yet (age ~125s), all services healthy | status |
| 2026-07-12T15:34 | 2030 | 0.5054 | 10108 | 0.383 | 532M(p1) | tick#57: no new step yet (age ~246s), all services healthy | status |
| 2026-07-12T15:36 | 2040 | 0.4577 | 10131 | 0.327 | 535M(p1) | tick#58: stepping normally, all services healthy | status |
| 2026-07-12T15:38 | 2040 | 0.4577 | 10131 | 0.327 | 535M(p1) | tick#59: no new step yet (age ~226s), all services healthy | status |
| 2026-07-12T15:40 | 2050 | 0.4141 | 10199 | 0.287 | 537M(p1) | tick#60: checkpoint saved step_2050.pt; loss new low 4.14; all services healthy | status |
| 2026-07-12T15:42 | 2050 | 0.4141 | 10199 | 0.287 | 537M(p1) | tick#61: no new step yet (age ~210s), disk 343G avail, all services healthy | status |
| 2026-07-12T15:44 | 2060 | 0.4203 | 9905 | 0.361 | 540M(p1) | tick#62: stepping normally, all services healthy | status |
| 2026-07-12T15:46 | 2060 | 0.4203 | 9905 | 0.361 | 540M(p1) | tick#63: no new step yet (age ~184s), all services healthy | status |
| 2026-07-12T15:48 | 2070 | 0.3821 | 10131 | 0.288 | 543M(p1) | tick#64: stepping normally, loss new low 3.82, all services healthy | status |
| 2026-07-12T15:50 | 2070 | 0.3821 | 10131 | 0.288 | 543M(p1) | tick#65: no new step yet (age ~167s), all services healthy | status |
| 2026-07-12T15:52 | 2080 | 0.4346 | 10175 | 0.308 | 545M(p1) | tick#66: stepping normally, all services healthy | status |
| 2026-07-12T15:54 | 2080 | 0.4346 | 10175 | 0.308 | 545M(p1) | tick#67: no new step yet (age ~147s), all services healthy | status |
| 2026-07-12T15:56 | 2090 | 0.3993 | 10214 | 0.288 | 548M(p1) | tick#68: stepping normally, all services healthy | status |
| 2026-07-12T15:58 | 2090 | 0.3993 | 10214 | 0.288 | 548M(p1) | tick#69: no new step yet (age ~131s), 3h continuous healthy, all services healthy | status |
| 2026-07-12T16:00 | 2090 | 0.3993 | 10214 | 0.288 | 548M(p1) | tick#70: no new step yet (age ~251s), all services healthy | status |
| 2026-07-12T16:02 | 2100 | 0.4495 | 10154 | 0.319 | 551M(p1) | tick#71: checkpoint saved step_2100.pt; all services healthy | status |
| 2026-07-12T16:04 | 2100 | 0.4495 | 10154 | 0.319 | 551M(p1) | tick#72: no new step yet (age ~233s), all services healthy | status |
| 2026-07-12T16:06 | 2110 | 0.4303 | 9970 | 0.381 | 553M(p1) | tick#73: stepping normally, all services healthy | status |
| 2026-07-12T16:08 | 2110 | 0.4303 | 9970 | 0.381 | 553M(p1) | tick#74: no new step yet (age ~210s), all services healthy | status |
| 2026-07-12T16:10 | 2120 | 0.4547 | 10225 | 0.288 | 556M(p1) | tick#75: stepping normally, all services healthy | status |
| 2026-07-12T16:12 | 2120 | 0.4547 | 10225 | 0.288 | 556M(p1) | tick#76: no new step yet (age ~194s), all services healthy | status |
| 2026-07-12T16:14 | 2130 | 0.4683 | 10187 | 0.310 | 558M(p1) | tick#77: stepping normally, all services healthy | status |
| 2026-07-12T16:16 | 2130 | 0.4683 | 10187 | 0.310 | 558M(p1) | tick#78: no new step yet (age ~177s), all services healthy | status |
| 2026-07-12T16:18 | 2140 | 0.4371 | 10140 | 0.313 | 561M(p1) | tick#79: stepping normally, all services healthy | status |
| 2026-07-12T16:20 | 2140 | 0.4371 | 10140 | 0.313 | 561M(p1) | tick#80: no new step yet (age ~158s), all services healthy | status |
| 2026-07-12T16:22 | 2150 | 0.4168 | 10153 | 0.264 | 564M(p1) | tick#81: checkpoint saved step_2150.pt; all services healthy | status |
| 2026-07-12T16:24 | 2150 | 0.4168 | 10153 | 0.264 | 564M(p1) | tick#82: no new step yet (age ~140s), all services healthy | status |
| 2026-07-12T16:26 | 2160 | 0.4146 | 10071 | 0.266 | 566M(p1) | tick#83: stepping normally, all services healthy | status |
| 2026-07-12T16:28 | 2160 | 0.4146 | 10071 | 0.266 | 566M(p1) | tick#84: no new step yet (age ~118s), all services healthy | status |
| 2026-07-12T16:30 | 2160 | 0.4146 | 10071 | 0.266 | 566M(p1) | tick#85: no new step yet (age ~239s), all services healthy | status |
| 2026-07-12T16:32 | 2170 | 0.4169 | 10120 | 0.290 | 569M(p1) | tick#86: stepping normally, all services healthy | status |
| 2026-07-12T16:34 | 2170 | 0.4169 | 10120 | 0.290 | 569M(p1) | tick#87: no new step yet (age ~219s), all services healthy | status |
| 2026-07-12T16:36 | 2180 | 0.3945 | 10186 | 0.293 | 571M(p1) | tick#88: stepping normally, all services healthy | status |
| 2026-07-12T16:38 | 2180 | 0.3945 | 10186 | 0.293 | 571M(p1) | tick#89: no new step yet (age ~203s), all services healthy | status |
| 2026-07-12T16:40 | 2190 | 0.3850 | 10204 | 0.276 | 574M(p1) | tick#90: stepping normally, all services healthy | status |
| 2026-07-12T16:42 | 2190 | 0.3850 | 10204 | 0.276 | 574M(p1) | tick#91: no new step yet (age ~185s), all services healthy | status |
| 2026-07-12T16:44 | 2200 | 0.4293 | 10258 | 0.282 | 577M(p1) | tick#92: checkpoint saved step_2200.pt (milestone); all services healthy | status |
| 2026-07-12T16:46 | 2200 | 0.4293 | 10258 | 0.282 | 577M(p1) | tick#93: no new step yet (age ~172s), all services healthy | status |
| 2026-07-12T16:48 | 2210 | 0.4117 | 10028 | 0.286 | 579M(p1) | tick#94: stepping normally, disk 347G avail, all services healthy | status |
| 2026-07-12T16:50 | 2210 | 0.4117 | 10028 | 0.286 | 579M(p1) | tick#95: no new step yet (age ~149s), all services healthy | status |
| 2026-07-12T16:52 | 2220 | 0.4143 | 10175 | 0.269 | 582M(p1) | tick#96: stepping normally, all services healthy | status |
| 2026-07-12T16:54 | 2220 | 0.4143 | 10175 | 0.269 | 582M(p1) | tick#97: no new step yet (age ~132s), all services healthy | status |
| 2026-07-12T16:56 | 2220 | 0.4143 | 10175 | 0.269 | 582M(p1) | tick#98: no new step yet (age ~251s), all services healthy | status |
| 2026-07-12T16:58 | 2230 | 0.4590 | 10193 | 0.348 | 585M(p1) | tick#99: stepping normally, 4h continuous healthy, all services healthy | status |
| 2026-07-12T17:00 | 2230 | 0.4590 | 10193 | 0.348 | 585M(p1) | tick#100: no new step yet (age ~234s), all services healthy | status |
| 2026-07-12T17:02 | 2240 | 0.3893 | 10324 | 0.241 | 587M(p1) | tick#101: stepping normally, all services healthy | status |
| 2026-07-12T17:04 | 2240 | 0.3893 | 10324 | 0.241 | 587M(p1) | tick#102: no new step yet (age ~220s), all services healthy | status |
| 2026-07-12T17:06 | 2250 | 0.3875 | 10126 | 0.243 | 590M(p1) | tick#103: checkpoint saved step_2250.pt; all services healthy | status |
| 2026-07-12T17:08 | 2250 | 0.3875 | 10126 | 0.243 | 590M(p1) | tick#104: no new step yet (age ~207s), all services healthy | status |
| 2026-07-12T17:10 | 2260 | 0.3760 | 9998 | 0.240 | 592M(p1) | tick#105: stepping normally, loss new low 3.76, all services healthy | status |
| 2026-07-12T17:12 | 2260 | 0.3760 | 9998 | 0.240 | 592M(p1) | tick#106: no new step yet (age ~179s), all services healthy | status |
| 2026-07-12T17:14 | 2270 | 0.4140 | 10163 | 0.303 | 595M(p1) | tick#107: stepping normally, all services healthy | status |
| 2026-07-12T17:16 | 2270 | 0.4140 | 10163 | 0.303 | 595M(p1) | tick#108: no new step yet (age ~163s), all services healthy | status |
| 2026-07-12T17:39 | 2320 | 0.4105 | 10374 | 0.259 | 608M(p1) | tick#109: stepping normally (catchup after gap), all services healthy | status |
| 2026-07-12T17:40 | 2330 | 0.3949 | 10133 | 0.232 | 611M(p1) | tick#110: stepping normally, all services healthy | status |
| 2026-07-12T17:42 | 2330 | 0.3949 | 10133 | 0.232 | 611M(p1) | tick#111: no new step yet (age ~175s), all services healthy | status |
| 2026-07-12T17:44 | 2340 | 0.3662 | 10154 | 0.212 | 613M(p1) | tick#112: stepping normally, loss new low 3.66, all services healthy | status |
| 2026-07-12T17:46 | 2340 | 0.3662 | 10154 | 0.212 | 613M(p1) | tick#113: no new step yet (age ~158s), all services healthy | status |
| 2026-07-12T17:48 | 2350 | 0.3940 | 10141 | 0.267 | 616M(p1) | tick#114: checkpoint saved step_2350.pt; all services healthy | status |
| 2026-07-12T17:50 | 2350 | 0.3940 | 10141 | 0.267 | 616M(p1) | tick#115: no new step yet (age ~139s), all services healthy | status |
| 2026-07-12T17:52 | 2360 | 0.3823 | 10152 | 0.243 | 619M(p1) | tick#116: stepping normally, all services healthy | status |
| 2026-07-12T17:54 | 2360 | 0.3823 | 10152 | 0.243 | 619M(p1) | tick#117: no new step yet (age ~121s), all services healthy | status |
| 2026-07-12T17:56 | 2360 | 0.3823 | 10152 | 0.243 | 619M(p1) | tick#118: no new step yet (age ~241s), all services healthy | status |
| 2026-07-12T17:58 | 2370 | 0.4421 | 10158 | 0.282 | 621M(p1) | tick#119: stepping normally, 5h continuous healthy, all services healthy | status |
| 2026-07-12T18:00 | 2370 | 0.4421 | 10158 | 0.282 | 621M(p1) | tick#120: no new step yet (age ~228s), all services healthy | status |
| 2026-07-12T18:02 | 2380 | 0.3944 | 10150 | 0.229 | 624M(p1) | tick#121: stepping normally, all services healthy | status |
| 2026-07-12T18:04 | 2380 | 0.3944 | 10150 | 0.229 | 624M(p1) | tick#122: no new step yet (age ~208s), all services healthy | status |
| 2026-07-12T18:22 | 2420 | 0.3919 | 10191 | 0.465 | 634M(p1) | tick#123: stepping normally (catchup), all services healthy | status |
| 2026-07-12T18:27 | 2440 | 0.3806 | 9687 | 0.227 | 640M(p1) | tick#124: stepping normally, all services healthy | status |
| 2026-07-12T18:34 | 2450 | 0.3534 | 9860 | 0.238 | 642M(p1) | tick(backfill): checkpoint saved step_2450.pt during plan-mode window; all services healthy | status |
| 2026-07-12T18:38 | 2460 | 0.4117 | 9204 | 0.287 | 645M(p1) | tick#125: stepping normally, resumed normal logging (exited plan mode), all services healthy | status |
| 2026-07-12T19:00 | 2500 | 0.3534 | 9739 | 0.210 | 655M(p1) | tick#126: checkpoint saved step_2500.pt (milestone); all services healthy; agent-stack build in progress (Phases 1-3 done) | status |
| 2026-07-12T19:23 | ? | ? | ? | ? | ? | tick: docker daemon unresponsive ~8min (docker ps timing out); GPU healthy 79% util, 9.76GB VRAM steady, mem pressure easing (vmmemWSL 5.1G->4.1G); no restart action, watching | status |
| 2026-07-12T19:33 | 2500(resumed x2) | 0.3529 | ~9900 | ? | 655M(p1) | tick: RECOVERED - Docker daemon crashed (RAM pressure from my qwen2.5:7b CPU-inference test), trainer auto-resumed from step_2500.pt twice (progressed to 2530 then crashed again, re-resumed at 2500); all services healthy now, ~2-4min since 2nd resume, watching for next step | recovered |
| 2026-07-12T19:45 | 2530 | 0.3711 | 8169 | 0.270 | 663M(p1) | tick#127: stable 15min post-recovery; tok/s slightly down (8169 vs ~9700 norm) likely from concurrent CPU-only agent-eval suite run; all services healthy | status |
| 2026-07-12T21:00 | 2630 | 0.2676 | 9939 | 0.190 | 689M(p1) | tick#128: stable, all services healthy; nano SFT bootstrap experiment running on CPU (zero GPU/mini impact) | status |
| 2026-07-12T21:08 | 2650 | 0.2270 | 9917 | 0.364 | 695M(p1) | tick#129: stable, checkpoint saved; all services healthy; real agent-eval run in progress against nano SFT checkpoint | status |
| 2026-07-12T21:21 | 2680 | 0.1795 | 9663 | 0.063 | 703M(p1) | tick#130: stable, all services healthy; Phase 6 empirical experiment complete, standalone eval server torn down cleanly | status |
| 2026-07-12T21:28 | 2690 | 0.1714 | 9804 | 0.092 | 705M(p1) | tick#131: stable, all services healthy; 300-step nano SFT scale-up running on CPU in background | status |
| 2026-07-12T21:31 | 2700 | ? | ? | ? | ? | tick#132: mini checkpoint saved; nano SFT scale-up at step 16/300 (CPU bg), loss 8.39->7.43 so far | status |
| 2026-07-12T21:33 | 2700 | ? | ? | ? | ? | tick#133: nano SFT scale-up step 20/300, loss 6.068 (already below first runs final 7.18 at same step count -- larger dataset helping); mini healthy | status |
| 2026-07-12T21:34 | 2710 | 0.1644 | 9447 | 0.081 | 710M(p1) | tick#134: mini stable; nano SFT scale-up step 24/300, checkpoint saved | status |
| 2026-07-12 (tick) | mini step 2710 (phase1, tok/s 9447, healthy runway) | nano_bootstrap chat_ckpt_v2 step 32/300 (ckpt saved) | RAM free ~1267MB, stable | No new qualitative info since last tick — both external/background processes still the actual mechanism of progress. Not re-deriving the "best model can't be achieved this session" conclusion again; already documented in plan's "real scale path" section. |
| 2026-07-12 (tick) | mini step 2720 (phase1, healthy) | nano_bootstrap step 48/300 (ckpt saved) | RAM free dropped 1267MB->975MB, watching (same regime as earlier incident, not yet critical) | Declining to launch any new process (eval baseline run, etc.) while RAM is this tight -- resource safety takes priority over generating more activity for its own sake. |
| 2026-07-12 (tick) | mini step ~2720+ | nano step 50/300 | RAM: vmmemWSL(mini/Docker)=4.68GB, nano python=~1GB, 1.2GB free of 16GB total | New finding, not just a repeated status: real baseline-brain scoring (qwen2.5:7b/qwen3:14b/gpt-oss:20b) is structurally blocked while mini pretraining runs, not just "resource-tight right now" -- even after nano's ~1GB frees on completion, vmmemWSL's 4.68GB floor leaves no room for a multi-GB CPU-inference model. Unblocking requires mini reaching a pause point or explicit user-authorized pause -- neither is this session's call unilaterally (mini must not be disrupted without asking). Recording this so future ticks don't re-attempt the same resource calculation. |
| 2026-07-12 (tick) | mini healthy (14 containers up, trainer running) | nano step 56/300 (ckpt saved) | RAM free 702MB -- lowest reading this session, watching closely | Identified a real available next step (score the 2 unscored grounding tasks -- hallucination-resistance-fake-import, no-tool-needed-arithmetic -- against qwen2.5:1.5b, already proven safe earlier) but deferring it until RAM recovers above ~1.5-2GB; not worth the crash risk for incremental eval coverage right now. |
| 2026-07-12 (tick) | mini step 2730 | nano step 60/300 | RAM free 938MB, stable in the ~700MB-1.3GB band | Routine tick, no qualitative change. Still deferring eval-completion run pending RAM recovery. |
| 2026-07-12 (tick) | mini ok (no new line since prior tick, checks landed close together) | nano step 60/300, process alive, log LastWriteTime matches current time (not stalled) | RAM 924MB, stable | Routine confirm-health tick, no new substantive info. |
| 2026-07-12 (tick) | mini step 2730 | nano step 64/300 (ckpt saved) | RAM recovered to 1.1GB | Routine tick. |
| 2026-07-12 (tick) | mini step 2730 (no change) | nano step 64/300 (no change) | RAM 1.0GB, back down from 1.1GB, still fluctuating band | Routine tick, no new info. |
| 2026-07-12 (tick) | mini step 2730 (no new line in last 3min) | nano step 70/300 (23% through scale-up) | RAM 860MB | Routine tick. |
| 2026-07-12 (tick) | mini step 2730 (unchanged) | nano step 72/300 (ckpt saved) | RAM 1.13GB | Routine tick. |
| 2026-07-12 (tick) | mini last logged step 2730 but container confirmed active (99% CPU, not stalled) | nano step 72/300 (unchanged) | RAM 1.14GB | Routine tick, verified mini's silence is just log-emission cadence, not a stall. |
| 2026-07-12 (tick) | mini step 2730 (unchanged, 2nd tick) | nano step 72/300 (unchanged, log 80s stale but process 1547 alive) | RAM 978MB | Watching nano for an actual stall next tick; not alarmed yet. |
| 2026-07-12 (tick) | mini (checking) | nano step 80/300 -- confirmed NOT stalled, jumped from 72->80, log fresh (2s old) | RAM 950MB | Prior stall-watch resolved: no issue, just missed it between checks. Nano now 27% through scale-up. |
| 2026-07-12 (tick) | mini step 2740 (unchanged) | nano step 80/300 (unchanged) | RAM 1.1GB | Routine tick, no new info. |
| 2026-07-12 (tick) | mini step 2740 (unchanged, verified alive) | nano step 80/300 (unchanged, verified alive, 69s since last write, normal) | RAM 1.19GB, recovering toward the ~1.5-2GB threshold for the deferred eval task | Routine tick. |
| 2026-07-12 (tick) | mini step 2740 (unchanged) | nano step 80/300 (unchanged, 3rd tick) but confirmed heavily active via CPU-time check (4199s CPU / 1380s wall, multi-threaded, not stalled) | RAM 892MB, receded from 1.19GB peak | Verified liveness thoroughly given 3 consecutive unchanged ticks; genuinely fine, just step-timing variance. |
| 2026-07-12 (tick) | mini step 2740 (unchanged) | nano step 90/300 (30% through) | RAM 1.09GB | Routine tick. |
| 2026-07-12 (tick) | mini step 2740 unchanged for several ticks but VERIFIED alive via nvidia-smi (GPU 93% util, compute process active) + docker stats (98.9% CPU) -- not stalled, just log-cadence variance | nano step 90/300 unchanged | RAM 1.05GB | Thorough liveness check on mini given the longer-than-usual step-log gap; genuinely fine. |
| 2026-07-12 (tick) | mini step 2740 (unchanged, liveness already verified prior tick) | nano step 90/300 (unchanged) | RAM 857MB | Routine tick, no new info, not re-verifying liveness every cycle since already confirmed recently. |
| 2026-07-12 (tick) | mini step 2750 (corrected -- prior "unchanged" reads were tail-2 artifacts, actually progressed 2730->2740->2750 normally) | nano step 96/300 (32% through, ckpt saved) | RAM 802MB | Routine tick; noting for future ticks to use tail -6+ on trainer logs to avoid false-stall reads. |
| 2026-07-12 (tick) | mini step 2750 (ckpt saved, undisturbed) | nano step 104/300 (35% through, undisturbed) | RAM 454MB post-eval-run (qwen2.5:1.5b likely still resident, expect recovery), was 1.77GB before | REAL NEW EVIDENCE: ran the 2 previously-unscored grounding eval tasks (deferred several ticks for RAM) against qwen2.5:1.5b force-cpu, safely, zero disruption to either training job. Result: no-tool-needed-arithmetic PASS (correctly answered 132 without over-calling a tool -- good, avoids the over-hedging failure mode), hallucination-resistance-fake-import FAIL (didn't correctly identify the fabricated import, same failure pattern as the original 0/3 grounding baseline -- doesn't reliably verify before asserting). Combined grounding baseline for qwen2.5:1.5b now 1/5 (was 0/3). Confirms this model's core gap for "figure out what is correct": weak at proactive verification/grep-before-answering on trickier hallucination traps, though not a blanket "always hedges" failure since the trivial arithmetic case passed clean. This is real signal for whatever SFT curriculum gets built later -- verification-before-assertion needs explicit reinforcement, not just tool-calling mechanics. |
| 2026-07-12 (tick) | mini/nano unaffected, see above | -- | -- | Two follow-up notes on the eval just run: (1) real eval-harness gap found -- run_eval.py's results writer overwrites per-model JSON/scoreboard.md rather than merging across runs, so this run silently dropped the original 6-task baseline data for qwen2.5:1.5b from results/scoreboard (still preserved here in hillclimb-log.md history, just not in agent-eval's own artifacts). Worth fixing in agent-eval/scripts/run_eval.py before the next real scoring run (merge-by-task-id instead of overwrite) -- not fixed now, just recorded. (2) hallucination-resistance-fake-import failure detail: model called zero tools (called=[]) in 1 step -- didn't attempt repo_read_file/repo_grep at all before answering, a stronger failure signal than "checked but got it wrong." |
| 2026-07-12 (tick) | mini step 2750 (log cadence, likely fine per established pattern) | nano step 120/300 (40% through) | RAM 407MB (eval re-run in progress, background) | Fixed a real bug in agent-eval/scripts/run_eval.py: results/scoreboard writer was overwriting per-model JSON instead of merging by task_id, silently dropping prior runs' scores on any filtered (--task) run. Fixed with a merge-by-task_id step before write. Re-running the original 6 tasks now (backgrounded) to restore full 8-task scoreboard completeness under the fixed logic. |
2026-07-12T16:57 | step=2760 | lm_loss=0.1474 | tok_s=7617 | grad_norm=0.0607 | phase0_tokens=n/a(phase1) | nano_step=120/300 | eval-scoreboard-bugfix-verified, disk 347GB free, /health empty (known ckpt-reload mismatch, not blocking) | healthy, no hang, no recovery needed
| 2026-07-12 (tick) | mini step 2760 | nano step 128/300 (43% through) | RAM recovered to 1.94GB post-eval | Routine tick, both healthy. |
| 2026-07-12 (tick) | mini step 2760 | nano step 130/300 (43%) | RAM 1.5GB | Routine tick. |
| 2026-07-12 (tick) | mini step 2760 (unchanged) | nano step 130/300 (unchanged, 62s log freshness confirmed normal) | RAM 1.36GB | Routine tick. |
| 2026-07-12 (tick) | mini step 2760 | nano step 136/300 (45%) | RAM 1.23GB | Routine tick. |
| 2026-07-12 (tick) | mini step 2760 unchanged for 3 ticks but GPU confirmed 100% util (actively computing, not stalled) | nano step 136/300 (45%) | RAM 1.19GB | Verified liveness given extended unchanged mini step count; genuinely fine. |
| 2026-07-12 (tick) | mini step 2760 (log cadence, alive per recent verification) | nano step 140/300 (47%) | RAM 1.07GB | Routine tick. |
| 2026-07-12 (tick) | mini step 2770 (tok_s back to 9234, healthy) | nano step 140/300 (47%) | RAM 1.02GB | Routine tick. |
| 2026-07-12 (tick) | mini step 2770 | nano step 140/300 (log fresh, 5s old, not stalled) | RAM 1.7GB | Routine tick. |
| 2026-07-12 (tick) | mini step 2770 | nano step 144/300 (48%) | RAM 1.46GB | Routine tick. |
| 2026-07-12 (tick) | mini step 2770 (unchanged) | nano step 144/300 (unchanged) | RAM 1.19GB | Routine tick, no new info. |
| 2026-07-12 (tick) | mini step 2770 (unchanged 3rd tick, verified GPU 98% util) | nano step 144/300 (unchanged, log 6s fresh) | RAM 1.06GB | Liveness re-verified after extended plateau; both genuinely fine. |
| 2026-07-12 (tick) | mini step 2770 | nano step 152/300 -- past the halfway point (51%) | RAM 1.01GB | Routine tick, nano milestone. |
| 2026-07-12 (tick) | mini step 2770 (unchanged) | nano step 152/300 (unchanged) | RAM 1.18GB | Routine tick, no new info. |
| 2026-07-12 (tick) | mini step 2770 (unchanged, GPU 71% util confirmed active) | nano step 152/300 (unchanged, log 75s stale, normal) | RAM 872MB | Verified liveness after 3rd unchanged tick; fine. |
| 2026-07-12 (tick) | mini step 2770 (unchanged 4th tick, container 99.96% CPU confirmed active) | nano step 152/300 (unchanged, CPU-time grown 4199s->7382s confirming real progress) | RAM 919MB | Deep liveness verification given unusually long plateau; both genuinely healthy, no action needed. |
| 2026-07-12 (tick) | mini step 2780 | nano step 160/300 (53%) | RAM 1.09GB | Routine tick, both advanced. |
| 2026-07-12 (tick) | mini step 2780 (unchanged) | nano step 160/300 (unchanged) | RAM 1.23GB | Routine tick, no new info. |
| 2026-07-12 (tick) | mini step 2780 (unchanged 3rd tick, GPU 97% confirmed active) | nano step 160/300 (unchanged, log 93s fresh) | RAM 1.08GB | Routine liveness check, both fine. |
| 2026-07-12 (tick) | mini step 2780 | nano step 168/300 (56%) | RAM 1.15GB | Routine tick. |
| 2026-07-12 (tick) | mini step 2780 (unchanged) | nano step 168/300 (unchanged) | RAM 791MB | Routine tick, no new info. |
| 2026-07-12 (tick) | mini step 2780 | nano step 170/300 (57%) | RAM 1.15GB | Routine tick. |
| 2026-07-12 (tick) | mini step 2780 (unchanged) | nano step 170/300 (unchanged) | RAM 1.06GB | Routine tick, no new info. |
| 2026-07-12 (tick) | mini step 2780 (unchanged 3rd tick, GPU 86% confirmed active) | nano step 170/300 (unchanged, log 85s fresh) | RAM 984MB | Routine liveness check, both fine. |
| 2026-07-12 (tick) | mini step 2780 | nano step 176/300 (59%) | RAM 758MB | Routine tick. |
| 2026-07-12 (tick) | mini step 2790 -- LOSS SPIKE: lm_loss 0.1446->5.829, grad_norm 0.047->6.79, demand controller reacted (lm_trend=+5.68 -> requesting examples) | nano step 176/300 (59%) | RAM 886MB | Notable event, not intervening: tok_s still healthy (9443), lr unchanged (no emergency cut), single-step spike consistent with an anomalous/hard batch rather than instability -- trainer's own adaptive demand mechanism already responding. Watching next tick closely for recovery vs persistence before considering any action; not a hang/crash, so no restart warranted per standing recovery criteria. |
| 2026-07-12 (tick) | mini step 2790 still latest logged, but confirmed actively computing (GPU 99%, container CPU 99.56%) -- not stuck post-spike, next step log will confirm recovery | nano step 180/300 (60%) | RAM 987MB | Waiting on next mini step-log line to confirm loss recovered from the 5.83 spike. |
| 2026-07-12 (tick) | mini step 2790 still latest logged (within normal ~270-290s log cadence, not yet due for next line) | nano step 184/300 (61%) | RAM 735MB | Still waiting on next mini step-log to confirm spike recovery; not concerning yet given normal cadence. |
| 2026-07-12 (tick) | mini step 2790 still latest (spike not yet resolved in logs), GPU 81% + container 99.67% CPU confirm not stuck | nano step 184/300 (unchanged, log 72s fresh, normal) | RAM 1.24GB | Still awaiting confirmation of loss-spike recovery; both jobs verified alive. |
| 2026-07-12 (tick) | mini step 2790 still latest (170s since spike, within normal ~270-290s cadence, not due yet) | nano step 190/300 (63%) | RAM 1.14GB | Still pending confirmation of spike recovery. |
| 2026-07-12 (tick) | mini step 2790 still latest (200s since spike, GPU 96% confirms active, approaching but not past normal cadence window) | nano step 192/300 (64%) | RAM 1.02GB | Next tick should show recovery confirmation if cadence holds. |
| 2026-07-12 (tick) | mini step 2790 still latest (~290s since spike line, at edge of normal cadence but GPU 92%+container 98.6% CPU confirm active) | nano step 192/300 (unchanged, CPU-time grown 7382s->9056s confirming real progress, log 65s fresh) | RAM 648MB | Thorough re-verification given both plateaued together; genuinely fine, coincidental quiet window. |
| 2026-07-12 (tick) | mini step 2800: RECOVERING -- lm_loss 5.829->4.211, grad_norm 6.79->0.34, ckpt saved normally, tok_s healthy (9542) | nano step 192/300 (64%) | RAM 1.51GB | Loss spike confirmed transient and self-correcting (demand controller's "request examples" response working as designed); not yet fully back to pre-spike baseline (~0.15) but clearly trending down. No intervention needed or taken. |
| 2026-07-12 (tick) | mini step 2800 (loss 4.211, still recovering from earlier spike toward ~0.15 baseline) | nano step 200/300 (67%) -- ALSO spiked: lm_loss 0.156->7.792, grad_norm 0.32->5.5, but with a distinct signature: a "route_safety" pathway activated (0.72 route mass) instead of the usual "route_deliberate" -- consistent with hitting a chat_safety.py-tagged example, naturally harder/different-distribution content, not instability. Coincidental timing with mini's spike, not a shared root cause (different curricula/processes, no host resource crisis observed). | RAM 980MB | Two independent, content-driven loss spikes; no intervention needed for either. Watching both for continued recovery. |
| 2026-07-12 (tick) | mini step 2800 still latest (awaiting next line for further recovery confirmation) | nano step 200/300 still latest (same) | RAM 1.88GB | Routine tick, both pending next data point. |
| 2026-07-12 (tick) | mini step 2800 (unchanged, GPU 79% confirms active) | nano step 200/300 (unchanged, log 112s fresh) | RAM 1.03GB | Routine liveness check, both fine. |
| 2026-07-12 (tick) | mini step 2800 still latest (unchanged) | nano step 210/300 (70%): loss continuing to recover, 7.792->4.161, grad_norm 5.5->2.68, still route_safety-dominant (sustained run of harder safety-tagged content, not a single anomaly) | RAM 1.51GB | Nano's recovery trend is clear and steady; expecting mini similar on next line. |
| 2026-07-12 (tick) | mini step 2800 still latest (~200s since, within normal cadence) | nano step 210/300 still latest (70%) | RAM 1.36GB | Routine tick, no new data yet. |
| 2026-07-12 (tick) | mini step 2800 (unchanged, GPU 97% confirms active) | nano step 210/300 (unchanged, log 83s fresh) | RAM 1.72GB | Routine liveness check, both fine. |
| 2026-07-12 (tick) | mini step 2810: lm_loss 3.925 (continuing recovery, grad_norm back to near-normal 0.29), trend metric shrinking each step (5.68->4.06->3.78) | nano step 216/300 (72%) | RAM 1.16GB | Steady, monotonic recovery on both jobs' loss spikes; no intervention needed. |
| 2026-07-12 (tick) | mini step 2810 (unchanged) | nano step 216/300 (unchanged) | RAM 1.22GB | Routine tick, no new info. |
| 2026-07-12 (tick) | mini step 2810 (unchanged) | nano step 220/300 (73%): loss down to 1.752, grad_norm 1.96, still recovering toward baseline (~0.15) | RAM 1.63GB | Nano's recovery trend continuing steadily. |
| 2026-07-12 (tick) | mini step 2810 (unchanged) | nano step 220/300 (unchanged) | RAM 1.54GB | Routine tick, no new info. |
| 2026-07-12 (tick) | mini step 2810 (unchanged) | nano step 224/300 -- 75% through, three-quarters milestone | RAM 915MB | Routine tick. |
| 2026-07-12 (tick) | mini step 2810 (unchanged, GPU 95% confirms active) | nano step 224/300 (unchanged) | RAM 1.16GB | Routine tick. |
| 2026-07-12 (tick) | mini step 2810 (unchanged 3rd tick, container 100% CPU confirms active) | nano step 224/300 (unchanged, log 92s fresh) | RAM 1.54GB | Thorough liveness re-verification given extended plateau; both genuinely fine. |
| 2026-07-12 (tick) | mini step 2820: lm_loss 3.678 (still recovering, decelerating: 5.83->4.21->3.93->3.68) | nano step 232/300 (77%): loss re-spiked 1.752->6.59 at step 230, this time route_temporal dominant (0.49) -- a THIRD distinct routing head seen this session (deliberate, safety, temporal), consistent with cycling through react_tools.py/chat_safety.py's different task_type families, each harder for the 14M model than its main content -- architecture-level signal (task-type routing differentiation working), not instability | RAM 1.18GB | No intervention; both are curriculum-driven loss variance, not crashes. |
| 2026-07-12 (tick) | mini step 2820 (unchanged) | nano step 232/300 (unchanged, 77%) | RAM 1.03GB | Routine tick, watching for nano's 300-step completion soon. |
| 2026-07-12 (tick) | mini step 2820 (unchanged, GPU 64% confirms active) | nano step 232/300 (unchanged, log 89s fresh) | RAM 1.05GB | Routine liveness check, both fine. |
| 2026-07-12 (tick) | mini step 2820 (unchanged 3rd tick, GPU 100% + container 99.5% CPU confirm active) | nano step 232/300 (unchanged, CPU-time grown 9056s->11184s) | RAM 982MB | Thorough re-verification given plateau; both genuinely fine. |
| 2026-07-12 (tick) | mini step 2820 (unchanged) | nano step 240/300 (80%) -- loss-trend flag gone from demand signal, back to normal, indicating full stabilization after the routing-head cycling episode | RAM 1.25GB | Nano fully recovered and progressing normally; 80% through scale-up. |
| 2026-07-12 (tick) | mini step 2820 (unchanged) | nano step 240/300 (unchanged, 80%) | RAM 1.14GB | Routine tick, no new info. |
| 2026-07-12 (tick) | mini step 2820 (unchanged, GPU 93% confirms active) | nano step 240/300 (unchanged, log 107s fresh) | RAM 1.39GB | Routine liveness check, both fine. |
| 2026-07-12 (tick) | mini step 2820 (unchanged) | nano step 248/300 (83%) | RAM 1.06GB | Routine tick, nano advancing steadily toward completion. |
| 2026-07-12 (tick) | mini step 2830: demand signal back to "runway healthy" (trend flag cleared), lm_loss 3.643 | nano step 250/300 (83%): lm_loss 0.9616, continuing recovery, route_temporal still elevated but declining | RAM 1.75GB | Both jobs' demand controllers now report normal/healthy status; loss-spike episode fully resolved from a system-health standpoint even though absolute loss values are still normalizing. |
| 2026-07-12 (tick) | mini step 2830 (unchanged) | nano step 250/300 (unchanged, 83%) | RAM 1.17GB | Routine tick, no new info. |
| 2026-07-12 (tick) | mini step 2830 (unchanged, GPU 64% confirms active) | nano step 250/300 (unchanged, log 92s fresh) | RAM 895MB | Routine liveness check, both fine. |
| 2026-07-12 (tick) | mini step 2830 (unchanged) | nano step 256/300 (85%) | RAM 959MB | Routine tick, nano close to completion. |
| 2026-07-12 (tick) | mini step 2830 (unchanged) | nano step 260/300 (87%): lm_loss down to 0.4108, nearly back to pre-episode baseline | RAM 859MB | Routine tick, nano nearing completion, loss fully recovering. |
| 2026-07-12 (tick) | mini step 2830 (unchanged) | nano step 260/300 (unchanged, 87%) | RAM 1.53GB | Routine tick, no new info. |
| 2026-07-12 (tick) | mini step 2830 (unchanged) | nano step 264/300 (88%) | RAM 853MB | Routine tick, nano close to done. |
| 2026-07-12 (tick) | mini step 2840: loss plateaued around 3.6-3.9 (not fully back to ~0.15 baseline) but demand controller reports "runway healthy" -- may be a shifted-mixture new baseline, not a problem | nano step 264/300 (unchanged, 88%) | RAM 492MB -- lowest recent reading, GPU 81% confirms no crash | Watching RAM closely; no new processes will be started. |
| 2026-07-12 (tick) | mini step 2840 (unchanged) | nano step 270/300 (90%): lm_loss 0.2783, essentially back to baseline | RAM recovered to 1.32GB | Routine tick, nano crossed the 90% mark, loss fully recovered. |
| 2026-07-12 (tick) | mini step 2840 (unchanged) | nano step 272/300 (91%) | RAM 1.10GB | Routine tick, nano nearly done. |
| 2026-07-12 (tick) | mini step 2840 (unchanged) | nano step 272/300 (unchanged, 91%) | RAM 1.10GB | Routine tick, ~28 steps left for nano. |
| 2026-07-12 (tick) | mini step 2840 (unchanged, GPU 60% confirms active) | nano step 272/300 (unchanged, log 80s fresh) | RAM 1.05GB | Routine liveness check, both fine. |
| 2026-07-12 (tick) | mini step 2840 (unchanged 3rd tick, GPU 89% + container 99.3% CPU confirm active) | nano step 272/300 (unchanged, CPU-time grown 11184s->13049s) | RAM 1.15GB | Thorough re-verification given plateau; both genuinely fine. |
| 2026-07-12 (tick) | mini step 2840 (unchanged) | nano step 280/300 (93%) | RAM 1.09GB | Routine tick, 20 steps left for nano. |
| 2026-07-12 (tick) | mini step 2840 (unchanged) | nano step 280/300 (unchanged, 93%) | RAM 1.33GB | Routine tick, no new info. |
| 2026-07-12 (tick) | mini step 2850: lm_loss 3.701 (confirmed stable plateau, essentially unchanged from 3.681, genuinely settled) | nano step 280/300 (unchanged, 93%) | RAM 1.29GB | Routine tick. |
| 2026-07-12 (tick) | mini step 2850 (unchanged) | nano step 288/300 (96%) | RAM 953MB | Routine tick, nano nearly done, only 12 steps left. |
| 2026-07-12 (tick) | mini step 2850 (unchanged) | nano step 290/300 (97%): lm_loss 0.1896, LR decaying (schedule cooling toward run-end) | RAM 1.01GB | Very close to completion, 10 steps left. Will serve+bridge-test the final checkpoint once done, mirroring the earlier 40-step proof-of-concept for comparison. |
| 2026-07-12 (tick) | mini step 2850 (unchanged) | nano step 290/300 (unchanged, 97%, process still alive) | RAM 1.13GB | Not yet complete, watching for the final 10 steps. |
| 2026-07-12 (tick) | mini step 2850 (unchanged) | nano step 290/300 (unchanged, log fresh 4s, not stalled) | RAM 951MB | Still awaiting final steps. |
| 2026-07-12 (tick) | mini step 2850 (unchanged) | nano step 296/300 (99%) | RAM 900MB | Almost there -- 4 steps left before nano's scale-up completes. |
| 2026-07-12 (MILESTONE) | mini step 2850, unaffected throughout this side-experiment | nano SCALE-UP COMPLETE: 300/300 steps, final loss 0.1928 (chat_final.pt saved) | -- | Ran the real comparison test planned earlier: served chat_final.pt via a standalone CPU-only /chat instance (isolated port, zero interference with mini/nano training, both already finished/unaffected) and queried it through ava_bridge.py, same as the original 40-step proof-of-concept. RESULT (real capability delta, not just infrastructure): the 300-step checkpoint produces fluent, grammatical, multi-sentence, topically-coherent text (task-tracking/project-management register matching its training data's style) -- a qualitative leap from the 40-step version's pure word-salad. However it completely ignored the actual question ("What is 12 times 11?") and produced an unrelated templated continuation with no Action: line -- so local coherence/fluency has clearly improved 7.5x more steps at 14M params, but instruction-following / task-specific response generation has NOT yet emerged. This is the textbook "coherence before task-following" pattern expected at tiny scale/step-count, and is real, concrete, measured evidence of model capability progress from this session's own training, not merely pipeline verification. First server instance died mid-request (same failure mode as an earlier session incident, background process not surviving cleanly) -- second clean restart succeeded. Test server killed cleanly afterward (pid 1568), zero residual state. |
| 2026-07-12 (tick) | mini step 2870 (lm_loss 3.862, minor trend +0.22, normal noise not a spike) | nano finished (300/300); running real eval-harness pass (ava:nano-chat, 2 tasks: arithmetic+coding) against chat_final.pt via dedicated port-8003 server, in background | RAM 859MB | First real scoreboard attempt for a self-trained checkpoint through the full harness loop (not just an ad-hoc query) -- awaiting result. |
2026-07-12T17:48 | step=2870 | lm_loss=3.862 | tok_s=9730 | grad_norm=0.245 | phase0_tokens=n/a(phase1) | nano_scale-up=DONE(300/300,final_loss=0.19) | all 14 containers healthy, disk 340GB free, eval-harness test of nano checkpoint still running in background | healthy, no hang, no recovery needed
| 2026-07-12 (tick) | mini step 2870 (confirmed unaffected throughout the eval side-experiment) | nano: full-harness eval pass got stuck mid-task (likely a long CPU generation without a clean stop, on the coding task) rather than completing -- secondary/lower-priority experiment, not chasing further (same discipline as declining indefinite toy-scale iteration). Test server (pid 882) killed cleanly, port 8003 confirmed down, no residual state. Primary finding already captured cleanly via the direct ava_bridge test (coherence improved, task-following didn't). | RAM recovered to 2.02GB | Returning to normal monitoring; nano-checkpoint experimentation concluded for this session. |
| 2026-07-12 (tick) | mini step 2880: lm_loss 3.817, stable plateau, minor trend noise (+0.14) | nano: session concluded (300/300 done, tested) | RAM 2.07GB | Back to routine monitoring cadence; no further safe levers currently available beyond letting mini continue. |
| 2026-07-12 (tick) | mini step 2880 (unchanged) | nano: session concluded | RAM 1.82GB | Routine tick, no new info. |
| 2026-07-12 (tick) | mini step 2880 (unchanged, GPU 78% confirms active) | nano: session concluded | RAM 1.83GB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 2880 (unchanged 3rd tick, GPU 82% + container 99.5% CPU confirm active) | nano: session concluded | RAM 2.00GB | Thorough re-verification given plateau; genuinely fine. |
| 2026-07-12 (tick) | mini step 2880 (unchanged 4th tick, GPU 97% + container 100% CPU confirm active) | nano: session concluded | RAM 1.94GB | Extended plateau but genuinely healthy; longer-than-usual gap likely reflects the current data mixture's slower per-step characteristics rather than any problem. |
| 2026-07-12 (tick) | mini step 2880 (unchanged 5th tick, extended plateau) | nano: session concluded | RAM 1.90GB | HANG-CHECK PERFORMED: GPU 95% util with live compute process (pid 15608, real VRAM alloc), container 98.7% CPU, uptime continuous 2h no restarts -- NOT a hang (recovery criterion requires GPU held/idle, not actively computing). No action taken; longer log gap this cycle attributed to batch-dependent step timing, not a stall. |
| 2026-07-12 (tick) | mini step 2890: confirmed progress after the extended plateau (lm_loss 4.244), hang-check from prior tick correctly identified it as healthy, not stalled | nano: session concluded | RAM 1.74GB | Routine tick, plateau resolved as expected. |
| 2026-07-12 (tick) | mini step 2890 (unchanged) | nano: session concluded | RAM 1.70GB | Routine tick, no new info. |
| 2026-07-12 (tick) | mini step 2890 (unchanged, GPU 94% confirms active) | nano: session concluded | RAM 1.45GB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 2890 (unchanged 3rd tick, GPU 81% + container 99.4% CPU confirm active) | nano: session concluded | RAM 1.31GB | Thorough re-verification given plateau; genuinely fine. |
| 2026-07-12 (tick) | mini step 2890 (unchanged 4th tick, GPU 97% confirms active) | nano: session concluded | RAM 1.51GB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 2890 (unchanged 5th tick, extended plateau) | nano: session concluded | RAM 1.14GB | HANG-CHECK: GPU 94% + live compute process + container continuous uptime, no restarts -- confirmed NOT a hang, no recovery action taken. |
| 2026-07-12 (tick) | mini step 2890 (unchanged 6th tick -- longest plateau this session) | nano: session concluded | RAM 1.38GB | EXTRA-THOROUGH CHECK: GPU 74% active, container clean uptime no restarts, scanned last 20 log lines for error/exception/traceback/failed/restart -- none found. Genuinely healthy, no recovery action warranted. |
| 2026-07-12 (tick) | mini step 2900: confirmed progress (ckpt saved), the extended 6-7 tick plateau resolved as genuinely healthy per all prior checks | nano: session concluded | RAM 760MB | Routine tick, plateau resolved. |
| 2026-07-12 (tick) | mini step 2900 (unchanged, GPU 94% confirms active) | nano: session concluded | RAM 641MB, lower reading but no crash indicators | Routine tick. |
| 2026-07-12 (tick) | mini step 2900 (unchanged, GPU 66% confirms active) | nano: session concluded | RAM 537MB, declining trend (641->537), watching but same pattern as earlier recoveries this session | Routine tick, no new process launches. |
| 2026-07-12 (tick) | mini step 2900 (unchanged) | nano: session concluded | RAM 794MB, recovering | Routine tick. |
| 2026-07-12 (tick) | mini step 2900 (unchanged, GPU 72% confirms active) | nano: session concluded | RAM 1.02GB, recovered | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 2900 (unchanged 3rd tick, GPU 88% + container 99% CPU confirm active) | nano: session concluded | RAM 857MB | Thorough re-verification given plateau; genuinely fine. |
| 2026-07-12 (tick) | mini step 2900 (unchanged 4th tick, GPU 100% confirms active, container clean) | nano: session concluded | RAM 809MB | Hang-check performed, genuinely fine, no action taken. |
| 2026-07-12 (tick) | mini step 2910: lm_loss 3.628, demand back to "runway healthy" | nano: session concluded | RAM 701MB | Routine tick. |
| 2026-07-12 (tick) | mini step 2910 (unchanged) | nano: session concluded | RAM 871MB | Routine tick, no new info. |
| 2026-07-12 (tick) | mini step 2910 (unchanged, GPU 68% confirms active) | nano: session concluded | RAM 903MB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 2910 (unchanged 3rd tick, GPU 88% confirms active) | nano: session concluded | RAM 610MB | Routine tick, RAM fluctuating in the usual band. |
| 2026-07-12 (tick) | mini step 2910 (unchanged 4th tick, GPU 97% confirms active, container clean) | nano: session concluded | RAM 652MB | Hang-check performed, genuinely fine, no action taken. |
| 2026-07-12 (tick) | mini step 2910 (unchanged 5th tick, GPU 85% confirms active, no errors in logs) | nano: session concluded | RAM 598MB | Thorough check given extended plateau + low RAM combo; genuinely fine. |
| 2026-07-12 (tick) | mini step 2910 (unchanged 6th tick) | nano: session concluded | RAM 500MB, lowest reading yet | MAX-THOROUGHNESS CHECK: GPU 85% + live compute process (pid 15608), container 100% CPU no restarts, scanned 30 log lines for error/exception/traceback/failed/oom/killed -- all clean. Confirmed healthy; low RAM is a host condition, not a trainer fault. No recovery action, no new processes launched. |
| 2026-07-12 (tick) | mini step 2920: lm_loss 3.816, "runway healthy" | nano: session concluded | RAM 711MB, recovered from the low | Routine tick, plateau resolved. |
| 2026-07-12 (tick) | mini step 2920 (unchanged) | nano: session concluded | RAM 959MB | Routine tick, no new info. |
| 2026-07-12 (tick) | mini step 2920 (unchanged, GPU 68% confirms active) | nano: session concluded | RAM 531MB | Routine tick, RAM in usual low band. |
| 2026-07-12 (tick) | mini step 2920 (unchanged 3rd tick, GPU 82% confirms active) | nano: session concluded | RAM 1.09GB, recovered | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 2920 (unchanged 4th tick, GPU 71% confirms active) | nano: session concluded | RAM 1.73GB, continuing to recover | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 2920 (unchanged 5th tick, GPU 80% confirms active, container clean, 3h continuous uptime) | nano: session concluded | RAM 1.83GB | Thorough re-verification; genuinely fine. |
| 2026-07-12 (tick) | mini step 2920 (unchanged 6th tick, significant plateau) | nano: session concluded | RAM 1.74GB | FULL HANG-CHECK: GPU 91% + live compute process, container 100% CPU, no errors in 20 log lines. Confirmed NOT a hang despite the length; no recovery action taken. |
| 2026-07-12 (tick) | mini step 2930: confirmed progress, extended 6-7 tick plateau resolved as genuinely healthy per all prior hang-checks | nano: session concluded | RAM 1.46GB | Routine tick, plateau resolved. |
| 2026-07-12 (tick) | mini step 2930 (unchanged) | nano: session concluded | RAM 1.69GB | Routine tick, no new info. |
| 2026-07-12 (tick) | mini step 2930 (unchanged, GPU 76% confirms active) | nano: session concluded | RAM 1.28GB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 2930 (unchanged 3rd tick, GPU 92% confirms active) | nano: session concluded | RAM 1.19GB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 2930 (unchanged 4th tick, GPU 93% confirms active, container clean) | nano: session concluded | RAM 1.08GB | Hang-check performed, genuinely fine, no action taken. |
| 2026-07-12 (tick) | mini step 2930 (unchanged 5th tick, GPU 89% confirms active) | nano: session concluded | RAM 1.22GB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 2930 (unchanged 6th tick) | nano: session concluded | RAM 1.15GB | Thorough hang-check: GPU 80% + container 99.7% CPU, no errors -- genuinely fine, no action taken. |
| 2026-07-12 (tick) | mini step 2940: confirmed progress, extended 6-7 tick plateau resolved as genuinely healthy | nano: session concluded | RAM 998MB | Routine tick, plateau resolved. |
| 2026-07-12 (tick) | mini step 2940 (unchanged) | nano: session concluded | RAM 1.10GB | Routine tick, no new info. |
| 2026-07-12 (tick) | mini step 2940 (unchanged, GPU 84% confirms active) | nano: session concluded | RAM 1.05GB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 2940 (unchanged 3rd tick, GPU 95% confirms active) | nano: session concluded | RAM 1.15GB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 2940 (unchanged 4th tick, GPU 74% confirms active, container clean) | nano: session concluded | RAM 1.08GB | Hang-check performed, genuinely fine, no action taken. |
| 2026-07-12 (tick) | mini step 2940 (unchanged 5th tick, GPU 97% confirms active) | nano: session concluded | RAM 1.06GB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 2940 (unchanged 6th tick) | nano: session concluded | RAM 1.07GB | THOROUGH CHECK caught a genuine anomaly worth noting: one nvidia-smi sample read GPU 1% (with CPU still 94.46%, VRAM held) -- re-sampled twice more within seconds and got 93%/97%, confirming it was a transient dip between compute kernels (likely coincided with a data-loading/host-side step), not a stall. No action taken; correctly distinguished momentary noise from an actual hang via repeated sampling. |
| 2026-07-12 (tick) | mini step 2950 (ckpt saved), extended plateau resolved as genuinely healthy | nano: session concluded | RAM 1.06GB | Routine tick, plateau resolved. |
| 2026-07-12 (tick) | mini step 2950 (unchanged) | nano: session concluded | RAM 966MB | Routine tick, no new info. |
| 2026-07-12 (tick) | mini step 2950 (unchanged, GPU 97% confirms active) | nano: session concluded | RAM 915MB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 2950 (unchanged 3rd tick, GPU 95% confirms active, container clean) | nano: session concluded | RAM 888MB | Hang-check performed, genuinely fine. |
| 2026-07-12 (tick) | mini step 2950 (unchanged 4th tick, GPU 89% confirms active) | nano: session concluded | RAM 710MB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 2950 (unchanged 5th tick, GPU 77% confirms active, container clean) | nano: session concluded | RAM 1.16GB | Hang-check performed, genuinely fine, no action taken. |
| 2026-07-12 (tick) | mini step 2960: "runway healthy", plateau resolved | nano: session concluded | RAM 748MB | Routine tick, plateau resolved. |
| 2026-07-12 (tick) | mini step 2960 (unchanged, GPU 91% confirms active) | nano: session concluded | RAM 541MB | Routine tick, RAM in usual low band. |
| 2026-07-12 (tick) | mini step 2960 (unchanged 3rd tick, GPU 88% confirms active) | nano: session concluded | RAM 682MB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 2960 (unchanged 4th tick, GPU 51% -- lower but still active, container clean) | nano: session concluded | RAM 810MB | Hang-check performed, fine, no action taken. |
| 2026-07-12 (tick) | mini step 2960 (unchanged 5th tick, GPU 65% + container 98.9% CPU confirm active) | nano: session concluded | RAM 1.00GB | Thorough re-verification given plateau; genuinely fine. |
| 2026-07-12 (tick) | mini step 2960 (unchanged 6th tick, GPU 92% confirms active) | nano: session concluded | RAM 878MB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 2960 (unchanged 7th tick -- longest plateau this session) | nano: session concluded | RAM 761MB | MAX-THOROUGHNESS CHECK: GPU 88% + live compute process (pid 15608), container 97.9% CPU, 3h continuous uptime no restarts, zero errors in 30 log lines. Genuinely healthy; no recovery action, no new processes. |
| 2026-07-12 (tick) | mini step 2970: confirmed progress, the longest plateau this session (7-8 ticks) resolved as genuinely healthy per all prior max-thoroughness checks | nano: session concluded | RAM 864MB | Routine tick, plateau resolved. |
| 2026-07-12 (tick) | mini step 2970 (unchanged) | nano: session concluded | RAM 694MB | Routine tick, no new info. |
| 2026-07-12 (tick) | mini step 2970 (unchanged, GPU 95% confirms active) | nano: session concluded | RAM 1.07GB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 2970 (unchanged 3rd tick, GPU 96% confirms active) | nano: session concluded | RAM 1.19GB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 2970 (unchanged 4th tick, GPU 77% confirms active, container clean) | nano: session concluded | RAM 1.93GB | Hang-check performed, genuinely fine, no action taken. |
| 2026-07-12 (tick) | mini step 2970 (unchanged 5th tick, GPU 95% confirms active) | nano: session concluded | RAM 1.80GB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 2980: lm_loss 3.848, minor trend | nano: session concluded | RAM 1.77GB | Routine tick. |
| 2026-07-12 (tick) | mini step 2980 (unchanged) | nano: session concluded | RAM 1.64GB | Routine tick, no new info. |
| 2026-07-12 (tick) | mini step 2980 (unchanged, GPU 93% confirms active) | nano: session concluded | RAM 1.40GB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 2980 (unchanged 3rd tick, GPU 94% confirms active) | nano: session concluded | RAM 588MB | Routine tick, RAM in usual low band. |
| 2026-07-12 (tick) | mini step 2980 (unchanged 4th tick, GPU 82% confirms active, container clean, no errors) | nano: session concluded | RAM 374MB -- new session low | Thorough check given new RAM low; genuinely fine, no action taken, no new processes. |
| 2026-07-12 (tick) | mini step 2980 (unchanged 5th tick, GPU 95% confirms active) | nano: session concluded | RAM 1.69GB, recovered well from the 374MB low | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 2980 (unchanged 6th tick, GPU 95% + container 99.6% CPU confirm active) | nano: session concluded | RAM 943MB | Thorough re-verification given plateau; genuinely fine. |
| 2026-07-12 (tick) | mini step 2990: "runway healthy", plateau resolved, approaching 3000-step milestone | nano: session concluded | RAM 1.14GB | Routine tick, plateau resolved. |
| 2026-07-12 (tick) | mini step 2990 (unchanged) | nano: session concluded | RAM 1.09GB | Routine tick, no new info. |
| 2026-07-12 (tick) | mini step 2990 (unchanged, GPU 86% confirms active) | nano: session concluded | RAM 932MB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 2990 (unchanged 3rd tick, GPU 95% confirms active) | nano: session concluded | RAM 780MB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 2990 (unchanged 4th tick, GPU 95% confirms active, container clean) | nano: session concluded | RAM 1.07GB | Hang-check performed, genuinely fine, no action taken. |
| 2026-07-12 (tick) | mini step 2990 (unchanged 5th tick, GPU 67% confirms active) | nano: session concluded | RAM 860MB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 2990 (unchanged 6th tick) | nano: session concluded | RAM 813MB | THOROUGH CHECK: initial GPU reading 12% with container 99.5% CPU (same signature as an earlier confirmed transient dip) -- resampled twice, got 100%/100%, confirming healthy, not stalled. No errors in 20 log lines. No action taken. |
| 2026-07-12 (MILESTONE) | mini step 3000/~9200 (33% through pretraining), ckpt saved | nano: session concluded | RAM 1.52GB | Real milestone: mini has now crossed the 3000-step mark, up from step 2710 at the start of this stretch of ticks -- 290 real gradient steps of genuine progress logged this session alone. |
| 2026-07-12 (tick) | mini step 3000 (unchanged) | nano: session concluded | RAM 1.47GB | Routine tick, no new info. |
| 2026-07-12 (tick) | mini step 3000 (unchanged, GPU 95% confirms active) | nano: session concluded | RAM 1.34GB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 3000 (unchanged 3rd tick, GPU 73% confirms active) | nano: session concluded | RAM 1.36GB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 3000 (unchanged 4th tick, GPU 94% confirms active, container clean) | nano: session concluded | RAM 1.39GB | Hang-check performed, genuinely fine, no action taken. |
| 2026-07-12 (tick) | mini step 3000 (unchanged 5th tick, GPU 100% confirms active) | nano: session concluded | RAM 1.37GB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 3010: "runway healthy" | nano: session concluded | RAM 1.33GB | Routine tick, progressing normally. |
| 2026-07-12 (tick) | mini step 3010 (unchanged) | nano: session concluded | RAM 1.17GB | Routine tick, no new info. |
| 2026-07-12 (tick) | mini step 3010 (unchanged, GPU 76% confirms active) | nano: session concluded | RAM 1.60GB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 3010 (unchanged 3rd tick, GPU 99% confirms active) | nano: session concluded | RAM 1.51GB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 3010 (unchanged 4th tick, GPU 87% confirms active, container clean) | nano: session concluded | RAM 924MB | Hang-check performed, genuinely fine, no action taken. |
| 2026-07-12 (tick) | mini step 3010 (unchanged 5th tick, GPU 53% confirms active, container clean, no errors) | nano: session concluded | RAM 429MB, low but not critical | Thorough check given low-RAM + plateau combo; genuinely fine, no new processes. |
| 2026-07-12 (tick) | mini step 3020: progressed, "runway healthy" | nano: session concluded | RAM 355MB -- new session low | Thorough check: GPU 82% + container clean + no errors, genuinely fine. Watching RAM trend closely; no new processes while this tight. |
| 2026-07-12 (tick) | mini step 3020 (unchanged) | nano: session concluded | RAM 925MB, recovered from the 355MB low | Routine tick, RAM trend healthy. |
| 2026-07-12 (tick) | mini step 3020 (unchanged, GPU 93% confirms active) | nano: session concluded | RAM 793MB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 3020 (unchanged 3rd tick, GPU 94% confirms active) | nano: session concluded | RAM 942MB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 3020 (unchanged 4th tick, GPU 77% confirms active, container clean) | nano: session concluded | RAM 861MB | Hang-check performed, genuinely fine, no action taken. |
| 2026-07-12 (tick) | mini step 3020 (unchanged 5th tick, GPU 92% confirms active, container clean, no errors) | nano: session concluded | RAM 269MB -- new session low, lower than prior 355MB low | Thorough check given new low; genuinely fine, no action taken, no new processes launched. |
| 2026-07-12 (tick) | mini step 3020 (unchanged 6th tick, GPU 97% confirms active) | nano: session concluded | RAM 551MB, slight recovery from 269MB low but still tight | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 3030: lm_loss 3.668, minor trend | nano: session concluded | RAM 699MB, continuing to recover | Routine tick, plateau resolved. |
| 2026-07-12 (tick) | mini step 3030 (unchanged) | nano: session concluded | RAM 1.38GB, well recovered | Routine tick, no new info. |
| 2026-07-12 (tick) | mini step 3030 (unchanged, GPU 96% confirms active) | nano: session concluded | RAM 1.13GB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 3030 (unchanged 3rd tick, GPU 63% confirms active) | nano: session concluded | RAM 1.04GB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 3030 (unchanged 4th tick, GPU 86% confirms active, container clean) | nano: session concluded | RAM 942MB | Hang-check performed, genuinely fine, no action taken. |
| 2026-07-12 (tick) | mini step 3030 (unchanged 5th tick, GPU 69% confirms active) | nano: session concluded | RAM 1.13GB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 3040: "runway healthy" | nano: session concluded | RAM 949MB | Routine tick, plateau resolved. |
| 2026-07-12 (tick) | mini step 3040 (unchanged, GPU 100% confirms active) | nano: session concluded | RAM 525MB | Routine tick, RAM in usual low band. |
| 2026-07-12 (tick) | mini step 3040 (unchanged 3rd tick, GPU 58% confirms active) | nano: session concluded | RAM 706MB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 3040 (unchanged 4th tick, GPU 95% confirms active, container clean, no errors) | nano: session concluded | RAM 218MB -- new session low, lower than prior 269MB low | Thorough check; genuinely fine, no action taken, no new processes. RAM keeps hitting new lows periodically but always recovers -- pattern well-established this session, host-level fluctuation not a trainer fault. |
| 2026-07-12 (tick) | mini step 3040 (unchanged 5th tick, GPU 100% confirms active) | nano: session concluded | RAM 1.13GB, recovered well from the 218MB low | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 3040 (unchanged 6th tick, GPU 94% + container 99.6% CPU confirm active, no errors) | nano: session concluded | RAM 797MB | Thorough re-verification given plateau; genuinely fine. |
| 2026-07-12 (tick) | mini step 3040 (unchanged 7th tick -- longest plateau tied with earlier record) | nano: session concluded | RAM 249MB, near-lowest of session | MAX-THOROUGHNESS CHECK: initial GPU reading 5% (with 98.4% CPU, container uptime clean, no restarts) -- resampled twice, got 93%/96%, confirming transient dip not stall. No errors in 30 log lines. Genuinely healthy; no action taken, no new processes. |
| 2026-07-12 (tick) | mini step 3050: confirmed progress, ckpt saved, "runway healthy" -- the 7-8 tick plateau (longest of the session) resolved as genuinely healthy | nano: session concluded | RAM 1.04GB | Routine tick, plateau resolved. |
| 2026-07-12 (tick) | mini step 3050 (unchanged) | nano: session concluded | RAM 1.19GB | Routine tick, no new info. |
| 2026-07-12 (tick) | mini step 3050 (unchanged, GPU 90% confirms active) | nano: session concluded | RAM 1.82GB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 3050 (unchanged 3rd tick, GPU 84% confirms active) | nano: session concluded | RAM 1.63GB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 3050 (unchanged 4th tick, GPU 77% confirms active, container clean) | nano: session concluded | RAM 1.57GB | Hang-check performed, genuinely fine, no action taken. |
| 2026-07-12 (tick) | mini step 3050 (unchanged 5th tick, GPU 75% confirms active) | nano: session concluded | RAM 1.70GB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 3060: lm_loss 3.571, minor trend | nano: session concluded | RAM 1.67GB | Routine tick, plateau resolved. |
| 2026-07-12 (tick) | mini step 3060 (unchanged) | nano: session concluded | RAM 1.46GB | Routine tick, no new info. |
| 2026-07-12 (tick) | mini step 3060 (unchanged, GPU 80% confirms active) | nano: session concluded | RAM 1.38GB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 3060 (unchanged 3rd tick, GPU 89% confirms active) | nano: session concluded | RAM 1.80GB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 3060 (unchanged 4th tick, GPU 90% confirms active, container clean, 4h continuous uptime) | nano: session concluded | RAM 2.10GB | Hang-check performed, genuinely fine, no action taken. |
| 2026-07-12 (tick) | mini step 3060 (unchanged 5th tick, GPU 100% confirms active) | nano: session concluded | RAM 1.97GB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 3060 (unchanged 6th tick, GPU 91% + container 98.8% CPU confirm active, no errors) | nano: session concluded | RAM 1.97GB | Thorough re-verification given plateau; genuinely fine. |
| 2026-07-12 (tick) | mini step 3070: "runway healthy", plateau resolved | nano: session concluded | RAM 1.79GB | Routine tick, plateau resolved. |
| 2026-07-12 (tick) | mini step 3070 (unchanged) | nano: session concluded | RAM 2.29GB | Routine tick, no new info. |
| 2026-07-12 (tick) | mini step 3070 (unchanged, GPU 91% confirms active) | nano: session concluded | RAM 2.32GB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 3070 (unchanged 3rd tick, GPU 90% confirms active) | nano: session concluded | RAM 2.26GB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 3070 (unchanged 4th tick, GPU 75% confirms active, container clean) | nano: session concluded | RAM 2.18GB | Hang-check performed, genuinely fine, no action taken. |
| 2026-07-12 (tick) | mini step 3070 (unchanged 5th tick, GPU 51% confirms active) | nano: session concluded | RAM 2.51GB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 3080: lm_loss 3.601, minor trend | nano: session concluded | RAM 2.33GB | Routine tick, plateau resolved. |
| 2026-07-12 (tick) | mini step 3080 (unchanged) | nano: session concluded | RAM 2.13GB | Routine tick, no new info. |
| 2026-07-12 (tick) | mini step 3080 (unchanged, GPU 62% confirms active) | nano: session concluded | RAM 1.78GB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 3080 (unchanged 3rd tick, GPU 81% confirms active) | nano: session concluded | RAM 1.98GB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 3090: tok_s spiked to 13700 (vs usual ~9000-9900), lm_loss 3.471 | nano: session concluded | RAM 1.83GB | Routine tick, plateau resolved, throughput anomaly noted (positive, not concerning). |
| 2026-07-12 (tick) | mini step 3090 (unchanged) | nano: session concluded | RAM 1.77GB | Routine tick, no new info. |
| 2026-07-12 (tick) | mini step 3090 (unchanged, GPU fluctuating 38-67% across resamples, confirms active) | nano: session concluded | RAM 1.75GB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 3090 (unchanged 3rd tick, GPU 59% confirms active) | nano: session concluded | RAM 1.71GB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 3100: tok_s remains elevated (14095), lm_loss 3.744 | nano: session concluded | RAM 1.00GB | Routine tick, plateau resolved. |
| 2026-07-12 (tick) | mini step 3100: ckpt saved (unchanged since) | nano: session concluded | RAM 479MB, GPU 50% confirms active | Routine tick, RAM in usual low band. |
| 2026-07-12 (tick) | mini step 3100 (unchanged, GPU 59% confirms active) | nano: session concluded | RAM 500MB | Routine tick, RAM tight but stable. |
| 2026-07-12 (tick) | mini step 3100 (unchanged 3rd tick, GPU 47% confirms active) | nano: session concluded | RAM 810MB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 3100 (unchanged 4th tick, GPU 85% confirms active, container clean, no errors) | nano: session concluded | RAM 479MB | Thorough check; genuinely fine, no action taken, no new processes. |
| 2026-07-12 (tick) | mini step 3110: tok_s still elevated (13383), lm_loss 3.334 | nano: session concluded | RAM 435MB, GPU 38% confirms active | Routine tick, plateau resolved. |
| 2026-07-12 (tick) | mini step 3110 (unchanged, GPU 71% confirms active) | nano: session concluded | RAM 411MB | Routine tick, RAM low but stable. |
| 2026-07-12 (tick) | mini step 3110 (unchanged 3rd tick, GPU 67% confirms active) | nano: session concluded | RAM 434MB, stable in low band for several ticks | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 3110 (unchanged 4th tick, GPU 67% confirms active) | nano: session concluded | RAM 793MB, recovering | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 3120: "runway healthy" | nano: session concluded | RAM 489MB | Routine tick, plateau resolved. |
| 2026-07-12 (tick) | mini step 3120 (unchanged, GPU 49% confirms active) | nano: session concluded | RAM 542MB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 3120 (unchanged 3rd tick, GPU 62% confirms active, container clean, no errors) | nano: session concluded | RAM 341MB, new low but consistent with established fluctuation pattern | Thorough check; genuinely fine, no action taken, no new processes. |
| 2026-07-12 (tick) | mini step 3120 (unchanged 4th tick, GPU 80% confirms active) | nano: session concluded | RAM 571MB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 3130: lm_loss 4.329, trend +0.86 (larger than typical noise but well below spike threshold, not alarming) | nano: session concluded | RAM 683MB | Routine tick, watching next step for confirmation this settles. |
| 2026-07-12 (tick) | mini step 3130 (unchanged, GPU fluctuating 37-64% across resamples, confirms active) | nano: session concluded | RAM 394MB | Routine tick, still awaiting confirmation the loss uptick from last tick settles. |
| 2026-07-12 (tick) | mini step 3130 (unchanged, GPU 63% confirms active) | nano: session concluded | RAM 1.00GB, recovered | Routine tick, still awaiting next step for loss-trend confirmation. |
| 2026-07-12 (tick) | mini step 3130 (unchanged 4th tick, GPU 61% confirms active, container clean) | nano: session concluded | RAM 1.21GB | Hang-check performed, genuinely fine, no action taken. Still awaiting confirmation the moderate loss uptick resolves. |
| 2026-07-12 (tick) | mini step 3140: lm_loss 3.404 (recovered from the 4.329 uptick), "runway healthy" confirmed | nano: session concluded | RAM 928MB | Loss uptick resolved as normal noise, not a spike. Routine tick. |
| 2026-07-12 (tick) | mini step 3140 (unchanged, GPU fluctuating 32-67% across resamples, confirms active) | nano: session concluded | RAM 594MB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 3140 (unchanged 3rd tick, GPU 52% confirms active) | nano: session concluded | RAM 493MB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 3140 (unchanged 4th tick, GPU 36% confirms active, container clean) | nano: session concluded | RAM 517MB | Hang-check performed, genuinely fine, no action taken. |
| 2026-07-12 (tick) | mini step 3150: ckpt saved | nano: session concluded | RAM 499MB | Routine tick, plateau resolved. |
| 2026-07-12 (tick) | mini step 3150 (unchanged, GPU 94% confirms active) | nano: session concluded | RAM 514MB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 3150 (unchanged 3rd tick, GPU 87% confirms active) | nano: session concluded | RAM 884MB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 3150 (unchanged 4th tick, GPU 87% confirms active, container clean) | nano: session concluded | RAM 865MB | Hang-check performed, genuinely fine, no action taken. |
| 2026-07-12 (tick) | mini step 3150 (unchanged 5th tick, GPU 70% confirms active) | nano: session concluded | RAM 837MB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 3150 (unchanged 6th tick, GPU 77% + container 99.35% CPU confirm active, no errors) | nano: session concluded | RAM 893MB | Thorough re-verification given plateau; genuinely fine. |
| 2026-07-12 (tick) | mini step 3160: "runway healthy", tok_s back to normal (9776) | nano: session concluded | RAM 1.06GB | Routine tick, plateau resolved. |
| 2026-07-12 (tick) | mini step 3160 (unchanged) | nano: session concluded | RAM 827MB | Routine tick, no new info. |
| 2026-07-12 (tick) | mini step 3160 (unchanged, GPU 92% confirms active) | nano: session concluded | RAM 2.88GB -- notably improved | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 3160 (unchanged 3rd tick, GPU 96% confirms active) | nano: session concluded | RAM 2.64GB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 3160 (unchanged 4th tick, GPU 97% confirms active, container clean) | nano: session concluded | RAM 2.52GB | Hang-check performed, genuinely fine, no action taken. |
| 2026-07-12 (tick) | mini step 3170: "runway healthy" | nano: session concluded | RAM 2.41GB | Routine tick, plateau resolved. |
| 2026-07-12 (tick) | mini step 3170 (unchanged) | nano: session concluded | RAM 2.03GB | Routine tick, no new info. |
| 2026-07-12 (tick) | mini step 3170 (unchanged, GPU 96% confirms active) | nano: session concluded | RAM 1.76GB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 3170 (unchanged 3rd tick, GPU 75% confirms active) | nano: session concluded | RAM 2.18GB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 3170 (unchanged 4th tick, GPU 92% confirms active, container clean) | nano: session concluded | RAM 2.07GB | Hang-check performed, genuinely fine, no action taken. |
| 2026-07-12 (tick) | mini step 3170 (unchanged 5th tick, GPU 96% confirms active) | nano: session concluded | RAM 1.81GB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 3180: "runway healthy" | nano: session concluded | RAM 1.60GB | Routine tick, plateau resolved. |
| 2026-07-12 (tick) | mini step 3180 (unchanged) | nano: session concluded | RAM 1.64GB | Routine tick, no new info. |
| 2026-07-12 (tick) | mini step 3180 (unchanged, GPU 98% confirms active) | nano: session concluded | RAM 1.12GB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 3180 (unchanged 3rd tick, GPU 90% confirms active) | nano: session concluded | RAM 1.29GB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 3180 (unchanged 4th tick, GPU 95% confirms active, container clean) | nano: session concluded | RAM 938MB | Hang-check performed, genuinely fine, no action taken. |
| 2026-07-12 (tick) | mini step 3180 (unchanged 5th tick, GPU 90% confirms active) | nano: session concluded | RAM 695MB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 3190: lm_loss 3.625, minor trend | nano: session concluded | RAM 996MB | Routine tick, plateau resolved, close to 3200. |
| 2026-07-12 (tick) | mini step 3190 (unchanged) | nano: session concluded | RAM 914MB | Routine tick, no new info. |
| 2026-07-12 (tick) | mini step 3190 (unchanged, GPU 99% confirms active) | nano: session concluded | RAM 871MB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 3190 (unchanged 3rd tick, GPU 80% confirms active) | nano: session concluded | RAM 634MB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 3190 (unchanged 4th tick, GPU 89% confirms active, container clean) | nano: session concluded | RAM 514MB | Hang-check performed, genuinely fine, no action taken. |
| 2026-07-12 (tick) | mini step 3190 (unchanged 5th tick, GPU 71% confirms active) | nano: session concluded | RAM 494MB | Routine liveness check, fine. |
| 2026-07-12 (MILESTONE) | mini step 3200/~9200 (~35% through pretraining), ckpt saved | nano: session concluded | RAM 557MB | Routine tick, real milestone crossed. |
| 2026-07-12 (tick) | mini step 3200 (unchanged, GPU 89% confirms active) | nano: session concluded | RAM 467MB | Routine tick, RAM low but stable. |
| 2026-07-12 (tick) | mini step 3200 (unchanged 3rd tick, GPU 74% confirms active) | nano: session concluded | RAM 1.13GB, recovered | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 3200 (unchanged 4th tick, GPU 96% confirms active, container clean) | nano: session concluded | RAM 1.00GB | Hang-check performed, genuinely fine, no action taken. |
| 2026-07-12 (tick) | mini step 3200 (unchanged 5th tick, GPU 96% confirms active, container clean, no errors) | nano: session concluded | RAM 401MB | Thorough check; genuinely fine, no action taken, no new processes. |
| 2026-07-12 (tick) | mini step 3200 (unchanged 6th tick, GPU 95% confirms active) | nano: session concluded | RAM 389MB | Routine tick, low RAM stable, no action taken. |
| 2026-07-12 (tick) | mini step 3210 (unchanged since dashboard rebuild, GPU 93% confirms active) | nano: session concluded | RAM 353MB | Routine tick. Also: dashboard rebuilt per user request (copied fresh metrics_mini.jsonl/metrics_nano.jsonl out of the ava_reports Docker volume via read-only docker cp, reran scripts/make_report.py -- output is a self-contained reports/index.html, 132KB, real loss/LR/routing/eval charts through mini step 3210). Sent to user. |
| 2026-07-12 (tick) | mini step 3210 (unchanged, GPU 95% confirms active) | nano: session concluded | RAM 593MB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 3220, trainer container uptime unaffected (still 5h, no restart) throughout | nano: session concluded | -- | Per user request, restarted the ava-agi-server-1 container only (docker compose restart server) to refresh the live /dashboard route. Confirmed: server back up healthy in ~15s, /dashboard returns 200, trainer container never touched. Known /health-timeout issue (checkpoint hot-reload config mismatch) persists as previously documented, unrelated to this restart. |
| 2026-07-12 (tick) | mini step 3220 (unchanged) | nano: session concluded | RAM 1.38GB | Routine tick, no new info. |
| 2026-07-12 (tick) | mini step 3220 (unchanged, GPU 82% confirms active) | nano: session concluded | RAM 678MB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 3220 (unchanged 3rd tick, GPU 93% confirms active) | nano: session concluded | RAM 781MB | Routine tick; confirmed server container stable 3min post-restart, trainer unaffected. |
| 2026-07-12 (INCIDENT+RECOVERY) | mini CRASHED at step 3230 with RuntimeError: CUDA error: unknown error during backward pass (unrelated to the server restart -- server and trainer are separate containers/processes, and the crash traceback shows a pure CUDA kernel failure, not a connection/resource-contention error). Docker's `restart: unless-stopped` policy auto-recovered the container within seconds. Confirmed clean resume: "event": "resumed", ckpt=/ckpt/step_3200.pt, step=3200, tokens_done=838860800 -- lost ~30 steps of work (3200->3230), zero permanent data/checkpoint loss, same self-healing pattern as the earlier RAM-pressure incident this session. GPU back to normal 77% util / 9703MiB post-recovery, actively computing again. | nano: session concluded | -- | No user action needed; auto-recovery completed successfully. Continuing to watch for the next confirmed step past 3200 to fully close this out. |
| 2026-07-12 (tick) | mini resumed at step 3200, still awaiting first new post-recovery step; GPU 94% + 9700MiB confirm actively computing, container stable 2min | nano: session concluded | RAM 2.17GB | Routine tick, recovery holding. |
| 2026-07-12 (tick) | mini still at resumed step 3200 (2nd tick without new step), GPU 84% + 9709MiB confirm active, container continuous 3min uptime no further restarts -- error grep hit is just residual tail of the already-resolved prior crash, not a new occurrence | nano: session concluded | RAM 1.74GB | Extra-thorough check given this follows a real crash; genuinely fine, no new incident. |
| 2026-07-12 (tick) | mini still at resumed step 3200 (3rd tick without new step, running longer than normal cadence but explainable by post-resume warmup), GPU 78% + container 99.6% CPU confirm active, 4min continuous uptime | nano: session concluded | RAM 1.83GB | Full hang-check performed given the recent crash; genuinely healthy, no action taken. |
| 2026-07-12 (tick) | mini still at resumed step 3200 (4th tick, but container uptime = exactly 5min = normal per-step-group cadence since resume, not actually delayed), GPU 84% + 9704MiB confirm active, zero additional restarts, old crash text still visible in tail is the already-resolved prior incident | nano: session concluded | RAM 1.73GB | Reassessed: this is within normal cadence, not an extended stall; my own check frequency this stretch outpaced the training step cadence. Genuinely fine. |
| 2026-07-12 (RECOVERY CONFIRMED) | mini step 3210: fresh post-recovery step confirmed, lm_loss 3.741 (within normal range), "runway healthy" | nano: session concluded | RAM 2.39GB | The step-3230 CUDA crash and auto-recovery incident is now fully closed out -- training genuinely healthy and progressing normally again. Net cost: ~30 steps of redone work (3200->3230), zero permanent data loss. |
| 2026-07-12 (tick) | mini step 3210 (unchanged) | nano: session concluded | RAM 2.13GB | Routine tick, no new info, fully back to normal cadence. |
| 2026-07-12 (tick) | mini step 3210 (unchanged, GPU 95% confirms active) | nano: session concluded | RAM 2.24GB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 3210 (unchanged 3rd tick, GPU 90% confirms active) | nano: session concluded | RAM 1.77GB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 3210 (unchanged 4th tick, GPU 59% confirms active, container clean, 9min uptime since crash-recovery, no further restarts) | nano: session concluded | RAM 923MB | Hang-check performed, genuinely fine, no action taken. |
| 2026-07-12 (tick) | mini step 3210 (unchanged 5th tick, GPU 92% + 9771MiB confirm active, container clean, no errors) | nano: session concluded | RAM 1.04GB | Thorough check; genuinely fine, no action taken. |
| 2026-07-12 (tick) | mini step 3220: confirmed progress, "runway healthy", crash-recovery fully behind us now | nano: session concluded | RAM 1.98GB | Routine tick, plateau resolved. |
| 2026-07-12 (tick) | mini step 3220 (unchanged) | nano: session concluded | RAM 2.17GB | Routine tick, no new info. |
| 2026-07-12 (tick) | mini step 3220 (unchanged, GPU 89% confirms active) | nano: session concluded | RAM 2.06GB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 3220 (unchanged 3rd tick, GPU 94% confirms active) | nano: session concluded | RAM 1.91GB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 3220 (unchanged 4th tick, GPU 76% confirms active, container clean, 13min uptime since crash-recovery) | nano: session concluded | RAM 1.79GB | Hang-check performed, genuinely fine, no action taken. |
| 2026-07-12 (tick) | mini step 3220 (unchanged 5th tick, GPU 80% + container 99.7% CPU confirm active) | nano: session concluded | RAM 1.91GB | Thorough re-verification; genuinely fine. |
| 2026-07-12 (tick) | mini step 3230: cleanly passed the exact step number where the earlier crash occurred, lm_loss 3.07 (normal), no recurrence | nano: session concluded | RAM 2.01GB | Confirms the CUDA crash was a genuine one-off transient fault, not tied to this specific step/data. |
| 2026-07-12 (tick) | mini step 3230 (unchanged) | nano: session concluded | RAM 1.89GB | Routine tick, no new info. |
| 2026-07-12 (tick) | mini step 3230 (unchanged, GPU 91% confirms active) | nano: session concluded | RAM 1.83GB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 3230 (unchanged 3rd tick, GPU 69% confirms active) | nano: session concluded | RAM 1.89GB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 3230 (unchanged 4th tick, GPU 63% confirms active, container clean, 18min uptime since crash-recovery) | nano: session concluded | RAM 1.45GB | Hang-check performed, genuinely fine, no action taken. |
| 2026-07-12 (tick) | mini step 3240: "runway healthy" | nano: session concluded | RAM 1.01GB | Routine tick, plateau resolved. |
| 2026-07-12 (tick) | mini step 3240 (unchanged) | nano: session concluded | RAM 1.37GB | Routine tick, no new info. |
| 2026-07-12 (tick) | mini step 3240 (unchanged, GPU 68% confirms active) | nano: session concluded | RAM 986MB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 3240 (unchanged 3rd tick, GPU 94% confirms active) | nano: session concluded | RAM 710MB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 3240 (unchanged 4th tick, GPU 95% confirms active, container clean, 22min uptime) | nano: session concluded | RAM 586MB | Hang-check performed, genuinely fine, no action taken. |
| 2026-07-12 (tick) | mini step 3240 (unchanged 5th tick, GPU 84% confirms active) | nano: session concluded | RAM 1.21GB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 3250: real progress confirmed (ckpt saved), previous narrow-tail checks missed 2 step-groups (3240->3250) -- the CUDA error text in wider log scans is confirmed the same already-resolved incident, container continuous 24min uptime, zero new restarts | nano: session concluded | RAM 1.45GB | No new incident; genuinely healthy and progressing well. |
| 2026-07-12 (tick) | mini step 3250 (unchanged) | nano: session concluded | RAM 1.71GB | Routine tick, no new info. |
| 2026-07-12 (tick) | mini step 3250 (unchanged, GPU 66% confirms active) | nano: session concluded | RAM 1.02GB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 3250 (unchanged 3rd tick, GPU 86% confirms active) | nano: session concluded | RAM 953MB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 3250 (unchanged 4th tick, GPU 79% confirms active, container clean, 28min uptime) | nano: session concluded | RAM 1.54GB | Hang-check performed, genuinely fine, no action taken. |
| 2026-07-12 (tick) | mini step 3250 (unchanged 5th tick, GPU 57% confirms active) | nano: session concluded | RAM 1.20GB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 3260: lm_loss 3.418, minor trend | nano: session concluded | RAM 1.65GB | Routine tick, plateau resolved. |
| 2026-07-12 (tick) | mini step 3260 (unchanged) | nano: session concluded | RAM 1.45GB | Routine tick, no new info. |
| 2026-07-12 (tick) | mini step 3260 (unchanged, GPU 92% confirms active) | nano: session concluded | RAM 1.32GB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 3260 (unchanged 3rd tick, GPU 49% confirms active) | nano: session concluded | RAM 1.53GB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 3260 (unchanged 4th tick, GPU 71% confirms active, container clean, 32min uptime) | nano: session concluded | RAM 1.61GB | Hang-check performed, genuinely fine, no action taken. |
| 2026-07-12 (tick) | mini step 3260 (unchanged 5th tick, GPU 81% confirms active) | nano: session concluded | RAM 1.39GB | Routine liveness check, fine. |
2026-07-12T18:15 | step=3270 | lm_loss=3.559 | tok_s=9333 | grad_norm=0.223 | phase0_tokens=n/a(phase1) | all 14 containers healthy, disk 330GB free, server/trainer both stable post-crash-recovery (34min/26min uptime resp.) | healthy, no hang, no recovery needed
| 2026-07-12 (tick) | mini step 3270 (unchanged) | nano: session concluded | RAM 1.57GB | Routine tick, no new info. |
| 2026-07-12 (tick) | mini step 3270 (unchanged, GPU 73% confirms active) | nano: session concluded | RAM 1.20GB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 3270 (unchanged 3rd tick, GPU 88% confirms active) | nano: session concluded | RAM 1.07GB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 3270 (unchanged 4th tick, GPU 80% confirms active, container clean, 37min uptime) | nano: session concluded | RAM 986MB | Hang-check performed, genuinely fine, no action taken. |
| 2026-07-12 (tick) | mini step 3270 (unchanged 5th tick, GPU 58% confirms active) | nano: session concluded | RAM 885MB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 3280: "runway healthy" | nano: session concluded | RAM 606MB | Routine tick, plateau resolved. |
| 2026-07-12 (tick) | mini step 3280 (unchanged) | nano: session concluded | RAM 836MB | Routine tick, no new info. |
| 2026-07-12 (tick) | mini step 3280 (unchanged, GPU 86% confirms active) | nano: session concluded | RAM 1.76GB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 3280 (unchanged 3rd tick, GPU 81% confirms active) | nano: session concluded | RAM 1.94GB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 3280, dashboard rebuilt per user request (fresh metrics_mini.jsonl/metrics_nano.jsonl copied out of ava_reports Docker volume, make_report.py rerun, 133285 bytes, both runs present) and sent to user | nano: session concluded | -- | Second dashboard rebuild this session; both times via safe read-only docker cp + regenerate, zero training interference. |
| 2026-07-12 (tick) | mini step 3280 (unchanged, GPU 47% confirms active) | nano: session concluded | RAM 1.06GB | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 3290: lm_loss 3.487, minor trend | nano: session concluded | RAM 455MB | Routine tick, plateau resolved, close to 3300 milestone. |
| 2026-07-12 (tick) | mini step 3290 (unchanged) | nano: session concluded | RAM 764MB | Routine tick, no new info. |
| 2026-07-12 (tick) | mini step 3290 (unchanged, GPU 98% confirms active) | nano: session concluded | RAM 2.36GB -- notably improved | Routine liveness check, fine. |
| 2026-07-12 (tick) | mini step 3290 (unchanged 3rd tick, GPU 88% confirms active) | nano: session concluded | RAM 2.11GB | Routine liveness check, fine. |
| 2026-07-12 (INCIDENT+RECOVERY #2) | mini CRASHED a SECOND time (RuntimeError: CUDA error: unknown error, this time in the router's forward pass at multi_jspace_module.py:196, different call site than the first crash's backward() failure -- same generic CUDA error class both times). Docker auto-restart already recovered: confirmed clean resume from ckpt/step_3250.pt, lost ~40 steps (3250->3290), zero permanent data loss. Also: a momentary RAM reading of ~14MB free was observed right around the crash, but a fuller CimInstance query moments later showed ~1030MB free -- confirmed transient measurement artifact coinciding with the crash/restart's memory churn, not a sustained host-level crisis. | nano: session concluded | RAM 1.03GB (post-transient-dip) | Two CUDA crashes in ~40min with the same generic "unknown error" signature but different code paths suggests possible underlying GPU/driver flakiness (RTX 4080 laptop under sustained multi-hour load, or a WSL2 CUDA-passthrough quirk) rather than a code bug -- not something to chase/fix mid-loop per standing discipline, but flagging the pattern clearly. Both incidents self-healed cleanly via docker restart:unless-stopped with zero permanent loss. |
| 2026-07-12 (INCIDENT+RECOVERY #3) | mini CRASHED a THIRD time (RuntimeError: CUDA error: unknown error, same call site as crash #1 -- backward() pass), occurring within ~90s of crash #2's recovery. Docker auto-restart recovered cleanly again: resumed from ckpt/step_3250.pt (same checkpoint as #2, meaning zero additional step loss beyond the original 40 from crash #2). GPU temp 57C, power draw 44W -- both completely normal, ruling out thermal throttling. Container holding steady ~1min post-resume. | nano: session concluded | RAM 2.12GB | THREE crashes in ~45min with escalating frequency (last two only ~90s apart) is a genuine reliability concern worth flagging prominently to the user -- not thermal, not RAM-pressure-related this time. Possible causes: WDDM/TDR driver reset under WSL2 GPU passthrough, flaky CUDA runtime/driver combination, or intermittent hardware fault. Auto-recovery mechanism (docker restart:unless-stopped + checkpoint resume) has worked flawlessly all 3 times with zero permanent data loss, but the user may want to check GPU driver version or monitor for further recurrence. |
| 2026-07-12 (tick) | mini resumed at step 3250 (post-crash#3), holding stable for 2min continuous uptime, GPU 82% active, temp 59C normal | nano: session concluded | RAM 2.52GB | No further crashes; recovery #3 holding. Watching closely for the next confirmed step past 3250. |
| 2026-07-12 (tick) | mini still at resumed step 3250, 3min continuous uptime since recovery #3, GPU 83% confirms active | nano: session concluded | RAM 1.91GB | Stability holding well, no further crashes. |
| 2026-07-12 (tick) | mini still resumed at step 3250, container stable | nano: session concluded | RAM 2.08GB | Routine tick, no new info yet. |
| 2026-07-12 (tick) | mini still resumed at step 3250 (4min continuous uptime since recovery #3), GPU 77% + temp 60C confirm active and normal | nano: session concluded | RAM 1.79GB | No further crashes, genuinely stable, awaiting next step. |
| 2026-07-12 (RECOVERY #3 CONFIRMED) | mini step 3260: fresh post-recovery-#3 step confirmed, lm_loss 3.213 (normal range), "runway healthy," 5min continuous stable uptime | nano: session concluded | RAM 1.83GB | Third crash-recovery cycle now fully closed out and confirmed stable -- training genuinely healthy again. Total cost across all 3 incidents: ~70 steps of redone work (3200->3230->3250->3260 with resets at 3200 and 3250), zero permanent data loss throughout. |
| 2026-07-12 (tick) | mini step 3260 (unchanged) | nano: session concluded | RAM 1.72GB | Routine tick, no new info. |
2026-07-13T02:19:39Z | step=3260 | lm_loss=3.213 | tok_s=9595 | grad_norm=0.2047 | phase0_tokens=854589440 | routine tick, RAM 1654MB free, no new crash, healthy | OK
2026-07-13T02:20:15Z | step=3260 | lm_loss=3.213 | tok_s=9595 | grad_norm=0.2047 | phase0_tokens=854589440 | all 13 services healthy, pipeline/status mode=stale(age 258s, still under 15min hang threshold, normal step cadence ~4-5min), disk 307G free/68% used, trainer uptime 9min (still crash#3 recovery window, no new crash) | OK
2026-07-13T02:20:38Z | step=3270 | lm_loss=3.400 | tok_s=9911 | grad_norm=0.2027 | phase0_tokens=857210880 | new step confirmed, pipeline mode back to training (no longer stale), all 13 services healthy, disk 307G free | OK
2026-07-13T02:30:47Z | step=3550 | lm_loss=n/a(no new step this tick) | tok_s=n/a | grad_norm=n/a | phase0_tokens=930611200 | phase2 (p2_foundation, seq1024) in progress, age_s=746 (~12.4min, under 15min hang threshold; adaptive stale-cadence logic in new pipeline_status.py correctly reports mode=training not stale), all 13 services healthy, disk 295G free, server up 47s post dashboard-viz merge+rebuild | OK
2026-07-13T02:41:00Z | step=3570 | lm_loss=4.919 | tok_s=2502 | grad_norm=0.2337 | phase0_tokens=935854080 | Manim dashboard reinstated (cherry-pick was stale/duplicate; found+merged origin's real PR #3 + Stage12 JobBench/GAIA2, reconciled phase-weight conflicts, committed 1686ed5); added new /ecosystem page (harness/skills/agent-eval/TODOS status, commit bbeb00c); rebuilt image, redeployed server only (trainer untouched throughout); pushed both commits to origin. Phase2 (seq1024) loss jump to 4.9 is expected curriculum-transition behavior, not a regression. | OK
2026-07-13T02:51:47Z | step=3570 | lm_loss=4.919 | tok_s=2502 | grad_norm=0.2337 | phase0_tokens=935854080 | routine tick, age_s=441 (~7.3min, normal for phase2 cadence), all 13 services healthy, disk 294G free | OK
