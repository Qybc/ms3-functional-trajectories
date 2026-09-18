# Package validation

Validated on 18 September 2026:

- All Python files passed static compilation.
- `code/agent/ms3_agent.py --help` completed successfully with the packaged
  supporting modules.
- The packaged Fig. 4 comparison script regenerated its SVG from the copied raw
  workbooks.
- Both packaged Fig. 5 characterization scripts regenerated SVG output from the
  copied adhesion and electrical workbooks.
- The Source Data workbook passed ZIP-container integrity testing and reopened
  with `openpyxl`.
- Source Data and Supplementary Data were independently rebuilt from the
  released CSV/JSON files and matched the distributed workbooks cell by cell.
- The final ZIP was extracted into a clean temporary directory; the validator,
  deep workbook rebuild and example-record demonstration all passed there.
The ECG extraction script requires the complete porcine recording supplied by the
authors through `MS3_PORCINE_RECORDING`; the public package instead contains the
exact decimated ECG points and smoothed heart-rate points used in the figure.
