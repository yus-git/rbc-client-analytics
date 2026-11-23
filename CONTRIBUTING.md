# Contributing

1. Use a branch and a pull request. Keep source data synthetic.
2. Keep target IDs in `config/environment.local.json` and generated artifacts in
   `.generated/`; neither belongs in Git.
3. Run `python -B -m unittest discover -s tests -v` and
   `python -B tools/validate.py` before submitting.
4. Change the builder, not only its generated output. Add a focused regression
   test for changed behavior and update the relevant deployment instructions.
5. Never replace a running model with a fresh generated model without a backup,
   a reviewed diff and an approved change window. New lineage tags can disrupt
   dependent reports and user customizations.
6. Preserve single-direction relationship behavior, SCD2 keys, scenario grain,
   and semi-additive AUM rules unless an explicit design change is approved.
7. Cite official documentation and its review date for platform limitations.
   Mark untested infrastructure as proposed rather than validated.
