# OpenStax Math → Independent OER Equivalents

Source shelf: [openstax.org/subjects/math](https://openstax.org/subjects/math) (16 live titles).

**Not OpenStax mirrors.** Each row maps to author-maintained CC/GFDL books.
Machine-readable catalog: `configs/openstax_math_oer_equivalents.yaml`.
Downloader: `scripts/download_math_oer_equivalents.py`.

| OpenStax title | Primary independent OER | License | PDF? |
|---|---|---|---|
| Prealgebra 2e | Stitz–Zeager College Algebra | CC BY-NC-SA 3.0 | yes |
| Elementary Algebra 2e | Stitz–Zeager College Algebra | CC BY-NC-SA 3.0 | yes |
| Intermediate Algebra 2e | Stitz–Zeager College Algebra | CC BY-NC-SA 3.0 | yes |
| College Algebra 2e | Stitz–Zeager College Algebra | CC BY-NC-SA 3.0 | yes |
| College Algebra 2e + Corequisite | Stitz–Zeager College Algebra | CC BY-NC-SA 3.0 | yes |
| Algebra and Trigonometry 2e | Stitz–Zeager Algebra + Trig | CC BY-NC-SA 3.0 | yes |
| Precalculus 2e | Stitz–Zeager Precalculus 4 | CC BY-NC-SA 3.0 | yes |
| Calculus Volume 1 | Active Calculus (Boelkins) | CC BY-SA 4.0 | yes |
| Calculus Volume 2 | Active Calculus (Boelkins) | CC BY-SA 4.0 | yes |
| Calculus Volume 3 | Active Calculus Multivariable | CC BY-SA 4.0 | yes |
| Statistics (K12) | Think Stats 2e | CC BY-NC 4.0 | yes |
| Introductory Statistics 2e | Think Stats 2e (+ OpenIntro IMS HTML) | CC BY-NC / BY-SA | yes |
| Introductory Business Statistics 2e | Think Stats 2e | CC BY-NC 4.0 | yes |
| Contemporary Mathematics | Book of Proof (Hammack) | CC BY-ND | yes |
| Principles of Data Science | Think Stats 2e | CC BY-NC 4.0 | yes |
| Algebra 1 (RAISE) | Stitz–Zeager College Algebra | CC BY-NC-SA 3.0 | yes |

Also kept as backups: Whitman/Guichard calculus PDFs, Open Textbook Library listings, OpenIntro IMS HTML/GitHub.

```bash
cd apps/ava-factory
python scripts/download_math_oer_equivalents.py --out data/research_inbox/math-oer-equivalents
python scripts/ingest_research_pdfs.py \
  --inbox data/research_inbox/math-oer-equivalents \
  --out data/research_corpus --domain math
```
