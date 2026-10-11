"""Page CSS for the notes assistant. Injected once from ``app.py``."""

CSS = """
<style>
html, body, [class*="css"] {
  font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
}
.stApp {
  background: #f3efe6;
}
section[data-testid="stSidebar"] {
  background: #e7e1d4;
  border-right: 1px solid #d9d0c0;
}
section[data-testid="stSidebar"] .block-container {
  padding-top: 1.4rem;
}
section[data-testid="stSidebar"] [data-testid="stButton"] button {
  justify-content: flex-start;
  text-align: left;
  border-radius: 10px;
  border: 1px solid transparent;
}
section[data-testid="stSidebar"] [data-testid="stButton"] button p {
  text-align: left !important;
  width: 100%;
}
div[data-testid="stChatMessage"] {
  background: transparent;
}
div[data-testid="stChatMessageContent"] {
  font-family: "Palatino Linotype", "Songti SC", Georgia, serif;
  font-size: 1.05rem;
  line-height: 1.65;
}
section.main .block-container {
  max-width: 920px;
  padding-top: 1.6rem;
  padding-bottom: 7rem;
}
.desk-kicker {
  letter-spacing: 0.14em;
  text-transform: uppercase;
  font-size: 0.72rem;
  color: #6d6458;
  margin-bottom: 0.2rem;
}
.desk-title {
  font-family: "Palatino Linotype", "Songti SC", Georgia, serif;
  font-size: 1.7rem;
  line-height: 1.25;
  margin: 0 0 0.3rem 0;
}
.hit {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  column-gap: 1rem;
  padding: 0.45rem 0;
  border-bottom: 1px solid #e4ddd0;
  font-family: "Segoe UI", "PingFang SC", sans-serif;
}
.hit-path {
  font-size: 0.92rem;
}
.hit-line {
  color: #6d6458;
  font-size: 0.82rem;
  white-space: nowrap;
}
.hit-snippet {
  grid-column: 1 / -1;
  color: #5c564c;
  font-size: 0.84rem;
  line-height: 1.4;
  margin-top: 0.15rem;
}
.page-meta {
  font-family: "Segoe UI", "PingFang SC", sans-serif;
  font-size: 0.92rem;
  margin-bottom: 0.4rem;
}
.page-body {
  max-height: 16rem;
  overflow: auto;
  white-space: pre-wrap;
  font-family: Consolas, "Cascadia Mono", monospace;
  font-size: 0.82rem;
  line-height: 1.45;
  background: #fffdf8;
  border: 1px solid #e4ddd0;
  border-radius: 8px;
  padding: 0.7rem 0.85rem;
}
.confirm {
  margin: 0.2rem 0 0.75rem;
  background: #fffdf8;
  border: 1px solid #e0d8c8;
  border-radius: 12px;
  overflow: hidden;
}
.confirm-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 0.8rem;
  padding: 0.38rem 0.75rem;
  background: #f7f3ea;
  border-bottom: 1px solid #e0d8c8;
  font-family: "Segoe UI", "PingFang SC", sans-serif;
  font-size: 0.78rem;
  line-height: 1.3;
}
.confirm-path {
  color: #3f3933;
  font-weight: 600;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.confirm-kind {
  color: #6d6458;
  flex: none;
}
.confirm-body {
  max-height: 22rem;
  overflow: auto;
  padding: 0.42rem 0.75rem 0.5rem;
}
.note-h1 {
  font-family: "Palatino Linotype", "Songti SC", Georgia, serif;
  font-size: 1.02rem;
  line-height: 1.3;
  color: #2c2824;
  margin: 0.05rem 0 0.2rem;
}
.note-h2 {
  font-family: "Segoe UI", "PingFang SC", sans-serif;
  font-size: 0.72rem;
  letter-spacing: 0.08em;
  color: #6d6458;
  margin: 0.42rem 0 0.1rem;
}
.note-p {
  font-family: "Palatino Linotype", "Songti SC", Georgia, serif;
  font-size: 0.9rem;
  line-height: 1.4;
  color: #2c2824;
  margin: 0;
}
.note-gap {
  height: 0.28rem;
}
.diff-line {
  font-family: "Palatino Linotype", "Songti SC", Georgia, serif;
  font-size: 0.86rem;
  line-height: 1.35;
  padding: 0.02rem 0.4rem;
  margin: 1px 0;
  border-left: 2px solid transparent;
}
.diff-add {
  background: #e7f2e4;
  border-left-color: #5f8a58;
}
.diff-del {
  background: #f6e8e4;
  border-left-color: #a85b4e;
  color: #7a645c;
}
.diff-ctx {
  color: #8a8175;
}
</style>
"""
