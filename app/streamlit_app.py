"""craft-automation アプリ（起動: streamlit run app/streamlit_app.py）。

要件は docs/requirements.md。正本はリポジトリのファイルで、アプリなしでも
`photocraft-cli batch --actions actions/<名前>.json …` で同じレシピが動く（FR-09）。
"""

import streamlit as st

from views import batch, common, history, recipes_page, smoke_page, upstream_page, versions

st.set_page_config(page_title="craft-automation", page_icon=":material/photo_filter:", layout="wide")

common.PAGES.update(
    batch=st.Page(batch.render, title="一括実行", icon=":material/play_arrow:", url_path="batch", default=True),
    recipes=st.Page(recipes_page.render, title="レシピ", icon=":material/receipt_long:", url_path="recipes"),
    smoke=st.Page(smoke_page.render, title="スモークテスト", icon=":material/science:", url_path="smoke"),
    upstream=st.Page(upstream_page.render, title="本家の更新", icon=":material/update:", url_path="upstream"),
    versions=st.Page(versions.render, title="バージョン", icon=":material/download:", url_path="versions"),
    history=st.Page(history.render, title="履歴", icon=":material/history:", url_path="history"),
)
page = st.navigation(list(common.PAGES.values()))
common.sidebar()
common.upstream_badge()
page.run()
