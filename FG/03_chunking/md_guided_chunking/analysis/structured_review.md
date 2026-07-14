# Boundary Analysis Review

Document type (from profile): `technical_spec`
Total units: 8
Unresolved block ids: 28

| Confidence | Needs Review | Unit Type | Identifier | Start Block | End Block | Reason |
|---:|:---:|---|---|---|---|---|
| 0.80 | no | section | - | b0039 | b0039 | The block b0039 contains a single list item in Hindi, which appears to be a self-contained unit related to name change procedures. |
| 0.85 | no | section | - | b0029 | b0030 | The block contains a heading at level 2 followed by a paragraph with a signature and date, likely representing a formal section of the document. |
| 0.85 | no | section | - | b0035 | b0035 | The block b0035 contains a list of instructions in Hindi, which appears to be a self-contained unit related to name change procedures. |
| 0.90 | no | section | - | b0013 | b0013 | The block contains a heading at level 2, which is consistent with the document's hierarchy. |
| 0.90 | no | section | - | b0037 | b0037 | The heading 'नाम परिवर्तन लिस्ट पर Approve बटन पर क्लिक करके स्वीकृत करे |' (block b0037) is a standalone heading, likely marking the start of a new section. |
| 0.95 | no | table | - | b0005 | b0005 | The block contains a structured table with numbered items, likely representing a list of functions or processes related to charge transfer. |
| 0.95 | no | table | - | b0028 | b0028 | The block contains a structured table with charge type, office name, and date of charge given, likely representing a formal record of charge transfer. |
| 0.95 | no | section | - | b0031 | b0034 | The heading 'Signature of the Officer Handing Over the Charge' (block b0031) is followed by related paragraphs (b0032-b0034) that describe the signature and date, forming a coherent section. |

## Unresolved block IDs (not assigned to any unit)

- b0001
- b0002
- b0003
- b0004
- b0006
- b0007
- b0008
- b0009
- b0010
- b0011
- b0012
- b0014
- b0015
- b0016
- b0017
- b0018
- b0019
- b0020
- b0021
- b0022
- b0023
- b0024
- b0025
- b0026
- b0027
- b0031
- b0032
- b0033

## What to do next

This report is informational only - nothing was auto-retried. If you see rows you're not happy with, run, for example:

```bash
python cli.py repair path/to/your_doc.md --unit-id <identifier> --context-blocks 6
```

or target a raw block range directly:

```bash
python cli.py repair path/to/your_doc.md --block-range <start_block_id>:<end_block_id>
```