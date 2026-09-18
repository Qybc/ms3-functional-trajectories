# Third-party notices

This file identifies external resources referenced by the MS³ release. Their
names do not imply redistribution or endorsement. Users must obtain each resource
from its original provider and comply with the terms in force there.

## Software dependencies

- Python: https://www.python.org/
- NumPy: https://numpy.org/
- SciPy: https://scipy.org/
- openpyxl: https://openpyxl.readthedocs.io/

The public demonstration and validator use the Python standard library plus the
packages declared in `requirements.txt` and `environment.yml`. Optional agent
paths may use PyMuPDF or pypdf for local PDF inspection; neither package nor any
publisher document is bundled by this release.

## Models and hosted services

- Qwen2.5-72B-Instruct was used as the shared extraction backbone. Model weights
  are not included.
- Comparison systems and judge services named in the manuscript and evaluation
  tables were accessed through their respective providers. Their weights,
  proprietary APIs and credentials are not included.

## Evaluation resources

- LitQA2-FullText
- ScholarQA-CS2
- SciCUEval Materials

Benchmark questions, copyrighted evidence and third-party answer corpora are not
republished here. The release provides only author-generated evaluation summaries
and, where rights permit, derived numeric judgments and identifiers.

## Literature corpus

Publisher full text, figures and tables remain governed by their original rights
holders. The public archive excludes publisher PDFs, long excerpts and
institutional-access acquisition tooling. Bibliographic references and source
pointers do not grant rights to the underlying articles.

Dependency names and benchmark titles identify the frozen analysis environment;
they do not extend this package's licences to third-party resources.
