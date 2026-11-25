# Reference data provenance

## Supplied product inputs

- `Nutrilift Text PRD.pdf`, supplied by the user, extracted into `docs/source/requirements.txt` without modification to the original PDF.
- `Student_Growth__Health_Assessment_Tool_-_8_languages.xlsx`, supplied by the user. `screening_workbook.json` preserves populated cells in rows 1–97, columns A–F across English, Hindi, Tamil, Malayalam, Kannada, Telugu, Marathi and Bengali. Later rows were formatting-only. Product question mappings are in `core/schema.py`.

## WHO BMI-for-age LMS data

Downloaded 24 November 2026 from WHO. `who_bmi_lms.json` contains the published L, M and S coefficients by sex and completed month; no parameters were invented. The runtime does not fetch these files.

- Reference and cut-offs: https://www.who.int/tools/growth-reference-data-for-5to19-years/indicators/bmi-for-age/
- Boys, months 61–228: https://cdn.who.int/media/docs/default-source/child-growth/growth-reference-5-19-years/bmi-for-age-%285-19-years%29/bmi-boys-z-who-2007-exp.xlsx?sfvrsn=a84bca93_2
- Girls, months 61–228: https://cdn.who.int/media/docs/default-source/child-growth/growth-reference-5-19-years/bmi-for-age-%285-19-years%29/bmi-girls-z-who-2007-exp.xlsx?sfvrsn=79222875_2
- WHO Child Growth Standards (used at month 60): https://www.who.int/toolkits/child-growth-standards/standards/body-mass-index-for-age-bmi-for-age
- Boys at month 60: https://cdn.who.int/media/docs/default-source/child-growth/child-growth-standards/indicators/body-mass-index-for-age/bmi_boys_2-to-5-years_zscores.xlsx?sfvrsn=73010c9b_5
- Girls at month 60: https://cdn.who.int/media/docs/default-source/child-growth/child-growth-standards/indicators/body-mass-index-for-age/bmi_girls_2-to-5-years_zscores.xlsx?sfvrsn=452aca36_7
- Calculation method and worked examples: https://cdn.who.int/media/docs/default-source/child-growth/growth-reference-5-19-years/computation.pdf?sfvrsn=c2ff6a95_4

The LMS z-score is `((BMI/M)^L - 1)/(L*S)`, with the log form at L=0 and the WHO linear extension beyond ±3 SD. The supplied workbook's 5–18-year flag thresholds are applied: below -3 SD or above +2 SD red; below -2 SD or above +1 SD yellow; otherwise green. Boundaries are compared before display rounding. The 2006 month-60 coefficient bridges to the 2007 month-61 reference without extrapolation.
