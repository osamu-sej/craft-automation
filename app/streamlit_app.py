"""craft-automation アプリ（起動: streamlit run app/streamlit_app.py）。

要件は docs/requirements.md。正本はリポジトリのファイルで、アプリなしでも
`photocraft-cli batch --actions actions/<名前>.json …` で同じレシピが動く（FR-09）。
"""

import streamlit as st

from views import batch, common, history, ledger_page, mcp_page, recipes_page, smoke_page, upgrade_page, upstream_page, versions

st.set_page_config(page_title="craft-automation", page_icon=":material/photo_filter:", layout="wide")

common.PAGES.update(
    batch=st.Page(batch.render, title="一括実行", icon=":material/play_arrow:", url_path="batch", default=True),
    recipes=st.Page(recipes_page.render, title="レシピ", icon=":material/receipt_long:", url_path="recipes"),
    history=st.Page(history.render, title="履歴", icon=":material/history:", url_path="history"),
    smoke=st.Page(smoke_page.render, title="スモークテスト", icon=":material/science:", url_path="smoke"),
    upstream=st.Page(upstream_page.render, title="本家の更新", icon=":material/update:", url_path="upstream"),
    upgrade=st.Page(upgrade_page.render, title="ピン更新", icon=":material/upgrade:", url_path="upgrade"),
    versions=st.Page(versions.render, title="バージョン", icon=":material/download:", url_path="versions"),
    ledger=st.Page(ledger_page.render, title="コマンド台帳", icon=":material/menu_book:", url_path="ledger"),
    mcp=st.Page(mcp_page.render, title="MCP 接続", icon=":material/power:", url_path="mcp"),
)
P = common.PAGES
page = st.navigation({
    "画像処理": [P["batch"], P["recipes"], P["history"]],
    "本家の追跡": [P["smoke"], P["upstream"], P["upgrade"]],
    "設定と資料": [P["versions"], P["ledger"], P["mcp"]],
})
common.sidebar()
common.upstream_badge()
page.run()
