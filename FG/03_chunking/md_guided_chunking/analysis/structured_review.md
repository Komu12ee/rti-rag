# Boundary Analysis Review

Document type (from profile): `technical_spec`
Total units: 3
Unresolved block ids: 0

| Confidence | Needs Review | Unit Type | Identifier | Start Block | End Block | Reason |
|---:|:---:|---|---|---|---|---|
| 0.90 | no | section | - | b0007 | b0008 | The heading 'नोडल अधिकारी क लिए' (For the Nodal Officer) is followed by a paragraph explaining the process for the Nodal Officer, forming a section. |
| 0.90 | no | section | - | b0011 | b0015 | The heading 'प्रथम अपीलीय अधिकारी के लिए' (For the First Appellate Officer) is followed by several paragraphs explaining the process for the First Appellate Officer, forming a section. |
| 0.95 | no | section | - | b0002 | b0003 | The heading 'जनसूचना अधिकारी का पंजीयन' (Registration of Information Officer) is followed by a list of steps for registration, which logically forms a section. |

## What to do next

This report is informational only - nothing was auto-retried. If you see rows you're not happy with, run, for example:

```bash
python cli.py repair path/to/your_doc.md --unit-id <identifier> --context-blocks 6
```

or target a raw block range directly:

```bash
python cli.py repair path/to/your_doc.md --block-range <start_block_id>:<end_block_id>
```