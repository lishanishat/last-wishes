"""Calm, plain styling for the chat shell. One centered column, no emoji."""

CSS = """
<style>
.block-container { max-width: 760px; padding-top: 2rem; padding-bottom: 6rem; }
html, body, [data-testid="stAppViewContainer"] { overflow-x: hidden; }
h1, h2, h3 { font-weight: 600; letter-spacing: 0; }
.lw-badge { display:inline-block; padding:1px 8px; border:1px solid #b9a98a; border-radius:10px;
            font-size:0.72rem; color:#6b5b3a; background:#f6f1e6; margin-left:6px; vertical-align:middle; }
.lw-stub  { border-color:#9aa; color:#566; background:#eef2f3; }
.lw-totals { font-size:0.95rem; margin:6px 0 2px 0; }
.lw-totals b { font-weight:600; }
.lw-quote { border-left:3px solid #c9bda3; padding:6px 12px; margin:0; color:#3b3524; background:#faf7f0;
            font-size:0.92rem; overflow-wrap:anywhere; }
.lw-ref   { border-left:3px solid #8aa0a8; padding:6px 12px; margin:0; color:#27393f; background:#f1f5f6;
            font-size:0.92rem; overflow-wrap:anywhere; }
.lw-label { font-size:0.75rem; text-transform:uppercase; letter-spacing:0.04em; color:#777; margin:8px 0 2px; }
.lw-msg   { font-family: ui-monospace, Menlo, monospace; font-size:0.85rem;
            border:1px solid #ddd; border-radius:6px; padding:10px 12px; background:#fcfcfc; overflow-wrap:anywhere; }
.lw-table-wrap { overflow-x:auto; max-width:100%; }
table.lw { border-collapse:collapse; width:100%; font-size:0.88rem; }
table.lw th, table.lw td { text-align:left; padding:4px 8px; border-bottom:1px solid #e6e2d8; vertical-align:top;
                           overflow-wrap:anywhere; }
table.lw th { font-weight:600; color:#555; font-size:0.78rem; }
table.lw td.amt { white-space:nowrap; text-align:right; }
.lw-flag-cols { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
@media (max-width: 640px) {
  .block-container { padding-left:0.8rem; padding-right:0.8rem; }
  .lw-flag-cols { grid-template-columns:1fr; }
  table.lw { font-size:0.8rem; }
  table.lw th, table.lw td { padding:3px 5px; }
}
</style>
"""
